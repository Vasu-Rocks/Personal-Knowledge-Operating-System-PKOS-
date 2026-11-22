"""
Step 4 evaluation (docs/07_MEMORY_PLAN.md): does rewriting follow-up questions find the right passage more often?

  python eval_followups.py                  # uses the local Ollama model (OLLAMA_MODEL, default llama3.2)
  python eval_followups.py --model llama3.1 --k 3

For each case a short chat already happened (question + answer); the follow-up is then searched two ways over a small
corpus with the real embedding model: as typed, and after rewrite_question. A hit means the expected passage is among
the top k. Rework requests ("shorter please") check needs_search instead. No database is used.
"""
import argparse
import asyncio
import io
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

from core.llm import LLMSettings  # noqa: E402
from rag.memory.rewrite import rewrite_question  # noqa: E402
from rag.vector.embedder import embed_query, embed_text_batch  # noqa: E402

CORPUS = {
    "station": "The surveyor visits the Aletsch glacier station every Tuesday to read the temperature sensors and "
               "check the batteries of the weather mast.",
    "sensors": "The March meeting decided to order 12 new temperature sensors from Campbell Scientific; delivery is "
               "expected in six weeks and the cost is 4,800 euros.",
    "ice_loss": "Measurements show the glacier lost 2.7 metres of ice thickness in 2023, compared with 1.9 metres "
                "in 2022, the largest loss since records began.",
    "budget": "The project budget for 2024 is 120,000 euros: 70,000 for salaries, 30,000 for equipment and 20,000 "
              "for travel to the field sites.",
    "fastapi": "The backend is written in FastAPI; requests are validated with Pydantic models and the database is "
               "accessed through asyncpg connection pools.",
    "deploy": "Deployment uses a Windows installer built with electron-builder; the PostgreSQL database and Ollama "
              "are bundled and started by the desktop app.",
    "pasta": "For the tomato pasta, simmer crushed tomatoes with garlic and olive oil for twenty minutes, then add "
             "basil and toss with spaghetti cooked al dente.",
    "bread": "The sourdough needs a 12-hour cold proof in the fridge; bake it at 250 degrees for 20 minutes with "
             "the lid on and 25 minutes without.",
    "trip": "The Kyoto trip is planned for April 10 to 17; the hotel is near Gion and the tea ceremony is booked "
            "for April 12.",
    "visa": "Indian citizens need a tourist visa for Japan; apply at the VFS centre at least three weeks before "
            "travel with a bank statement and itinerary.",
    "exam": "The GATE exam covers engineering mathematics, digital logic, algorithms, operating systems and "
            "computer networks; the paper is three hours long.",
    "os_topics": "In operating systems, the most tested topics are process scheduling, deadlocks, paging and "
                 "virtual memory, and file system allocation.",
    # Distractors: same vocabulary, different facts, so a vague follow-up searched as typed can land on them.
    "mast_rhone": "The weather mast at the Rhone glacier was repaired in May; its wind sensor had failed during "
                  "the winter storms and the batteries were replaced.",
    "sensors_old": "The old temperature sensors were installed in 2015; several now drift by up to half a degree "
                   "and will arrive back from calibration in two weeks.",
    "ice_rhone": "The Rhone glacier lost 1.4 metres of ice thickness in 2023 and 1.1 metres the year before.",
    "budget_2023": "The 2023 budget was 95,000 euros; travel took 8,000 euros and the rest went to salaries.",
    "flask": "The first prototype used Flask with SQLite; the database was accessed directly with raw SQL strings.",
    "carbonara": "The carbonara uses eggs, pecorino and guanciale; let the pasta rest for one minute and never add "
                 "cream.",
    "osaka": "After Kyoto, two days in Osaka are planned; the hotel there is near Namba station.",
    "exam_dates": "The GATE exam is held in February; registration closes in October and the fee is 1,800 rupees.",
}

# (first question, first answer, follow-up, expected passage)
FOLLOW_UPS = [
    ("Who visits the glacier station?", "The surveyor visits it.", "How often does he go there?", "station"),
    ("Who visits the glacier station?", "The surveyor visits it every Tuesday.", "What does he check besides the sensors?", "station"),
    ("What did the March meeting decide?", "To order 12 new temperature sensors.", "How much will they cost?", "sensors"),
    ("What did the March meeting decide?", "To order 12 new temperature sensors.", "When will they arrive?", "sensors"),
    ("How much ice did the glacier lose in 2023?", "2.7 metres of thickness.", "And the year before?", "ice_loss"),
    ("What is the 2024 budget?", "120,000 euros in total.", "How much of it goes to travel?", "budget"),
    ("What is the backend written in?", "FastAPI.", "How is the database accessed from it?", "fastapi"),
    ("How is the app deployed?", "With a Windows installer.", "What does it bundle?", "deploy"),
    ("How do I make the tomato pasta?", "Simmer tomatoes with garlic and oil.", "How long should it simmer?", "pasta"),
    ("How do I bake the sourdough?", "Cold proof, then bake at 250 degrees.", "How long is the proof?", "bread"),
    ("When is the Kyoto trip?", "April 10 to 17.", "Where is the hotel?", "trip"),
    ("When is the Kyoto trip?", "April 10 to 17.", "Do I need a visa for it?", "visa"),
    ("What does the GATE exam cover?", "Mathematics, digital logic, algorithms, OS and networks.",
     "Which topics of the fourth subject are tested most?", "os_topics"),
    ("What does the GATE exam cover?", "Mathematics, digital logic, algorithms, OS and networks.", "How long is it?", "exam"),
    ("Where is the hotel in Kyoto?", "Near Gion.", "And what is booked on the 12th?", "trip"),
]

