"""
K1: graph analytics and same-concept suggestions, recomputed by the worker after every community rebuild.

entity_stats    one row per entity: degree, strong_degree (links backed by 2+ passages), PageRank, betweenness,
                mentions, the documents it appears in, its community and whether its name is generic. Maps and
                bridge rankings read these instead of running graph algorithms per request (~3-4 s on 3.5k nodes).
concept_links   pairs of entities from different documents whose embeddings are nearly identical: a candidate for
                "same concept, different name". Suggestions only; confirmed/rejected decisions survive recomputation.
"""
import logging
import uuid

import asyncpg
import networkx as nx
from starlette.concurrency import run_in_threadpool

from rag.graph.vocab import is_generic_name

logger = logging.getLogger(__name__)

BETWEENNESS_SAMPLES = 300  # sampled betweenness: exact is O(n*m), sampling keeps a rebuild at a few seconds
SAME_CONCEPT_MAX_DISTANCE = 0.10  # measured: real pairs (CDC names, BRFSS spellings) sit at 0.02-0.08
SAME_CONCEPT_NEIGHBOURS = 3


def _graph_metrics(edges, pair_support: dict) -> dict:
    """pair_support: {(a, b) sorted: distinct passages backing any relation between a and b}."""
    G = nx.Graph()
    strong = {}
    for e in edges:
        a, b, w = e["source_entity_id"], e["target_entity_id"], float(e["weight"] or 1.0)
        if a == b:
            continue
        if G.has_edge(a, b):
            G[a][b]["weight"] += w
        else:
            G.add_edge(a, b, weight=w)
    for a, b, d in G.edges(data=True):
        # Strength = distinct supporting passages for the pair, not summed weights: two predicates extracted
        # from one passage are still one piece of evidence.
        support = pair_support.get(tuple(sorted((a, b))), d["weight"])
        if support >= 2:
            strong[a] = strong.get(a, 0) + 1
            strong[b] = strong.get(b, 0) + 1
    if G.number_of_nodes() == 0:
        return {}
    pagerank = nx.pagerank(G, weight="weight")
    k = min(BETWEENNESS_SAMPLES, G.number_of_nodes())
    betweenness = nx.betweenness_centrality(G, k=k, seed=1)
    return {n: {"degree": G.degree(n), "strong_degree": strong.get(n, 0),
                "pagerank": pagerank[n], "betweenness": betweenness[n]} for n in G.nodes}


async def compute_entity_stats(pool: asyncpg.Pool, user_id: str) -> int:
    uid = uuid.UUID(user_id)
    async with pool.acquire() as conn:
        edges = await conn.fetch(
            "SELECT source_entity_id, target_entity_id, weight FROM relationships WHERE user_id = $1", uid)
        pair_support = {(r["a"], r["b"]): r["n"] for r in await conn.fetch("""
            SELECT LEAST(r.source_entity_id, r.target_entity_id) AS a,
                   GREATEST(r.source_entity_id, r.target_entity_id) AS b,
                   COUNT(DISTINCT m.chunk_id) AS n
            FROM relationships r JOIN relationship_mentions m ON m.rel_id = r.rel_id
            WHERE r.user_id = $1
            GROUP BY 1, 2""", uid)}
        entities = await conn.fetch("""
            SELECT e.entity_id, e.name,
                   COUNT(j.chunk_id) AS mentions,
                   COALESCE(array_agg(DISTINCT dc.doc_id) FILTER (WHERE dc.doc_id IS NOT NULL), '{}') AS doc_ids,
                   (SELECT cm.community_id FROM community_members cm WHERE cm.entity_id = e.entity_id LIMIT 1) AS community_id
            FROM entities e
            LEFT JOIN chunk_entity_junction j ON j.entity_id = e.entity_id
            LEFT JOIN document_chunks dc ON dc.chunk_id = j.chunk_id
            WHERE e.user_id = $1
            GROUP BY e.entity_id, e.name""", uid)

    metrics = await run_in_threadpool(_graph_metrics, edges, pair_support)
    zero = {"degree": 0, "strong_degree": 0, "pagerank": 0.0, "betweenness": 0.0}  # isolated entities
    rows = [(e["entity_id"], uid, *(lambda m: (m["degree"], m["strong_degree"], m["pagerank"], m["betweenness"]))(
                metrics.get(e["entity_id"], zero)),
             e["mentions"], list(e["doc_ids"]), len(e["doc_ids"]), e["community_id"], is_generic_name(e["name"]))
            for e in entities]

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM entity_stats WHERE user_id = $1", uid)
            await conn.executemany("""
                INSERT INTO entity_stats (entity_id, user_id, degree, strong_degree, pagerank, betweenness,
                                          mentions, doc_ids, book_count, community_id, is_generic)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""", rows)
    return len(rows)


