"""Follow-up rewriting, step 4 of docs/07_MEMORY_PLAN.md: the rewriter itself, and how /query/stream uses it."""
import asyncio
import json

import pytest

from api import routes_query
from conftest import event, sse_events
from core.llm import LLMError, LLMSettings
from rag.memory import rewrite as rw
from rag.memory.rewrite import Rewrite, rewrite_question

HISTORY = [{"role": "user", "content": "Who visits the glacier station?"},
           {"role": "assistant", "content": "The surveyor visits it every Tuesday."}]
SETTINGS = LLMSettings()


def run(coro):
    return asyncio.run(coro)


def model_replies(monkeypatch, reply=None, error=None, delay=0.0):
    """Replaces the model call; records the messages it was given."""
    calls = []

    async def fake_chat_json(settings, messages, **kw):
        calls.append({"messages": messages, **kw})
        if delay:
            await asyncio.sleep(delay)
        if error:
            raise error
        return reply

    monkeypatch.setattr(rw, "chat_json", fake_chat_json)
    return calls


# ------------------------------------------------------------------------------------------------ the rewriter

def test_first_question_makes_no_model_call(monkeypatch):
    calls = model_replies(monkeypatch, {"question": "x", "needs_search": True})
    assert run(rewrite_question(SETTINGS, [], None, "Who visits?")) == Rewrite("Who visits?", True, False)
    assert calls == []


def test_a_follow_up_is_rewritten(monkeypatch):
    calls = model_replies(monkeypatch, {"question": "When does the surveyor visit the glacier station?", "needs_search": True})
    result = run(rewrite_question(SETTINGS, HISTORY, None, "When does he come?"))
    assert result == Rewrite("When does the surveyor visit the glacier station?", True, True)
    prompt = calls[0]["messages"][1]["content"]
    assert "User: Who visits the glacier station?" in prompt and prompt.endswith("Latest message: When does he come?")
    assert calls[0]["schema"] == rw.SCHEMA and calls[0]["temperature"] == 0.0


def test_rework_of_the_previous_answer_needs_no_search(monkeypatch):
    model_replies(monkeypatch, {"question": "Make the answer shorter", "needs_search": False})
    assert run(rewrite_question(SETTINGS, HISTORY, None, "shorter please")).needs_search is False


def test_an_unchanged_question_is_not_counted_as_rewritten(monkeypatch):
    model_replies(monkeypatch, {"question": "What is the  station's   altitude?", "needs_search": True})
    result = run(rewrite_question(SETTINGS, HISTORY, None, "What is the station's altitude?"))
    assert result == Rewrite("What is the station's altitude?", True, False)  # whitespace normalised


@pytest.mark.parametrize("reply", [
    None,                                              # invalid JSON
    "When does he come?",                              # not an object
    {"needs_search": True},                            # no question
    {"question": "", "needs_search": True},
    {"question": "   ", "needs_search": True},
    {"question": 42, "needs_search": True},
    {"question": "x" * 301, "needs_search": True},     # too long to be a question
])
def test_unusable_replies_fall_back_to_the_question_as_typed(monkeypatch, reply):
    model_replies(monkeypatch, reply)
    assert run(rewrite_question(SETTINGS, HISTORY, None, "When does he come?")) == Rewrite("When does he come?", True, False)


def test_a_missing_or_odd_needs_search_means_search(monkeypatch):
    model_replies(monkeypatch, {"question": "When does the surveyor come?", "needs_search": "no"})
    assert run(rewrite_question(SETTINGS, HISTORY, None, "When?")).needs_search is True


def test_line_breaks_in_the_rewrite_are_flattened(monkeypatch):
    model_replies(monkeypatch, {"question": "When does\nthe surveyor\n come?", "needs_search": True})
    assert run(rewrite_question(SETTINGS, HISTORY, None, "When?")).question == "When does the surveyor come?"


@pytest.mark.parametrize("error", [LLMError("Cannot connect to Ollama"), RuntimeError("boom")])
def test_model_errors_fall_back(monkeypatch, error):
    model_replies(monkeypatch, error=error)
    assert run(rewrite_question(SETTINGS, HISTORY, None, "When?")) == Rewrite("When?", True, False)


def test_a_slow_model_falls_back_after_the_timeout(monkeypatch):
    model_replies(monkeypatch, {"question": "late", "needs_search": True}, delay=5)
    assert run(rewrite_question(SETTINGS, HISTORY, None, "When?", timeout=0.05)) == Rewrite("When?", True, False)


def test_long_answers_are_shortened_and_the_summary_is_included(monkeypatch):
    calls = model_replies(monkeypatch, {"question": "q", "needs_search": True})
    history = [{"role": "user", "content": "Tell me everything"}, {"role": "assistant", "content": "word " * 500}]
    run(rewrite_question(SETTINGS, history, "We talked about sensors.", "And the rest?"))
    prompt = calls[0]["messages"][1]["content"]
    assert "(Earlier: We talked about sensors.)" in prompt
    assistant_line = next(line for line in prompt.splitlines() if line.startswith("Assistant:"))
    assert len(assistant_line) < rw.ANSWER_EXCERPT_CHARS + 20 and assistant_line.endswith("...")


# ------------------------------------------------------------------------------------------------ in the API

API = "/api/v1"
TEXT = ("The surveyor visits the glacier station every Tuesday to read the temperature sensors. " * 4).encode()
QUESTION = TEXT.decode().strip()  # the fake embedder only finds the passage for (nearly) identical text


