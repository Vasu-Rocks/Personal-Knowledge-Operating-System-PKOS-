"""Long-term memories and their per-user settings (migration 0004). Every function is scoped by user_id."""
import uuid

import asyncpg

KINDS = ("fact", "preference", "conclusion")
MAX_TEXT = 300
MAX_MEMORIES = 500   # per user; memories are notes, not a second document store

_COLUMNS = """m.memory_id, m.text, m.kind, m.origin, m.status, m.source_conversation_id, m.source_message_id,
              c.title AS source_title, m.created_at, m.updated_at, m.last_used_at, m.use_count"""
_FROM = "memories m LEFT JOIN conversations c ON c.conversation_id = m.source_conversation_id"


def _memory(row) -> dict:
    iso = lambda value: value.isoformat() if value else None  # noqa: E731
    return {
        "memory_id": str(row["memory_id"]),
        "text": row["text"],
        "kind": row["kind"],
        "origin": row["origin"],
        "status": row["status"],
        "source_conversation_id": str(row["source_conversation_id"]) if row["source_conversation_id"] else None,
        "source_message_id": str(row["source_message_id"]) if row["source_message_id"] else None,
        "source_title": row["source_title"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "last_used_at": iso(row["last_used_at"]),
        "use_count": row["use_count"],
    }


async def _get(conn, user_id: str, memory_id: uuid.UUID) -> dict | None:
    row = await conn.fetchrow(f"SELECT {_COLUMNS} FROM {_FROM} WHERE m.memory_id = $1 AND m.user_id = $2",
                              memory_id, uuid.UUID(user_id))
    return _memory(row) if row else None


async def get_memory(pool: asyncpg.Pool, user_id: str, memory_id: uuid.UUID) -> dict | None:
    async with pool.acquire() as conn:
        return await _get(conn, user_id, memory_id)


async def list_memories(pool: asyncpg.Pool, user_id: str, status: str | None = None) -> list[dict]:
    """Newest change first; status 'active' or 'pending' filters, None lists both."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT {_COLUMNS} FROM {_FROM} WHERE m.user_id = $1 AND ($2::text IS NULL OR m.status = $2)
                ORDER BY m.updated_at DESC, m.memory_id""", uuid.UUID(user_id), status)
    return [_memory(r) for r in rows]


async def count_memories(pool: asyncpg.Pool, user_id: str, status: str | None = None) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT count(*) FROM memories WHERE user_id = $1 AND ($2::text IS NULL OR status = $2)",
                                   uuid.UUID(user_id), status)


async def closest_any(pool: asyncpg.Pool, user_id: str, vector: list, max_distance: float) -> dict | None:
    """The user's memory (kept or suggested) closest to vector, if within max_distance: a duplicate check."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT memory_id, text, (embedding <=> $2) AS distance FROM memories
               WHERE user_id = $1 AND embedding IS NOT NULL AND (embedding <=> $2) < $3
               ORDER BY distance LIMIT 1""", uuid.UUID(user_id), vector, max_distance)
    return {"memory_id": str(row["memory_id"]), "text": row["text"], "distance": float(row["distance"])} if row else None


async def find_same_text(pool: asyncpg.Pool, user_id: str, text: str,
                         exclude: uuid.UUID | None = None) -> dict | None:
    """An existing memory with the same text (case and spacing ignored)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""SELECT {_COLUMNS} FROM {_FROM} WHERE m.user_id = $1 AND lower(m.text) = lower($2)
                AND ($3::uuid IS NULL OR m.memory_id <> $3) LIMIT 1""", uuid.UUID(user_id), text, exclude)
    return _memory(row) if row else None


async def source_belongs_to_user(pool: asyncpg.Pool, user_id: str, conversation_id: uuid.UUID | None,
                                 message_id: uuid.UUID | None) -> bool:
    """A memory may point at a chat (and a message in it) only if that chat is the user's own."""
    if conversation_id is None:
        return message_id is None
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            """SELECT EXISTS (SELECT 1 FROM conversations c WHERE c.conversation_id = $1 AND c.user_id = $2
                 AND ($3::uuid IS NULL OR EXISTS (SELECT 1 FROM messages WHERE message_id = $3 AND conversation_id = $1)))""",
            conversation_id, uuid.UUID(user_id), message_id))


