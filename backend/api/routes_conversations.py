"""Saved chats: list, create, open, rename, delete (docs/07_MEMORY_PLAN.md, step 1).
A conversation that does not exist and one that belongs to another user both give 404, so ids reveal nothing."""
import uuid
from datetime import datetime

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from api.dependencies import get_current_user, get_db
from database import conversations_db as db

router = APIRouter()

NOT_FOUND = "Chat not found."


class ConversationIn(BaseModel):
    title: str | None = Field(default=None, max_length=db.MAX_TITLE_LENGTH)


class RenameIn(BaseModel):
    title: str = Field(..., max_length=db.MAX_TITLE_LENGTH)

    @field_validator("title")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("The title cannot be empty.")
        return value


@router.get("/conversations")
async def list_conversations(limit: int = Query(50, ge=1, le=200), before: datetime | None = None,
                             current_user: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db)):
    items = await db.list_conversations(pool, current_user["user_id"], limit=limit, before=before)
    # A full page means there may be more: the client asks again with before = the last updated_at.
    return {"conversations": items, "next_before": items[-1]["updated_at"] if len(items) == limit else None}


@router.post("/conversations", status_code=201)
async def create_conversation(payload: ConversationIn | None = None, current_user: dict = Depends(get_current_user),
                              pool: asyncpg.Pool = Depends(get_db)):
    title = " ".join(payload.title.split()) if payload and payload.title else None
    return await db.create_conversation(pool, current_user["user_id"], title)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, current_user: dict = Depends(get_current_user),
                           pool: asyncpg.Pool = Depends(get_db)):
    conversation = await db.get_owned_conversation(pool, current_user["user_id"], conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    messages = await db.get_messages(pool, current_user["user_id"], conversation_id)
    # The running summary is internal working memory, not part of what the chat view shows.
    conversation.pop("summary"), conversation.pop("summary_upto_seq")
    return {**conversation, "messages": messages}


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(conversation_id: uuid.UUID, payload: RenameIn,
                              current_user: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db)):
    conversation = await db.rename_conversation(pool, current_user["user_id"], conversation_id, payload.title)
    if conversation is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, current_user: dict = Depends(get_current_user),
                              pool: asyncpg.Pool = Depends(get_db)):
    if not await db.delete_conversation(pool, current_user["user_id"], conversation_id):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
