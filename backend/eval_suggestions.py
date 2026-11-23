"""
Step B5 evaluation (docs/07_MEMORY_PLAN.md 10.3): does PKOS propose sensible memories from what the user says about
themselves, and none from ordinary questions? Runs rag/memory/suggest.py propose() against the local model
(default llama3.2), each case several times like the app would; no database.

  python eval_suggestions.py [model] [runs]
"""
import asyncio
import io
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from core.llm import LLMSettings  # noqa: E402
from rag.memory.suggest import propose, says_something_about_the_user  # noqa: E402

# (question, words one suggestion must contain (all), kind) - the user says something lasting about themselves.
LASTING = [
    ("I am a beginner in machine learning, keep it simple. What is gradient descent?", ["beginner"], None),
    ("I'm preparing for the GATE exam in February. Which topics in operating systems matter most?", ["gate"], "fact"),
    ("Please always answer in short bullet points. How does TCP congestion control work?", ["bullet"], "preference"),
    ("My supervisor is Dr. Rao and my thesis is about glacier melt. What should chapter 2 cover?", ["rao", "thesis"], "fact"),
    ("I work as a nurse, so explain it simply: what does the Krebs cycle do?", ["nurse"], "fact"),
    ("I only use Python, never Java. How do I read a CSV file?", ["python"], None),
    ("My exam is on 14 February. How many weeks do I have left to revise the networking notes?", ["february"], "fact"),
]

# Ordinary questions: no suggestion should come out (most never reach the model).
NONE = [
    "What does the March meeting say about travel costs?",
    "Summarise my notes on photosynthesis",
    "Who visits the glacier station?",
    "Make this shorter",
    "I think the second option is better, why did the notes reject it?",
    "What do my notes say about ice loss?",
    "I need the formula for the area of a circle",
    "I want to know how many sensors were ordered",
    "Can you explain the light reactions simply?",
    "What did we decide about the sensors last time?",
    "My question is about the budget: how much is for travel?",
    "I have a question about chapter 3 - what is a deadlock?",
    # First-person, but not lasting: these reach the model, which must label them "none".
    "I am confused by this chapter. What is a deadlock?",
    "I'm looking for the part about ice loss in my notes",
    "I have read the notes twice but still don't get the Calvin cycle. Explain it again",
]


async def main(model="llama3.2", runs=3):
    settings = LLMSettings(provider="ollama", ollama_model=model)
    good = total = 0
    print("LASTING - a sensible suggestion expected")
    for question, words, kind in LASTING:
        hits = []
        for _ in range(runs):
            found = await propose(settings, question)
            ok = any(all(w in s["text"].lower() for w in words) and (kind is None or s["kind"] == kind) for s in found)
            hits.append(ok)
        good += sum(hits)
        total += runs
        print(f"  {sum(hits)}/{runs}  {question[:70]!r}\n        last: {found}")
    print(f"=> {good}/{total} sensible\n")

    noise = calls = n = 0
    print("NONE - no suggestion expected")
    for question in NONE:
        asked = says_something_about_the_user(question)
        calls += asked
        for _ in range(runs if asked else 1):
            found = await propose(settings, question)
            n += 1
            noise += bool(found)
            if found:
                print(f"  NOISE {question!r} -> {found}")
    print(f"=> {noise}/{n} runs gave a suggestion; the model was asked for {calls}/{len(NONE)} questions")


if __name__ == "__main__":
    asyncio.run(main(*(sys.argv[1:2] or ["llama3.2"]), *(int(x) for x in sys.argv[2:3])))
