import sys
import os
import asyncio
import uuid
from database.postgres_core import init_db_pool
from rag.vector.embedder import embed_query

async def test_distance():
    pool = await init_db_pool()
    
    query = "What is Artificial Intelligence?"
    embedding = embed_query(query).flatten().tolist()
    
    async with pool.acquire() as conn:
        print("Testing chunks...")
        rows = await conn.fetch("""
            SELECT text_content, (embedding <=> $1) as dist
            FROM document_chunks
            ORDER BY dist ASC
            LIMIT 3
        """, embedding)
        for row in rows:
            print(f"Dist: {row['dist']:.4f} | Text: {row['text_content'][:50]}...")
            
        print("\nTesting entities...")
        rows = await conn.fetch("""
            SELECT name, (embedding <=> $1) as dist
            FROM entities
            ORDER BY dist ASC
            LIMIT 3
        """, embedding)
        for row in rows:
            print(f"Dist: {row['dist']:.4f} | Entity: {row['name']}")

    await pool.close()

if __name__ == "__main__":
    asyncio.run(test_distance())
