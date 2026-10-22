import sys
import os
import asyncio
import logging

# Add backend directory to sys.path so we can import from rag and database
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.postgres_core import init_db_pool
from rag.vector.embedder import embed_text_batch

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def backfill_embeddings():
    logger.info("Initializing database pool...")
    pool = await init_db_pool()
    
    batch_size = 500
    total_processed = 0
    
    async with pool.acquire() as conn:
        while True:
            # 1. Fetch batch
            rows = await conn.fetch("""
                SELECT entity_id, name, description 
                FROM entities 
                WHERE embedding IS NULL 
                LIMIT $1
            """, batch_size)
            
            if not rows:
                logger.info(f"Backfill complete! Total entities processed: {total_processed}")
                break
                
            # 2. Extract and format
            texts_to_embed = []
            entity_ids = []
            
            for row in rows:
                name = row['name']
                desc = row['description'] if row['description'] else ""
                text_to_embed = f"Name: {name}. Description: {desc}"
                texts_to_embed.append(text_to_embed)
                entity_ids.append(row['entity_id'])
                
            # 3. Embed synchronously since this script is a standalone task
            logger.info(f"Embedding batch of {len(texts_to_embed)} entities...")
            embeddings_np = embed_text_batch(texts_to_embed)
            embeddings = embeddings_np.tolist()
            
            # 4. Prepare args for executemany
            update_args = [
                (embeddings[i], entity_ids[i]) for i in range(len(entity_ids))
            ]
            
            # 5. Update database
            await conn.executemany("""
                UPDATE entities 
                SET embedding = $1 
                WHERE entity_id = $2
            """, update_args)
            
            total_processed += len(rows)
            logger.info(f"Successfully processed {total_processed} entities so far...")

    await pool.close()

if __name__ == "__main__":
    asyncio.run(backfill_embeddings())
