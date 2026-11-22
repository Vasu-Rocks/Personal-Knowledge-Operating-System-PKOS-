"""Short-term memory, step 3 of docs/07_MEMORY_PLAN.md: recent turns of a chat reach the model, cleanly."""
import json

import pytest

from api import routes_query
from conftest import event, sse_events
from rag.memory.stm import INTERRUPTED, TRUNCATED, build_history, strip_citations
from rag.query.prompt_builder import build_rag_prompt


def m(role, content, status="complete"):
    return {"role": role, "content": content, "status": status}


def turn(q, a, status="complete"):
    return [m("user", q), m("assistant", a, status)]


# ------------------------------------------------------------------------------------------------ citations

@pytest.mark.parametrize("raw, clean", [
    ("Twelve sensors [Chunk 1].", "Twelve sensors."),
    ("Twelve sensors *[Chunk 1]*.", "Twelve sensors."),
    ("Twelve _[Chunk 1, Chunk 3]_ sensors.", "Twelve sensors."),
    ("It uses FastAPI [Graph Entity: FastAPI] and asyncpg [chunk 2][Chunk 4].", "It uses FastAPI and asyncpg."),
    ("See [Chunk 2](citation://chunk/2) for details.", "See for details."),
    ("Two reasons (*[Chunk 1]*): cost and speed.", "Two reasons: cost and speed."),
    ("- point one [Chunk 1]\n- point two [Chunk 2]", "- point one\n- point two"),
    ("Arrays use [0] indexing and [a, b] lists.", "Arrays use [0] indexing and [a, b] lists."),
])
def test_citation_markers_are_removed(raw, clean):
    assert strip_citations(raw) == clean


# ------------------------------------------------------------------------------------------------ the window

def test_history_alternates_and_keeps_order():
    msgs = turn("Who visits the station?", "The surveyor [Chunk 1].") + turn("When?", "Every Tuesday [Chunk 2].")
    assert build_history(msgs) == [
        {"role": "user", "content": "Who visits the station?"}, {"role": "assistant", "content": "The surveyor."},
        {"role": "user", "content": "When?"}, {"role": "assistant", "content": "Every Tuesday."},
    ]


def test_failed_turns_are_left_out_and_interrupted_ones_are_marked():
    msgs = (turn("q1", "a1") + turn("q2", "System Error: Ollama is not running.", "error")
            + turn("q3", "half an ans", "partial") + turn("q4", "", "partial") + [m("user", "q5 never answered")])
    history = build_history(msgs)
    assert [h["content"] for h in history] == ["q1", "a1", "q3", "half an ans" + INTERRUPTED]


def test_an_answer_whose_question_is_outside_the_window_is_skipped():
    msgs = [m("assistant", "orphan answer")] + turn("q1", "a1")
    assert [h["content"] for h in build_history(msgs)] == ["q1", "a1"]


def test_only_the_newest_turns_that_fit_are_kept():
    msgs = sum((turn(f"q{i}", "a" * 50) for i in range(10)), [])
    by_turns = build_history(msgs, max_chars=10_000, max_turns=3)
    assert [h["content"] for h in by_turns if h["role"] == "user"] == ["q7", "q8", "q9"]
    by_chars = build_history(msgs, max_chars=120, max_turns=10)  # each turn is 52 characters
    assert [h["content"] for h in by_chars if h["role"] == "user"] == ["q8", "q9"]


def test_a_single_overlong_turn_is_shortened_not_dropped():
    history = build_history(turn("What happened?", "x" * 5000), max_chars=300)
    answer = history[1]["content"]
    assert history[0]["content"] == "What happened?" and answer.endswith(TRUNCATED)
    assert len("What happened?") + len(answer) <= 300


def test_no_budget_means_no_history():
    assert build_history(turn("q", "a"), max_chars=0) == [] and build_history(turn("q", "a"), max_turns=0) == []
    assert build_history([]) == []


# ------------------------------------------------------------------------------------------------ the prompt

