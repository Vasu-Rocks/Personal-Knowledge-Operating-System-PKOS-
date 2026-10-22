import asyncpg
import httpx
import json
import logging
import uuid
from starlette.concurrency import run_in_threadpool
from core.config import OLLAMA_GENERATE_URL, get_ollama_model
from rag.vector.embedder import embed_text_batch

logger = logging.getLogger(__name__)

async def run_community_summarizer(pool: asyncpg.Pool, user_id: str):
    """
    Phase 4: Global Summarization (Reducer)
    Pulls pending communities from the database queue, builds their context,
    runs them through the LLM for summarization, embeds the summary, and upserts.
    Only the given user's communities are processed.
    """
    user_uuid = uuid.UUID(user_id)
    while True:
        try:
            # Step 1: Resilient Polling
            async with pool.acquire() as conn:
                community = await conn.fetchrow("""
                    SELECT community_id, user_id 
                    FROM communities 
                    WHERE summary IS NULL AND user_id = $1
                    LIMIT 1
                """, user_uuid)
                
                if not community:
                    # Queue is empty, exit the worker loop
                    break
                    
                community_id = community['community_id']
                user_id_db = community['user_id']

                member_entities = [r['entity_id'] for r in await conn.fetch(
                    "SELECT entity_id FROM community_members WHERE community_id = $1", community_id)]

                if not member_entities:
                    await conn.execute("DELETE FROM communities WHERE community_id = $1", community_id)
                    continue

                # Fetch entity details
                entities = await conn.fetch("""
                    SELECT name, description 
                    FROM entities 
                    WHERE user_id = $2 AND entity_id = ANY($1::uuid[])
                """, member_entities, user_uuid)
                
                # Fetch internal edges for this community
                edges = await conn.fetch("""
                    SELECT r.predicate, r.description, e1.name as source_name, e2.name as target_name
                    FROM relationships r
                    JOIN entities e1 ON r.source_entity_id = e1.entity_id
                    JOIN entities e2 ON r.target_entity_id = e2.entity_id
                    WHERE r.user_id = $2
                      AND r.source_entity_id = ANY($1::uuid[])
                      AND r.target_entity_id = ANY($1::uuid[])
                """, member_entities, user_uuid)

            # Step 2: Fractal Context Assembly
            context_blocks = []
            context_blocks.append("--- ENTITIES ---")
            for ent in entities:
                context_blocks.append(f"{ent['name']}: {ent['description']}")
                
            context_blocks.append("--- RELATIONSHIPS ---")
            for edge in edges:
                context_blocks.append(f"{edge['source_name']} {edge['predicate']} {edge['target_name']} ({edge['description']})")
                
            full_context = "\n".join(context_blocks)
            
            # Truncate context to prevent Context Window Blowout (~6000 chars is safe for 8k token windows)
            if len(full_context) > 6000:
                full_context = full_context[:6000] + "\n...[TRUNCATED TO PREVENT CONTEXT BLOWOUT]"

            # Step 3: Local Inference (Ollama)
            system_prompt = "You are a senior systems architect. Analyze the provided technical entities and relationships."
            user_prompt = f"""Generate a concise title and a detailed 1-2 paragraph summary describing the overarching theme, core functions, and critical dependencies of this technical community.
            
[COMMUNITY FACTS]
{full_context}

Output your response as JSON matching this schema:
{{
  "title": "A short, descriptive title",
  "summary": "The detailed 1-2 paragraph summary"
}}
"""
            
            async with httpx.AsyncClient(timeout=300.0) as client: # generous 5min timeout for complex summaries
                payload = {
                    "model": get_ollama_model(),
                    "prompt": f"{system_prompt}\n\n{user_prompt}",
                    "format": "json",
                    "stream": False,
                    "options": {
                        "temperature": 0.2
                    }
                }
                
                response = await client.post(OLLAMA_GENERATE_URL, json=payload)
                response.raise_for_status()
                data = response.json()
                content = data.get("response", "{}")
                
            try:
                result = json.loads(content)
                title = result.get("title", "Unnamed Community")
                summary = result.get("summary", "No summary generated.")
            except Exception:
                title = "Unnamed Community"
                summary = content

            # Step 4: Embedding & Upsert
            # Documents are embedded without the query prefix, matching chunk/entity embeddings.
            summary_vector_np = await run_in_threadpool(embed_text_batch, [f"{title}. {summary}"])
            summary_vector_list = summary_vector_np[0].tolist()
            
            async with pool.acquire() as conn:
                await conn.execute("""
                    UPDATE communities 
                    SET title = $1, summary = $2, embedding = $3 
                    WHERE community_id = $4 AND user_id = $5
                """, title, summary, summary_vector_list, community_id, user_id_db)
                
            logger.info(f"Successfully summarized and embedded community {community_id}: '{title}'")
            
        except Exception as e:
            logger.error(f"Summarizer loop crashed: {e}")
            break # Exit the queue processing if a hard crash happens (e.g. Ollama offline)
