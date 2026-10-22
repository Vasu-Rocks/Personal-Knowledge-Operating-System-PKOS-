import httpx
import json
import logging
import asyncpg
import uuid
from core.config import OLLAMA_GENERATE_URL, get_ollama_model
from rag.graph.reconciler import reconcile_graph_chunk

logger = logging.getLogger(__name__)

GRAPH_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category": {"type": "string"},
                    "description": {"type": "string"}
                },
                "required": ["name", "category", "description"]
            }
        },
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "predicate": {"type": "string"},
                    "mention_snippet": {"type": "string"}
                },
                "required": ["source", "target", "predicate", "mention_snippet"]
            }
        }
    },
    "required": ["entities", "relationships"]
}

async def run_offline_extraction(pool: asyncpg.Pool, doc_id: str, filename: str):
    """
    Phase 2: Offline Triplet Extraction
    """
    logger.info(f"Starting offline graph extraction for {filename} ({doc_id})")
    
    try:
        # Step 3: State Machine - Mark as PROCESSING
        async with pool.acquire() as conn:
            await conn.execute("UPDATE documents SET extraction_status = 'PROCESSING' WHERE doc_id = $1", uuid.UUID(doc_id))
            
            # Fetch chunks
            rows = await conn.fetch(
                "SELECT chunk_id, text_content FROM document_chunks WHERE doc_id = $1 ORDER BY chunk_id ASC",
                uuid.UUID(doc_id)
            )
            
        # Step 1: Async I/O inside the background task (yielding to event loop)
        async with httpx.AsyncClient(timeout=180.0) as client:
            previous_context = ""
            
            for row in rows:
                chunk_id = row['chunk_id']
                current_text = row['text_content']
                
                system_prompt = f"""You are an expert knowledge graph extractor. 
Extract entities and relationships strictly from the provided text.
The text comes from a document named: '{filename}'. Use this context to resolve pronouns (he, she, it, they) to their actual noun subjects.
Output strictly valid JSON matching the schema.
Normalize entity names (capitalize proper nouns).
Use standardized, uppercase relationship predicates (e.g., USES, DEPENDS_ON, EXPLAINS).
"""
                
                # Step 2: Sliding Window Context Separation
                user_prompt = ""
                if previous_context:
                    user_prompt += f"[PREVIOUS CONTEXT FOR PRONOUN RESOLUTION ONLY]\n{previous_context}\n\n"
                    
                user_prompt += f"[ACTIVE TEXT TO EXTRACT FROM]\n{current_text}"
                
                payload = {
                    "model": get_ollama_model(),
                    "prompt": f"{system_prompt}\n\n{user_prompt}",
                    "format": GRAPH_SCHEMA,
                    "stream": False,
                    "options": {
                        "temperature": 0.0, # Forces deterministic extraction
                        "num_ctx": 2048, # Caps VRAM usage
                        "num_predict": 1024 # Bounds runaway generations (observed >300s without a cap)
                    }
                }
                
                # Execute POST to Ollama
                response = await client.post(OLLAMA_GENERATE_URL, json=payload)
                response.raise_for_status()
                
                data = response.json()
                content = data.get("response", "")
                
                # Phase 3 Integration (The Reconciliation Layer)
                try:
                    json_data = json.loads(content)
                    await reconcile_graph_chunk(pool, doc_id, chunk_id, json_data)
                    logger.info(f"Successfully reconciled Chunk {chunk_id} to DB.")
                except json.JSONDecodeError:
                    logger.warning(f"Ollama returned invalid JSON for Chunk {chunk_id}: {content}")
                
                # Prepare sliding window for next iteration (last 150 chars)
                previous_context = current_text[-150:] if len(current_text) > 150 else current_text
                
        # State Machine - Mark as COMPLETED
        async with pool.acquire() as conn:
            await conn.execute("UPDATE documents SET extraction_status = 'COMPLETED' WHERE doc_id = $1", uuid.UUID(doc_id))
            
        logger.info(f"✅ Entity and Relationship Graph Extraction FULLY COMPLETE for document: {filename}!")
            
    except Exception as e:
        logger.error(f"Graph extraction failed for {doc_id}: {e}")
        # Step 3: State Machine - Mark as FAILED to prevent zombie jobs
        try:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE documents SET extraction_status = 'FAILED' WHERE doc_id = $1", uuid.UUID(doc_id))
        except Exception as db_err:
            logger.error(f"Failed to update extraction_status to FAILED: {db_err}")
