"""Past chats (episodic memory), step B3 of docs/07_MEMORY_PLAN.md."""
import json
import uuid

import numpy as np
import pytest

from api import routes_query
from conftest import event, fake_vector, run_db, sse_events
from rag.memory import episodic
from rag.memory.episodic import RECAP_MAX_CHARS, build_recap, refers_to_past_chats
from rag.query.prompt_builder import build_rag_prompt
from rag.query.retriever import format_context_blocks

API = "/api/v1"


# ------------------------------------------------------------------------------------------------ when to look back

@pytest.mark.parametrize("question", [
    "What did we decide about the sensors last time?",
    "In our earlier chat you explained paging - remind me what you said",
    "What did we conclude about the budget?",
    "Did we ever discuss the Kyoto trip?",
    "You told me something about the visa, what was it?",
    "Last time we talked about ice loss. What was the number?",
    "Find the previous conversation about my thesis",
    "Remind me what the exam topics were",
    "We discussed the surveyor before, who was it?",
])
def test_questions_that_refer_to_earlier_chats(question):
    assert refers_to_past_chats(question)


@pytest.mark.parametrize("question", [
    "What does the March meeting say about travel costs?",
    "Summarise my notes on photosynthesis",
    "How does TCP congestion control work?",
    "Who visits the glacier station?",
    "Explain the light reactions simply",
    "What is the last chapter of the networking book about?",
    "Compare paging and segmentation",
])
def test_ordinary_questions_do_not_look_back(question):
    assert not refers_to_past_chats(question)


def test_the_rewritten_question_counts_too():
    assert refers_to_past_chats("and the budget?", "What did we decide about the budget last time?")


# ------------------------------------------------------------------------------------------------ recaps

def msg(role, content, status="complete"):
    return {"role": role, "content": content, "status": status}


def test_a_short_chat_is_recapped_from_its_turns():
    recap = build_recap("Sensor order", None, [
        msg("user", "Which sensors should we order?"),
        msg("assistant", "The Campbell Scientific ones [Chunk 1], because they drift less. " + "x " * 200),
        msg("user", "broken"), msg("assistant", "System Error: down", "error"),
    ])
    assert recap.startswith("Sensor order. Question: Which sensors should we order? Answer: The Campbell Scientific ones,")
    assert "[Chunk" not in recap and "System Error" not in recap and "..." in recap


def test_a_long_chat_is_recapped_from_its_summary_and_kept_short():
    assert build_recap("Budget", "They agreed on 120,000 euros.", [msg("user", "ignored")]) == \
        "Budget. They agreed on 120,000 euros."
    assert len(build_recap("T", "word " * 400, [])) <= RECAP_MAX_CHARS


def test_update_recap_stores_the_text_and_its_embedding(make_user):
    u = make_user("recapper")
    r = u.client.post(f"{API}/query/stream", json={"query": "Which sensors should we order?"}, headers=u.headers)
    cid = event(sse_events(r.text), "conversation")["conversation_id"]
    uid = u.client.get(f"{API}/me", headers=u.headers).json()["user_id"]

    async def go(pool):
        assert await episodic.update_recap(pool, uid, uuid.UUID(cid))
        async with pool.acquire() as conn:
            return await conn.fetchrow("SELECT recap, recap_embedding FROM conversations WHERE conversation_id = $1",
                                       uuid.UUID(cid))

    row = run_db(go)
    assert row["recap"].startswith("Which sensors should we order?. Question: Which sensors should we order?")
    assert np.allclose(np.asarray(row["recap_embedding"]), fake_vector(row["recap"]), atol=1e-6)


# ------------------------------------------------------------------------------------------------ prompt and blocks

def test_past_chat_blocks_have_their_own_header_and_rule():
    chunk = {"chunk_id": "chat:x", "conversation_id": "x", "filename": "Sensor order", "page": "2026-11-20",
             "text": "They chose Campbell.", "via": "chat"}
    context, used = format_context_blocks([chunk])
    assert context.startswith('[Chunk 1] Earlier chat: "Sensor order" (2026-11-20)\nThey chose Campbell.')
    system = build_rag_prompt("What did we decide?", context, {})[0]["content"]
    assert '5. Blocks marked "Earlier chat:" are recaps of the user\'s earlier conversations' in system
    assert "Earlier chat:\" are recaps" not in build_rag_prompt("q", "[Chunk 1] Source: a.pdf (Page 1)\nx", {})[0]["content"]


# ------------------------------------------------------------------------------------------------ end to end

@pytest.fixture
def prompts(monkeypatch):
    seen = []

    async def recording(messages, settings=None):
        seen.append(messages)
        yield json.dumps({"type": "token", "content": "from the earlier chat"})

    monkeypatch.setattr(routes_query, "generate_rag_response_stream", recording)
    return seen


def ask(u, question, cid=None):
    body = {"query": question} | ({"conversation_id": cid} if cid else {})
    r = u.client.post(f"{API}/query/stream", json=body, headers=u.headers)
    assert r.status_code == 200, r.text
    return sse_events(r.text)


TOPIC = "campbell scientific sensors drift less order twelve"
# The fake embedder compares words, so the question repeats the topic to land within the distance cutoff.
LOOKBACK = f"what did we decide last time: {TOPIC} {TOPIC}"


def chat_with_recap(u):
    """A finished chat about the sensor order, with its recap stored (the background task is off in tests)."""
    cid = event(ask(u, f"Which sensors: {TOPIC}"), "conversation")["conversation_id"]
    uid = u.client.get(f"{API}/me", headers=u.headers).json()["user_id"]
    assert run_db(lambda pool: episodic.update_recap(pool, uid, uuid.UUID(cid)))
    return cid


def chat_sources(events):
    return [s for s in event(events, "sources")["sources"] if s.get("via") == "chat"]


def test_a_question_about_an_earlier_chat_gets_that_chat(make_user, prompts):
    u = make_user("pastuser")
    earlier = chat_with_recap(u)
    events = ask(u, LOOKBACK)
    (found,) = chat_sources(events)
    assert found["conversation_id"] == earlier and found["filename"].startswith("Which sensors")
    assert 'Earlier chat: "Which sensors' in prompts[-1][0]["content"]
    assert "recaps of the user's earlier conversations" in prompts[-1][0]["content"]


def test_ordinary_questions_never_pull_in_old_chats(make_user, prompts):
    u = make_user("pastquiet")
    chat_with_recap(u)
    assert chat_sources(ask(u, f"Tell me about the {TOPIC}")) == []


def test_the_chat_being_asked_in_is_not_its_own_past(make_user, prompts):
    u = make_user("pastself")
    earlier = chat_with_recap(u)
    assert chat_sources(ask(u, LOOKBACK, earlier)) == []


def test_another_users_chats_and_memory_off(make_user, prompts):
    owner, other = make_user("pastowner"), make_user("pastother")
    chat_with_recap(owner)
    assert chat_sources(ask(other, LOOKBACK)) == []
    owner.client.put(f"{API}/memories/settings", json={"enabled": False}, headers=owner.headers)
    assert chat_sources(ask(owner, LOOKBACK)) == []
