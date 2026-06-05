import asyncio
import asyncpg
from pgvector.asyncpg import register_vector
import logging
import os

logger = logging.getLogger(__name__)

# Temporary OS Environment Mappings (will be secured later)
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
POSTGRES_DB = os.getenv("POSTGRES_DB", "pkos_v2")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5433")

DSN = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

async def init_db_pool() -> asyncpg.Pool:
    """
    Establishes the massively concurrent asynchronous database connection pool,
    guaranteeing pgvector is registered on every single worker connection.
    """
    async def init_connection(conn):
        await register_vector(conn)

    try:
        pool = await asyncpg.create_pool(
            dsn=DSN,
            min_size=1,
            max_size=10,
            init=init_connection
        )
        return pool
    except Exception as e:
        logger.error(f"Failed to establish AsyncPG Pool: {e}")
        raise

async def configure_unified_schema(pool: asyncpg.Pool):
    """
    Mathematically locks the Relational Database schema into memory,
    destroying the Split Brain architecture.
    """
    async with pool.acquire() as conn:
        # 1. Enforce pgvector Native Extension
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        
        # Pre-Flight Column Presence Check (Handles legacy DB automatic restructuring safely)
        table_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'users'
            );
        """)
        
        if table_exists:
            column_count = await conn.fetchval("""
                SELECT COUNT(*) 
                FROM information_schema.columns 
                WHERE table_schema = 'public' AND table_name = 'users' 
                  AND column_name IN ('email', 'username', 'name');
            """)
            if column_count < 3:
                logger.info("Legacy DB schema detected (missing email, username, or name columns). Dropping tables to rebuild with full identity mapping...")
                await conn.execute("DROP TABLE IF EXISTS document_chunks CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS documents CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS users CASCADE;")

        # 2. Auth Layer
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id UUID PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                username VARCHAR(255) UNIQUE NOT NULL,
                name VARCHAR(255) NOT NULL,
                hashed_password TEXT NOT NULL
            );
        """)
        
        # 3. Relational Anchor Layer
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id UUID PRIMARY KEY,
                user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
                filename VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 4. Mathematical Vector Domain
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id SERIAL PRIMARY KEY,
                doc_id UUID REFERENCES documents(doc_id) ON DELETE CASCADE,
                page_number INTEGER,
                text_content TEXT,
                embedding vector(384)
            );
        """)
        
        # 5. HNSW Retrieval Optimization (Cosine Bounds natively mapped)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS hnsw_embedding_idx 
            ON document_chunks USING hnsw (embedding vector_cosine_ops);
        """)
        logger.info("Successfully stamped Phase 5 Relational and Vector structure.")

async def verify_infrastructure():
    print("Initiating Database Build Script (Phase 5 Stage 1)...")
    try:
        # Pre-flight: Establish raw connection to create extension BEFORE the pool attempts to register it
        conn = await asyncpg.connect(DSN)
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        await conn.close()
        
        pool = await init_db_pool()
        await configure_unified_schema(pool)
        await pool.close()
        print("Build Complete. Please verify '\\d document_chunks' in the psql terminal.")
    except Exception as e:
        print(f"Build Failed: Ensure PostgreSQL is running on {POSTGRES_HOST}:{POSTGRES_PORT} with pgvector installed.")
        print(f"Error Details: {e}")

if __name__ == "__main__":
    asyncio.run(verify_infrastructure())
