"""Import from another PKOS database: a second database on the test server plays the old installation."""
import asyncio
import os
import uuid

import asyncpg
import numpy as np
import pytest

from conftest import fake_vector

SOURCE_DB = os.environ["POSTGRES_DB"] + "_import_src"


def conn_args(db):
    return dict(host=os.environ["POSTGRES_HOST"], port=int(os.environ["POSTGRES_PORT"]), user=os.environ["POSTGRES_USER"],
                password=os.environ["POSTGRES_PASSWORD"], database=db)


async def _build_source():
    """A fresh PKOS schema in SOURCE_DB with two users, a document with two chunks, entities and links."""
    admin = await asyncpg.connect(**conn_args(os.environ["POSTGRES_DB"]))
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{SOURCE_DB}"')
        await admin.execute(f'CREATE DATABASE "{SOURCE_DB}"')
    finally:
        await admin.close()

    from pgvector.asyncpg import register_vector
    from database.postgres_core import configure_unified_schema

    boot = await asyncpg.connect(**conn_args(SOURCE_DB))
    await boot.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await boot.close()
    pool = await asyncpg.create_pool(**conn_args(SOURCE_DB), init=register_vector, min_size=1, max_size=2)
    try:
        await configure_unified_schema(pool)
        alice, bob = uuid.uuid4(), uuid.uuid4()
        doc = uuid.uuid4()
        e1, e2 = uuid.uuid4(), uuid.uuid4()
        rel = uuid.uuid4()
        async with pool.acquire() as c:
            for uid, name in [(alice, "old_alice"), (bob, "old_bob")]:
                await c.execute("INSERT INTO users (user_id, email, username, name, hashed_password) VALUES ($1, $2, $3, $4, 'x')",
                                uid, f"{name}@example.com", name, name.title())
            await c.execute("INSERT INTO documents (doc_id, user_id, filename) VALUES ($1, $2, 'notes.txt')", doc, alice)
            chunk_ids = [await c.fetchval(
                "INSERT INTO document_chunks (doc_id, page_number, text_content, embedding) VALUES ($1, 1, $2, $3) RETURNING chunk_id",
                doc, text, fake_vector(text)) for text in ["glaciers melt in the alps", "sensors measure the melt"]]
            for eid, n in [(e1, "Glacier"), (e2, "Sensor")]:
                await c.execute("""INSERT INTO entities (entity_id, user_id, name, canonical_name, category, embedding)
                                   VALUES ($1, $2, $3::text, lower($3::text), 'CONCEPT', $4)""", eid, alice, n, fake_vector(n))
            await c.execute("""INSERT INTO relationships (rel_id, user_id, source_entity_id, target_entity_id, predicate)
                               VALUES ($1, $2, $3, $4, 'RELATED_TO')""", rel, alice, e2, e1)
            await c.execute("INSERT INTO chunk_entity_junction (chunk_id, entity_id) VALUES ($1, $2), ($3, $4)",
                            chunk_ids[0], e1, chunk_ids[1], e2)
            await c.execute("INSERT INTO relationship_mentions (rel_id, chunk_id) VALUES ($1, $2)", rel, chunk_ids[1])
            chat = uuid.uuid4()
            await c.execute("""INSERT INTO conversations (conversation_id, user_id, title, summary, summary_upto_seq, message_count)
                               VALUES ($1, $2, 'Melting glaciers', 'They discussed melt rates.', 0, 2)""", chat, alice)
            await c.execute("""INSERT INTO messages (message_id, conversation_id, seq, role, content, standalone_query, needs_search)
                               VALUES ($1, $2, 1, 'user', 'Why do they melt?', 'Why do the alpine glaciers melt?', true)""",
                            uuid.uuid4(), chat)
            await c.execute("""INSERT INTO messages (message_id, conversation_id, seq, role, content, sources, status)
                               VALUES ($1, $2, 2, 'assistant', 'Warmer summers [Chunk 1].', $3::jsonb, 'complete')""",
                            uuid.uuid4(), chat, '[{"chunk_id": %d, "filename": "notes.txt", "page": 1, '
                            '"text": "glaciers melt in the alps", "via": "vector"}]' % chunk_ids[0])
        return {"alice": alice, "bob": bob, "doc": doc, "chunk_ids": chunk_ids, "chat": chat}
    finally:
        await pool.close()


@pytest.fixture(scope="module")
def source(client):
    return asyncio.run(_build_source())


@pytest.fixture
def desktop_mode(monkeypatch):
    from core import config
    monkeypatch.setattr(config, "ENV", "desktop")


def run_import(user, **overrides):
    body = {"host": "localhost" if os.environ["POSTGRES_HOST"] in ("localhost", "127.0.0.1") else os.environ["POSTGRES_HOST"],
            "port": int(os.environ["POSTGRES_PORT"]), "user": os.environ["POSTGRES_USER"],
            "password": os.environ["POSTGRES_PASSWORD"], "database": SOURCE_DB, **overrides}
    return user.client.post("/api/v1/import/pkos", json=body, headers=user.headers)


def target_rows(sql, *args):
    async def q():
        c = await asyncpg.connect(**conn_args(os.environ["POSTGRES_DB"]))
        try:
            return await c.fetch(sql, *args)
        finally:
            await c.close()
    return asyncio.run(q())


def test_only_available_in_the_desktop_app(make_user, source):
    assert run_import(make_user("webuser")).status_code == 404


