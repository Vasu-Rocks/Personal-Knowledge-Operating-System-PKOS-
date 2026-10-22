"""
Phase G0 baseline for Graph RAG. Read-only: it never writes to the database.

  python graph_baseline.py                  # graph statistics for every user
  python graph_baseline.py --sample 10      # also time extraction on 10 random chunks
  python graph_baseline.py --user <uuid>    # restrict to one user
"""
import argparse
import asyncio
import json
import logging
import statistics
import sys
import os
import time
import uuid

import httpx

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.config import OLLAMA_BASE_URL, OLLAMA_GENERATE_URL, get_ollama_model
from database.postgres_core import init_db_pool
from rag.graph.extractor import GRAPH_SCHEMA

logging.basicConfig(level=logging.WARNING)


async def graph_stats(pool, user_id):
    clause = "WHERE user_id = $1" if user_id else ""
    args = [uuid.UUID(user_id)] if user_id else []
    chunk_join = "WHERE d.user_id = $1" if user_id else ""

    async with pool.acquire() as conn:
        print("== Counts ==")
        print("documents:", await conn.fetchval(f"SELECT COUNT(*) FROM documents {clause}", *args))
        print("chunks:", await conn.fetchval(
            f"SELECT COUNT(*) FROM document_chunks dc JOIN documents d USING (doc_id) {chunk_join}", *args))
        entities = await conn.fetchval(f"SELECT COUNT(*) FROM entities {clause}", *args)
        edges = await conn.fetchval(f"SELECT COUNT(*) FROM relationships {clause}", *args)
        print("entities:", entities)
        print("relationships:", edges)
        print("communities:", await conn.fetchval(f"SELECT COUNT(*) FROM communities {clause}", *args))
        print("communities pending summary:", await conn.fetchval(
            f"SELECT COUNT(*) FROM communities WHERE summary IS NULL {'AND user_id = $1' if user_id else ''}", *args))

        print("\n== Extraction status per document ==")
        for r in await conn.fetch(
                f"SELECT extraction_status, COUNT(*) AS n FROM documents {clause} GROUP BY 1 ORDER BY 2 DESC", *args):
            print(f"{r['extraction_status']}: {r['n']}")

        print("\n== Quality signals ==")
        print("entities without embedding:", await conn.fetchval(
            f"SELECT COUNT(*) FROM entities WHERE embedding IS NULL {'AND user_id = $1' if user_id else ''}", *args))
        print("entities per chunk (avg):", await conn.fetchval(
            f"""SELECT ROUND(AVG(c)::numeric, 2) FROM (
                    SELECT COUNT(*) AS c FROM chunk_entity_junction j
                    JOIN document_chunks dc USING (chunk_id) JOIN documents d USING (doc_id)
                    {chunk_join} GROUP BY j.chunk_id) t""", *args))
        print("chunks with graph entities:", await conn.fetchval(
            f"""SELECT COUNT(DISTINCT j.chunk_id) FROM chunk_entity_junction j
                JOIN document_chunks dc USING (chunk_id) JOIN documents d USING (doc_id) {chunk_join}""", *args))
        print("isolated entities (no edges):", await conn.fetchval(
            f"""SELECT COUNT(*) FROM entities e {('WHERE e.user_id = $1 AND' if user_id else 'WHERE')}
                NOT EXISTS (SELECT 1 FROM relationships r
                            WHERE r.source_entity_id = e.entity_id OR r.target_entity_id = e.entity_id)""", *args))
        print("edges with weight 1 (seen once):", await conn.fetchval(
            f"SELECT COUNT(*) FROM relationships WHERE weight <= 1 {'AND user_id = $1' if user_id else ''}", *args))
        print("distinct predicates:", await conn.fetchval(
            f"SELECT COUNT(DISTINCT predicate) FROM relationships {clause}", *args))
        print("junction rows with mention_snippet:", await conn.fetchval(
            "SELECT COUNT(*) FROM chunk_entity_junction WHERE mention_snippet IS NOT NULL"))

        print("\n== Entity categories ==")
        for r in await conn.fetch(
                f"SELECT category, COUNT(*) AS n FROM entities {clause} GROUP BY 1 ORDER BY 2 DESC LIMIT 15", *args):
            print(f"{r['category']}: {r['n']}")

        # Cheap duplicate signal: names equal after removing non-alphanumerics.
        dupes = await conn.fetch(
            f"""SELECT regexp_replace(canonical_name, '[^a-z0-9]', '', 'g') AS k,
                       array_agg(name) AS names
                FROM entities {clause} GROUP BY user_id, k HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC LIMIT 10""", *args)
        print(f"\n== Likely duplicate entities (top {len(dupes)}) ==")
        for r in dupes:
            print(list(r["names"]))

        print("\n== Community sizes ==")
        sizes = [len(json.loads(r["member_entities"]) if isinstance(r["member_entities"], str) else r["member_entities"] or [])
                 for r in await conn.fetch(f"SELECT member_entities FROM communities {clause}", *args)]
        if sizes:
            print(f"count={len(sizes)} min={min(sizes)} median={statistics.median(sizes)} max={max(sizes)}")
        else:
            print("none")