# (first question, first answer, follow-up): should NOT need a new search
REWORKS = [
    ("What did the March meeting decide?", "To order 12 new temperature sensors from Campbell Scientific.", "Make that shorter"),
    ("What does the GATE exam cover?", "Mathematics, digital logic, algorithms, OS and networks.", "Put it in a bullet list"),
    ("How do I make the tomato pasta?", "Simmer tomatoes with garlic and oil, add basil.", "Explain that more simply"),
    ("What is the 2024 budget?", "120,000 euros.", "Translate your answer to Hindi"),
]
# Follow-ups that need new information even though they look like rework requests.
NEW_INFO = [
    ("How do I make the tomato pasta?", "Simmer tomatoes with garlic and oil.", "What about the sourdough bread?"),
    ("What is the 2024 budget?", "120,000 euros.", "Summarise the ice loss measurements too"),
]


MAX_DISTANCE = 0.35  # PKOS drops passages farther than this (rag/vector/vector_db_pg.py retrieve_similar_chunks_async)


def top_k(vectors: np.ndarray, ids: list[str], query: str, k: int) -> list[tuple[str, float]]:
    """(passage id, cosine distance) of the k closest passages."""
    q = embed_query(query).flatten()
    scores = vectors @ q / (np.linalg.norm(vectors, axis=1) * np.linalg.norm(q))
    return [(ids[i], 1.0 - float(scores[i])) for i in np.argsort(-scores)[:k]]


def history(question: str, answer: str) -> list[dict]:
    return [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]


async def main(model: str, k: int):
    settings = LLMSettings(provider="ollama", ollama_model=model)
    ids = list(CORPUS)
    vectors = embed_text_batch([CORPUS[i] for i in ids])
    print(f"model {model}, {len(ids)} passages\n")

    # Load the model first: the app has always just answered the first question when a follow-up arrives.
    await rewrite_question(settings, history("warm up", "ok"), None, "warm up")
    hits = {(how, what): 0 for how in ("typed", "rewritten") for what in ("first", "topk", "app")}
    times = []
    print(f"first / top {k} / reaches the answer (top {k} and distance < {MAX_DISTANCE})")
    print("as typed | rewritten")
    for q1, a1, follow_up, expected in FOLLOW_UPS:
        started = time.perf_counter()
        r = await rewrite_question(settings, history(q1, a1), None, follow_up)
        times.append(time.perf_counter() - started)
        marks = []
        for how, query in (("typed", follow_up), ("rewritten", r.question)):
            ranked = top_k(vectors, ids, query, k)
            found = {pid: dist for pid, dist in ranked}
            for what, hit in (("first", ranked[0][0] == expected), ("topk", expected in found),
                              ("app", expected in found and found[expected] < MAX_DISTANCE)):
                hits[(how, what)] += hit
                marks.append("+" if hit else "-")
        flag = "" if r.needs_search else "  (said no search!)"
        print(f"{' '.join(marks[:3])} | {' '.join(marks[3:])}  {follow_up!r} -> {r.question!r}{flag}")

    print("\nRework requests (expect needs_search = False):")
    rework_ok = 0
    for q1, a1, follow_up in REWORKS:
        r = await rewrite_question(settings, history(q1, a1), None, follow_up)
        rework_ok += not r.needs_search
        print(f"  {'ok ' if not r.needs_search else 'NO '} {follow_up!r} -> needs_search={r.needs_search}")
    print("New information (expect needs_search = True):")
    new_ok = 0
    for q1, a1, follow_up in NEW_INFO:
        r = await rewrite_question(settings, history(q1, a1), None, follow_up)
        new_ok += r.needs_search
        print(f"  {'ok ' if r.needs_search else 'NO '} {follow_up!r} -> needs_search={r.needs_search}, {r.question!r}")

    n = len(FOLLOW_UPS)
    for what, label in (("first", "Right passage first"), ("topk", f"Right passage in top {k}"),
                        ("app", "Right passage reaches the answer in PKOS")):
        print(f"{'' if what != 'first' else chr(10)}{label}: as typed {hits[('typed', what)]}/{n}, "
              f"rewritten {hits[('rewritten', what)]}/{n}")
    print(f"needs_search: rework {rework_ok}/{len(REWORKS)} correct, new information {new_ok}/{len(NEW_INFO)} correct")
    print(f"Rewrite time: median {sorted(times)[len(times) // 2]:.2f} s, max {max(times):.2f} s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "llama3.2"))
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(main(args.model, args.k))
