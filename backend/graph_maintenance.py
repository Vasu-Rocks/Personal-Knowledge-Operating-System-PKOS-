"""
G3 clean-up for graphs built before name/predicate normalisation existed.

  python graph_maintenance.py            # dry run: report what would change, write nothing
  python graph_maintenance.py --apply    # back up the graph tables, then apply everything in one transaction

Steps: (1) delete noise entities (code variables, figure/chapter refs), (2) re-key entities with the
squashed canonical name and merge duplicates, (3) normalise predicates onto the fixed vocabulary
(flipping passive forms), (4) recompute edge weights from relationship_mentions, (5) mark communities stale.
Edges created before G1 have no relationship_mentions; their weights are summed when edges merge.
"""
import argparse
import asyncio
import collections
import io
import os
import sys
import time
import uuid

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from database.postgres_core import init_db_pool
from rag.graph.vocab import canonicalize, is_noise_entity, normalize_predicate

BACKUP_TABLES = ["entities", "relationships", "relationship_mentions", "chunk_entity_junction",
                 "communities", "community_members"]


async def plan(conn):
    """Computes the work without writing anything."""
    entities = await conn.fetch("""
        SELECT e.entity_id, e.user_id, e.name, e.canonical_name, e.description,
               (SELECT COUNT(*) FROM chunk_entity_junction j WHERE j.entity_id = e.entity_id) AS mentions
        FROM entities e""")

    noise = [e for e in entities if is_noise_entity(e["name"]) or not canonicalize(e["name"])]
    noise_ids = {e["entity_id"] for e in noise}

    groups: dict[tuple, list] = collections.defaultdict(list)
    for e in entities:
        if e["entity_id"] not in noise_ids:
            groups[(e["user_id"], canonicalize(e["name"]))].append(e)
    merges = {k: sorted(v, key=lambda e: (-e["mentions"], -len(e["description"] or ""), len(e["name"])))
              for k, v in groups.items() if len(v) > 1}
    rekeys = [(k, v[0]) for k, v in groups.items() if len(v) == 1 and v[0]["canonical_name"] != k[1]]

    preds = await conn.fetch("SELECT predicate, COUNT(*) AS n FROM relationships GROUP BY predicate")
    changed = collections.Counter()
    after = collections.Counter()
    for r in preds:
        new, flip = normalize_predicate(r["predicate"])
        after[new] += r["n"]
        if new != r["predicate"] or flip:
            changed[(r["predicate"], new, flip)] += r["n"]
    return {"entities": entities, "noise": noise, "merges": merges, "rekeys": rekeys,
            "predicates_before": len(preds), "predicates_after": len(after), "pred_changes": changed,
            "pred_after": after, "edges": sum(r["n"] for r in preds)}


def report(p):
    print(f"Entities: {len(p['entities'])}")
    print(f"\n1. Noise entities to delete: {len(p['noise'])}")
    print("   sample:", [e["name"] for e in p["noise"][:25]])
    lost = sum(len(v) - 1 for v in p["merges"].values())
    print(f"\n2. Duplicate groups: {len(p['merges'])} (removes {lost} entities); re-key only: {len(p['rekeys'])}")
    for (uid, key), v in sorted(p["merges"].items(), key=lambda kv: -len(kv[1]))[:20]:
        print(f"   {key!r}: keep {v[0]['name']!r} <- {[e['name'] for e in v[1:]]}")
    print(f"\n3. Predicates: {p['predicates_before']} distinct -> {p['predicates_after']} distinct over {p['edges']} edges")
    print("   most common after:", p["pred_after"].most_common(12))
    print("   biggest rewrites:", [(f"{a}->{b}{' (flip)' if f else ''}", n) for (a, b, f), n in p["pred_changes"].most_common(12)])


async def move_edge(conn, rel_id, user_id, source, target, predicate, weight):
    """Re-point or merge one edge. Returns 'moved' | 'merged' | 'dropped'."""
    if source == target:
        await conn.execute("DELETE FROM relationships WHERE rel_id = $1", rel_id)
        return "dropped"
    existing = await conn.fetchval("""
        SELECT rel_id FROM relationships
        WHERE user_id = $1 AND source_entity_id = $2 AND target_entity_id = $3 AND predicate = $4 AND rel_id <> $5
    """, user_id, source, target, predicate, rel_id)
    if existing is None:
        await conn.execute("""
            UPDATE relationships SET source_entity_id = $2, target_entity_id = $3, predicate = $4 WHERE rel_id = $1
        """, rel_id, source, target, predicate)
        return "moved"
    had_mentions = await conn.fetchval("SELECT COUNT(*) FROM relationship_mentions WHERE rel_id = $1", rel_id)
    await conn.execute("""
        INSERT INTO relationship_mentions (rel_id, chunk_id, snippet)
        SELECT $2, chunk_id, snippet FROM relationship_mentions WHERE rel_id = $1 ON CONFLICT DO NOTHING
    """, rel_id, existing)
    if not had_mentions:  # legacy edge without provenance: carry its weight over
        await conn.execute("UPDATE relationships SET weight = weight + $2 WHERE rel_id = $1", existing, weight)
    await conn.execute("""
        UPDATE relationships SET description = $2
        WHERE rel_id = $1 AND COALESCE(description, '') = ''
    """, existing, await conn.fetchval("SELECT description FROM relationships WHERE rel_id = $1", rel_id))
    await conn.execute("DELETE FROM relationships WHERE rel_id = $1", rel_id)
    return "merged"


