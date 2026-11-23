from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging
import os
from contextlib import asynccontextmanager

# Load .env FIRST — before any module that reads os.getenv() at import time (e.g. security.py)
try:
    from dotenv import load_dotenv
    load_dotenv()  # Reads backend/.env if it exists; silently skips if not found
except ImportError:
    pass  # python-dotenv not installed; rely on shell environment variables

import asyncio

from core import config
from database.postgres_core import init_db_pool
from rag.graph.worker import GraphWorker
from rag.vector import embedder

# stdout, plus logs/api.log under PKOS_DATA_DIR when running as the desktop app
config.configure_logging()
logger = logging.getLogger(__name__)

# Import Modular Pipelines
from api import routes_ingest
from api import routes_query
from api import routes_auth
from api import routes_graph
from api import routes_settings
from api import routes_llm
from api import routes_import
from api import routes_media
from api import routes_conversations
from api import routes_memories

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 5: Initialize the robust asyncpg pool on application startup
    # and map it to Uvicorn's state directly for dependency injection!
    logger.info("Initializing unified PostgreSQL connection pool...")
    pool = await init_db_pool()
    app.state.pool = pool
    # Auto-create schema (idempotent - safe to run every startup)
    from database.postgres_core import configure_unified_schema
    await configure_unified_schema(pool)
    logger.info("Database schema verified.")
    # Single background worker for graph extraction; resumes jobs interrupted by a restart.
    app.state.graph_worker = GraphWorker(pool)
    await app.state.graph_worker.start()
    # Load the embedding model (torch) in a thread so /health answers immediately; uploads/queries wait for it.
    if config.EMBED_WARMUP:
        asyncio.get_running_loop().run_in_executor(None, embedder.warm_up)
    yield
    await app.state.graph_worker.stop()
    # Safely close down connections on system tear down
    logger.info("Terminating pooled database connections securely.")
    await pool.close()

app = FastAPI(
    title="PKOS V2 API",
    description="The Local Personal Knowledge Operating System OS Core",
    version="1.0.0",
    lifespan=lifespan
)

# Phase 4.1: The Web Bridge CORS Logic
# Structurally locks down origin requests tightly to the React Sandbox ensuring absolute system security.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"],
)

# Phase 1: File Processor
app.include_router(routes_ingest.router, prefix="/api/v1")

# Phase 4 Stage 1: Query API Bridge
app.include_router(routes_query.router, prefix="/api/v1")

# Phase 4 Stage 2: Authentication Bridge
app.include_router(routes_auth.router, prefix="/api/v1", tags=["Auth"])

# Phase 4 Stage 3: Graph RAG
app.include_router(routes_graph.router, prefix="/api/v1", tags=["Graph"])

# Desktop app: per-user AI provider settings, model management, system status
app.include_router(routes_settings.router, prefix="/api/v1", tags=["Settings"])
app.include_router(routes_llm.router, prefix="/api/v1", tags=["AI"])
app.include_router(routes_import.router, prefix="/api/v1", tags=["Import"])
app.include_router(routes_media.router, prefix="/api/v1", tags=["Media"])
app.include_router(routes_conversations.router, prefix="/api/v1", tags=["Chats"])
app.include_router(routes_memories.router, prefix="/api/v1", tags=["Memories"])



@app.get("/health")
async def health(response: Response):
    """Reports database and Ollama reachability; 503 if the database is down."""
    db_ok = ollama_ok = False
    try:
        async with app.state.pool.acquire() as conn:
            db_ok = (await conn.fetchval("SELECT 1")) == 1
    except Exception:
        logger.exception("Health check: database unreachable")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            ollama_ok = (await client.get(f"{config.OLLAMA_BASE_URL}/api/tags")).status_code == 200
    except Exception:
        pass  # Ollama is optional (cloud providers), so this only degrades the status
    if not db_ok:
        response.status_code = 503
    return {"status": "ok" if db_ok else "error", "database": db_ok, "ollama": ollama_ok,
            "embedder_ready": embedder.is_ready()}