async def time_extraction(pool, user_id, n):
    """Run the extraction prompt on n random chunks and report latency and JSON validity."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT dc.text_content, d.filename FROM document_chunks dc
                JOIN documents d USING (doc_id)
                {'WHERE d.user_id = $2' if user_id else ''}
                ORDER BY random() LIMIT $1""",
            n, *([uuid.UUID(user_id)] if user_id else []))
    if not rows:
        print("\nNo chunks to sample.")
        return

    model = get_ollama_model()
    print(f"\n== Extraction timing: {len(rows)} chunks, model={model}, {OLLAMA_BASE_URL} ==")
    latencies, valid, ents, rels = [], 0, [], []
    async with httpx.AsyncClient(timeout=300.0) as client:
        for i, row in enumerate(rows, 1):
            prompt = (
                "You are an expert knowledge graph extractor.\n"
                "Extract entities and relationships strictly from the provided text.\n"
                f"The text comes from a document named: '{row['filename']}'.\n"
                "Output strictly valid JSON matching the schema.\n"
                "Use standardized, uppercase relationship predicates (e.g., USES, DEPENDS_ON, EXPLAINS).\n\n"
                f"[ACTIVE TEXT TO EXTRACT FROM]\n{row['text_content']}"
            )
            payload = {"model": model, "prompt": prompt, "format": GRAPH_SCHEMA, "stream": False,
                       "options": {"temperature": 0.0, "num_ctx": 2048}}
            start = time.perf_counter()
            resp = await client.post(OLLAMA_GENERATE_URL, json=payload)
            resp.raise_for_status()
            elapsed = time.perf_counter() - start
            body = resp.json()
            latencies.append(elapsed)
            try:
                data = json.loads(body.get("response", ""))
                valid += 1
                ents.append(len(data.get("entities", [])))
                rels.append(len(data.get("relationships", [])))
            except json.JSONDecodeError:
                pass
            print(f"chunk {i}/{len(rows)}: {elapsed:.1f}s, eval_tokens={body.get('eval_count')}")

    # The first call includes model load time, so report it separately from the steady state.
    steady = latencies[1:] or latencies
    print(f"first call (includes model load): {latencies[0]:.1f}s")
    print(f"steady-state seconds/chunk: mean={statistics.mean(steady):.1f} median={statistics.median(steady):.1f}")
    print(f"valid JSON: {valid}/{len(rows)}")
    if ents:
        print(f"avg entities/chunk: {statistics.mean(ents):.1f}, avg relationships/chunk: {statistics.mean(rels):.1f}")
    total = await _chunk_total(pool, user_id)
    print(f"estimated full extraction of {total} chunks: {total * statistics.mean(steady) / 3600:.1f} h")


async def _chunk_total(pool, user_id):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            f"SELECT COUNT(*) FROM document_chunks dc JOIN documents d USING (doc_id) "
            f"{'WHERE d.user_id = $1' if user_id else ''}",
            *([uuid.UUID(user_id)] if user_id else []))


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", help="restrict to one user_id")
    parser.add_argument("--sample", type=int, default=0, help="time extraction on N random chunks")
    args = parser.parse_args()

    pool = await init_db_pool()
    try:
        await graph_stats(pool, args.user)
        if args.sample:
            await time_extraction(pool, args.user, args.sample)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
