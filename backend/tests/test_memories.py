"""Long-term memories, step B1 of docs/07_MEMORY_PLAN.md: storage, the /memories API and the settings."""
import uuid

import numpy as np
import pytest

from conftest import event, fake_vector, run_db, sse_events
from database import memories_db as db

API = "/api/v1/memories"


def me(u):
    return u.client.get("/api/v1/me", headers=u.headers).json()["user_id"]


def add(u, text, kind="fact", **extra):
    return u.client.post(API, json={"text": text, "kind": kind, **extra}, headers=u.headers)


def stored_embedding(memory_id):
    async def q(pool):
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT embedding FROM memories WHERE memory_id = $1", uuid.UUID(memory_id))
    return np.asarray(run_db(q))


# ------------------------------------------------------------------------------------------------ adding and listing

def test_add_list_edit_delete(make_user):
    u = make_user("memo")
    assert u.client.get(API, headers=u.headers).json() == {"memories": []}

    r = add(u, "  My GATE exam is in\n February.  ")
    assert r.status_code == 201, r.text
    m = r.json()
    assert (m["text"], m["kind"], m["origin"], m["status"], m["use_count"]) == \
        ("My GATE exam is in February.", "fact", "manual", "active", 0)
    assert np.allclose(stored_embedding(m["memory_id"]), fake_vector("My GATE exam is in February."), atol=1e-6)

    pref = add(u, "Answer in short bullet points.", "preference").json()
    assert [x["text"] for x in u.client.get(API, headers=u.headers).json()["memories"]] == \
        ["Answer in short bullet points.", "My GATE exam is in February."]  # newest change first

    edited = u.client.patch(f"{API}/{m['memory_id']}", json={"text": "My GATE exam is on 8 February."}, headers=u.headers)
    assert edited.status_code == 200 and edited.json()["text"] == "My GATE exam is on 8 February."
    assert np.allclose(stored_embedding(m["memory_id"]), fake_vector("My GATE exam is on 8 February."), atol=1e-6)
    kind_only = u.client.patch(f"{API}/{pref['memory_id']}", json={"kind": "fact"}, headers=u.headers).json()
    assert kind_only["kind"] == "fact" and kind_only["text"] == "Answer in short bullet points."
    assert np.allclose(stored_embedding(pref["memory_id"]), fake_vector("Answer in short bullet points."), atol=1e-6)

    assert u.client.delete(f"{API}/{m['memory_id']}", headers=u.headers).status_code == 204
    assert u.client.delete(f"{API}/{m['memory_id']}", headers=u.headers).status_code == 404
    assert [x["memory_id"] for x in u.client.get(API, headers=u.headers).json()["memories"]] == [pref["memory_id"]]


@pytest.mark.parametrize("text, error", [
    ("", "cannot be empty"), ("   \n  ", "cannot be empty"), ("=====", "cannot be empty"),
    ("x" * 301, "at most 300"),
])
def test_text_is_checked(make_user, text, error):
    u = make_user("memocheck")
    r = add(u, text)
    assert r.status_code == 422 and error in r.text


def test_prompt_fences_are_removed_and_kinds_are_checked(make_user):
    u = make_user("memoclean")
    assert add(u, "I like === short answers").json()["text"] == "I like short answers"
    assert add(u, "Something", kind="secret").status_code == 422
    assert add(u, "x" * 300).status_code == 201  # exactly the limit is fine


def test_the_same_memory_twice_is_refused(make_user):
    u = make_user("memodupe")
    first = add(u, "I prefer metric units.").json()
    r = add(u, "i prefer  METRIC units.")
    assert r.status_code == 409 and "already saved" in r.json()["detail"]
    other = add(u, "I live in Zurich.").json()
    assert u.client.patch(f"{API}/{other['memory_id']}", json={"text": "I prefer metric units."},
                          headers=u.headers).status_code == 409
    # Saving a memory's own text again is not a duplicate of itself.
    assert u.client.patch(f"{API}/{first['memory_id']}", json={"text": "I prefer metric units."},
                          headers=u.headers).status_code == 200


def test_a_memory_can_point_at_the_users_own_chat_and_message(make_user):
    owner, other = make_user("memosrc"), make_user("memothief")
    events = sse_events(owner.client.post("/api/v1/query/stream", json={"query": "My exam is in February"},
                                          headers=owner.headers).text)
    cid = event(events, "conversation")["conversation_id"]
    qid = event(events, "saved")["question_id"]

    m = add(owner, "My exam is in February.", source_conversation_id=cid, source_message_id=qid).json()
    assert (m["source_conversation_id"], m["source_message_id"], m["source_title"]) == \
        (cid, qid, "My exam is in February")
    assert add(other, "stolen", source_conversation_id=cid).status_code == 404
    assert add(owner, "bad message", source_conversation_id=cid, source_message_id=str(uuid.uuid4())).status_code == 404
    assert add(owner, "message without chat", source_message_id=qid).status_code == 404

    # Deleting the chat keeps the memory; only the link goes.
    assert owner.client.delete(f"/api/v1/conversations/{cid}", headers=owner.headers).status_code == 204
    (kept,) = owner.client.get(API, headers=owner.headers).json()["memories"]
    assert kept["text"] == "My exam is in February." and kept["source_conversation_id"] is None


