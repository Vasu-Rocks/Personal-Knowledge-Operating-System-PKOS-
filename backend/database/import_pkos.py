"""
One-time import from another PKOS database (desktop app plan D5-3), e.g. the old dev/Docker database on port 5433.

- The source is only read (a read-only, repeatable-read transaction), never changed.
- Everything is written in one transaction: an import either completes or leaves the app database untouched.
- Users are imported with their IDs. A source user whose ID, email or username already exists here is skipped with
  all of their data (so running the import twice adds nothing the second time).
- document_chunks.chunk_id is a SERIAL: chunks get fresh IDs here and every reference (chunk_entity_junction,
  relationship_mentions) is rewritten, so they can never collide with chunks already in the app.
- Vectors are copied as-is (same embedding model), as text through COPY CSV.
- Saved chats and their messages are copied (a source from before saved chats simply has none).
- Saved AI settings are not copied: their API keys are encrypted with the other installation's secret.
- Only columns present on both sides are copied, so an older source schema works too.
"""
import io
import logging
import uuid

import asyncpg

logger = logging.getLogger(__name__)

# (table, filter on the source) in foreign-key order. $1 = list of importable user IDs.
USER_DOCS = "SELECT doc_id FROM documents WHERE user_id = ANY($1::uuid[])"
USER_ENTITIES = "SELECT entity_id FROM entities WHERE user_id = ANY($1::uuid[])"
TABLES = [
    ("users", "user_id = ANY($1::uuid[])"),
    ("documents", "user_id = ANY($1::uuid[])"),
    ("document_chunks", f"doc_id IN ({USER_DOCS})"),
    ("entities", "user_id = ANY($1::uuid[])"),
    ("relationships", "user_id = ANY($1::uuid[])"),
    ("chunk_entity_junction", f"entity_id IN ({USER_ENTITIES})"),
    ("relationship_mentions", "rel_id IN (SELECT rel_id FROM relationships WHERE user_id = ANY($1::uuid[]))"),
    ("communities", "user_id = ANY($1::uuid[])"),
    ("community_members", "community_id IN (SELECT community_id FROM communities WHERE user_id = ANY($1::uuid[]))"),
    ("entity_stats", "user_id = ANY($1::uuid[])"),
    ("concept_links", "user_id = ANY($1::uuid[])"),
    ("graph_jobs", "user_id = ANY($1::uuid[])"),
    ("graph_state", "user_id = ANY($1::uuid[])"),
    # Saved chats (migration 0003). Their sources are snapshots (text included), so the chunk ids inside them are
    # labels only and need no remapping.
    ("conversations", "user_id = ANY($1::uuid[])"),
    ("messages", "conversation_id IN (SELECT conversation_id FROM conversations WHERE user_id = ANY($1::uuid[]))"),
]
CHUNK_REFERENCING = {"chunk_entity_junction", "relationship_mentions"}


class ImportSourceError(Exception):
    """A problem with the source database, worded for the user."""


