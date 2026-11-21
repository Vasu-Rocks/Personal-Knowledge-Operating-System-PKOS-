"""
Removes repeating page headers/footers from PDFs that were ingested before header stripping existed, and the
graph links that came from them.

  python clean_headers.py            # dry run: report what would change, write nothing
  python clean_headers.py --apply    # back up chunks + graph tables, then apply in one transaction

How it works: PDF chunks are made page by page, so a page's header is at the start of its first chunk and its
footer at the end of its last chunk. The same detector used at ingestion finds lines repeated at those edges;
they are removed from the stored text, changed chunks are re-embedded, and entity/relationship links are dropped
only where the entity name occurred in the removed lines and nowhere else in the chunk. An entity that loses
its last link is deleted by the existing orphan trigger.
"""
import argparse
import asyncio
import collections
import io
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from database.postgres_core import init_db_pool
from rag.graph.vocab import squash
from rag.ingestion.headers import detect_repeating_edges, strip_edges
from rag.vector.embedder import embed_text_batch

CONTEXT_TAIL_CHARS = 150  # extraction grounded entities against the previous chunk's tail too
BACKUP_TABLES = ["document_chunks", "entities", "relationships", "relationship_mentions", "chunk_entity_junction",
                 "communities", "community_members"]


async def plan(conn):
    docs = await conn.fetch("SELECT doc_id, filename FROM documents WHERE lower(filename) LIKE '%.pdf' ORDER BY filename")
    changes, per_doc = [], {}
    for d in docs:
        rows = await conn.fetch(
            "SELECT chunk_id, page_number, text_content FROM document_chunks WHERE doc_id = $1 ORDER BY chunk_id",
            d["doc_id"])
        pages = collections.defaultdict(list)
        for r in rows:
            pages[r["page_number"]].append(r)
        # A page's edges are the start of its first chunk and the end of its last chunk.
        page_texts = [p[0]["text_content"] + "\n" + p[-1]["text_content"] if len(p) > 1 else p[0]["text_content"]
                      for p in pages.values()]
        headers = detect_repeating_edges(page_texts)
        per_doc[d["filename"]] = {"headers": sorted(headers), "chunks": len(rows), "changed": 0}
        if not headers:
            continue

        for page in pages.values():
            for idx, r in enumerate(page):
                text, removed = r["text_content"], []
                text, top = strip_edges(text, headers, top=(idx == 0), bottom=False)
                removed += top
                text, bottom = strip_edges(text, headers, top=False, bottom=(idx == len(page) - 1))
                removed += bottom
                if removed:
                    changes.append({"chunk_id": r["chunk_id"], "doc": d["filename"], "old": r["text_content"],
                                    "new": text.strip(), "removed": removed})
                    per_doc[d["filename"]]["changed"] += 1
        # Neighbouring-chunk tails, for the grounding check below.
        by_id = {r["chunk_id"]: r["text_content"] for r in rows}
        for c in changes:
            prev = max((i for i in by_id if i < c["chunk_id"]), default=None)
            c["context"] = by_id[prev][-CONTEXT_TAIL_CHARS:] if prev is not None else ""

    # Links to drop: the entity is named in the removed lines but not in the cleaned chunk (or its context).
    drop_links, drop_mentions = [], []
    for c in changes:
        gone, kept = squash(" ".join(c["removed"])), squash(c["new"] + " " + c["context"])
        for e in await conn.fetch(
                "SELECT e.entity_id, e.name, e.canonical_name FROM chunk_entity_junction j "
                "JOIN entities e USING (entity_id) WHERE j.chunk_id = $1", c["chunk_id"]):
            if e["canonical_name"] in gone and e["canonical_name"] not in kept:
                drop_links.append((c["chunk_id"], e["entity_id"], e["name"]))
        for m in await conn.fetch(
                "SELECT m.rel_id, s.canonical_name AS sk, t.canonical_name AS tk, s.name AS sn, t.name AS tn "
                "FROM relationship_mentions m JOIN relationships r USING (rel_id) "
                "JOIN entities s ON s.entity_id = r.source_entity_id JOIN entities t ON t.entity_id = r.target_entity_id "
                "WHERE m.chunk_id = $1", c["chunk_id"]):
            if any(k in gone and k not in kept for k in (m["sk"], m["tk"])):
                drop_mentions.append((m["rel_id"], c["chunk_id"], f"{m['sn']} -> {m['tn']}"))
    return {"per_doc": per_doc, "changes": changes, "drop_links": drop_links, "drop_mentions": drop_mentions}


def report(p):
    for name, d in p["per_doc"].items():
        print(f"{name}: {d['chunks']} chunks, {len(d['headers'])} header patterns, {d['changed']} chunks change")
        if d["headers"]:
            print("   patterns:", d["headers"][:10])
    print(f"\nChunks to rewrite and re-embed: {len(p['changes'])}")
    removed = collections.Counter(l for c in p["changes"] for l in c["removed"])
    print("Most common removed lines:", removed.most_common(8))
    print(f"Entity links to drop: {len(p['drop_links'])}", sorted({n for _, _, n in p['drop_links']})[:15])
    print(f"Edge mentions to drop: {len(p['drop_mentions'])}", [n for _, _, n in p['drop_mentions'][:6]])


async def apply(conn, p):
    changes = p["changes"]
    vectors = []
    for i in range(0, len(changes), 64):  # CPU embedding in batches, before the transaction opens
        vectors += embed_text_batch([c["new"] for c in changes[i:i + 64]]).tolist()

    async with conn.transaction():
        await conn.executemany("UPDATE document_chunks SET text_content = $2, embedding = $3 WHERE chunk_id = $1",
                               [(c["chunk_id"], c["new"], v) for c, v in zip(changes, vectors)])
        await conn.executemany("DELETE FROM relationship_mentions WHERE rel_id = $1 AND chunk_id = $2",
                               [(r, ch) for r, ch, _ in p["drop_mentions"]])
        # Deleting the last link of an entity makes the orphan trigger delete the entity itself.
        await conn.executemany("DELETE FROM chunk_entity_junction WHERE chunk_id = $1 AND entity_id = $2",
                               [(ch, e) for ch, e, _ in p["drop_links"]])
        await conn.execute("""
            INSERT INTO graph_state (user_id, dirty, updated_at)
            SELECT DISTINCT d.user_id, TRUE, now() FROM documents d
            WHERE d.filename = ANY($1) AND d.user_id IS NOT NULL
            ON CONFLICT (user_id) DO UPDATE SET dirty = TRUE, updated_at = now()
        """, sorted({c["doc"] for c in changes}))


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
            if not p["changes"]:
                print("\nNothing to change.")
                return

            suffix = time.strftime("%Y%m%d_%H%M%S")
            for t in BACKUP_TABLES:
                await conn.execute(f'CREATE TABLE "{t}_bak_{suffix}" AS SELECT * FROM {t}')
            print(f"\nBackup tables created: <table>_bak_{suffix}")
            await apply(conn, p)
            print("Applied. Communities will rebuild automatically (graph flagged dirty).")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