async def create_memory(pool: asyncpg.Pool, user_id: str, text: str, kind: str, embedding, *, origin: str = "manual",
                        status: str = "active", source_conversation_id: uuid.UUID | None = None,
                        source_message_id: uuid.UUID | None = None) -> dict:
    memory_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO memories (memory_id, user_id, text, kind, origin, status, embedding,
                                     source_conversation_id, source_message_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
            memory_id, uuid.UUID(user_id), text, kind, origin, status, embedding, source_conversation_id, source_message_id)
        return await _get(conn, user_id, memory_id)


async def update_memory(pool: asyncpg.Pool, user_id: str, memory_id: uuid.UUID, *, text: str | None = None,
                        kind: str | None = None, embedding=None, activate: bool = False) -> dict | None:
    """Changes text (with its new embedding) and/or kind; activate=True also turns a suggestion into a memory."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE memories SET text = COALESCE($3, text), kind = COALESCE($4, kind),
                   embedding = CASE WHEN $3::text IS NULL THEN embedding ELSE $5 END,
                   status = CASE WHEN $6 THEN 'active' ELSE status END, updated_at = now()
               WHERE memory_id = $1 AND user_id = $2""",
            memory_id, uuid.UUID(user_id), text, kind, embedding, activate)
        return await _get(conn, user_id, memory_id) if result.endswith(" 1") else None


async def delete_memory(pool: asyncpg.Pool, user_id: str, memory_id: uuid.UUID) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM memories WHERE memory_id = $1 AND user_id = $2", memory_id, uuid.UUID(user_id))
    return result.endswith(" 1")


async def delete_all_memories(pool: asyncpg.Pool, user_id: str) -> int:
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM memories WHERE user_id = $1", uuid.UUID(user_id))
    return int(result.split()[-1])


async def get_settings(pool: asyncpg.Pool, user_id: str) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT enabled, suggest FROM user_memory_settings WHERE user_id = $1", uuid.UUID(user_id))
    return {"enabled": row["enabled"], "suggest": row["suggest"]} if row else {"enabled": True, "suggest": True}


async def save_settings(pool: asyncpg.Pool, user_id: str, *, enabled: bool | None = None,
                        suggest: bool | None = None) -> dict:
    current = await get_settings(pool, user_id)
    enabled = current["enabled"] if enabled is None else enabled
    suggest = current["suggest"] if suggest is None else suggest
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO user_memory_settings (user_id, enabled, suggest) VALUES ($1, $2, $3)
               ON CONFLICT (user_id) DO UPDATE SET enabled = $2, suggest = $3""",
            uuid.UUID(user_id), enabled, suggest)
    return {"enabled": enabled, "suggest": suggest}


async def active_preferences(pool: asyncpg.Pool, user_id: str, limit: int) -> list[dict]:
    """The user's kept preferences, newest first: they shape every answer."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT memory_id, text, kind FROM memories WHERE user_id = $1 AND status = 'active' AND kind = 'preference'
               ORDER BY updated_at DESC LIMIT $2""", uuid.UUID(user_id), limit)
    return [{"memory_id": str(r["memory_id"]), "text": r["text"], "kind": r["kind"]} for r in rows]


async def closest_facts(pool: asyncpg.Pool, user_id: str, query_vector: list, limit: int,
                        max_distance: float) -> list[dict]:
    """Kept facts and conclusions closest to the question, within max_distance (cosine)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT memory_id, text, kind, (embedding <=> $2) AS distance FROM memories
               WHERE user_id = $1 AND status = 'active' AND kind <> 'preference' AND embedding IS NOT NULL
                 AND (embedding <=> $2) < $3
               ORDER BY distance LIMIT $4""", uuid.UUID(user_id), query_vector, max_distance, limit)
    return [{"memory_id": str(r["memory_id"]), "text": r["text"], "kind": r["kind"], "distance": float(r["distance"])}
            for r in rows]


async def mark_used(pool: asyncpg.Pool, user_id: str, memory_ids: list[str]) -> None:
    if not memory_ids:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE memories SET last_used_at = now(), use_count = use_count + 1
               WHERE user_id = $1 AND memory_id = ANY($2::uuid[])""",
            uuid.UUID(user_id), [uuid.UUID(m) for m in memory_ids])
