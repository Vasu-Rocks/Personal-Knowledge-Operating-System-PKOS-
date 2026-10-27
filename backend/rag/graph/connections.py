"""
Cross-document exploration of the knowledge graph:
  lookup_term      - where does a word appear (which books, which pages) and what is it linked to in each book?
  find_connection  - how are two words connected, and which books does the chain pass through?

A word is resolved to graph entities in four ways, best first: exact (same squashed name, so 'tf-idf' = 'TF_IDF'),
variant (plural or one-letter difference: 'BRFS' -> 'BRFSS'), contains (the word inside a longer name:
'regression' -> 'Ridge Regression'), and similar (nearest by embedding, so spellings and near-synonyms from
different books land on each other). Everything is scoped to one user.
"""
import math
import re
import uuid

import asyncpg
import networkx as nx
from starlette.concurrency import run_in_threadpool

from rag.graph.vocab import is_generic_name as _is_generic, squash
from rag.vector.embedder import embed_text_batch

SIMILAR_MAX_DISTANCE = 0.15  # cosine distance; measured: a nonsense word never gets closer than ~0.29 to any entity
MAX_SIMILAR = 5
MAX_MATCHES = 10
MAX_PATH_HOPS = 6
SNIPPET_CHARS = 420


def _number_ratio(text: str) -> float:
    """Share of whitespace-separated tokens that are bare numbers: high for indexes and tables, low for prose."""
    tokens = text.split()
    return sum(t.strip(".,;:()[]").isdigit() for t in tokens) / max(1, len(tokens))


