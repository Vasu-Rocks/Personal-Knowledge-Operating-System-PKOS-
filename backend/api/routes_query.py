from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from fastapi.concurrency import run_in_threadpool
import logging
import json
import asyncpg
from api.dependencies import get_current_user, get_db

# Phase 3 Core Integrations
from rag.vector.embedder import embed_query
from rag.query.prompt_builder import build_rag_prompt
from rag.query.generator import generate_rag_response, generate_rag_response_stream

# Phase 5 Stage 4 Vector Database Native Bridge
from rag.query.retrieval import retrieve_context
from rag.query.retriever import format_context_blocks

logger = logging.getLogger(__name__)

router = APIRouter()

class QueryRequest(BaseModel):
    query: str = Field(..., max_length=1000)

class QueryResponse(BaseModel):
    query: str
    response: str
    sources: list[dict] = [] # Phase 6 Step 0: The Front-End Architecture Transparency Hook

@router.post("/query", response_model=QueryResponse)
async def process_query(
    payload: QueryRequest, 
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """
    Phase 5 Stage 4: The Read Path API Bridge
    Orchestrates the lifecycle of a RAG query tracking live into PostgreSQL pgvector 
    bounds securely locking LLM hallucinations.
    """
    user_query = payload.query.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
        
    # Phase 4 Stage 2: True User Isolation
    active_user_id = current_user["user_id"]
    
    try:
        # Step 1: Embed the natural language question mathematically via Threadpool shield
        # We explicitly run CPU-bound transforms offline so FastAPI isn't locked down!
        query_vector_np = await run_in_threadpool(embed_query, user_query)
        
        # We securely flatten the array to structurally guarantee a 1D mapping to pgvector
        query_vector_list = query_vector_np.flatten().tolist()
        
        # Step 2: HNSW Dual-Track Extraction safely scoped by cryptographic isolation boundary
        raw_chunks, graph_data = await retrieve_context(pool, active_user_id, user_query, query_vector_list)
        
        # Performance Guardrail: If no chunks or graph nodes are relevant, skip LLM entirely
        if not raw_chunks and not graph_data.get("nodes"):
            return QueryResponse(
                query=user_query,
                response="I cannot find the answer in your documents or graph.",
                sources=[]
            )
            
        # Step 3: Fast text assembly
        # Only chunks that fit the prompt budget are cited, so sources must be the chunks actually used
        retrieved_context, raw_chunks = format_context_blocks(raw_chunks)
        
        # Step 4: Build strict instructions preventing hallucination
        rag_prompt = build_rag_prompt(user_query=user_query, retrieved_context=retrieved_context, graph_data=graph_data)
        
        # Step 5: Dispatch safely to Ollama API without freezing FastAPI Event Loop
        response_text = await run_in_threadpool(generate_rag_response, rag_prompt)
        
        return QueryResponse(
            query=user_query,
            response=response_text,
            sources=raw_chunks # Push raw Postgres metrics visually to the X-Ray Sidebar!
        )
    except Exception as e:
        logger.error(f"[ERROR] Engine Core Failed to Process Query: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal RAG Engine Execution Error.")

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
    
    # Extract stateless API keys from request headers
    llm_provider = request.headers.get("x-llm-provider", "ollama")
    ollama_model = request.headers.get("x-ollama-model", "llama3.2")
    openai_key = request.headers.get("x-openai-key")
    anthropic_key = request.headers.get("x-anthropic-key")

    settings = {
        "provider": llm_provider,
        "ollama_model": ollama_model,
        "openai_key": openai_key,
        "anthropic_key": anthropic_key
    }

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

