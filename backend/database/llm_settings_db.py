"""Per-user LLM provider settings (table user_llm_settings, migration 0002). Every query is scoped by user_id."""
import uuid

import asyncpg

from core import crypto
from core.llm import LLMSettings

UNSET = object()  # "leave this key unchanged" (distinct from "" = remove the key)


async def get_settings_row(pool: asyncpg.Pool, user_id: str) -> asyncpg.Record | None:
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM user_llm_settings WHERE user_id = $1", uuid.UUID(user_id))


def _to_settings(row) -> LLMSettings:
    return LLMSettings(
        provider=row["provider"],
        ollama_model=row["ollama_model"] or "",
        openai_model=row["openai_model"] or "",
        anthropic_model=row["anthropic_model"] or "",
        openai_key=crypto.decrypt(row["openai_key_enc"]),
        anthropic_key=crypto.decrypt(row["anthropic_key_enc"]),
    )


async def load_llm_settings(pool: asyncpg.Pool, user_id: str) -> LLMSettings | None:
    """The user's saved settings with decrypted keys, or None if they never saved any."""
    row = await get_settings_row(pool, user_id)
    return _to_settings(row) if row else None


def public_view(row) -> dict:
    """What the UI may see: never the keys themselves, only whether one is set and its last 4 characters."""
    s = _to_settings(row) if row else LLMSettings()
    return {
        "provider": s.provider,
        "ollama_model": s.ollama_model or None,
        "openai_model": s.openai_model or None,
        "anthropic_model": s.anthropic_model or None,
        "effective_model": s.model,
        "openai_key_set": bool(s.openai_key),
        "openai_key_hint": row["openai_key_hint"] if row and s.openai_key else None,
        "anthropic_key_set": bool(s.anthropic_key),
        "anthropic_key_hint": row["anthropic_key_hint"] if row and s.anthropic_key else None,
        "saved": row is not None,
    }


def _key_columns(value) -> tuple:
    """(enc, hint, changed) for one key field: UNSET keeps the stored value, '' or None removes it."""
    if value is UNSET:
        return None, None, False
    if not value:
        return None, None, True
    return crypto.encrypt(value), crypto.hint(value), True


async def save_llm_settings(pool: asyncpg.Pool, user_id: str, *, provider: str, ollama_model: str | None,
                            openai_model: str | None, anthropic_model: str | None,
                            openai_key=UNSET, anthropic_key=UNSET) -> asyncpg.Record:
    o_enc, o_hint, o_changed = _key_columns(openai_key)
    a_enc, a_hint, a_changed = _key_columns(anthropic_key)
    async with pool.acquire() as conn:
        return await conn.fetchrow("""
            INSERT INTO user_llm_settings (user_id, provider, ollama_model, openai_model, anthropic_model,
                                           openai_key_enc, openai_key_hint, anthropic_key_enc, anthropic_key_hint)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (user_id) DO UPDATE SET
                provider = EXCLUDED.provider,
                ollama_model = EXCLUDED.ollama_model,
                openai_model = EXCLUDED.openai_model,
                anthropic_model = EXCLUDED.anthropic_model,
                openai_key_enc = CASE WHEN $10 THEN EXCLUDED.openai_key_enc ELSE user_llm_settings.openai_key_enc END,
                openai_key_hint = CASE WHEN $10 THEN EXCLUDED.openai_key_hint ELSE user_llm_settings.openai_key_hint END,
                anthropic_key_enc = CASE WHEN $11 THEN EXCLUDED.anthropic_key_enc ELSE user_llm_settings.anthropic_key_enc END,
                anthropic_key_hint = CASE WHEN $11 THEN EXCLUDED.anthropic_key_hint ELSE user_llm_settings.anthropic_key_hint END,
                updated_at = now()
            RETURNING *
        """, uuid.UUID(user_id), provider, ollama_model, openai_model, anthropic_model,
            o_enc, o_hint, a_enc, a_hint, o_changed, a_changed)
