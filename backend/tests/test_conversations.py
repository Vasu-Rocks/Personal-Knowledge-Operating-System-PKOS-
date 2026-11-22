"""Saved chats, step 1 of docs/07_MEMORY_PLAN.md: tables, data access and the /conversations API."""
import asyncio
import uuid

import pytest

from database import conversations_db as db
from database.conversations_db import title_from_question
from conftest import run_db

API = "/api/v1/conversations"


def user_id(u):
    return u.client.get("/api/v1/me", headers=u.headers).json()["user_id"]


# ---------------------------------------------------------------------------------------------------- titles

@pytest.mark.parametrize("question, title", [
    ("What did the meeting notes say?", "What did the meeting notes say?"),
    ("  spaces\n and\tnew lines  ", "spaces and new lines"),
    ("", "New chat"),
    ("How does the graph worker decide which chunks to process first when a large book is uploaded?",
     "How does the graph worker decide which chunks to process..."),
    ("x" * 80, "x" * 60 + "..."),
])
def test_title_from_question(question, title):
    assert title_from_question(question) == title
    assert len(title_from_question(question)) <= db.TITLE_MAX + 3


# ---------------------------------------------------------------------------------------------------- API

def test_create_list_open_rename_delete(make_user):
    u = make_user("chats")
    h = u.headers
    assert u.client.get(API, headers=h).json() == {"conversations": [], "next_before": None}

    first = u.client.post(API, headers=h)
    assert first.status_code == 201, first.text
    first = first.json()
    assert first["title"] == "New chat" and first["message_count"] == 0
    second = u.client.post(API, json={"title": "  Glacier   research "}, headers=h).json()
    assert second["title"] == "Glacier research"

    listed = u.client.get(API, headers=h).json()["conversations"]
    assert [c["conversation_id"] for c in listed] == [second["conversation_id"], first["conversation_id"]]

    opened = u.client.get(f"{API}/{first['conversation_id']}", headers=h)
    assert opened.status_code == 200
    assert opened.json()["messages"] == [] and "summary" not in opened.json()

    renamed = u.client.patch(f"{API}/{first['conversation_id']}", json={"title": "Exam prep"}, headers=h)
    assert renamed.status_code == 200 and renamed.json()["title"] == "Exam prep"
    assert u.client.patch(f"{API}/{first['conversation_id']}", json={"title": "   "}, headers=h).status_code == 422
    assert u.client.patch(f"{API}/{first['conversation_id']}", json={"title": "x" * 201}, headers=h).status_code == 422

    assert u.client.delete(f"{API}/{first['conversation_id']}", headers=h).status_code == 204
    assert u.client.get(f"{API}/{first['conversation_id']}", headers=h).status_code == 404
    assert u.client.delete(f"{API}/{first['conversation_id']}", headers=h).status_code == 404
    assert [c["title"] for c in u.client.get(API, headers=h).json()["conversations"]] == ["Glacier research"]


def test_another_users_chat_is_invisible(make_user):
    owner, other = make_user("owner"), make_user("intruder")
    chat = owner.client.post(API, json={"title": "Private"}, headers=owner.headers).json()
    url = f"{API}/{chat['conversation_id']}"

    assert other.client.get(API, headers=other.headers).json()["conversations"] == []
    assert other.client.get(url, headers=other.headers).status_code == 404
    assert other.client.patch(url, json={"title": "hacked"}, headers=other.headers).status_code == 404
    assert other.client.delete(url, headers=other.headers).status_code == 404
    # Same answer as a chat that never existed: the id reveals nothing.
    assert other.client.get(f"{API}/{uuid.uuid4()}", headers=other.headers).json() == \
        other.client.get(url, headers=other.headers).json()

    assert owner.client.get(url, headers=owner.headers).json()["title"] == "Private"
    assert run_db(lambda pool: db.append_message(pool, user_id(other), uuid.UUID(chat["conversation_id"]),
                                                 "user", "sneaky")) is None


def test_login_and_valid_ids_are_required(make_user):
    u = make_user("chatauth")
    assert u.client.get(API).status_code == 401
    assert u.client.post(API).status_code == 401
    assert u.client.get(f"{API}/not-a-uuid", headers=u.headers).status_code == 422


