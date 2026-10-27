"""
K2: the knowledge map - every relation between concepts across the user's documents, filtered down to something
a person can read.

Modes
  backbone     links backed by 2+ distinct passages (default; ~560 concepts on a 3-book library)
  full         every link, nodes capped to the top N by PageRank
  communities  one node per community (topic), links = relations crossing between topics

Filters (all modes): documents, minimum support, categories, cross-document concepts only, hide generic names,
one community (drill-down). Links are undirected pairs that carry every relation between the two concepts, the
distinct passages behind them and the documents those passages come from.
"""
import math
import uuid
from collections import defaultdict

import asyncpg

MAX_NODES = 1000
MIN_TOPIC_SIZE = 10  # same floor as global search: smaller clusters are mostly example data and tangents
DEFAULT_LIMIT = 600  # the 3-book backbone is ~530 concepts; force layout stays smooth well past that
MODES = ("backbone", "full", "communities")


def _short(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if filename.lower().endswith(".pdf") else filename


async def build_map(pool: asyncpg.Pool, user_id: str, mode: str = "backbone", doc_ids: list[str] | None = None,
                    min_support: int | None = None, categories: list[str] | None = None, cross_book: bool = False,
                    hide_generic: bool = True, community_id: str | None = None, limit: int = DEFAULT_LIMIT) -> dict:
    uid = uuid.UUID(user_id)
    min_support = min_support if min_support is not None else (2 if mode == "backbone" else 1)
    limit = max(1, min(limit, MAX_NODES))
    cats = {c.upper() for c in categories} if categories else None

    async with pool.acquire() as conn:
        docs = await conn.fetch(
            "SELECT doc_id, filename FROM documents WHERE user_id = $1 ORDER BY created_at", uid)
        all_docs = {d["doc_id"] for d in docs}
        selected = {uuid.UUID(d) for d in doc_ids} & all_docs if doc_ids else all_docs

        rels = await conn.fetch("""
            SELECT r.rel_id, r.source_entity_id AS s, r.target_entity_id AS t, r.predicate, r.weight,
                   COALESCE(array_agg(m.chunk_id ORDER BY m.chunk_id) FILTER (WHERE m.chunk_id IS NOT NULL), '{}') AS chunks,
                   COALESCE(array_agg(dc.doc_id ORDER BY m.chunk_id) FILTER (WHERE m.chunk_id IS NOT NULL), '{}') AS chunk_docs
            FROM relationships r
            LEFT JOIN relationship_mentions m ON m.rel_id = r.rel_id
            LEFT JOIN document_chunks dc ON dc.chunk_id = m.chunk_id
            WHERE r.user_id = $1 AND r.source_entity_id <> r.target_entity_id
            GROUP BY r.rel_id""", uid)
        ents = await conn.fetch("""
            SELECT e.entity_id, e.name, e.category, s.mentions, s.pagerank, s.degree, s.strong_degree,
                   s.doc_ids, s.community_id, s.is_generic
            FROM entities e JOIN entity_stats s ON s.entity_id = e.entity_id
            WHERE e.user_id = $1""", uid)
        comms = {r["community_id"]: r for r in await conn.fetch(
            "SELECT community_id, title, summary FROM communities WHERE user_id = $1", uid)}

    entity = {e["entity_id"]: e for e in ents}
    node_docs = {eid: set(e["doc_ids"]) & selected for eid, e in entity.items()}

    def node_ok(eid) -> bool:
        e = entity.get(eid)
        if e is None or not node_docs[eid]:
            return False
        if hide_generic and e["is_generic"]:
            return False
        if cats and e["category"] not in cats:
            return False
        if cross_book and len(node_docs[eid]) < 2:
            return False
        if community_id and str(e["community_id"]) != community_id:
            return False
        return True

    # Aggregate relations into undirected pairs, counting only passages from the selected documents.
    pairs: dict[tuple, dict] = {}
    for r in rels:
        a, b = sorted((r["s"], r["t"]))
        evidence = {(c, d) for c, d in zip(r["chunks"], r["chunk_docs"]) if d in selected}
        if r["chunks"] and not evidence:
            continue  # this relation is only supported by documents outside the selection
        p = pairs.setdefault((a, b), {"rels": [], "chunks": set(), "docs": set(), "legacy_weight": 0.0})
        p["rels"].append({"rel_id": str(r["rel_id"]), "forward": r["s"] == a,  # True: points from link.source to link.target
                          "predicate": r["predicate"], "support": len(evidence) or int(r["weight"] or 1)})
        p["chunks"] |= {c for c, _ in evidence}
        p["docs"] |= {d for _, d in evidence}
        if not r["chunks"]:  # pre-provenance relation: only its stored weight is known
            p["legacy_weight"] = max(p["legacy_weight"], float(r["weight"] or 1))

    kept = []
    for (a, b), p in pairs.items():
        support = len(p["chunks"]) or int(p["legacy_weight"])
        if support < min_support or not (node_ok(a) and node_ok(b)):
            continue
        kept.append((a, b, support, p))

    total_nodes = {n for a, b, _, _ in kept for n in (a, b)}
    concepts_per_doc = defaultdict(int)
    for e in ents:
        for d in e["doc_ids"]:
            concepts_per_doc[d] += 1
    books = [{"doc_id": str(d["doc_id"]), "filename": d["filename"], "book": _short(d["filename"]),
              "selected": d["doc_id"] in selected, "concepts": concepts_per_doc[d["doc_id"]]} for d in docs]
    book_index = {d["doc_id"]: i for i, d in enumerate(docs)}  # nodes/links refer to books by index (smaller payload)

    if mode == "communities":
        return _communities_view(kept, entity, node_docs, comms, books, book_index, min_support, limit)

    # Keep the most central concepts when there are too many to draw.
    shown = set(sorted(total_nodes, key=lambda n: -entity[n]["pagerank"])[:limit])
    links = [(a, b, s, p) for a, b, s, p in kept if a in shown and b in shown]
    shown = {n for a, b, _, _ in links for n in (a, b)}  # drop concepts left without links after truncation

    nodes = [{
        "id": str(n), "name": entity[n]["name"], "category": entity[n]["category"],
        "mentions": entity[n]["mentions"],  # description comes from /graph/entity when a node is opened
        "pagerank": round(entity[n]["pagerank"], 6), "links": entity[n]["degree"],
        "strong_links": entity[n]["strong_degree"], "books": sorted(book_index[d] for d in node_docs[n]),
        "community_id": str(entity[n]["community_id"]) if entity[n]["community_id"] else None,
    } for n in shown]
    return {
        "mode": mode, "min_support": min_support, "books": books,
        "nodes": nodes,
        "links": [{"source": str(a), "target": str(b), "support": s,
                   "predicates": sorted({r["predicate"] for r in p["rels"]}), "relations": p["rels"],
                   "books": sorted(book_index[d] for d in p["docs"]),
                   "cross_book": len(p["docs"]) > 1} for a, b, s, p in links],
        "stats": {"matching_concepts": len(total_nodes), "shown_concepts": len(nodes),
                  "matching_links": len(kept), "shown_links": len(links), "truncated": len(total_nodes) > len(shown)},
    }


def _communities_view(kept, entity, node_docs, comms, books, book_index, min_support, limit) -> dict:
    members = defaultdict(set)
    for a, b, _, _ in kept:
        for n in (a, b):
            if entity[n]["community_id"] in comms:
                members[entity[n]["community_id"]].add(n)

    between = defaultdict(lambda: {"support": 0, "pairs": 0, "docs": set()})
    for a, b, s, p in kept:
        ca, cb = entity[a]["community_id"], entity[b]["community_id"]
        if ca in comms and cb in comms and ca != cb:
            key = tuple(sorted((ca, cb), key=str))
            between[key]["support"] += s
            between[key]["pairs"] += 1
            between[key]["docs"] |= p["docs"]

    ranked = [c for c in sorted(members, key=lambda c: -len(members[c])) if len(members[c]) >= MIN_TOPIC_SIZE][:limit]
    shown = set(ranked)
    nodes = []
    for c in ranked:
        top = sorted(members[c], key=lambda n: -entity[n]["pagerank"])
        docs = set().union(*(node_docs[n] for n in members[c]))
        summary = comms[c]["summary"] or ""
        nodes.append({"id": str(c), "name": comms[c]["title"], "category": "TOPIC", "size": len(members[c]),
                      "mentions": len(members[c]), "summary": summary[:600],
                      "top_members": [entity[n]["name"] for n in top[:8]], "books": sorted(book_index[d] for d in docs),
                      "pagerank": 0, "community_id": str(c)})
    links = [{"source": str(a), "target": str(b), "support": v["support"], "pairs": v["pairs"],
              "books": sorted(book_index[d] for d in v["docs"]), "cross_book": len(v["docs"]) > 1,
              # strength on a log scale so one dense topic pair does not dwarf the rest
              "width": round(1 + math.log2(1 + v["pairs"]), 2)}
             for (a, b), v in between.items() if a in shown and b in shown]
    return {"mode": "communities", "min_support": min_support, "books": books, "nodes": nodes, "links": links,
            "stats": {"matching_concepts": sum(len(m) for m in members.values()), "shown_concepts": len(nodes),
                      "matching_links": len(between), "shown_links": len(links), "truncated": len(members) > len(shown)}}
