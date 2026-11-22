import json
import logging
import uuid

import anyio
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import get_current_user, get_db
from core import config
from core.llm import LLMSettings
from database import conversations_db
from database.llm_settings_db import load_llm_settings
from rag.memory.stm import build_history
from rag.query.generator import generate_rag_response_stream
from rag.query.prompt_builder import build_rag_prompt
from rag.query.retrieval import retrieve_context
from rag.query.retriever import format_context_blocks
from rag.vector.embedder import embed_query

logger = logging.getLogger(__name__)

router = APIRouter()

NO_ANSWER = "I cannot find the answer in your documents."
ERROR_PREFIX = "System Error:"   # generate_rag_response_stream reports provider failures as a token starting with this
GRAPH_SNAPSHOT_MAX_NODES = 80    # what is kept of the graph for reopening a chat; the X-Ray panel shows far fewer


class QueryRequest(BaseModel):
    query: str = Field(..., max_length=1000)
    # The chat this question belongs to. Without it a new chat is started (clients from before saved chats keep working).
    conversation_id: uuid.UUID | None = None


def _sse(event) -> str:
    return f"data: {event if isinstance(event, str) else json.dumps(event)}\n\n"


def _graph_snapshot(graph: dict) -> dict | None:
    nodes = (graph or {}).get("nodes") or []
    if not nodes:
        return None
    kept = nodes[:GRAPH_SNAPSHOT_MAX_NODES]
    ids = {n.get("id") for n in kept}
    links = [link for link in graph.get("links") or [] if link.get("source") in ids and link.get("target") in ids]
    return {"nodes": kept, "links": links}


@router.post("/query/stream")
async def process_query_stream(
    payload: QueryRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """
    Answers one question as Server-Sent Events, in this order: conversation (the chat it was saved in), sources,
    graph, token..., saved (the ids of the stored question and answer), [DONE].
    The question and the answer are stored in the chat; an answer cut short by the client is stored as 'partial',
    a provider failure as 'error'.
    """
    user_query = payload.query.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    active_user_id = current_user["user_id"]
    history, summary = [], None
    if payload.conversation_id:
        existing = await conversations_db.get_owned_conversation(pool, active_user_id, payload.conversation_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        if config.MEMORY_ENABLED:
            # Short-term memory: the recent turns not yet folded into the running summary (docs/07_MEMORY_PLAN.md).
            summary = existing["summary"]
            recent = await conversations_db.get_messages(
                pool, active_user_id, payload.conversation_id, after_seq=existing["summary_upto_seq"],
                last=2 * config.HISTORY_MAX_TURNS + 1)
            history = build_history(recent)

    # Saved per-user settings (Settings page) win. The X-LLM-* headers are the legacy path for clients that
    # still keep provider and keys in the browser; they are used only until the user saves settings.
    settings = await load_llm_settings(pool, active_user_id)
    if settings is None:
        settings = LLMSettings.from_dict({
            "provider": request.headers.get("x-llm-provider"),
            "ollama_model": request.headers.get("x-ollama-model"),
            "openai_key": request.headers.get("x-openai-key"),
            "anthropic_key": request.headers.get("x-anthropic-key"),
        })

    try:
        query_vector_np = await run_in_threadpool(embed_query, user_query)
        query_vector_list = query_vector_np.flatten().tolist()

        raw_chunks, graph_data = await retrieve_context(pool, active_user_id, user_query, query_vector_list)

        # Do all string building and prompt parsing safely inside the try block
        # so any exceptions return a proper 500 status before response headers are sent
        retrieved_context, raw_chunks = format_context_blocks(raw_chunks)
        has_context = bool(raw_chunks or graph_data.get("nodes"))
        rag_prompt = build_rag_prompt(user_query=user_query, retrieved_context=retrieved_context, graph_data=graph_data,
                                      history=history, summary=summary) if has_context else ""

        # Stored only once the question can be answered, so a failure above leaves no half-written chat behind.
        conversation_id = payload.conversation_id
        if conversation_id is None:
            conversation_id = uuid.UUID((await conversations_db.create_conversation(pool, active_user_id))["conversation_id"])
        question = await conversations_db.append_message(pool, active_user_id, conversation_id, "user", user_query)
        conversation = await conversations_db.get_owned_conversation(pool, active_user_id, conversation_id)
        if question is None or conversation is None:  # deleted between the check above and now
            raise HTTPException(status_code=404, detail="Chat not found.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] Engine Core Failed to Process Query Stream: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal RAG Engine Execution Error.")

    async def save_answer(text: str, status: str) -> dict | None:
        # Shielded: when the client disconnects this runs while the response is being cancelled, and must still finish.
        with anyio.CancelScope(shield=True):
            try:
                return await conversations_db.append_message(
                    pool, active_user_id, conversation_id, "assistant", text, sources=raw_chunks,
                    graph=_graph_snapshot(graph_data), status=status, provider=settings.provider, model=settings.model)
            except Exception:
                logger.exception("Could not save the answer in chat %s", conversation_id)
                return None

    async def sse_event_generator():
        answer, finished = [], False
        try:
            yield _sse({"type": "conversation", "conversation_id": str(conversation_id), "title": conversation["title"]})
            # Sources first for the X-Ray sidebar, then the graph.
            yield _sse({"type": "sources", "sources": raw_chunks})
            yield _sse({"type": "graph", "data": graph_data})

            if not has_context:
                answer.append(NO_ANSWER)
                yield _sse({"type": "token", "content": NO_ANSWER})
            else:
                async for token_event_str in generate_rag_response_stream(rag_prompt, settings=settings):
                    try:
                        answer.append(json.loads(token_event_str).get("content", ""))
                    except (ValueError, AttributeError):
                        pass
                    yield _sse(token_event_str)

            text = "".join(answer)
            saved = await save_answer(text, "error" if text.startswith(ERROR_PREFIX) else "complete")
            finished = True
            yield _sse({"type": "saved", "question_id": question["message_id"],
                        "answer_id": saved["message_id"] if saved else None})
            yield _sse("[DONE]")
        except Exception:
            # A failure while answering (not a disconnect: that is GeneratorExit/cancellation, not an Exception).
            logger.exception("Answer stream failed in chat %s", conversation_id)
            if not finished:
                finished = True
                await save_answer("".join(answer), "error")
            raise
        finally:
            if not finished:
                # The client went away (or the stream broke) mid-answer: keep what was generated.
                await save_answer("".join(answer), "partial")

    return StreamingResponse(sse_event_generator(), media_type="text/event-stream")
