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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                extraction_status VARCHAR(50) DEFAULT 'PENDING'
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

        # ---------------------------------------------------------
        # GRAPH RAG SCHEMA (Phase 1)
        # ---------------------------------------------------------

        # 6. Entity Store (Node Subsystem)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                entity_id UUID PRIMARY KEY,
                user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                canonical_name VARCHAR(255) NOT NULL,
                category VARCHAR(50) NOT NULL,
                description TEXT,
                embedding vector(384),
                UNIQUE(user_id, canonical_name)
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS entities_embedding_idx 
            ON entities USING hnsw (embedding vector_cosine_ops);
        """)

        # 7. Relationship Store (Edge Subsystem)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                rel_id UUID PRIMARY KEY,
                user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
                source_entity_id UUID REFERENCES entities(entity_id) ON DELETE CASCADE,
                target_entity_id UUID REFERENCES entities(entity_id) ON DELETE CASCADE,
                predicate VARCHAR(100) NOT NULL,
                description TEXT,
                weight FLOAT DEFAULT 1.0,
                UNIQUE(user_id, source_entity_id, target_entity_id, predicate)
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS rel_source_idx ON relationships(source_entity_id);")
        await conn.execute("CREATE INDEX IF NOT EXISTS rel_target_idx ON relationships(target_entity_id);")

        # 8. Grounding Junction (Provenance Subsystem)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chunk_entity_junction (
                chunk_id INTEGER REFERENCES document_chunks(chunk_id) ON DELETE CASCADE,
                entity_id UUID REFERENCES entities(entity_id) ON DELETE CASCADE,
                mention_snippet TEXT,
                PRIMARY KEY (chunk_id, entity_id)
            );
        """)

        # 9. Community Structure Store (Macro Subsystem)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS communities (
                community_id UUID PRIMARY KEY,
                user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
                hierarchy_level INTEGER NOT NULL,
                title VARCHAR(255) NOT NULL,
                summary TEXT,
                embedding vector(384),
                member_entities JSONB
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS communities_embedding_idx 
            ON communities USING hnsw (embedding vector_cosine_ops);
        """)

        # 9b. Edge Provenance (G1): which chunks support each relationship.
        # Edge weight is derived from this table, and an edge disappears with its last mention.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS relationship_mentions (
                rel_id UUID REFERENCES relationships(rel_id) ON DELETE CASCADE,
                chunk_id INTEGER REFERENCES document_chunks(chunk_id) ON DELETE CASCADE,
                snippet TEXT,
                PRIMARY KEY (rel_id, chunk_id)
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS rel_mentions_chunk_idx ON relationship_mentions(chunk_id);")
        await conn.execute("""
            CREATE OR REPLACE FUNCTION delete_orphan_relationships()
            RETURNS TRIGGER AS $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM relationship_mentions WHERE rel_id = OLD.rel_id) THEN
                    DELETE FROM relationships WHERE rel_id = OLD.rel_id;
                ELSE
                    UPDATE relationships
                    SET weight = (SELECT COUNT(*) FROM relationship_mentions WHERE rel_id = OLD.rel_id)
                    WHERE rel_id = OLD.rel_id;
                END IF;
                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql;
        """)
        await conn.execute("""
            DROP TRIGGER IF EXISTS trg_delete_orphan_relationships ON relationship_mentions;
            CREATE TRIGGER trg_delete_orphan_relationships
            AFTER DELETE ON relationship_mentions
            FOR EACH ROW
            EXECUTE FUNCTION delete_orphan_relationships();
        """)

        # 9c. Community membership with real foreign keys (replaces communities.member_entities JSONB).
        await conn.execute("ALTER TABLE communities ADD COLUMN IF NOT EXISTS is_stale BOOLEAN NOT NULL DEFAULT FALSE;")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS community_members (
                community_id UUID REFERENCES communities(community_id) ON DELETE CASCADE,
                entity_id UUID REFERENCES entities(entity_id) ON DELETE CASCADE,
                PRIMARY KEY (community_id, entity_id)
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS community_members_entity_idx ON community_members(entity_id);")
        # One-time copy of JSONB members written before this table existed (skips entities that are gone).
        await conn.execute("""
            INSERT INTO community_members (community_id, entity_id)
            SELECT c.community_id, e.entity_id
            FROM communities c
            CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(c.member_entities, '[]'::jsonb)) AS m(id)
            JOIN entities e ON e.entity_id = m.id::uuid
            WHERE NOT EXISTS (SELECT 1 FROM community_members cm WHERE cm.community_id = c.community_id)
            ON CONFLICT DO NOTHING;
        """)
        # Deleting an entity removes it from its communities; flag them so the next run reclusters.
        await conn.execute("""
            CREATE OR REPLACE FUNCTION mark_community_stale()
            RETURNS TRIGGER AS $$
            BEGIN
                UPDATE communities SET is_stale = TRUE WHERE community_id = OLD.community_id;
                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql;
        """)
        await conn.execute("""
            DROP TRIGGER IF EXISTS trg_mark_community_stale ON community_members;
            CREATE TRIGGER trg_mark_community_stale
            AFTER DELETE ON community_members
            FOR EACH ROW
            EXECUTE FUNCTION mark_community_stale();
        """)

        # 9d. Durable graph-extraction queue (G2). One row per document; a single worker claims
        # PENDING rows. Per-chunk progress is checkpointed in document_chunks.graph_extracted_at,
        # so a restarted job resumes where it stopped.
        await conn.execute("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS graph_extracted_at TIMESTAMPTZ;")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_jobs (
                doc_id UUID PRIMARY KEY REFERENCES documents(doc_id) ON DELETE CASCADE,
                user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                total_chunks INTEGER NOT NULL DEFAULT 0,
                processed_chunks INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS graph_jobs_status_idx ON graph_jobs(status, created_at);")
        # Documents uploaded before the queue existed: finished ones become COMPLETED, the rest are
        # PAUSED so that a restart never silently starts hours of LLM work. Users start them from the UI.
        await conn.execute("""
            INSERT INTO graph_jobs (doc_id, user_id, status, total_chunks, processed_chunks)
            SELECT d.doc_id, d.user_id,
                   CASE WHEN d.extraction_status = 'COMPLETED' THEN 'COMPLETED' ELSE 'PAUSED' END,
                   COUNT(dc.chunk_id),
                   CASE WHEN d.extraction_status = 'COMPLETED' THEN COUNT(dc.chunk_id) ELSE 0 END
            FROM documents d
            LEFT JOIN document_chunks dc ON dc.doc_id = d.doc_id
            WHERE d.user_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM graph_jobs j WHERE j.doc_id = d.doc_id)
            GROUP BY d.doc_id, d.user_id, d.extraction_status;
        """)
        await conn.execute("""
            UPDATE document_chunks SET graph_extracted_at = now()
            WHERE graph_extracted_at IS NULL
              AND doc_id IN (SELECT doc_id FROM graph_jobs WHERE status = 'COMPLETED');
        """)

        # 10. Orphan Cleanup Trigger
        await conn.execute("""
            CREATE OR REPLACE FUNCTION delete_orphan_entities()
            RETURNS TRIGGER AS $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM chunk_entity_junction WHERE entity_id = OLD.entity_id) THEN
                    DELETE FROM entities WHERE entity_id = OLD.entity_id;
                END IF;
                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql;
        """)
        await conn.execute("""
            DROP TRIGGER IF EXISTS trg_delete_orphan_entities ON chunk_entity_junction;
            CREATE TRIGGER trg_delete_orphan_entities
            AFTER DELETE ON chunk_entity_junction
            FOR EACH ROW
            EXECUTE FUNCTION delete_orphan_entities();
        """)

        logger.info("Successfully stamped Phase 1 Graph RAG Schema (Nodes, Edges, Communities, Junctions).")

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
