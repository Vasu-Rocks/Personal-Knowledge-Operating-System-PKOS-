"""Saved chats, step 2 of docs/07_MEMORY_PLAN.md: every question and answer from /query/stream is stored in a chat."""
import json
import uuid
from types import SimpleNamespace

import pytest

from api import routes_query
from conftest import event, run_db, sse_events
from database import conversations_db as db

API = "/api/v1"
TEXT = ("The surveyor visits the glacier station every Tuesday to read the temperature sensors. " * 4).encode()
QUESTION = TEXT.decode().strip()  # identical text: distance 0 with the fake embedder, so the passage is found


def ask(u, question, conversation_id=None):
    body = {"query": question} | ({"conversation_id": conversation_id} if conversation_id else {})
    r = u.client.post(f"{API}/query/stream", json=body, headers=u.headers)
    return r, (sse_events(r.text) if r.status_code == 200 else None)


def chat(u, conversation_id):
    return u.client.get(f"{API}/conversations/{conversation_id}", headers=u.headers).json()


def fake_stream(*tokens, fail=None):
    async def stream(prompt, settings=None):
        for t in tokens:
            yield json.dumps({"type": "token", "content": t})
        if fail:
            raise fail
    return stream


def test_question_and_answer_are_saved_in_a_new_chat(make_user):
    u = make_user("saver")
    u.upload("station.txt", TEXT)
    r, events = ask(u, QUESTION)
    assert r.status_code == 200 and events[-1] == "[DONE]"
    assert [e["type"] for e in events[:3]] == ["conversation", "sources", "graph"]

    conv = event(events, "conversation")
    saved = event(events, "saved")
    stored = chat(u, conv["conversation_id"])
    assert conv["title"] == stored["title"] == db.title_from_question(QUESTION)
    q, a = stored["messages"]
    assert (q["role"], q["content"], q["message_id"]) == ("user", QUESTION, saved["question_id"])
    assert (a["role"], a["content"], a["status"], a["message_id"]) == ("assistant", "fake answer", "complete", saved["answer_id"])
    assert a["sources"] == event(events, "sources")["sources"] and a["sources"][0]["filename"] == "station.txt"
    assert a["provider"] == "ollama"
    assert [c["conversation_id"] for c in u.client.get(f"{API}/conversations", headers=u.headers).json()["conversations"]] \
        == [conv["conversation_id"]]


def test_follow_up_questions_go_into_the_same_chat(make_user):
    u = make_user("follower")
    u.upload("station.txt", TEXT)
    cid = event(ask(u, QUESTION)[1], "conversation")["conversation_id"]
    r, events = ask(u, "And on which day?", cid)
    assert r.status_code == 200 and event(events, "conversation")["conversation_id"] == cid
    stored = chat(u, cid)
    assert [(m["seq"], m["role"]) for m in stored["messages"]] == [(1, "user"), (2, "assistant"), (3, "user"), (4, "assistant")]
    assert stored["messages"][2]["content"] == "And on which day?"
    assert stored["title"] == db.title_from_question(QUESTION)  # the title stays the first question
    assert len(u.client.get(f"{API}/conversations", headers=u.headers).json()["conversations"]) == 1


def test_an_empty_chat_created_first_gets_the_question_as_title(make_user):
    u = make_user("emptyfirst")
    cid = u.client.post(f"{API}/conversations", headers=u.headers).json()["conversation_id"]
    _, events = ask(u, "Where is the glacier station?", cid)
    assert event(events, "conversation")["title"] == "Where is the glacier station?"


def test_the_no_documents_answer_is_saved_too(make_user):
    u = make_user("nodocsaver")
    _, events = ask(u, "anything at all")
    stored = chat(u, event(events, "conversation")["conversation_id"])
    assert [m["content"] for m in stored["messages"]] == ["anything at all", routes_query.NO_ANSWER]
    assert stored["messages"][1]["sources"] == [] and stored["messages"][1]["status"] == "complete"


def test_unknown_or_foreign_chat_is_refused_and_nothing_is_saved(make_user):
    owner, other = make_user("chatowner"), make_user("chatthief")
    cid = event(ask(owner, "my private question")[1], "conversation")["conversation_id"]
    assert ask(other, "inject this", cid)[0].status_code == 404
    assert ask(other, "inject this", str(uuid.uuid4()))[0].status_code == 404
    assert len(chat(owner, cid)["messages"]) == 2
    assert other.client.get(f"{API}/conversations", headers=other.headers).json()["conversations"] == []


def test_a_provider_error_is_saved_as_error(make_user, monkeypatch):
    u = make_user("provfail")
    u.upload("station.txt", TEXT)
    monkeypatch.setattr(routes_query, "generate_rag_response_stream",
                        fake_stream("System Error: Cannot connect to Ollama. Is it running?"))
    _, events = ask(u, QUESTION)
    answer = chat(u, event(events, "conversation")["conversation_id"])["messages"][1]
    assert answer["status"] == "error" and answer["content"].startswith("System Error:")


def test_a_failure_mid_answer_keeps_what_was_written(make_user, monkeypatch):
    u = make_user("midfail")
    u.upload("station.txt", TEXT)
    monkeypatch.setattr(routes_query, "generate_rag_response_stream",
                        fake_stream("The surveyor ", "comes on", fail=RuntimeError("connection reset")))
    with pytest.raises(RuntimeError):
        ask(u, QUESTION)
    (conv,) = u.client.get(f"{API}/conversations", headers=u.headers).json()["conversations"]
    answer = chat(u, conv["conversation_id"])["messages"][1]
    assert (answer["status"], answer["content"]) == ("error", "The surveyor comes on")


def test_a_client_that_disconnects_mid_answer_leaves_a_partial_answer(make_user, monkeypatch):
    u = make_user("leaver")
    u.upload("station.txt", TEXT)
    me = u.client.get(f"{API}/me", headers=u.headers).json()
    monkeypatch.setattr(routes_query, "generate_rag_response_stream",
                        fake_stream("Every ", "Tuesday", ", with a full sensor check"))

    async def read_two_tokens_then_leave(pool):
        response = await routes_query.process_query_stream(
            routes_query.QueryRequest(query=QUESTION), SimpleNamespace(headers={}), me, pool)
        stream, tokens = response.body_iterator, 0
        async for chunk in stream:
            tokens += '"type": "token"' in chunk
            if tokens == 2:
                break
        await stream.aclose()  # what Starlette does when the client goes away

    run_db(read_two_tokens_then_leave)
    (conv,) = u.client.get(f"{API}/conversations", headers=u.headers).json()["conversations"]
    question, answer = chat(u, conv["conversation_id"])["messages"]
    assert question["content"] == QUESTION
    assert (answer["status"], answer["content"]) == ("partial", "Every Tuesday")


def test_retrieval_failure_saves_nothing(make_user, monkeypatch):
    u = make_user("retrfail")

    async def broken(*args, **kwargs):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(routes_query, "retrieve_context", broken)
    r, _ = ask(u, "will this be saved?")
    assert r.status_code == 500
    assert u.client.get(f"{API}/conversations", headers=u.headers).json()["conversations"] == []
