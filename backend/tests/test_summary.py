"""Running summary, step 5 of docs/07_MEMORY_PLAN.md: turns that leave the history window are summarised."""
import asyncio
import json
import time
import uuid

import pytest

from api import routes_query
from conftest import event, run_db, sse_events
from core import config
from core.llm import LLMError, LLMSettings
from database import conversations_db as db
from rag.memory import summary as sm
from rag.memory.stm import turns_outside_window


def m(role, content, seq, status="complete"):
    return {"role": role, "content": content, "status": status, "seq": seq}


def chat_of(n, answer="a" * 50):
    msgs = []
    for i in range(n):
        msgs += [m("user", f"q{i}", 2 * i + 1), m("assistant", answer, 2 * i + 2)]
    return msgs


# ------------------------------------------------------------------------------------------------ what gets folded

def test_turns_outside_the_window_are_the_older_ones_with_their_seq():
    outside = turns_outside_window(chat_of(10), max_chars=120, max_turns=10)  # 2 turns of 52 characters fit
    assert [(q, seq) for q, _a, seq in outside] == [(f"q{i}", 2 * i + 2) for i in range(8)]
    assert [q for q, _a, _s in turns_outside_window(chat_of(5), max_chars=10_000, max_turns=3)] == ["q0", "q1"]


def test_nothing_is_folded_while_everything_fits_or_memory_has_no_budget():
    assert turns_outside_window(chat_of(3), max_chars=10_000, max_turns=6) == []
    assert turns_outside_window(chat_of(3), max_chars=0, max_turns=6) == []


def test_failed_turns_are_not_folded():
    msgs = chat_of(1) + [m("user", "broken", 3), m("assistant", "System Error: x", 4, "error")] + chat_of(3)[2:]
    for i, msg in enumerate(msgs):
        msg["seq"] = i + 1
    assert [q for q, _a, _s in turns_outside_window(msgs, max_chars=10_000, max_turns=1)] == ["q0", "q1"]


# ------------------------------------------------------------------------------------------------ the summarizer

def fake_model(monkeypatch, reply="The user asked about sensors.", error=None):
    calls = []

    async def fake_chat_text(settings, messages, **kw):
        calls.append({"messages": messages, **kw})
        if error:
            raise error
        return reply if not callable(reply) else reply(len(calls))

    monkeypatch.setattr(sm, "chat_text", fake_chat_text)
    return calls


def test_summary_prompt_has_the_old_summary_and_the_new_turns(monkeypatch):
    calls = fake_model(monkeypatch)
    turns = [("How many sensors?", "Twelve, from Campbell. " + "x " * 600, 2)]
    text = asyncio.run(sm.summarize(LLMSettings(), "They discussed the budget.", turns))
    assert text == "The user asked about sensors."
    prompt = calls[0]["messages"][1]["content"]
    assert "Current summary:\nThey discussed the budget." in prompt and "User: How many sensors?" in prompt
    assert len(prompt) < sm.ANSWER_EXCERPT_CHARS + 200          # the long answer was shortened
    assert f"at most {int(config.SUMMARY_MAX_CHARS * 0.8)} characters" in calls[0]["messages"][0]["content"]


@pytest.mark.parametrize("reply, expected", [
    ("Summary: The user asked about sensors.", "The user asked about sensors."),
    ("   ", None),
    ("First sentence. " + "Second sentence goes on. " * 100, None),  # clipped at a sentence end, checked below
])
def test_summary_replies_are_cleaned_and_clipped(monkeypatch, reply, expected):
    fake_model(monkeypatch, reply)
    text = asyncio.run(sm.summarize(LLMSettings(), None, [("q", "a", 2)], max_chars=200))
    if expected is not None or not reply.strip():
        assert text == expected
    else:
        assert len(text) <= 200 and text.endswith(".")


def test_an_overlong_summary_is_compressed_by_the_model_before_any_cut(monkeypatch):
    calls = fake_model(monkeypatch, reply=lambda n: "Long sentence here. " * 30 if n == 1 else "Short version.")
    assert asyncio.run(sm.summarize(LLMSettings(), None, [("q", "a", 2)], max_chars=200)) == "Short version."
    assert len(calls) == 2 and "Shorten this summary" in calls[1]["messages"][0]["content"]
    assert "at most 160 characters" in calls[0]["messages"][0]["content"]  # 80% of the limit is asked for


@pytest.mark.parametrize("error", [LLMError("Ollama is not running"), asyncio.TimeoutError(), RuntimeError("x")])
def test_a_failed_summary_returns_none(monkeypatch, error):
    fake_model(monkeypatch, error=error)
    assert asyncio.run(sm.summarize(LLMSettings(), "old", [("q", "a", 2)])) is None


# ------------------------------------------------------------------------------------------------ saving

def test_a_summary_is_only_saved_over_the_version_it_was_built_from(make_user):
    u = make_user("sumrace")
    cid = uuid.UUID(u.client.post("/api/v1/conversations", headers=u.headers).json()["conversation_id"])
    uid = u.client.get("/api/v1/me", headers=u.headers).json()["user_id"]

    async def race(pool):
        first = await db.save_summary(pool, uid, cid, "first", upto_seq=4, expected_upto_seq=0)
        stale = await db.save_summary(pool, uid, cid, "stale", upto_seq=2, expected_upto_seq=0)
        backwards = await db.save_summary(pool, uid, cid, "backwards", upto_seq=4, expected_upto_seq=4)
        conv = await db.get_owned_conversation(pool, uid, cid)
        return first, stale, backwards, conv["summary"], conv["summary_upto_seq"]

    assert run_db(race) == (True, False, False, "first", 4)


