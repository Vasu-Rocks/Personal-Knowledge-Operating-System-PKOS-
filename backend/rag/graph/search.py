import math
import re
import uuid

import asyncpg

from rag.graph.reconciler import canonicalize

# Words that match real entities (e.g. 'data', 'model') but say nothing about what the user asked.
STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "what", "which", "who", "whom", "when", "where", "why", "how",
    "does", "did", "can", "could", "would", "should", "will", "with", "without", "from", "into", "about", "between",
    "this", "that", "these", "those", "there", "their", "them", "than", "then", "your", "you", "its",
    "use", "used", "using", "difference", "different", "explain", "describe", "list", "give", "tell", "main",
    "data", "model", "models", "work", "works", "mean", "means", "example", "examples", "type", "types",
}
MAX_NAME_SEEDS = 3


def query_name_candidates(query: str) -> list[str]:
    """1-3 word n-grams of the query, as canonical entity names worth an exact lookup."""
    tokens = [t.strip(".-") for t in re.findall(r"[A-Za-z0-9_+#.\-]+", query)]
    tokens = [t for t in tokens if t]
    out: list[str] = []
    for n in (3, 2, 1):
        for i in range(len(tokens) - n + 1):
            gram = tokens[i:i + n]
            if n == 1 and (gram[0].lower() in STOPWORDS or len(gram[0]) < 3):
                continue
            if n > 1 and all(g.lower() in STOPWORDS for g in gram):
                continue
            key = canonicalize(" ".join(gram))
            if key and key not in out:
                out.append(key)
    return out


async def find_seed_entities(conn: asyncpg.Connection, user_id: uuid.UUID, query: str, query_embedding: list,
                             num_seeds: int, max_distance: float) -> list[dict]:
    """Exact name hits first (best signal for identifiers like 'GridSearchCV'), then nearest by embedding."""
    seeds: dict[uuid.UUID, dict] = {}

    names = query_name_candidates(query)
    if names:
        rows = await conn.fetch(
            "SELECT entity_id, name, canonical_name FROM entities WHERE user_id = $1 AND canonical_name = ANY($2)",
            user_id, names)
        # Longer matches are more specific ('support vector machine' beats 'machine').
        for r in sorted(rows, key=lambda r: -len(r["canonical_name"]))[:MAX_NAME_SEEDS]:
            seeds[r["entity_id"]] = {"entity_id": r["entity_id"], "name": r["name"], "score": 1.0, "match": "name"}

    rows = await conn.fetch(
        """
        SELECT entity_id, name, (embedding <=> $1) AS distance
        FROM entities
        WHERE user_id = $2 AND (embedding <=> $1) < $3
        ORDER BY embedding <=> $1 ASC
        LIMIT $4
        """, query_embedding, user_id, max_distance, num_seeds)
    for r in rows:
        if r["entity_id"] not in seeds:
            seeds[r["entity_id"]] = {"entity_id": r["entity_id"], "name": r["name"],
                                     "score": 1.0 - float(r["distance"]), "match": "embedding"}

    return sorted(seeds.values(), key=lambda s: -s["score"])[:max(num_seeds, MAX_NAME_SEEDS)]


async def retrieve_community_chunks(pool: asyncpg.Pool, user_id: str, query_embedding: list,
                                    limit: int, max_distance: float) -> list[dict]:
    """
    Global search: the communities whose summaries are closest to the query, shaped like chunks so they flow
    through the same context builder, citation labels and X-Ray panel (via='community').
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT community_id, title, summary, (embedding <=> $1) AS distance
            FROM communities
            WHERE user_id = $2 AND summary IS NOT NULL AND embedding IS NOT NULL AND (embedding <=> $1) < $3
            ORDER BY embedding <=> $1 ASC
            LIMIT $4
            """, query_embedding, uuid.UUID(user_id), max_distance, limit)
    return [{"chunk_id": None, "filename": f"Community summary: {r['title']}", "page": "-", "text": r["summary"],
             "distance": float(r["distance"]), "via": "community"} for r in rows]