async def _columns(conn, table: str) -> list[str]:
    rows = await conn.fetch("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1 ORDER BY ordinal_position
    """, table)
    return [r["column_name"] for r in rows]


async def _connect_source(host: str, port: int, user: str, password: str, database: str) -> asyncpg.Connection:
    try:
        return await asyncpg.connect(host=host, port=port, user=user, password=password, database=database, timeout=10)
    except asyncpg.InvalidPasswordError:
        raise ImportSourceError("The old database rejected the user name or password.") from None
    except asyncpg.InvalidCatalogNameError:
        raise ImportSourceError(f"Database '{database}' does not exist on {host}:{port}.") from None
    except (OSError, asyncpg.CannotConnectNowError, TimeoutError):
        raise ImportSourceError(f"Cannot connect to {host}:{port}. Is the old database running?") from None


async def import_pkos(pool: asyncpg.Pool, *, host: str, port: int, user: str, password: str, database: str,
                      dry_run: bool = False) -> dict:
    """Copies users and all their data from the source PKOS database. Returns a summary; dry_run rolls back."""
    src = await _connect_source(host, port, user, password, database)
    try:
        src_tables = {r["table_name"] for r in await src.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")}
        if not {"users", "documents", "document_chunks"} <= src_tables:
            raise ImportSourceError("That database does not look like a PKOS database (no users/documents tables).")
        src_version = await src.fetchval("SELECT max(version) FROM schema_version") if "schema_version" in src_tables else 0

        async with src.transaction(isolation="repeatable_read", readonly=True), pool.acquire() as dst:
            async with dst.transaction():
                summary = await _copy(src, dst, src_tables)
                summary["source_schema_version"] = src_version
                summary["dry_run"] = dry_run
                if dry_run:
                    raise _Rollback(summary)
        return summary
    except _Rollback as rb:
        return rb.summary
    finally:
        await src.close()


class _Rollback(Exception):
    def __init__(self, summary):
        super().__init__("dry run")
        self.summary = summary


async def _copy(src: asyncpg.Connection, dst: asyncpg.Connection, src_tables: set[str]) -> dict:
    source_users = await src.fetch("SELECT user_id, email, username FROM users ORDER BY username")
    existing = await dst.fetch("SELECT user_id, lower(email) AS email, lower(username) AS username FROM users")
    ids = {r["user_id"] for r in existing}
    emails = {r["email"] for r in existing}
    names = {r["username"] for r in existing}

    importable, skipped = [], []
    for u in source_users:
        if u["user_id"] in ids:
            skipped.append({"username": u["username"], "reason": "already imported"})
        elif u["email"].lower() in emails or u["username"].lower() in names:
            skipped.append({"username": u["username"], "reason": "a user with this email or username already exists"})
        else:
            importable.append(u["user_id"])

    counts: dict[str, int] = {}
    if importable:
        await dst.execute("CREATE TEMP TABLE import_chunk_map (old_id INTEGER PRIMARY KEY, new_id INTEGER) ON COMMIT DROP")
        for table, where in TABLES:
            if table not in src_tables:
                continue
            counts[table] = await _copy_table(src, dst, table, where, importable)

    return {
        "imported_users": [u["username"] for u in source_users if u["user_id"] in set(importable)],
        "skipped_users": skipped,
        "rows": counts,
        "note": "AI settings and API keys are not imported; set them again in Settings.",
    }


async def _copy_table(src, dst, table: str, where: str, user_ids: list[uuid.UUID]) -> int:
    dst_cols = await _columns(dst, table)
    src_cols = set(await _columns(src, table))
    cols = [c for c in dst_cols if c in src_cols]
    if not cols:
        return 0
    col_list = ", ".join(f'"{c}"' for c in cols)
    stage = f"import_{table}"

    buf = io.BytesIO()
    await src.copy_from_query(f"SELECT {col_list} FROM {table} WHERE {where}", user_ids, output=buf, format="csv")
    buf.seek(0)
    if not buf.getbuffer().nbytes:
        return 0

    await dst.execute(f"CREATE TEMP TABLE {stage} (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
    if table == "document_chunks":
        # Keep the source ID for the mapping; the real chunk_id comes from this database's sequence.
        await dst.execute(f"ALTER TABLE {stage} ALTER COLUMN chunk_id DROP DEFAULT")
    await dst.copy_to_table(stage, source=buf, columns=cols, format="csv")

    if table == "document_chunks":
        await dst.execute("""
            INSERT INTO import_chunk_map (old_id, new_id)
            SELECT chunk_id, nextval(pg_get_serial_sequence('document_chunks', 'chunk_id')) FROM import_document_chunks
        """)
        await dst.execute("""
            UPDATE import_document_chunks s SET chunk_id = m.new_id FROM import_chunk_map m WHERE s.chunk_id = m.old_id
        """)
    elif table in CHUNK_REFERENCING:
        # A reference to a chunk that was not imported must not keep its old number: here it could name another chunk.
        await dst.execute(f"DELETE FROM {stage} s WHERE NOT EXISTS (SELECT 1 FROM import_chunk_map m WHERE m.old_id = s.chunk_id)")
        await dst.execute(f"""
            UPDATE {stage} s SET chunk_id = m.new_id FROM import_chunk_map m WHERE s.chunk_id = m.old_id
        """)

    status = await dst.execute(f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM {stage} ON CONFLICT DO NOTHING")
    inserted = int(status.split()[-1])
    logger.info(f"Import: {table}: {inserted} rows")
    return inserted