@pytest.fixture
def rewrites(monkeypatch):
    """Scripted rewriter: maps a typed follow-up to a Rewrite; records the history it was given."""
    script, seen = {}, []

    async def scripted(settings, history, summary, question, timeout=None):
        seen.append(history)
        return script.get(question, Rewrite(question, True, False))

    monkeypatch.setattr(routes_query, "rewrite_question", scripted)
    return script, seen


def ask(u, question, cid=None):
    body = {"query": question} | ({"conversation_id": cid} if cid else {})
    r = u.client.post(f"{API}/query/stream", json=body, headers=u.headers)
    assert r.status_code == 200, r.text
    return sse_events(r.text)


def test_the_rewritten_question_is_what_gets_searched_and_saved(make_user, rewrites, monkeypatch):
    script, _ = rewrites
    u = make_user("rewriter")
    u.upload("station.txt", TEXT)
    cid = event(ask(u, QUESTION), "conversation")["conversation_id"]

    searched = []
    real_embed = routes_query.embed_query
    monkeypatch.setattr(routes_query, "embed_query", lambda q: searched.append(q) or real_embed(q))
    ask(u, "When does he come?", cid)                       # rewrite failed: searched as typed
    script["When does he come?"] = Rewrite(QUESTION, True, True)
    events = ask(u, "When does he come?", cid)
    assert searched == ["When does he come?", QUESTION]
    assert event(events, "rewrite") == {"type": "rewrite", "standalone": QUESTION, "needs_search": True, "rewritten": True}
    assert event(events, "sources")["sources"][0]["filename"] == "station.txt"
    assert [e["type"] for e in events[:3]] == ["conversation", "rewrite", "sources"]

    messages = u.client.get(f"{API}/conversations/{cid}", headers=u.headers).json()["messages"]
    assert messages[0]["standalone_query"] is None                       # the first question was not rewritten
    assert (messages[4]["content"], messages[4]["standalone_query"], messages[4]["needs_search"]) == \
        ("When does he come?", QUESTION, True)


def test_a_follow_up_whose_search_finds_nothing_keeps_the_previous_passages(make_user, rewrites):
    u = make_user("safetynet")
    u.upload("station.txt", TEXT)
    first = ask(u, QUESTION)
    cid = event(first, "conversation")["conversation_id"]
    # Judged as needing search, but the search finds nothing: the chat is most likely still about the last answer.
    events = ask(u, "Translate that into Hindi", cid)
    assert event(events, "sources")["sources"] == event(first, "sources")["sources"]
    assert event(events, "token")["content"] == "fake answer"  # the model answers instead of a canned refusal


def test_a_new_chat_whose_search_finds_nothing_still_says_so(make_user, rewrites):
    u = make_user("nonet")
    u.upload("station.txt", TEXT)
    events = ask(u, "Translate that into Hindi")  # no history, so no previous passages to fall back on
    assert event(events, "sources")["sources"] == [] and event(events, "token")["content"] == routes_query.NO_ANSWER


def test_the_first_question_has_no_rewrite_event(make_user, rewrites):
    u = make_user("norewrite")
    events = ask(u, "anything")
    assert not any(isinstance(e, dict) and e.get("type") == "rewrite" for e in events)


def test_reworking_the_previous_answer_reuses_its_passages_without_searching(make_user, rewrites, monkeypatch):
    script, _ = rewrites
    u = make_user("reworker")
    u.upload("station.txt", TEXT)
    first = ask(u, QUESTION)
    cid = event(first, "conversation")["conversation_id"]

    def no_search(*args, **kwargs):
        raise AssertionError("no new search expected")

    monkeypatch.setattr(routes_query, "embed_query", no_search)
    script["Make it shorter"] = Rewrite("Make the answer about the surveyor shorter", False, True)
    events = ask(u, "Make it shorter", cid)
    assert event(events, "sources")["sources"] == event(first, "sources")["sources"]
    assert event(events, "rewrite")["needs_search"] is False
    answer = u.client.get(f"{API}/conversations/{cid}", headers=u.headers).json()["messages"][3]
    assert answer["status"] == "complete" and answer["sources"] == event(first, "sources")["sources"]


def test_no_search_falls_back_to_search_when_there_is_nothing_to_rework(make_user, rewrites):
    script, _ = rewrites
    u = make_user("nothingtorework")
    cid = event(ask(u, "a question with no documents"), "conversation")["conversation_id"]  # answer has no sources
    script["shorter"] = Rewrite("shorter", False, True)
    events = ask(u, "shorter", cid)
    assert event(events, "rewrite")["needs_search"] is True
    assert event(events, "token")["content"] == routes_query.NO_ANSWER


def test_the_rewriter_gets_the_chat_history(make_user, rewrites):
    _, seen = rewrites
    u = make_user("historyrw")
    cid = event(ask(u, "first question"), "conversation")["conversation_id"]
    ask(u, "second question", cid)
    assert seen[0] == [] and [m["content"] for m in seen[1]] == ["first question", routes_query.NO_ANSWER]


def test_the_model_still_sees_the_question_as_typed(make_user, rewrites, monkeypatch):
    script, _ = rewrites
    sent = []

    async def recording(messages, settings=None):
        sent.append(messages)
        yield json.dumps({"type": "token", "content": "ok"})

    monkeypatch.setattr(routes_query, "generate_rag_response_stream", recording)
    u = make_user("typed")
    u.upload("station.txt", TEXT)
    cid = event(ask(u, QUESTION), "conversation")["conversation_id"]
    script["When does he come?"] = Rewrite(QUESTION, True, True)
    ask(u, "When does he come?", cid)
    assert sent[1][-1] == {"role": "user", "content": "When does he come?"}
