from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from contextlib import asynccontextmanager
from database.postgres_core import init_db_pool

# Set up global log format safely buffering to stdout seamlessly
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Import Modular Pipelines
from api import routes_ingest
from api import routes_query
from api import routes_auth

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 5: Initialize the robust asyncpg pool on application startup
    # and map it to Uvicorn's state directly for dependency injection!
    logger.info("Initializing unified PostgreSQL connection pool...")
    pool = await init_db_pool()
    app.state.pool = pool
    yield
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
    allow_origins=["http://localhost:3000"],
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



@app.get("/health")
def root():
    return {"status": "PKOS V2 Operating Natively"}