# ------------------------------------------------------------------------------------------------ isolation

def test_another_users_memories_are_invisible(make_user):
    owner, other = make_user("memoowner"), make_user("memospy")
    m = add(owner, "My bank is in Bern.").json()
    url = f"{API}/{m['memory_id']}"
    assert other.client.get(API, headers=other.headers).json() == {"memories": []}
    assert other.client.patch(url, json={"text": "changed"}, headers=other.headers).status_code == 404
    assert other.client.post(f"{url}/confirm", headers=other.headers).status_code == 404
    assert other.client.delete(url, headers=other.headers).status_code == 404
    assert other.client.delete(API, params={"confirm": "true"}, headers=other.headers).json() == {"deleted": 0}
    assert [x["text"] for x in owner.client.get(API, headers=owner.headers).json()["memories"]] == ["My bank is in Bern."]


def test_login_and_valid_ids_are_required(make_user):
    u = make_user("memoauth")
    assert u.client.get(API).status_code == 401
    assert u.client.post(API, json={"text": "x"}).status_code == 401
    assert u.client.get(f"{API}/settings").status_code == 401
    assert u.client.patch(f"{API}/not-a-uuid", json={"kind": "fact"}, headers=u.headers).status_code == 422


# ------------------------------------------------------------------------------------------------ suggestions, delete all

def test_a_suggestion_waits_until_it_is_kept(make_user):
    u = make_user("memosuggest")
    uid = me(u)
    pending = run_db(lambda pool: db.create_memory(pool, uid, "I am a beginner in statistics.", "fact",
                                                   fake_vector("x"), origin="suggested", status="pending"))
    assert [m["text"] for m in u.client.get(API, params={"status": "pending"}, headers=u.headers).json()["memories"]] \
        == ["I am a beginner in statistics."]
    assert u.client.get(API, params={"status": "active"}, headers=u.headers).json()["memories"] == []

    kept = u.client.post(f"{API}/{pending['memory_id']}/confirm", json={"text": "I am new to statistics."}, headers=u.headers)
    assert kept.status_code == 200, kept.text
    assert (kept.json()["status"], kept.json()["origin"], kept.json()["text"]) == ("active", "suggested", "I am new to statistics.")
    assert np.allclose(stored_embedding(pending["memory_id"]), fake_vector("I am new to statistics."), atol=1e-6)
    assert u.client.post(f"{API}/{pending['memory_id']}/confirm", headers=u.headers).status_code == 409


def test_delete_all_needs_confirmation(make_user):
    u = make_user("memowipe")
    for text in ("one fact", "two facts", "three facts"):
        add(u, text)
    r = u.client.delete(API, headers=u.headers)
    assert r.status_code == 400 and len(u.client.get(API, headers=u.headers).json()["memories"]) == 3
    assert u.client.delete(API, params={"confirm": "true"}, headers=u.headers).json() == {"deleted": 3}
    assert u.client.get(API, headers=u.headers).json() == {"memories": []}


def test_there_is_a_limit_per_user(make_user, monkeypatch):
    monkeypatch.setattr(db, "MAX_MEMORIES", 2)
    u = make_user("memolimit")
    assert add(u, "first").status_code == 201 and add(u, "second").status_code == 201
    r = add(u, "third")
    assert r.status_code == 409 and "Delete some" in r.json()["detail"]


# ------------------------------------------------------------------------------------------------ settings

def test_settings_default_on_and_can_be_changed_separately(make_user):
    u = make_user("memosettings")
    url = f"{API}/settings"
    assert u.client.get(url, headers=u.headers).json() == {"enabled": True, "suggest": True}
    assert u.client.put(url, json={"suggest": False}, headers=u.headers).json() == {"enabled": True, "suggest": False}
    assert u.client.put(url, json={"enabled": False}, headers=u.headers).json() == {"enabled": False, "suggest": False}
    assert u.client.get(url, headers=u.headers).json() == {"enabled": False, "suggest": False}
    other = make_user("memosettings2")
    assert other.client.get(url, headers=other.headers).json() == {"enabled": True, "suggest": True}


def test_deleting_the_user_removes_memories_and_settings(make_user):
    u = make_user("memogone")
    uid = me(u)
    add(u, "a fact")
    u.client.put(f"{API}/settings", json={"enabled": False}, headers=u.headers)

    async def drop(pool):
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE user_id = $1", uuid.UUID(uid))
            return (await conn.fetchval("SELECT count(*) FROM memories WHERE user_id = $1", uuid.UUID(uid)),
                    await conn.fetchval("SELECT count(*) FROM user_memory_settings WHERE user_id = $1", uuid.UUID(uid)))

    assert run_db(drop) == (0, 0)
