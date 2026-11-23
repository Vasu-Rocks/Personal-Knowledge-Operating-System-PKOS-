"""Long-term memories: list, add, edit, delete, confirm suggestions, and the on/off settings (docs/07_MEMORY_PLAN.md B1).
A memory that does not exist and one of another user both give 404."""
import re
import uuid
from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, field_validator

from api.dependencies import get_current_user, get_db
from database import memories_db as db
from rag.vector.embedder import embed_text_batch

router = APIRouter()

NOT_FOUND = "Memory not found."
Kind = Literal["fact", "preference", "conclusion"]


def clean_text(value: str) -> str:
    """One line, no prompt fences ('===' separates prompt sections), at most 300 characters."""
    value = " ".join(re.sub(r"={3,}", " ", value).split())
    if not value:
        raise ValueError("A memory cannot be empty.")
    if len(value) > db.MAX_TEXT:
        raise ValueError(f"A memory can be at most {db.MAX_TEXT} characters.")
    return value


class MemoryIn(BaseModel):
    text: str
    kind: Kind = "fact"
    source_conversation_id: uuid.UUID | None = None
    source_message_id: uuid.UUID | None = None

    @field_validator("text")
    @classmethod
    def _clean(cls, v):
        return clean_text(v)


class MemoryEdit(BaseModel):
    text: str | None = None
    kind: Kind | None = None

    @field_validator("text")
    @classmethod
    def _clean(cls, v):
        return None if v is None else clean_text(v)


class SettingsIn(BaseModel):
    enabled: bool | None = None
    suggest: bool | None = None


async def _embed(text: str):
    return (await run_in_threadpool(embed_text_batch, [text]))[0]


async def _refuse_duplicate(pool, user_id: str, text: str, exclude: uuid.UUID | None = None):
    if await db.find_same_text(pool, user_id, text, exclude):
        raise HTTPException(status_code=409, detail="You already saved this memory.")


# ---------------------------------------------------------------- settings (before /memories/{id})

@router.get("/memories/settings")
async def get_settings(current_user: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db)):
    return await db.get_settings(pool, current_user["user_id"])


@router.put("/memories/settings")
async def put_settings(payload: SettingsIn, current_user: dict = Depends(get_current_user),
                       pool: asyncpg.Pool = Depends(get_db)):
    return await db.save_settings(pool, current_user["user_id"], enabled=payload.enabled, suggest=payload.suggest)


# ---------------------------------------------------------------- memories

@router.get("/memories")
async def list_memories(status: Literal["active", "pending"] | None = None,
                        current_user: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db)):
    return {"memories": await db.list_memories(pool, current_user["user_id"], status)}


@router.post("/memories", status_code=201)
async def add_memory(payload: MemoryIn, current_user: dict = Depends(get_current_user),
                     pool: asyncpg.Pool = Depends(get_db)):
    user_id = current_user["user_id"]
    if not await db.source_belongs_to_user(pool, user_id, payload.source_conversation_id, payload.source_message_id):
        raise HTTPException(status_code=404, detail="Chat or message not found.")
    if await db.count_memories(pool, user_id) >= db.MAX_MEMORIES:
        raise HTTPException(status_code=409, detail=f"You have {db.MAX_MEMORIES} memories, the most PKOS keeps. "
                                                    "Delete some before adding more.")
    await _refuse_duplicate(pool, user_id, payload.text)
    return await db.create_memory(pool, user_id, payload.text, payload.kind, await _embed(payload.text),
                                  source_conversation_id=payload.source_conversation_id,
                                  source_message_id=payload.source_message_id)


@router.patch("/memories/{memory_id}")
async def edit_memory(memory_id: uuid.UUID, payload: MemoryEdit, current_user: dict = Depends(get_current_user),
                      pool: asyncpg.Pool = Depends(get_db)):
    return await _change(pool, current_user["user_id"], memory_id, payload, activate=False)


@router.post("/memories/{memory_id}/confirm")
async def confirm_memory(memory_id: uuid.UUID, payload: MemoryEdit | None = None,
                         current_user: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db)):
    """Keeps a suggestion (optionally edited first): from now on it is used like any other memory."""
    existing = await db.get_memory(pool, current_user["user_id"], memory_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if existing["status"] != "pending":
        raise HTTPException(status_code=409, detail="This memory is already kept.")
    return await _change(pool, current_user["user_id"], memory_id, payload or MemoryEdit(), activate=True)


async def _change(pool, user_id: str, memory_id: uuid.UUID, payload: MemoryEdit, activate: bool) -> dict:
    if payload.text is not None:
        await _refuse_duplicate(pool, user_id, payload.text, exclude=memory_id)
    embedding = await _embed(payload.text) if payload.text is not None else None
    memory = await db.update_memory(pool, user_id, memory_id, text=payload.text, kind=payload.kind,
                                    embedding=embedding, activate=activate)
    if memory is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return memory


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: uuid.UUID, current_user: dict = Depends(get_current_user),
                        pool: asyncpg.Pool = Depends(get_db)):
    if not await db.delete_memory(pool, current_user["user_id"], memory_id):
        raise HTTPException(status_code=404, detail=NOT_FOUND)


@router.delete("/memories")
async def delete_all(confirm: bool = Query(False), current_user: dict = Depends(get_current_user),
                     pool: asyncpg.Pool = Depends(get_db)):
    """Deletes every memory of the user. Needs ?confirm=true so it cannot happen by a stray request."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Add confirm=true to delete all memories.")
    return {"deleted": await db.delete_all_memories(pool, current_user["user_id"])}