async def merge_group(conn, key, members, stats):
    survivor, losers = members[0], members[1:]
    loser_ids = [e["entity_id"] for e in losers]
    sid = survivor["entity_id"]

    edges = await conn.fetch("""
        SELECT rel_id, user_id, source_entity_id, target_entity_id, predicate, weight FROM relationships
        WHERE source_entity_id = ANY($1) OR target_entity_id = ANY($1)""", loser_ids)
    for r in edges:
        src = sid if r["source_entity_id"] in loser_ids else r["source_entity_id"]
        tgt = sid if r["target_entity_id"] in loser_ids else r["target_entity_id"]
        stats["edges_" + await move_edge(conn, r["rel_id"], r["user_id"], src, tgt, r["predicate"], r["weight"])] += 1

    await conn.execute("""
        INSERT INTO community_members (community_id, entity_id)
        SELECT community_id, $2 FROM community_members WHERE entity_id = ANY($1) ON CONFLICT DO NOTHING
    """, loser_ids, sid)
    await conn.execute("DELETE FROM community_members WHERE entity_id = ANY($1)", loser_ids)
    await conn.execute("""
        INSERT INTO chunk_entity_junction (chunk_id, entity_id, mention_snippet)
        SELECT chunk_id, $2, mention_snippet FROM chunk_entity_junction WHERE entity_id = ANY($1) ON CONFLICT DO NOTHING
    """, loser_ids, sid)
    await conn.execute("DELETE FROM chunk_entity_junction WHERE entity_id = ANY($1)", loser_ids)  # orphan trigger may drop losers
    await conn.execute("DELETE FROM entities WHERE entity_id = ANY($1)", loser_ids)

    best_description = max([e["description"] or "" for e in members], key=len)
    await conn.execute("UPDATE entities SET canonical_name = $2, description = $3 WHERE entity_id = $1",
                       sid, key[1], best_description)
    stats["entities_merged"] += len(losers)


async def apply(conn, p):
    stats = collections.Counter()

    if p["noise"]:
        await conn.execute("DELETE FROM entities WHERE entity_id = ANY($1)", [e["entity_id"] for e in p["noise"]])
        stats["noise_deleted"] = len(p["noise"])

    for key, members in p["merges"].items():
        await merge_group(conn, key, members, stats)
    for key, e in p["rekeys"]:
        await conn.execute("UPDATE entities SET canonical_name = $2 WHERE entity_id = $1", e["entity_id"], key[1])
        stats["rekeyed"] += 1

    rows = await conn.fetch("SELECT rel_id, user_id, source_entity_id, target_entity_id, predicate, weight FROM relationships")
    for r in rows:
        new, flip = normalize_predicate(r["predicate"])
        if new == r["predicate"] and not flip:
            continue
        src, tgt = (r["target_entity_id"], r["source_entity_id"]) if flip else (r["source_entity_id"], r["target_entity_id"])
        stats["pred_" + await move_edge(conn, r["rel_id"], r["user_id"], src, tgt, new, r["weight"])] += 1

    await conn.execute("""
        UPDATE relationships r SET weight = m.c
        FROM (SELECT rel_id, COUNT(*)::float AS c FROM relationship_mentions GROUP BY rel_id) m
        WHERE r.rel_id = m.rel_id AND r.weight <> m.c""")
    if sum(stats.values()):
        await conn.execute("UPDATE communities SET is_stale = TRUE")
    return stats


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    args = parser.parse_args()

    pool = await init_db_pool()
    try:
        async with pool.acquire() as conn:
            p = await plan(conn)
            report(p)
            if not args.apply:
                print("\nDry run only. Re-run with --apply to back up and apply.")
                return

            suffix = time.strftime("%Y%m%d_%H%M%S")
            for t in BACKUP_TABLES:
                await conn.execute(f'CREATE TABLE "{t}_bak_{suffix}" AS SELECT * FROM {t}')
            print(f"\nBackup tables created: <table>_bak_{suffix} for {', '.join(BACKUP_TABLES)}")

            async with conn.transaction():
                stats = await apply(conn, p)
            print("Applied:", dict(stats))
            print("Now: entities", await conn.fetchval("SELECT COUNT(*) FROM entities"),
                  "| edges", await conn.fetchval("SELECT COUNT(*) FROM relationships"),
                  "| predicates", await conn.fetchval("SELECT COUNT(DISTINCT predicate) FROM relationships"))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