# ------------------------------------------------------------------------------------------------ end to end

API = "/api/v1"
TEXT = ("The surveyor visits the glacier station every Tuesday to read the temperature sensors. " * 4).encode()
QUESTION = TEXT.decode().strip()


def wait_for_summaries(timeout=10.0):
    deadline = time.time() + timeout
    while routes_query._summary_tasks and time.time() < deadline:
        time.sleep(0.05)
    assert not routes_query._summary_tasks, "summary update still running"


@pytest.fixture
def small_window(monkeypatch):
    """Two turns of history, real background summaries, a scripted summarizer and a recording answer model."""
    monkeypatch.setattr(config, "HISTORY_MAX_TURNS", 2)
    monkeypatch.setattr(routes_query, "update_summary", sm.update_summary)
    prompts = []

    async def recording(messages, settings=None):
        prompts.append(messages)
        yield json.dumps({"type": "token", "content": f"answer {len(prompts)}"})

    monkeypatch.setattr(routes_query, "generate_rag_response_stream", recording)
    return prompts


def ask(u, question, cid=None):
    body = {"query": question} | ({"conversation_id": cid} if cid else {})
    r = u.client.post(f"{API}/query/stream", json=body, headers=u.headers)
    assert r.status_code == 200, r.text
    wait_for_summaries()
    return event(sse_events(r.text), "conversation")["conversation_id"]


def stored(u, cid):
    uid = u.client.get(f"{API}/me", headers=u.headers).json()["user_id"]
    return run_db(lambda pool: db.get_owned_conversation(pool, uid, uuid.UUID(cid)))


def test_a_long_chat_keeps_its_start_in_the_summary(make_user, small_window, monkeypatch):
    prompts = small_window
    calls = fake_model(monkeypatch, reply=lambda n: f"Summary {n}: the surveyor comes on Tuesdays.")
    u = make_user("longchat")
    u.upload("station.txt", TEXT)
    cid = ask(u, QUESTION + " 1")
    ask(u, QUESTION + " 2", cid)
    assert calls == [] and stored(u, cid)["summary"] is None          # 2 turns: everything still fits

    ask(u, QUESTION + " 3", cid)                                      # turn 1 leaves the window
    conv = stored(u, cid)
    assert (conv["summary"], conv["summary_upto_seq"]) == ("Summary 1: the surveyor comes on Tuesdays.", 2)
    assert "User: " + QUESTION + " 1" in calls[0]["messages"][1]["content"]

    ask(u, QUESTION + " 4", cid)                                      # turn 2 follows, on top of summary 1
    conv = stored(u, cid)
    assert (conv["summary"], conv["summary_upto_seq"]) == ("Summary 2: the surveyor comes on Tuesdays.", 4)
    assert "Current summary:\nSummary 1" in calls[1]["messages"][1]["content"]

    ask(u, QUESTION + " 5", cid)
    last = prompts[-1]
    assert "EARLIER IN THIS CONVERSATION (summary):\nSummary 2" in last[0]["content"]
    # Only the two newest earlier turns are sent in full; the older ones live in the summary.
    assert [x["content"] for x in last[1:] if x["role"] == "user"] == [QUESTION + " 3", QUESTION + " 4", QUESTION + " 5"]


def test_a_failed_summary_is_retried_on_the_next_answer(make_user, small_window, monkeypatch):
    calls = fake_model(monkeypatch, error=LLMError("Ollama is not running"))
    u = make_user("retrysum")
    cid = ask(u, "first question")
    for i in range(2, 4):
        ask(u, f"question {i}", cid)
    assert len(calls) == 1 and stored(u, cid)["summary_upto_seq"] == 0
    fake_model(monkeypatch, reply="Recovered summary.")
    ask(u, "question 4", cid)
    conv = stored(u, cid)
    assert conv["summary"] == "Recovered summary." and conv["summary_upto_seq"] == 4  # both waiting turns folded


def test_summaries_never_delay_the_answer(make_user, monkeypatch):
    async def slow(pool, settings, user_id, conversation_id):
        await asyncio.sleep(3)
        return False

    monkeypatch.setattr(routes_query, "update_summary", slow)
    u = make_user("nodelay")
    started = time.time()
    r = u.client.post(f"{API}/query/stream", json={"query": "quick question"}, headers=u.headers)
    assert r.status_code == 200 and sse_events(r.text)[-1] == "[DONE]"
    assert time.time() - started < 2.5
    wait_for_summaries()


def test_memory_off_means_no_summaries(make_user, small_window, monkeypatch):
    monkeypatch.setattr(config, "MEMORY_ENABLED", False)
    calls = fake_model(monkeypatch)
    u = make_user("nosummary")
    cid = ask(u, "one")
    for q in ("two", "three", "four"):
        ask(u, q, cid)
    assert calls == [] and stored(u, cid)["summary"] is None
