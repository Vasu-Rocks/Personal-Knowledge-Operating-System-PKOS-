import asyncpg
import uuid
import numpy as np

async def create_document_anchor_async(pool: asyncpg.Pool, doc_id: uuid.UUID, user_id: str, filename: str):
    """
    Sub-Module 2.0: Relational Anchor Layer
    Inserts root document metadata to satisfy PostgreSQL's strict ON DELETE CASCADE
    foreign key structure. Fails forcefully if the User ID is not structurally sound.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO documents (doc_id, user_id, filename) VALUES ($1, $2, $3)",
            doc_id, uuid.UUID(user_id), filename
        )

async def ingest_vector_batch_async(pool: asyncpg.Pool, doc_id: uuid.UUID, batch_payloads: list[dict], embedded_vectors: np.ndarray):
    """
    Sub-Module 2.3: Highly Optimized Vector Batch Transmission!
    Compiles text chunks, relational ID maps, and AI math into a single
    list of tuples to blast via a massive binary transaction securely over the network.
    """
    # 1. Structure the tuple parameters correctly for executemany
    records_to_insert = [
        (
            doc_id,
            chunk["metadata"]["page_number"],
            chunk["text"],
            embedding.tolist() # Math mapping array -> Python standard Array for pgvector bounds
        )
        for chunk, embedding in zip(batch_payloads, embedded_vectors)
    ]
    
    # 2. Acid Compliant Fast Execution
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO document_chunks (doc_id, page_number, text_content, embedding)
            VALUES ($1, $2, $3, $4)
            """,
            records_to_insert
        )

async def retrieve_similar_chunks_async(pool: asyncpg.Pool, user_id: str, query_embedding: list, k: int = 3, max_distance: float = 1.0) -> list[dict]:
    """
    Sub-Module 3.2: Retrieval & Context Assembly (PostgreSQL Optimized)
    Uses native pgvector async serialization to binary-pack the floating point array
    and executes HNSW nearest neighbor cosine distance search on the database.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT d.filename, dc.page_number, dc.text_content, (dc.embedding <=> $1) AS distance
            FROM document_chunks dc
            JOIN documents d ON dc.doc_id = d.doc_id
            WHERE d.user_id = $2 AND (dc.embedding <=> $1) < $3
            ORDER BY distance ASC
            LIMIT $4
            """,
            query_embedding, uuid.UUID(user_id), max_distance, k
        )
        
        return [
            {
                "filename": row["filename"],
                "page": row["page_number"],
                "text": row["text_content"],
                "distance": row["distance"]
            }
            for row in rows
        ]

async def get_user_documents_async(pool: asyncpg.Pool, user_id: str) -> list[dict]:
    """
    Sub-Module 2.4: The Roster Exporter
    Fetches all uploaded documents strictly bound to the active user's cryptographic slice
    to hydrate the React Vault sidebar.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT filename, created_at FROM documents WHERE user_id = $1 ORDER BY created_at DESC",
            uuid.UUID(user_id)
        )
        return [{"filename": row["filename"], "timestamp": str(row["created_at"])} for row in rows]