def test_paging_newest_first(make_user):
    u = make_user("pager")
    ids = [u.client.post(API, json={"title": f"chat {i}"}, headers=u.headers).json()["conversation_id"] for i in range(5)]
    page1 = u.client.get(API, params={"limit": 2}, headers=u.headers).json()
    assert [c["title"] for c in page1["conversations"]] == ["chat 4", "chat 3"] and page1["next_before"]
    page2 = u.client.get(API, params={"limit": 2, "before": page1["next_before"]}, headers=u.headers).json()
    page3 = u.client.get(API, params={"limit": 2, "before": page2["next_before"]}, headers=u.headers).json()
    assert [c["title"] for c in page2["conversations"]] == ["chat 2", "chat 1"]
    assert [c["title"] for c in page3["conversations"]] == ["chat 0"] and page3["next_before"] is None
    assert len(set(ids)) == 5


# ---------------------------------------------------------------------------------------------------- messages

def test_messages_are_numbered_titled_and_kept_with_their_sources(make_user):
    u = make_user("messages")
    chat = u.client.post(API, headers=u.headers).json()
    cid, uid = uuid.UUID(chat["conversation_id"]), user_id(u)
    sources = [{"chunk_id": 7, "filename": "notes.pdf", "page": 2, "text": "Order 12 sensors", "via": "vector"}]
    graph = {"nodes": [{"id": "e1", "name": "Sensor"}], "links": []}

    async def write(pool):
        await db.append_message(pool, uid, cid, "user", "How many temperature sensors should we order for the station?",
                                standalone_query="How many temperature sensors should we order?", needs_search=True)
        await db.append_message(pool, uid, cid, "assistant", "Twelve. [Chunk 1]", sources=sources, graph=graph,
                                provider="ollama", model="llama3.2")
        await db.append_message(pool, uid, cid, "user", "And when?")
        await db.append_message(pool, uid, cid, "assistant", "On Tuesd", status="partial")
        return await db.get_messages(pool, uid, cid, last=2), await db.get_messages(pool, uid, cid, after_seq=3)

    last_two, after_three = run_db(write)
    assert [m["seq"] for m in last_two] == [3, 4] and [m["seq"] for m in after_three] == [4]

    opened = u.client.get(f"{API}/{cid}", headers=u.headers).json()
    assert opened["title"] == "How many temperature sensors should we order for the..."
    assert opened["message_count"] == 4
    msgs = opened["messages"]
    assert [(m["seq"], m["role"]) for m in msgs] == [(1, "user"), (2, "assistant"), (3, "user"), (4, "assistant")]
    assert msgs[0]["standalone_query"] == "How many temperature sensors should we order?" and msgs[0]["needs_search"]
    assert msgs[1]["sources"] == sources and msgs[1]["graph"] == graph and msgs[1]["model"] == "llama3.2"
    assert msgs[2]["sources"] is None and msgs[3]["status"] == "partial"


def test_a_title_the_user_chose_is_not_replaced(make_user):
    u = make_user("titlekeep")
    chat = u.client.post(API, json={"title": "My own title"}, headers=u.headers).json()
    run_db(lambda pool: db.append_message(pool, user_id(u), uuid.UUID(chat["conversation_id"]), "user", "A question"))
    assert u.client.get(f"{API}/{chat['conversation_id']}", headers=u.headers).json()["title"] == "My own title"


def test_concurrent_messages_get_distinct_numbers(make_user):
    u = make_user("concurrent")
    cid, uid = uuid.UUID(u.client.post(API, headers=u.headers).json()["conversation_id"]), user_id(u)

    async def burst(pool):
        await asyncio.gather(*(db.append_message(pool, uid, cid, "user", f"q{i}") for i in range(8)))
        return await db.get_messages(pool, uid, cid)

    assert sorted(m["seq"] for m in run_db(burst)) == list(range(1, 9))


def test_deleting_a_chat_or_its_user_removes_the_messages(make_user):
    u = make_user("cascade")
    cid, uid = uuid.UUID(u.client.post(API, headers=u.headers).json()["conversation_id"]), user_id(u)

    async def check(pool):
        await db.append_message(pool, uid, cid, "user", "hello")
        assert await db.delete_conversation(pool, uid, cid)
        async with pool.acquire() as conn:
            orphans = await conn.fetchval("SELECT count(*) FROM messages WHERE conversation_id = $1", cid)
            cid2 = (await db.create_conversation(pool, uid))["conversation_id"]
            await db.append_message(pool, uid, uuid.UUID(cid2), "user", "bye")
            await conn.execute("DELETE FROM users WHERE user_id = $1", uuid.UUID(uid))
            left = await conn.fetchval("SELECT count(*) FROM conversations WHERE user_id = $1", uuid.UUID(uid))
            msgs = await conn.fetchval("SELECT count(*) FROM messages WHERE conversation_id = $1", uuid.UUID(cid2))
        return orphans, left, msgs

    assert run_db(check) == (0, 0, 0)
