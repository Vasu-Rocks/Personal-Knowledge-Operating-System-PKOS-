from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from fastapi.concurrency import run_in_threadpool
import logging
import json
import asyncpg
from api.dependencies import get_current_user, get_db
from core.llm import LLMSettings
from database.llm_settings_db import load_llm_settings

# Phase 3 Core Integrations
from rag.vector.embedder import embed_query
from rag.query.prompt_builder import build_rag_prompt
from rag.query.generator import generate_rag_response_stream

# Phase 5 Stage 4 Vector Database Native Bridge
from rag.query.retrieval import retrieve_context
from rag.query.retriever import format_context_blocks

logger = logging.getLogger(__name__)

router = APIRouter()

class QueryRequest(BaseModel):
    query: str = Field(..., max_length=1000)

@router.post("/query/stream")
async def process_query_stream(
    payload: QueryRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """
    Phase 5 Stage 4 (SSE Streaming): Real-Time Token Conveyor
    Streams tokens as SSE events to the React frontend while delivering sources first.
    """
    user_query = payload.query.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    active_user_id = current_user["user_id"]
    
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
        rag_prompt = build_rag_prompt(user_query=user_query, retrieved_context=retrieved_context, graph_data=graph_data) if (raw_chunks or graph_data.get("nodes")) else ""

        async def sse_event_generator():
            # 1. Deliver sources event first for X-Ray sidebar hydration
            sources_event = json.dumps({"type": "sources", "sources": raw_chunks})
            yield f"data: {sources_event}\n\n"
            
            # 1.5 Deliver graph event
            graph_event = json.dumps({"type": "graph", "data": graph_data})
            yield f"data: {graph_event}\n\n"

            if not raw_chunks and not graph_data.get("nodes"):
                no_docs_msg = json.dumps({"type": "token", "content": "I cannot find the answer in your documents."})
                yield f"data: {no_docs_msg}\n\n"
                yield "data: [DONE]\n\n"
                return

            # 2. Stream tokens continuously from generator
            async for token_event_str in generate_rag_response_stream(rag_prompt, settings=settings):
                yield f"data: {token_event_str}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(sse_event_generator(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"[ERROR] Engine Core Failed to Process Query Stream: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal RAG Engine Execution Error.")