def test_only_local_databases(make_user, source, desktop_mode):
    r = run_import(make_user("remote"), host="db.example.com")
    assert r.status_code == 400 and "this computer" in r.json()["detail"]


def test_dry_run_reports_without_changing_anything(make_user, source, desktop_mode):
    r = run_import(make_user("dry"), dry_run=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["imported_users"]) == ["old_alice", "old_bob"] and body["dry_run"] is True
    assert body["rows"]["document_chunks"] == 2
    assert target_rows("SELECT 1 FROM users WHERE username = 'old_alice'") == []


def test_import_copies_everything_with_new_chunk_ids_and_is_idempotent(make_user, source, desktop_mode):
    # A chunk already in the app, so source chunk IDs are likely to collide with existing ones.
    existing = make_user("existing")
    existing.upload("mine.txt", b"my own document about photosynthesis and chlorophyll pigments")

    body = run_import(existing).json()
    assert sorted(body["imported_users"]) == ["old_alice", "old_bob"]
    assert body["rows"] == {**body["rows"], "users": 2, "documents": 1, "document_chunks": 2, "entities": 2,
                            "relationships": 1, "chunk_entity_junction": 2, "relationship_mentions": 1,
                            "conversations": 1, "messages": 2}
    assert "not imported" in body["note"]

    # Saved chats come along with their history, searched question, sources snapshot and running summary.
    (chat,) = target_rows("SELECT title, summary, message_count FROM conversations WHERE user_id = $1", source["alice"])
    assert dict(chat) == {"title": "Melting glaciers", "summary": "They discussed melt rates.", "message_count": 2}
    msgs = target_rows("SELECT seq, role, content, standalone_query, sources::text AS sources FROM messages "
                       "WHERE conversation_id = $1 ORDER BY seq", source["chat"])
    assert [(m["seq"], m["role"], m["content"]) for m in msgs] == [
        (1, "user", "Why do they melt?"), (2, "assistant", "Warmer summers [Chunk 1].")]
    assert msgs[0]["standalone_query"] == "Why do the alpine glaciers melt?"
    assert '"text": "glaciers melt in the alps"' in msgs[1]["sources"]

    chunks = target_rows("SELECT chunk_id, text_content, embedding::text AS emb FROM document_chunks WHERE doc_id = $1 "
                         "ORDER BY text_content", source["doc"])
    assert [c["text_content"] for c in chunks] == ["glaciers melt in the alps", "sensors measure the melt"]
    vector = np.array([float(x) for x in chunks[0]["emb"].strip("[]").split(",")])
    assert np.allclose(vector, fake_vector("glaciers melt in the alps"), atol=1e-6)  # vectors copied unchanged

    # Every junction row points at the imported chunk with the same text, through the new IDs.
    links = target_rows("""
        SELECT e.name, dc.text_content FROM chunk_entity_junction j
        JOIN entities e ON e.entity_id = j.entity_id JOIN document_chunks dc ON dc.chunk_id = j.chunk_id
        WHERE e.user_id = $1 ORDER BY e.name""", source["alice"])
    assert [(r["name"], r["text_content"]) for r in links] == [
        ("Glacier", "glaciers melt in the alps"), ("Sensor", "sensors measure the melt")]
    mention = target_rows("""SELECT dc.text_content FROM relationship_mentions m JOIN document_chunks dc ON dc.chunk_id = m.chunk_id
                             JOIN relationships r ON r.rel_id = m.rel_id WHERE r.user_id = $1""", source["alice"])
    assert [r["text_content"] for r in mention] == ["sensors measure the melt"]

    # The existing user's own document is untouched.
    assert [d["filename"] for d in existing.documents()] == ["mine.txt"]

    again = run_import(existing).json()
    assert again["imported_users"] == [] and {s["reason"] for s in again["skipped_users"]} == {"already imported"}
    assert len(target_rows("SELECT 1 FROM document_chunks WHERE doc_id = $1", source["doc"])) == 2


def test_imported_users_keep_their_ids(client, source, desktop_mode):
    rows = target_rows("SELECT username, hashed_password FROM users WHERE user_id = $1", source["alice"])
    assert rows and rows[0]["username"] == "old_alice" and rows[0]["hashed_password"] == "x"  # hash copied as-is


def test_name_clash_is_skipped(make_user, source, desktop_mode):
    async def add_clash():
        c = await asyncpg.connect(**conn_args(SOURCE_DB))
        try:
            await c.execute("INSERT INTO users (user_id, email, username, name, hashed_password) VALUES ($1, $2, $3, 'C', 'x')",
                            uuid.uuid4(), "other@example.com", "clash_user")
        finally:
            await c.close()
    asyncio.run(add_clash())

    u = make_user("clash")
    async def rename_here():
        c = await asyncpg.connect(**conn_args(os.environ["POSTGRES_DB"]))
        try:
            await c.execute("UPDATE users SET username = 'clash_user' WHERE username = $1", u.username)
        finally:
            await c.close()
    asyncio.run(rename_here())

    body = run_import(u).json()
    assert {"username": "clash_user", "reason": "a user with this email or username already exists"} in body["skipped_users"]


def test_bad_source_details_are_reported(make_user, source, desktop_mode):
    u = make_user("baddb")
    r = run_import(u, database="does_not_exist_db")
    assert r.status_code == 400 and "does not exist" in r.json()["detail"]
    r = run_import(u, password="wrong-password")
    assert r.status_code == 400