async def suggest_same_concepts(pool: asyncpg.Pool, user_id: str) -> dict:
    """
    Pairs of entities that never appear in the same document, share a category and have near-identical
    embeddings. New pairs are added as 'suggested'; stale suggestions are dropped; decisions are kept.
    """
    uid = uuid.UUID(user_id)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT a.entity_id AS x, n.entity_id AS y, n.distance
            FROM entities a
            CROSS JOIN LATERAL (
                SELECT e.entity_id, (e.embedding <=> a.embedding) AS distance
                FROM entities e
                WHERE e.user_id = a.user_id AND e.entity_id <> a.entity_id AND e.category = a.category
                ORDER BY e.embedding <=> a.embedding
                LIMIT $3
            ) n
            JOIN entity_stats sa ON sa.entity_id = a.entity_id
            JOIN entity_stats sb ON sb.entity_id = n.entity_id
            WHERE a.user_id = $1 AND n.distance < $2
              AND sa.book_count > 0 AND sb.book_count > 0
              AND NOT (sa.doc_ids && sb.doc_ids)          -- different documents only: that is the cross-book gap
              AND NOT sa.is_generic AND NOT sb.is_generic""",
            uid, SAME_CONCEPT_MAX_DISTANCE, SAME_CONCEPT_NEIGHBOURS)

        pairs = {}
        for r in rows:
            a, b = sorted((r["x"], r["y"]))
            pairs[(a, b)] = min(float(r["distance"]), pairs.get((a, b), 1.0))

        async with conn.transaction():
            # Suggestions that no longer qualify (entity renamed, now co-occurring, ...) disappear; decisions stay.
            existing = {(r["entity_a"], r["entity_b"]): r["status"] for r in await conn.fetch(
                "SELECT entity_a, entity_b, status FROM concept_links WHERE user_id = $1", uid)}
            stale = [k for k, st in existing.items() if st == "suggested" and k not in pairs]
            if stale:
                await conn.executemany(
                    "DELETE FROM concept_links WHERE user_id = $1 AND entity_a = $2 AND entity_b = $3",
                    [(uid, a, b) for a, b in stale])
            new = [(uuid.uuid4(), uid, a, b, d) for (a, b), d in pairs.items() if (a, b) not in existing]
            if new:
                await conn.executemany("""
                    INSERT INTO concept_links (link_id, user_id, entity_a, entity_b, distance)
                    VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING""", new)
    return {"candidates": len(pairs), "added": len(new), "removed_stale": len(stale)}


async def refresh_analytics(pool: asyncpg.Pool, user_id: str) -> dict:
    stats = await compute_entity_stats(pool, user_id)
    suggestions = await suggest_same_concepts(pool, user_id)  # reads entity_stats, so it runs second
    return {"entity_stats": stats, "same_concept": suggestions}


async def list_same_concepts(pool: asyncpg.Pool, user_id: str, status: str = "suggested") -> list[dict]:
    uid = uuid.UUID(user_id)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT l.link_id, l.status, l.distance, a.name AS a_name, b.name AS b_name, a.category,
                   (SELECT array_agg(DISTINCT d.filename) FROM documents d WHERE d.doc_id = ANY(sa.doc_ids)) AS a_books,
                   (SELECT array_agg(DISTINCT d.filename) FROM documents d WHERE d.doc_id = ANY(sb.doc_ids)) AS b_books
            FROM concept_links l
            JOIN entities a ON a.entity_id = l.entity_a
            JOIN entities b ON b.entity_id = l.entity_b
            LEFT JOIN entity_stats sa ON sa.entity_id = l.entity_a
            LEFT JOIN entity_stats sb ON sb.entity_id = l.entity_b
            WHERE l.user_id = $1 AND l.status = $2
            ORDER BY l.distance""", uid, status)
    return [{"link_id": str(r["link_id"]), "status": r["status"], "similarity": round(1 - float(r["distance"]), 3),
             "category": r["category"],
             "a": {"name": r["a_name"], "books": sorted(r["a_books"] or [])},
             "b": {"name": r["b_name"], "books": sorted(r["b_books"] or [])}} for r in rows]


async def decide_same_concept(pool: asyncpg.Pool, user_id: str, link_id: str, status: str) -> bool:
    """Confirm, reject or reset one suggestion. Returns False if it does not exist for this user."""
    async with pool.acquire() as conn:
        done = await conn.fetchval("""
            UPDATE concept_links
            SET status = $3::varchar, decided_at = CASE WHEN $3::varchar = 'suggested' THEN NULL ELSE now() END
            WHERE link_id = $1 AND user_id = $2
            RETURNING link_id""", uuid.UUID(link_id), uuid.UUID(user_id), status)
    return done is not None


async def list_bridges(pool: asyncpg.Pool, user_id: str, limit: int = 20, category: str | None = None) -> list[dict]:
    """Concepts that appear in 2+ documents and sit on many paths between others (generic names excluded)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT e.name, e.category, s.betweenness, s.pagerank, s.degree, s.strong_degree, s.mentions,
                   (SELECT array_agg(DISTINCT d.filename) FROM documents d WHERE d.doc_id = ANY(s.doc_ids)) AS books
            FROM entity_stats s JOIN entities e ON e.entity_id = s.entity_id
            WHERE s.user_id = $1 AND s.book_count > 1 AND NOT s.is_generic
              AND ($3::text IS NULL OR e.category = $3)
            ORDER BY s.betweenness DESC
            LIMIT $2""", uuid.UUID(user_id), limit, category)
    return [{"name": r["name"], "category": r["category"], "books": sorted(r["books"] or []),
             "betweenness": round(r["betweenness"], 5), "pagerank": round(r["pagerank"], 5),
             "links": r["degree"], "strong_links": r["strong_degree"], "mentions": r["mentions"]} for r in rows]
