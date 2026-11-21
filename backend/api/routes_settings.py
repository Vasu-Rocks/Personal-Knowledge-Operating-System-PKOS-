"""Per-user AI provider settings. API keys are write-only: they are stored encrypted and never returned."""
import logging
from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dependencies import get_current_user, get_db
from core.llm import LLMError, LLMSettings, test_connection
from database.llm_settings_db import UNSET, get_settings_row, load_llm_settings, public_view, save_llm_settings

logger = logging.getLogger(__name__)
router = APIRouter()

MODEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}$"


class LLMSettingsIn(BaseModel):
    provider: Literal["ollama", "openai", "anthropic"]
    ollama_model: str | None = Field(None, pattern=MODEL_PATTERN)
    openai_model: str | None = Field(None, pattern=MODEL_PATTERN)
    anthropic_model: str | None = Field(None, pattern=MODEL_PATTERN)
    # Omitted / null = keep the saved key, "" = remove it, anything else = replace it.
    openai_key: str | None = Field(None, max_length=400)
    anthropic_key: str | None = Field(None, max_length=400)


class LLMTestIn(BaseModel):
    """Unsaved values to try; anything omitted falls back to the saved settings."""
    provider: Literal["ollama", "openai", "anthropic"] | None = None
    ollama_model: str | None = Field(None, pattern=MODEL_PATTERN)
    openai_model: str | None = Field(None, pattern=MODEL_PATTERN)
    anthropic_model: str | None = Field(None, pattern=MODEL_PATTERN)
    openai_key: str | None = Field(None, max_length=400)
    anthropic_key: str | None = Field(None, max_length=400)


def _key(value: str | None):
    return UNSET if value is None else value.strip()


@router.get("/settings/llm")
async def get_llm_settings(current_user: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db)):
    return public_view(await get_settings_row(pool, current_user["user_id"]))


@router.put("/settings/llm")
async def put_llm_settings(payload: LLMSettingsIn, current_user: dict = Depends(get_current_user),
                           pool: asyncpg.Pool = Depends(get_db)):
    row = await save_llm_settings(
        pool, current_user["user_id"], provider=payload.provider,
        ollama_model=payload.ollama_model, openai_model=payload.openai_model, anthropic_model=payload.anthropic_model,
        openai_key=_key(payload.openai_key), anthropic_key=_key(payload.anthropic_key))
    return public_view(row)


@router.post("/settings/llm/test")
async def test_llm_settings(payload: LLMTestIn, current_user: dict = Depends(get_current_user),
                            pool: asyncpg.Pool = Depends(get_db)):
    """Sends a tiny prompt with the given (or saved) settings. Always 200; `ok` says whether it worked."""
    s = await load_llm_settings(pool, current_user["user_id"]) or LLMSettings()
    for name, value in payload.model_dump(exclude_none=True).items():
        setattr(s, name, value.strip() if isinstance(value, str) else value)
    try:
        reply = await test_connection(s)
        return {"ok": True, "provider": s.provider, "model": s.model, "reply": reply}
    except LLMError as e:
        return {"ok": False, "provider": s.provider, "model": s.model, "detail": str(e)}
