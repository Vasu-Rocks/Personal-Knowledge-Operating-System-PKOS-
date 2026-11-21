"""
G4/G6 evaluation: vector-only retrieval vs graph-expanded retrieval on a fixed question set.

  python eval_graph.py                       # retrieval metrics + generated answers
  python eval_graph.py --no-answers          # retrieval metrics only (fast, no LLM)
  python eval_graph.py --questions eval/questions_intro_ml.json --out eval/results

Metrics (rough, keyword-based, so read the saved answers too):
  chunk coverage  - share of the question's key facts (keywords) present in the chunks sent to the LLM
  answer coverage - share of key facts present in the generated answer
"""
import argparse
import asyncio
import io
import json
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from starlette.concurrency import run_in_threadpool

from database.postgres_core import init_db_pool
from rag.query.generator import generate_rag_response
from rag.query.prompt_builder import build_rag_prompt
from rag.query.retrieval import retrieve_context
from rag.query.retriever import format_context_blocks
from rag.vector.embedder import embed_query

# (graph expansion on/off, vector top-k). "vector5" is the control: same number of chunks as "graph", no graph.
# (graph expansion, vector top-k, global search). "global" = graph + the broad-question router (G5).
MODES = {"vector": (False, 3, False), "vector5": (False, 5, False), "graph": (True, 3, False), "global": (True, 3, True)}


def coverage(keywords: list[str], text: str) -> float:
    text = text.lower()
    return sum(1 for k in keywords if k.lower() in text) / len(keywords)


async def run_mode(pool, user_id, question, expansion, vector_k, global_search, answers):
    query_vector = (await run_in_threadpool(embed_query, question)).flatten().tolist()
    chunks, graph = await retrieve_context(pool, user_id, question, query_vector, expansion=expansion, vector_k=vector_k,
                                          global_search=global_search)
    context, used = format_context_blocks(chunks)
    result = {
        "chunks": [{"via": c["via"], "filename": c["filename"], "page": c["page"], "distance": round(c["distance"], 3), "text": c["text"]} for c in used],
        "graph_nodes": len(graph.get("nodes", [])),
        "graph_links": len(graph.get("links", [])),
        "context_chars": len(context),
    }
    if answers:
        prompt = build_rag_prompt(question, context, graph)
        start = time.perf_counter()
        result["answer"] = await run_in_threadpool(generate_rag_response, prompt)
        result["answer_seconds"] = round(time.perf_counter() - start, 1)
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", default="eval/questions_intro_ml.json")
    parser.add_argument("--out", default="eval/results")
    parser.add_argument("--no-answers", action="store_true")
    parser.add_argument("--ids", help="comma-separated question ids to run, e.g. b1,b2")
    parser.add_argument("--user", help="user_id (default: owner of the first document)")
    args = parser.parse_args()

    questions = json.load(open(args.questions, encoding="utf-8"))
    if args.ids:
        questions = [q for q in questions if q["id"] in args.ids.split(",")]
    pool = await init_db_pool()
    try:
        async with pool.acquire() as conn:
            # Default: the user with the most chunks, i.e. the owner of the book the questions are about.
            user_id = args.user or str(await conn.fetchval(
                "SELECT d.user_id FROM documents d JOIN document_chunks dc USING (doc_id) "
                "GROUP BY d.user_id ORDER BY COUNT(*) DESC LIMIT 1"))

        rows = []
        for q in questions:
            row = {"id": q["id"], "type": q["type"], "q": q["q"], "keywords": q["keywords"]}
            for mode, (expansion, vector_k, global_search) in MODES.items():
                res = await run_mode(pool, user_id, q["q"], expansion, vector_k, global_search, not args.no_answers)
                res["chunk_coverage"] = coverage(q["keywords"], " ".join(c["text"] for c in res["chunks"]))
                # Cross-document metric: share of the books the question needs that contribute a retrieved chunk.
                if q.get("docs"):
                    files = [c["filename"] for c in res["chunks"]]
                    res["book_coverage"] = sum(1 for d in q["docs"] if any(f.startswith(d) for f in files)) / len(q["docs"])
                else:
                    res["book_coverage"] = 1.0
                if "answer" in res:
                    res["answer_coverage"] = coverage(q["keywords"], res["answer"])
                row[mode] = res
            rows.append(row)
            print(f"{q['id']:3} {q['type']:6} chunk coverage " + " ".join(f"{m}={row[m]['chunk_coverage']:.2f}" for m in MODES)
                  + " | book coverage " + " ".join(f"{m}={row[m]['book_coverage']:.2f}" for m in MODES)
                  + (" | answer coverage " + " ".join(f"{m}={row[m]['answer_coverage']:.2f}" for m in MODES) if not args.no_answers else "")
                  + f" | graph chunks: {sum(1 for c in row['graph']['chunks'] if c['via'] == 'graph')}"
                  + f" | community summaries (global): {sum(1 for c in row['global']['chunks'] if c['via'] == 'community')}", flush=True)

        print("\n== Mean by question type (vector -> graph) ==")
        for t in ["single", "multi", "cross", "broad", "all"]:
            sel = [r for r in rows if t == "all" or r["type"] == t]
            if not sel:
                continue
            def mean(mode, key):
                return sum(r[mode][key] for r in sel) / len(sel)
            line = f"{t:6} n={len(sel):2} chunk coverage " + " ".join(f"{m}={mean(m, 'chunk_coverage'):.2f}" for m in MODES)
            line += " | book coverage " + " ".join(f"{m}={mean(m, 'book_coverage'):.2f}" for m in MODES)
            if not args.no_answers:
                line += " | answer coverage " + " ".join(f"{m}={mean(m, 'answer_coverage'):.2f}" for m in MODES)
            print(line)

        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        json_path, md_path = f"{args.out}_{stamp}.json", f"{args.out}_{stamp}.md"
        json.dump(rows, open(json_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# Vector-only vs graph-expanded retrieval\n\n")
            for r in rows:
                f.write(f"## {r['id']} ({r['type']}): {r['q']}\n\nKey facts: {', '.join(r['keywords'])}\n\n")
                for mode in MODES:
                    m = r[mode]
                    f.write(f"### {mode} - chunk coverage {m['chunk_coverage']:.2f}"
                            + (f", answer coverage {m['answer_coverage']:.2f}" if "answer" in m else "")
                            + f" ({m['graph_nodes']} graph nodes, {m['graph_links']} links, {m['context_chars']} context chars)\n\n")
                    f.write("Sources: " + "; ".join(f"p{c['page']} {c['via']} d={c['distance']}" for c in m["chunks"]) + "\n\n")
                    if "answer" in m:
                        f.write(m["answer"].strip() + "\n\n")
        print(f"\nSaved {md_path} and {json_path}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
