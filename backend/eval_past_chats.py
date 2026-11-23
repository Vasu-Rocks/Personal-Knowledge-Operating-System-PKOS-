"""
Step B3 evaluation (docs/07_MEMORY_PLAN.md 10.5): does a "what did we ... last time" question find the right earlier
chat, and which distance cutoff keeps the wrong ones out? Recaps are built like the app builds them
(rag/memory/episodic.py build_recap) and embedded with the real model; no database, no language model.
Also counts how many ordinary questions would wrongly trigger a past-chat search.

  python eval_past_chats.py
"""
import io
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

from rag.memory.episodic import build_recap, refers_to_past_chats  # noqa: E402
from rag.vector.embedder import embed_query, embed_text_batch  # noqa: E402


def turn(q, a):
    return [{"role": "user", "content": q, "status": "complete"}, {"role": "assistant", "content": a, "status": "complete"}]


CHATS = {
    "sensors": build_recap("Which temperature sensors should we order?", None, turn(
        "Which temperature sensors should we order?",
        "The March meeting chose 12 Campbell Scientific sensors because the old 2015 ones drift by half a degree; "
        "delivery in six weeks, 4,800 euros.")),
    "budget": build_recap("What is the 2024 project budget?", None, turn(
        "What is the 2024 project budget?", "120,000 euros: 70,000 salaries, 30,000 equipment, 20,000 travel.")),
    "kyoto": build_recap("Kyoto conference trip", "The user planned the April Kyoto trip: hotel near Gion, the tea "
                         "ceremony on April 12, a tourist visa from the VFS centre three weeks before travel.", []),
    "paging": build_recap("Explain paging vs segmentation", None, turn(
        "Explain paging vs segmentation", "Paging splits memory into fixed-size frames; segmentation uses variable "
        "segments that match program parts; paging avoids external fragmentation.")),
    "thesis": build_recap("Thesis structure", "The user and the assistant agreed on a five-chapter thesis about "
                          "Himalayan glacier melt; the draft is due on 30 March and Dr. Rao reviews chapter 2 first.", []),
    "pasta": build_recap("Tomato pasta recipe", None, turn(
        "How do I make the tomato pasta?", "Simmer crushed tomatoes with garlic and olive oil for twenty minutes, "
        "add basil, toss with spaghetti.")),
}

LOOKBACK = [
    ("What did we decide about the sensors last time?", "sensors"),
    ("Last time we talked about the budget - how much was for travel?", "budget"),
    ("Remind me what we planned for the Kyoto trip", "kyoto"),
    ("In our earlier chat you explained paging; what was the main advantage?", "paging"),
    ("What did we agree about my thesis chapters?", "thesis"),
    ("Did we discuss a pasta recipe before?", "pasta"),
    ("You told me something about a visa, what was it?", "kyoto"),
    ("What did we conclude about the cheaper sensors?", "sensors"),
]

# Ordinary questions from the other evaluations: none of these should trigger a past-chat search.
ORDINARY = [
    "Who visits the glacier station?", "How much will the 12 new temperature sensors cost?", "When is my exam?",
    "Summarise my notes on photosynthesis", "What does the March meeting say about travel costs?",
    "How does TCP congestion control work?", "Explain the attention mechanism in transformers",
    "Compare paging and segmentation", "Can I run a 7B model on my laptop?", "What is the Krebs cycle?",
    "Give me an overview of the station notes", "List the tasks the surveyor does", "Where is the hotel?",
    "How long should sourdough proof in the fridge?", "What are the key points of these notes?",
]

CUTOFFS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55]


def main():
    ids = list(CHATS)
    vectors = embed_text_batch([CHATS[i] for i in ids])
    rows = []
    print("question -> closest chat (distance) | expected chat distance")
    for question, expected in LOOKBACK:
        dist = 1.0 - vectors @ embed_query(question).flatten()
        order = np.argsort(dist)
        rows.append((expected, {ids[i]: float(dist[i]) for i in order}))
        best = ids[order[0]]
        print(f"  {'+' if best == expected else '-'} {question!r:72} -> {best:8} {dist[order[0]]:.3f} | "
              f"{expected} {dist[ids.index(expected)]:.3f}")

    print("\ncutoff | right chat found (first, under cutoff) | wrong chats also under cutoff (top 2)")
    for cut in CUTOFFS:
        right = sum(min(d, key=d.get) == e and d[e] < cut for e, d in rows)
        wrong = sum(sum(1 for c, v in sorted(d.items(), key=lambda kv: kv[1])[:2] if c != e and v < cut) for e, d in rows)
        print(f"  {cut:.2f} | {right}/{len(rows)} | {wrong}")

    triggered = [q for q in ORDINARY if refers_to_past_chats(q)]
    missed = [q for q, _ in LOOKBACK if not refers_to_past_chats(q)]
    print(f"\ntrigger words: {len(LOOKBACK) - len(missed)}/{len(LOOKBACK)} look-back questions recognised "
          f"{missed if missed else ''}; {len(triggered)}/{len(ORDINARY)} ordinary questions wrongly triggered "
          f"{triggered if triggered else ''}")


if __name__ == "__main__":
    main()
