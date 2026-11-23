"""
Step B2 evaluation (docs/07_MEMORY_PLAN.md 10.4): which distance cutoff picks the right saved memory and leaves
unrelated questions alone? Uses the real embedding model (memories embedded like passages, questions like queries,
as in the app); no database, no language model.

  python eval_memories.py
"""
import io
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402

from rag.vector.embedder import embed_query, embed_text_batch  # noqa: E402

MEMORIES = {
    "exam": "My GATE exam is on 8 February 2027.",
    "advisor": "My thesis advisor is Dr. Anjali Rao.",
    "thesis": "My thesis is about glacier melt in the Himalayas.",
    "deadline": "My thesis draft is due on 30 March.",
    "sensors": "We decided to order the Campbell Scientific sensors instead of the cheaper ones.",
    "laptop": "My laptop has 16 GB of RAM and no GPU.",
    "diet": "I am vegetarian.",
    "city": "I live in Pune and work at a water research institute.",
    "beginner": "I am a beginner in machine learning.",
    "language": "My native language is Hindi.",
}

# Questions a memory should help with: (question, expected memory)
RELATED = [
    ("When is my exam?", "exam"),
    ("How many days are left until my GATE exam?", "exam"),
    ("Who is my advisor?", "advisor"),
    ("What is my thesis about?", "thesis"),
    ("When is my draft due?", "deadline"),
    ("Which sensors did we choose?", "sensors"),
    ("Can I run a 7B model on my laptop?", "laptop"),
    ("Suggest a dinner recipe I can eat", "diet"),
    ("Where do I live?", "city"),
    ("Explain gradient descent at my level", "beginner"),
]

# Ordinary document questions: no memory should be pulled in.
UNRELATED = [
    "What is the boiling point of tungsten?",
    "Summarise chapter 3 of the networking book",
    "How does TCP congestion control work?",
    "Explain the attention mechanism in transformers",
    "List the main causes of the French revolution",
    "What does the March meeting say about travel costs?",
    "How long should sourdough proof in the fridge?",
    "Who wrote Pride and Prejudice?",
    "What is photosynthesis?",
    "Compare paging and segmentation",
]

# Questions in the first person that are still about documents: a looser cutoff for "personal" questions must not
# pull memories into these.
PERSONAL_DOCUMENT = [
    "Summarise my notes on photosynthesis",
    "What does my networking book say about TCP?",
    "Explain my lecture slides on paging",
    "What did I upload about the French revolution?",
    "Can you quiz me on chapter 2?",
    "What are the key formulas in my statistics notes?",
]

CUTOFFS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
TOP = 3


def main():
    ids = list(MEMORIES)
    vectors = embed_text_batch([MEMORIES[i] for i in ids])

    def ranked(question):
        q = embed_query(question).flatten()
        dist = 1.0 - vectors @ q  # both normalised
        order = np.argsort(dist)[:TOP]
        return [(ids[i], float(dist[i])) for i in order]

    related = [(q, expected, ranked(q)) for q, expected in RELATED]
    unrelated = [(q, ranked(q)) for q in UNRELATED]
    personal = [(q, ranked(q)) for q in PERSONAL_DOCUMENT]

    print("Distance of the expected memory, and the closest other one:")
    for q, expected, top in related:
        d_expected = next((d for i, d in top if i == expected), None)
        other = next((d for i, d in top if i != expected), None)
        print(f"  {q!r:48} expected {expected:9} {d_expected if d_expected is not None else '>top3':>6} | other {other:.3f}")
    print("Closest memory for unrelated questions:")
    for q, top in unrelated:
        print(f"  {q!r:48} {top[0][0]:9} {top[0][1]:.3f}")

    print("Closest memory for first-person document questions:")
    for q, top in personal:
        print(f"  {q!r:48} {top[0][0]:9} {top[0][1]:.3f}")

    print("\ncutoff | right memory found | wrong extra memories on those | unrelated given a memory | "
          "first-person document questions given a memory")
    for cut in CUTOFFS:
        found = sum(any(i == e and d < cut for i, d in top) for _q, e, top in related)
        extra = sum(sum(1 for i, d in top if i != e and d < cut) for _q, e, top in related)
        noisy = sum(any(d < cut for _i, d in top) for _q, top in unrelated)
        noisy_personal = sum(any(d < cut for _i, d in top) for _q, top in personal)
        print(f"  {cut:.2f} | {found:2}/{len(related)} | {extra:2} | {noisy:2}/{len(unrelated)} | "
              f"{noisy_personal:2}/{len(personal)}")


if __name__ == "__main__":
    main()