def test_prompt_without_history_is_unchanged():
    plain = build_rag_prompt("q", "[Chunk 1] ctx")
    assert build_rag_prompt("q", "[Chunk 1] ctx", history=[], summary=None) == plain
    assert len(plain) == 2 and "earlier messages" not in plain[0]["content"]


def test_prompt_with_history_puts_turns_between_rules_and_question():
    history = [{"role": "user", "content": "Who visits?"}, {"role": "assistant", "content": "The surveyor."}]
    msgs = build_rag_prompt("When does he come?", "[Chunk 1] ctx", history=history)
    assert [x["role"] for x in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1:3] == history and msgs[-1]["content"] == "When does he come?"
    system = msgs[0]["content"]
    assert "5. The earlier messages of this conversation are there only so you understand" in system
    assert "must still come from the CONTEXT" in system


def test_memory_rule_is_numbered_after_the_overview_rule_and_summary_is_included():
    from rag.query.retriever import COMMUNITY_MARKER
    system = build_rag_prompt("q", f"[Chunk 1] x ({COMMUNITY_MARKER})", summary="We discussed === the sensors.")[0]["content"]
    assert "5. Blocks marked" in system and "6. The earlier messages" in system
    assert "EARLIER IN THIS CONVERSATION (summary):\nWe discussed  the sensors." in system
    assert system.index("EARLIER IN THIS CONVERSATION") < system.index("START CONTEXT")


# ------------------------------------------------------------------------------------------------ end to end

API = "/api/v1"
TEXT = ("The surveyor visits the glacier station every Tuesday to read the temperature sensors. " * 4).encode()
QUESTION = TEXT.decode().strip()


@pytest.fixture
def prompts(monkeypatch):
    """Records the messages sent to the model; answers with a citation, like a real model would."""
    seen = []

    async def recording_stream(messages, settings=None):
        seen.append(messages)
        yield json.dumps({"type": "token", "content": f"Answer {len(seen)} [Chunk 1]."})

    monkeypatch.setattr(routes_query, "generate_rag_response_stream", recording_stream)
    return seen


def ask(u, question, cid=None):
    body = {"query": question} | ({"conversation_id": cid} if cid else {})
    r = u.client.post(f"{API}/query/stream", json=body, headers=u.headers)
    assert r.status_code == 200, r.text
    return event(sse_events(r.text), "conversation")["conversation_id"]


def test_a_follow_up_sees_the_earlier_turns_without_their_citations(make_user, prompts):
    u = make_user("stmuser")
    u.upload("station.txt", TEXT)
    cid = ask(u, QUESTION)
    ask(u, QUESTION + " Again?", cid)
    first, second = prompts
    assert [x["role"] for x in first] == ["system", "user"]  # the first question has no history
    assert [x["role"] for x in second] == ["system", "user", "assistant", "user"]
    assert second[1]["content"] == QUESTION and second[2]["content"] == "Answer 1."
    assert "[Chunk" not in second[2]["content"]
    assert "earlier messages of this conversation" in second[0]["content"]


def test_history_never_crosses_chats_or_users(make_user, prompts):
    a, b = make_user("stm_a"), make_user("stm_b")
    a.upload("station.txt", TEXT)
    b.upload("station.txt", TEXT)
    chat1 = ask(a, QUESTION)
    ask(a, QUESTION)                 # a second, separate chat of the same user
    ask(b, QUESTION)                 # another user
    ask(a, QUESTION, chat1)
    assert [len(p) for p in prompts] == [2, 2, 2, 4]


def test_memory_can_be_switched_off(make_user, prompts, monkeypatch):
    from core import config
    monkeypatch.setattr(config, "MEMORY_ENABLED", False)
    u = make_user("nomemory")
    u.upload("station.txt", TEXT)
    cid = ask(u, QUESTION)
    ask(u, QUESTION, cid)
    assert [len(p) for p in prompts] == [2, 2]