def _excerpt(text: str, needles: list[str]) -> str:
    """A window of the passage centred on the first occurrence of any matched word."""
    flat = " ".join(text.split())
    low = flat.lower()
    hits = [i for i in (low.find(n) for n in needles) if i >= 0]
    start = max(0, min(hits) - SNIPPET_CHARS // 3) if hits else 0
    piece = flat[start:start + SNIPPET_CHARS]
    return ("..." if start else "") + piece + ("..." if start + SNIPPET_CHARS < len(flat) else "")


def _short(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if filename.lower().endswith(".pdf") else filename


async def resolve_term(conn: asyncpg.Connection, user_id: uuid.UUID, term: str, limit: int = MAX_MATCHES) -> list[dict]:
    """Entities a word may refer to, best first: exact, then contains, then similar-by-embedding."""
    key = squash(term)
    if not key:
        return []
    found: dict[uuid.UUID, dict] = {}

    def add(rows, match, score_fn):
        for r in rows:
            if r["entity_id"] not in found:
                found[r["entity_id"]] = {"entity_id": r["entity_id"], "name": r["name"], "category": r["category"],
                                         "description": r["description"], "mentions": r["mentions"],
                                         "match": match, "score": score_fn(r)}

    mentions = "(SELECT COUNT(*) FROM chunk_entity_junction j WHERE j.entity_id = e.entity_id) AS mentions"
    add(await conn.fetch(f"""
        SELECT e.entity_id, e.name, e.category, e.description, {mentions}
        FROM entities e WHERE e.user_id = $1 AND e.canonical_name = $2""", user_id, key),
        "exact", lambda r: 1.0)

    if len(key) >= 3:
        # Plurals and one-letter variants ('BRFS' -> 'BRFSS', 'outlier' -> 'outliers').
        add(await conn.fetch(f"""
            SELECT e.entity_id, e.name, e.category, e.description, {mentions}
            FROM entities e
            WHERE e.user_id = $1 AND e.canonical_name LIKE $2 AND e.canonical_name <> $3
              AND length(e.canonical_name) <= $4
            ORDER BY mentions DESC LIMIT $5""", user_id, key.replace("%", "") + "%", key, len(key) + 2, limit),
            "variant", lambda r: 0.95)

    if len(key) >= 4:
        add(await conn.fetch(f"""
            SELECT e.entity_id, e.name, e.category, e.description, {mentions}
            FROM entities e WHERE e.user_id = $1 AND e.name ~* $2 AND e.canonical_name <> $3
            ORDER BY mentions DESC LIMIT $4""", user_id, r"\y" + re.escape(term.strip()) + r"\y", key, limit),
            "contains", lambda r: 0.9)

    vector = (await run_in_threadpool(embed_text_batch, [f"Name: {term}. Description: "]))[0].tolist()
    add(await conn.fetch(f"""
        SELECT e.entity_id, e.name, e.category, e.description, {mentions}, (e.embedding <=> $2) AS distance
        FROM entities e
        WHERE e.user_id = $1 AND (e.embedding <=> $2) < $3
        ORDER BY e.embedding <=> $2 LIMIT $4""", user_id, vector, SIMILAR_MAX_DISTANCE, MAX_SIMILAR),
        "similar", lambda r: round(1 - float(r["distance"]), 3))

    ranked = sorted(found.values(), key=lambda m: ({"exact": 0, "variant": 1, "contains": 2, "similar": 3}[m["match"]], -m["mentions"]))
    return ranked[:limit]


async def lookup_term(pool: asyncpg.Pool, user_id: str, term: str) -> dict:
    uid = uuid.UUID(user_id)
    async with pool.acquire() as conn:
        matches = await resolve_term(conn, uid, term)
        if not matches:
            return {"term": term, "matches": [], "books": []}
        ids = [m["entity_id"] for m in matches]
        names = {m["entity_id"]: m["name"] for m in matches}

        # Which chunks mention the matched entities, per book (best chunks first: those mentioning several matches).
        chunk_rows = await conn.fetch("""
            SELECT d.filename, dc.chunk_id, dc.page_number, dc.text_content, COUNT(DISTINCT j.entity_id) AS hits
            FROM chunk_entity_junction j
            JOIN document_chunks dc ON dc.chunk_id = j.chunk_id
            JOIN documents d ON d.doc_id = dc.doc_id
            WHERE j.entity_id = ANY($1) AND d.user_id = $2
            GROUP BY d.filename, dc.chunk_id, dc.page_number, dc.text_content
            ORDER BY hits DESC, dc.chunk_id""", ids, uid)

        # What the matched entities are linked to, per book (relationship_mentions says which book supports an edge).
        edge_rows = await conn.fetch("""
            SELECT d.filename, r.rel_id, r.predicate, r.source_entity_id, r.target_entity_id,
                   s.name AS source_name, t.name AS target_name, COUNT(*) AS support
            FROM relationships r
            JOIN relationship_mentions m ON m.rel_id = r.rel_id
            JOIN document_chunks dc ON dc.chunk_id = m.chunk_id
            JOIN documents d ON d.doc_id = dc.doc_id
            JOIN entities s ON s.entity_id = r.source_entity_id
            JOIN entities t ON t.entity_id = r.target_entity_id
            WHERE r.user_id = $2 AND (r.source_entity_id = ANY($1) OR r.target_entity_id = ANY($1))
            GROUP BY d.filename, r.rel_id, r.predicate, r.source_entity_id, r.target_entity_id, s.name, t.name
            ORDER BY support DESC""", ids, uid)

    books: dict[str, dict] = {}
    candidates: dict[str, list] = {}
    for r in chunk_rows:
        b = books.setdefault(r["filename"], {"filename": r["filename"], "book": _short(r["filename"]),
                                             "mentions": 0, "pages": set(), "chunks": [], "neighbors": []})
        b["mentions"] += 1
        b["pages"].add(r["page_number"])
        candidates.setdefault(r["filename"], []).append(r)
    needles = [n.lower() for n in names.values()]
    for filename, rows in candidates.items():
        # Prefer prose over index pages and tables (lots of digits), then passages naming several matched words.
        scored = sorted(rows[:40], key=lambda r: (_number_ratio(r["text_content"]) > 0.12, -r["hits"]))
        books[filename]["chunks"] = [{"page": r["page_number"], "text": _excerpt(r["text_content"], needles)}
                                     for r in scored[:2]]
    for r in edge_rows:
        b = books.get(r["filename"])
        if b is None or len(b["neighbors"]) >= 10:
            continue
        outgoing = r["source_entity_id"] in names
        other = r["target_name"] if outgoing else r["source_name"]
        if other in names.values():
            continue  # a link between two spellings of the searched word is not interesting
        b["neighbors"].append({"rel_id": str(r["rel_id"]), "name": other, "predicate": r["predicate"],
                               "direction": "out" if outgoing else "in",
                               "support": r["support"]})
    for b in books.values():
        b["pages"] = sorted(b["pages"])[:12]

    return {
        "term": term,
        "matches": [{"name": m["name"], "category": m["category"], "description": m["description"],
                     "match": m["match"], "score": m["score"], "mentions": m["mentions"]} for m in matches],
        "books": sorted(books.values(), key=lambda b: -b["mentions"]),
    }


def _build_graph(edges, names: dict) -> nx.Graph:
    """Undirected view of the user's graph. Hubs cost more to pass through, so paths prefer specific links."""
    G = nx.Graph()
    best: dict[frozenset, dict] = {}
    for e in edges:
        a, b = e["source_entity_id"], e["target_entity_id"]
        key = frozenset((a, b))
        if key not in best or e["weight"] > best[key]["weight"]:
            best[key] = {"rel_id": e["rel_id"], "predicate": e["predicate"], "source": a, "target": b,
                         "weight": float(e["weight"] or 1.0)}
    for key, data in best.items():
        a, b = tuple(key)
        G.add_edge(a, b, **data)
    degree = dict(G.degree())
    for a, b, data in G.edges(data=True):
        hub_penalty = 0.15 * (math.log1p(degree[a]) + math.log1p(degree[b]))
        generic = sum(1 for n in (a, b) if _is_generic(names.get(n, "")))
        data["cost"] = (1 + hub_penalty) / (1 + 0.2 * math.log1p(data["weight"])) + GENERIC_PENALTY * generic
    return G


GENERIC_PENALTY = 3.0
MAX_ALTERNATIVES = 3


def _strongest_tier(cands: list[dict]) -> list[dict]:
    """If the word names an entity (exactly or as a variant), use only those; weaker matches are for when it doesn't."""
    strong = [c for c in cands if c["match"] in ("exact", "variant")]
    return strong or cands


async def find_connection(pool: asyncpg.Pool, user_id: str, term_a: str, term_b: str) -> dict:
    uid = uuid.UUID(user_id)
    async with pool.acquire() as conn:
        cands_a = _strongest_tier(await resolve_term(conn, uid, term_a, 4))
        cands_b = _strongest_tier(await resolve_term(conn, uid, term_b, 4))
        result = {"a": term_a, "b": term_b,
                  "resolved_a": [{"name": c["name"], "match": c["match"], "score": c["score"]} for c in cands_a],
                  "resolved_b": [{"name": c["name"], "match": c["match"], "score": c["score"]} for c in cands_b]}
        if not cands_a or not cands_b:
            missing = [t for t, c in ((term_a, cands_a), (term_b, cands_b)) if not c]
            return {**result, "found": False, "reason": f"No concept in your documents matches: {', '.join(missing)}."}
        if {c["entity_id"] for c in cands_a} & {c["entity_id"] for c in cands_b}:
            return {**result, "found": False,
                    "reason": "Both words refer to the same concept in your documents; use Look up for that."}

        edges = await conn.fetch("""
            SELECT rel_id, source_entity_id, target_entity_id, predicate, weight
            FROM relationships WHERE user_id = $1""", uid)
        names = {r["entity_id"]: r["name"] for r in await conn.fetch(
            "SELECT entity_id, name FROM entities WHERE user_id = $1", uid)}
        G = await run_in_threadpool(_build_graph, edges, names)

        best = None  # (cost, a_entity, b_entity)
        for ca in cands_a:
            for cb in cands_b:
                a, b = ca["entity_id"], cb["entity_id"]
                if a not in G or b not in G:
                    continue
                try:
                    cost = nx.shortest_path_length(G, a, b, weight="cost")
                except nx.NetworkXNoPath:
                    continue
                if best is None or cost < best[0]:
                    best = (cost, a, b)
        if best is None:
            return {**result, "found": False, "reason": "These two concepts are not connected in your graph."}

        # Best path, plus up to two alternatives between the same two concepts.
        paths = []
        for path in nx.shortest_simple_paths(G, best[1], best[2], weight="cost"):
            if len(path) - 1 > MAX_PATH_HOPS:
                break
            paths.append(path)
            if len(paths) >= MAX_ALTERNATIVES:
                break
        if not paths:
            return {**result, "found": False, "reason": f"No chain of {MAX_PATH_HOPS} or fewer links connects them in your graph."}

        all_nodes = list({n for p in paths for n in p})
        all_rels = list({G[u][v]["rel_id"] for p in paths for u, v in zip(p, p[1:])})
        node_rows = await conn.fetch("""
            SELECT e.entity_id, e.name, e.category,
                   COALESCE(array_agg(DISTINCT d.filename) FILTER (WHERE d.filename IS NOT NULL), '{}') AS books
            FROM entities e
            LEFT JOIN chunk_entity_junction j ON j.entity_id = e.entity_id
            LEFT JOIN document_chunks dc ON dc.chunk_id = j.chunk_id
            LEFT JOIN documents d ON d.doc_id = dc.doc_id
            WHERE e.entity_id = ANY($1) GROUP BY e.entity_id, e.name, e.category""", all_nodes)
        link_books = {r["rel_id"]: sorted(r["books"]) for r in await conn.fetch("""
            SELECT m.rel_id, array_agg(DISTINCT d.filename) AS books
            FROM relationship_mentions m
            JOIN document_chunks dc ON dc.chunk_id = m.chunk_id
            JOIN documents d ON d.doc_id = dc.doc_id
            WHERE m.rel_id = ANY($1) GROUP BY m.rel_id""", all_rels)}

    nodes = {r["entity_id"]: r for r in node_rows}

    def describe(path) -> dict:
        steps = [{"name": nodes[n]["name"], "category": nodes[n]["category"],
                  "books": [_short(b) for b in sorted(nodes[n]["books"])]} for n in path]
        links = []
        for u, v in zip(path, path[1:]):
            d = G[u][v]
            links.append({"rel_id": str(d["rel_id"]), "predicate": d["predicate"], "weight": d["weight"],
                          "forward": d["source"] == u,  # False: the stored edge points from the next node back to this one
                          "books": [_short(b) for b in link_books.get(d["rel_id"], [])]})
        # Books that actually support a link in the chain (a node merely appearing in a book does not count).
        on_path = {b for l in links for b in l["books"]}
        weights = [l["weight"] for l in links]
        return {"hops": len(links), "steps": steps, "links": links, "books_on_path": sorted(on_path),
                "crosses_books": len(on_path) > 1,
                "bridge_concepts": [s["name"] for s in steps[1:-1] if len(s["books"]) > 1],
                "generic_nodes": [s["name"] for s in steps[1:-1] if _is_generic(s["name"])],
                # A long chain whose links mostly rest on a single passage is as likely a coincidence of extraction as a finding.
                "strong_links": sum(1 for w in weights if w >= 2),
                "weak": len(links) >= 3 and 2 * sum(1 for w in weights if w >= 2) < len(links)}

    described = [describe(p) for p in paths]
    return {**result, "found": True, **described[0], "alternatives": described[1:]}


async def get_evidence(pool: asyncpg.Pool, user_id: str, rel_id: str) -> dict | None:
    """The passages a relationship was extracted from, with an excerpt around the two concept names.
    Returns None when the relationship does not exist or belongs to another user."""
    uid = uuid.UUID(user_id)
    async with pool.acquire() as conn:
        rel = await conn.fetchrow("""
            SELECT r.rel_id, r.predicate, r.weight, s.name AS source, t.name AS target
            FROM relationships r
            JOIN entities s ON s.entity_id = r.source_entity_id
            JOIN entities t ON t.entity_id = r.target_entity_id
            WHERE r.rel_id = $1 AND r.user_id = $2""", uuid.UUID(rel_id), uid)
        if rel is None:
            return None
        rows = await conn.fetch("""
            SELECT d.filename, dc.page_number, dc.text_content
            FROM relationship_mentions m
            JOIN document_chunks dc ON dc.chunk_id = m.chunk_id
            JOIN documents d ON d.doc_id = dc.doc_id
            WHERE m.rel_id = $1 AND d.user_id = $2
            ORDER BY d.filename, dc.page_number""", rel["rel_id"], uid)
    needles = [rel["source"].lower(), rel["target"].lower()]
    return {
        "rel_id": str(rel["rel_id"]), "source": rel["source"], "predicate": rel["predicate"], "target": rel["target"],
        "weight": float(rel["weight"]),
        "passages": [{"book": _short(r["filename"]), "filename": r["filename"], "page": r["page_number"],
                      "excerpt": _excerpt(r["text_content"], needles)} for r in rows],
        # Relationships extracted before provenance existed (G1) have no recorded passages.
        "note": None if rows else "No passages are recorded for this relationship (it predates evidence tracking).",
    }
