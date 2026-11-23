"""Saved chats: tables conversations and messages (migration 0003). Every function that takes a conversation id also
takes the user id and only touches that user's conversations; get_owned_conversation is the gate for the rest."""
import json
import uuid
from datetime import datetime

import asyncpg

DEFAULT_TITLE = "New chat"
TITLE_MAX = 60          # automatic titles; a title the user types may be up to 200 characters
MAX_TITLE_LENGTH = 200

_CONVERSATION_COLUMNS = "conversation_id, title, message_count, created_at, updated_at"


def title_from_question(question: str) -> str:
    """The first question, on one line, cut at a word boundary to TITLE_MAX characters."""
    text = " ".join(question.split())
    if len(text) <= TITLE_MAX:
        return text or DEFAULT_TITLE
    cut = text[:TITLE_MAX]
    if " " in cut[TITLE_MAX // 2:]:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip(" ,.;:-") + "..."


def _conversation(row) -> dict:
    return {
        "conversation_id": str(row["conversation_id"]),
        "title": row["title"],
        "message_count": row["message_count"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def _message(row) -> dict:
    return {
        "message_id": str(row["message_id"]),
        "seq": row["seq"],
        "role": row["role"],
        "content": row["content"],
        "standalone_query": row["standalone_query"],
        "needs_search": row["needs_search"],
        "sources": json.loads(row["sources"]) if row["sources"] is not None else None,
        "graph": json.loads(row["graph"]) if row["graph"] is not None else None,
        "status": row["status"],
        "provider": row["provider"],
        "model": row["model"],
        "memories_used": json.loads(row["memories_used"]) if row.get("memories_used") is not None else None,
        "created_at": row["created_at"].isoformat(),
    }


async def create_conversation(pool: asyncpg.Pool, user_id: str, title: str | None = None) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"INSERT INTO conversations (conversation_id, user_id, title) VALUES ($1, $2, $3) RETURNING {_CONVERSATION_COLUMNS}",
            uuid.uuid4(), uuid.UUID(user_id), (title or DEFAULT_TITLE)[:MAX_TITLE_LENGTH])
    return _conversation(row)


async def list_conversations(pool: asyncpg.Pool, user_id: str, limit: int = 50,
                             before: datetime | None = None) -> list[dict]:
    """Newest activity first. `before` pages on: pass the updated_at of the last item already shown."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT {_CONVERSATION_COLUMNS} FROM conversations
                WHERE user_id = $1 AND ($2::timestamptz IS NULL OR updated_at < $2)
                ORDER BY updated_at DESC, conversation_id LIMIT $3""",
            uuid.UUID(user_id), before, limit)
    return [_conversation(r) for r in rows]


async def get_owned_conversation(pool: asyncpg.Pool, user_id: str, conversation_id: uuid.UUID) -> dict | None:
    """The conversation with its summary fields, or None when it does not exist or belongs to someone else."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""SELECT {_CONVERSATION_COLUMNS}, summary, summary_upto_seq FROM conversations
                WHERE conversation_id = $1 AND user_id = $2""",
            conversation_id, uuid.UUID(user_id))
    if row is None:
        return None
    return {**_conversation(row), "summary": row["summary"], "summary_upto_seq": row["summary_upto_seq"]}


async def get_messages(pool: asyncpg.Pool, user_id: str, conversation_id: uuid.UUID,
                       after_seq: int = 0, last: int | None = None) -> list[dict]:
    """Messages in order. `after_seq` skips older ones; `last` keeps only the newest N (still returned in order)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT m.* FROM messages m JOIN conversations c USING (conversation_id)
               WHERE m.conversation_id = $1 AND c.user_id = $2 AND m.seq > $3
               ORDER BY m.seq DESC LIMIT $4""",
            conversation_id, uuid.UUID(user_id), after_seq, last)
    return [_message(r) for r in reversed(rows)]


async def rename_conversation(pool: asyncpg.Pool, user_id: str, conversation_id: uuid.UUID, title: str) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""UPDATE conversations SET title = $3 WHERE conversation_id = $1 AND user_id = $2
                RETURNING {_CONVERSATION_COLUMNS}""",
            conversation_id, uuid.UUID(user_id), title[:MAX_TITLE_LENGTH])
    return _conversation(row) if row else None


async def delete_conversation(pool: asyncpg.Pool, user_id: str, conversation_id: uuid.UUID) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM conversations WHERE conversation_id = $1 AND user_id = $2", conversation_id, uuid.UUID(user_id))
    return result.endswith(" 1")


async def append_message(pool: asyncpg.Pool, user_id: str, conversation_id: uuid.UUID, role: str, content: str, *,
                         standalone_query: str | None = None, needs_search: bool | None = None,
                         sources: list | None = None, graph: dict | None = None, status: str = "complete",
                         provider: str | None = None, model: str | None = None,
                         memories_used: list | None = None) -> dict | None:
    """Adds a message at the end of the conversation (None if the conversation is not the user's).
    The first user message also becomes the title while the conversation still has the default one."""
    async with pool.acquire() as conn, conn.transaction():
        # The UPDATE locks the conversation row, so two messages arriving together still get distinct seq numbers.
        conv = await conn.fetchrow(
            """UPDATE conversations SET message_count = message_count + 1, updated_at = now(),
                   title = CASE WHEN $3 = 'user' AND message_count = 0 AND title = $4 THEN $5 ELSE title END
               WHERE conversation_id = $1 AND user_id = $2 RETURNING message_count""",
            conversation_id, uuid.UUID(user_id), role, DEFAULT_TITLE, title_from_question(content))
        if conv is None:
            return None
        row = await conn.fetchrow(
            """INSERT INTO messages (message_id, conversation_id, seq, role, content, standalone_query, needs_search,
                                     sources, graph, status, provider, model, memories_used)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11, $12, $13::jsonb) RETURNING *""",
            uuid.uuid4(), conversation_id, conv["message_count"], role, content, standalone_query, needs_search,
            json.dumps(sources) if sources is not None else None, json.dumps(graph) if graph is not None else None,
            status, provider, model, json.dumps(memories_used) if memories_used is not None else None)
    return _message(row)


async def save_summary(pool: asyncpg.Pool, user_id: str, conversation_id: uuid.UUID, summary: str, *,
                       upto_seq: int, expected_upto_seq: int) -> bool:
    """Stores a new running summary, but only if the summary still covers expected_upto_seq: a concurrent update
    that got there first wins, and this one is dropped instead of overwriting it with an older view."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE conversations SET summary = $3, summary_upto_seq = $4
               WHERE conversation_id = $1 AND user_id = $2 AND summary_upto_seq = $5 AND $4 > $5""",
            conversation_id, uuid.UUID(user_id), summary, upto_seq, expected_upto_seq)
    return result.endswith(" 1")