async def retrieve_graph_context(pool: asyncpg.Pool, user_id: str, query: str, query_embedding: list,
                                 num_seeds: int, max_edges: int, seed_max_distance: float,
                                 extra_chunks: int, chunk_max_distance: float,
                                 exclude_chunk_ids: set[int] | None = None) -> dict:
    """
    G4 local search: seeds -> ranked 1-hop edges -> graph-found chunks.
    Returns {"nodes", "links", "chunks", "seeds"}; chunks are extra evidence the vector search did not return.
    """
    uid = uuid.UUID(user_id)
    exclude_chunk_ids = exclude_chunk_ids or set()

    async with pool.acquire() as conn:
        seeds = await find_seed_entities(conn, uid, query, query_embedding, num_seeds, seed_max_distance)
        if not seeds:
            return {"nodes": [], "links": [], "chunks": [], "seeds": []}

        seed_score = {s["entity_id"]: s["score"] for s in seeds}
        seed_ids = list(seed_score)

        edge_rows = await conn.fetch(
            """
            SELECT rel_id, source_entity_id, target_entity_id, predicate, description, weight
            FROM relationships
            WHERE user_id = $1 AND (source_entity_id = ANY($2) OR target_entity_id = ANY($2))
            """, uid, seed_ids)

        # Rank by evidence (weight) x seed relevance, and cap per seed so one hub cannot take every slot.
        per_seed_cap = max(2, math.ceil(max_edges / len(seed_ids)))
        taken: dict[uuid.UUID, int] = {}
        scored = []
        for r in edge_rows:
            rel_seeds = [e for e in (r["source_entity_id"], r["target_entity_id"]) if e in seed_score]
            score = float(r["weight"]) * max(seed_score[e] for e in rel_seeds)
            scored.append((score, r, rel_seeds))
        scored.sort(key=lambda x: -x[0])

        edges = []
        for score, r, rel_seeds in scored:
            if len(edges) >= max_edges:
                break
            if all(taken.get(e, 0) >= per_seed_cap for e in rel_seeds):
                continue
            for e in rel_seeds:
                taken[e] = taken.get(e, 0) + 1
            edges.append(r)

        node_ids = set(seed_ids)
        for r in edges:
            node_ids.update((r["source_entity_id"], r["target_entity_id"]))
        node_rows = await conn.fetch(
            "SELECT entity_id, name, category, description FROM entities WHERE user_id = $1 AND entity_id = ANY($2)",
            uid, list(node_ids))

        # Graph-found chunks: chunks that mention a seed entity or support a selected edge, preferring
        # ones that do both. This is what lets a question reach text the embedding search missed.
        chunk_rows = []
        if extra_chunks > 0:
            chunk_rows = await conn.fetch(
                """
                WITH cand AS (
                    SELECT chunk_id, COUNT(DISTINCT entity_id) * 1.0 AS s
                    FROM chunk_entity_junction WHERE entity_id = ANY($2) GROUP BY chunk_id
                    UNION ALL
                    SELECT chunk_id, COUNT(*) * 2.0 AS s
                    FROM relationship_mentions WHERE rel_id = ANY($3) GROUP BY chunk_id
                )
                SELECT dc.chunk_id, d.filename, dc.page_number, dc.text_content,
                       (dc.embedding <=> $1) AS distance, SUM(cand.s) AS graph_score
                FROM cand
                JOIN document_chunks dc ON dc.chunk_id = cand.chunk_id
                JOIN documents d ON d.doc_id = dc.doc_id
                WHERE d.user_id = $4 AND (dc.embedding <=> $1) < $5 AND dc.chunk_id <> ALL($6::int[])
                GROUP BY dc.chunk_id, d.filename, dc.page_number, dc.text_content, dc.embedding
                ORDER BY SUM(cand.s) DESC, (dc.embedding <=> $1) ASC
                LIMIT $7
                """, query_embedding, seed_ids, [r["rel_id"] for r in edges], uid,
                chunk_max_distance, list(exclude_chunk_ids), extra_chunks)

    primary = str(seeds[0]["entity_id"])
    nodes = []
    for r in node_rows:
        node = {"id": str(r["entity_id"]), "name": r["name"], "category": r["category"], "description": r["description"]}
        if str(r["entity_id"]) == primary:
            node["isPrimarySeed"] = True
        nodes.append(node)
    links = [{"source": str(r["source_entity_id"]), "target": str(r["target_entity_id"]), "predicate": r["predicate"],
              "description": r["description"], "weight": float(r["weight"])} for r in edges]
    chunks = [{"chunk_id": r["chunk_id"], "filename": r["filename"], "page": r["page_number"], "text": r["text_content"],
               "distance": float(r["distance"]), "via": "graph"} for r in chunk_rows]
    return {"nodes": nodes, "links": links, "chunks": chunks,
            "seeds": [{"name": s["name"], "match": s["match"], "score": round(s["score"], 3)} for s in seeds]}
