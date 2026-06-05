from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from fastapi.concurrency import run_in_threadpool
import logging
import asyncpg
from api.dependencies import get_current_user, get_db

# Phase 3 Core Integrations
from rag.vector.embedder import embed_query
from rag.query.prompt_builder import build_rag_prompt
from rag.query.generator import generate_rag_response

# Phase 5 Stage 4 Vector Database Native Bridge
from rag.vector.vector_db_pg import retrieve_similar_chunks_async
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
        
        # Step 2: HNSW Extraction safely scoped by cryptographic isolation boundary
        raw_chunks = await retrieve_similar_chunks_async(pool, active_user_id, query_vector_list)
        
        # Performance Guardrail: If no chunks are relevant or exist, skip LLM entirely
        # Saves 5+ seconds of CPU blocking!
        if not raw_chunks:
            return QueryResponse(
                query=user_query,
                response="I cannot find the answer in your documents.",
                sources=[]
            )
            
        # Step 3: Fast text assembly
        retrieved_context = format_context_blocks(raw_chunks)
        
        # Step 4: Build strict instructions preventing hallucination
        rag_prompt = build_rag_prompt(user_query=user_query, retrieved_context=retrieved_context)
        
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
