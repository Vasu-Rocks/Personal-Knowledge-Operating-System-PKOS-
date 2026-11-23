"""Memory suggestions, step B5 of docs/07_MEMORY_PLAN.md (the model's labels are faked in conftest.py)."""
import asyncio

import pytest

from conftest import event, sse_events
from core.llm import LLMSettings
from rag.memory import suggest
from rag.memory.suggest import MAX_PENDING, propose, says_something_about_the_user, statements

API = "/api/v1"
BEGINNER = "I am a beginner in machine learning, keep it simple. What is gradient descent?"


# ------------------------------------------------------------------------------------------------ which words

@pytest.mark.parametrize("question, expected", [
    (BEGINNER, ["I am a beginner in machine learning", "Keep answers simple"]),
    ("Please always answer in short bullet points. How does TCP work?", ["Always answer in short bullet points"]),
    ("My supervisor is Dr. Rao and my thesis is about glacier melt. What next?",
     ["My supervisor is Dr. Rao and my thesis is about glacier melt"]),
    ("I work as a nurse, so explain it simply: what does the Krebs cycle do?", ["I work as a nurse", "Explain things simply"]),
    ("I'm preparing for the GATE exam in February.\nWhich topics matter?", ["I'm preparing for the GATE exam in February"]),
])
def test_statements_are_the_users_own_words(question, expected):
    assert says_something_about_the_user(question)
    assert statements(question) == expected


@pytest.mark.parametrize("question", [
    "What does the March meeting say about travel costs?",
    "Summarise my notes on photosynthesis",
    "Make this shorter",
    "What do my notes say about ice loss?",
    "Can you explain the light reactions simply?",       # a question, not a statement
    "What did I tell you about my trip last time?",      # look-back: repeats an earlier chat
])
def test_ordinary_questions_never_reach_the_model(question):
    assert not says_something_about_the_user(question) or not statements(question)


@pytest.mark.parametrize("question", [
    "I want to know how many sensors were ordered",
    "I have a question about chapter 3 - what is a deadlock?",
    "I need the formula for the area of a circle",
    "I think the second option is better, why did the notes reject it?",
])
def test_announcing_a_question_is_not_a_memory(question):
    assert statements(question) == []


# ------------------------------------------------------------------------------------------------ the model's labels

S = LLMSettings(provider="ollama", ollama_model="llama3.2")


def test_only_statements_the_model_labels_lasting_are_proposed(monkeypatch):
    async def labels(settings, messages, **kw):
        assert messages[-1]["content"] == "1. I am a beginner in machine learning\n2. Keep answers simple"
        return {"labels": [{"n": 1, "kind": "fact"}, {"n": 2, "kind": "none"}, {"n": 7, "kind": "fact"}, "junk"]}

    monkeypatch.setattr(suggest, "chat_json", labels)
    assert asyncio.run(propose(S, BEGINNER)) == [{"text": "I am a beginner in machine learning", "kind": "fact"}]


def test_a_failing_model_proposes_nothing(monkeypatch):
    async def broken(settings, messages, **kw):
        raise RuntimeError("model not loaded")

    monkeypatch.setattr(suggest, "chat_json", broken)
    assert asyncio.run(propose(S, BEGINNER)) == []


def test_ordinary_questions_do_not_call_the_model(monkeypatch):
    async def never(settings, messages, **kw):
        raise AssertionError("the model was asked")

    monkeypatch.setattr(suggest, "chat_json", never)
    assert asyncio.run(propose(S, "Who visits the glacier station?")) == []


# ------------------------------------------------------------------------------------------------ in a chat

def maybe(events, kind):
    return next((e for e in events if isinstance(e, dict) and e.get("type") == kind), None)


def ask(u, question, cid=None):
    body = {"query": question} | ({"conversation_id": cid} if cid else {})
    r = u.client.post(f"{API}/query/stream", json=body, headers=u.headers)
    assert r.status_code == 200, r.text
    return sse_events(r.text)


def pending(u):
    return u.client.get(f"{API}/memories?status=pending", headers=u.headers).json()["memories"]


def test_suggestions_arrive_after_the_answer_and_wait_for_the_user(make_user):
    u = make_user("suggester")
    events = ask(u, BEGINNER)
    types = [e.get("type") for e in events if isinstance(e, dict)]
    assert types.index("saved") < types.index("suggestions")
    cid = event(events, "conversation")["conversation_id"]
    question_id = event(events, "saved")["question_id"]
    shown = event(events, "suggestions")["memories"]
    assert [(m["text"], m["kind"], m["status"], m["origin"]) for m in shown] == [
        ("I am a beginner in machine learning", "fact", "pending", "suggested"),
        ("Keep answers simple", "preference", "pending", "suggested")]
    assert all(m["source_conversation_id"] == cid and m["source_message_id"] == question_id for m in shown)
    assert {m["memory_id"] for m in pending(u)} == {m["memory_id"] for m in shown}
    assert u.client.get(f"{API}/memories?status=active", headers=u.headers).json()["memories"] == []


def test_pending_suggestions_are_never_used_until_kept(make_user):
    u = make_user("keeper")
    shown = event(ask(u, BEGINNER), "suggestions")["memories"]
    assert maybe(ask(u, "Tell me about gradient descent in machine learning"), "memories") is None

    preference = next(m for m in shown if m["kind"] == "preference")
    kept = u.client.post(f"{API}/memories/{preference['memory_id']}/confirm", headers=u.headers)
    assert kept.status_code == 200 and kept.json()["status"] == "active"
    events = ask(u, "Tell me about gradient descent in machine learning")
    assert [m["text"] for m in event(events, "memories")["memories"]] == ["Keep answers simple"]

    fact = next(m for m in shown if m["kind"] == "fact")
    assert u.client.delete(f"{API}/memories/{fact['memory_id']}", headers=u.headers).status_code == 204   # dismissed
    assert pending(u) == []


def test_nothing_is_suggested_twice(make_user):
    u = make_user("nodupes")
    u.client.post(f"{API}/memories", json={"text": "I am a beginner in machine learning", "kind": "fact"},
                  headers=u.headers)
    shown = event(ask(u, BEGINNER), "suggestions")["memories"]
    assert [m["text"] for m in shown] == ["Keep answers simple"]       # the kept one is not proposed again
    assert maybe(ask(u, BEGINNER), "suggestions") is None              # nor the pending one


def test_not_lasting_statements_and_ordinary_questions_give_no_suggestions(make_user):
    u = make_user("quietuser")
    assert maybe(ask(u, "I am tired today. What is a deadlock?"), "suggestions") is None
    assert maybe(ask(u, "Who visits the glacier station?"), "suggestions") is None
    assert pending(u) == []


def test_suggestions_switched_off(make_user):
    u = make_user("nosuggest")
    u.client.put(f"{API}/memories/settings", json={"suggest": False}, headers=u.headers)
    assert maybe(ask(u, BEGINNER), "suggestions") is None
    u.client.put(f"{API}/memories/settings", json={"suggest": True, "enabled": False}, headers=u.headers)
    assert maybe(ask(u, BEGINNER), "suggestions") is None
    assert pending(u) == []


def test_unanswered_suggestions_are_capped(make_user):
    u = make_user("piledup")
    for i in range(MAX_PENDING + 3):
        ask(u, f"I am learning topic number {i} for project {i * 7}. What is it?")
    assert len(pending(u)) == MAX_PENDING
