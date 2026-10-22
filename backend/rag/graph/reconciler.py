import asyncpg
import uuid
import logging
from typing import Dict, Any
from starlette.concurrency import run_in_threadpool
from rag.vector.embedder import embed_text_batch

logger = logging.getLogger(__name__)

MAX_ENTITY_NAME_LEN = 100


def canonicalize(name) -> str:
    """Lower-cased, whitespace-collapsed key used to merge entities. Empty string means 'unusable'."""
    if not isinstance(name, str):
        return ""
    key = " ".join(name.lower().split())
    # Drops pure-symbol noise such as '++' or '-' that small models emit for code and layout fragments.
    # Single letters stay: 'C' and 'R' are real entities.
    if len(key) > MAX_ENTITY_NAME_LEN or not any(c.isalnum() for c in key):
        return ""
    return key

async def reconcile_graph_chunk(pool: asyncpg.Pool, doc_id: str, chunk_id: int, json_data: Dict[str, Any]):
    """
    Phase 3: The Reconciliation Layer
    Takes volatile JSON from Phase 2 and safely upserts it into the permanent PostgreSQL graph schema.
    """
    if not json_data.get("entities") and not json_data.get("relationships"):
        return # Nothing to reconcile

    async with pool.acquire() as conn:
        # Step 1: Atomic Transaction & User Resolution
        async with conn.transaction():
            # Get the user_id for this document
            user_id = await conn.fetchval(
                "SELECT user_id FROM documents WHERE doc_id = $1",
                uuid.UUID(doc_id)
            )
            
            if not user_id:
                logger.warning(f"Could not find user_id for doc_id {doc_id}. Aborting reconciliation for chunk {chunk_id}.")
                return

            # Step 2: Entity UPSERT & Translation Dictionary
            translation_dict = {}

            # Collect listed entities first, then add relationship endpoints the model forgot to list
            # (small models often name an entity only inside a relationship).
            pending: dict[str, dict] = {}
            for entity in json_data.get("entities", []):
                key = canonicalize(entity.get("name"))
                if key and key not in pending:
                    pending[key] = {
                        "name": " ".join(entity["name"].split()),
                        "category": (entity.get("category") or "OTHER").upper(),
                        "description": entity.get("description") or "",
                    }
            for rel in json_data.get("relationships", []):
                for endpoint in (rel.get("source"), rel.get("target")):
                    key = canonicalize(endpoint)
                    if key and key not in pending:
                        pending[key] = {"name": " ".join(endpoint.split()), "category": "OTHER", "description": ""}

            keys = list(pending)
            if keys:
                texts_to_embed = [f"Name: {pending[k]['name']}. Description: {pending[k]['description']}" for k in keys]
                embeddings = (await run_in_threadpool(embed_text_batch, texts_to_embed)).tolist()
            else:
                embeddings = []

            for key, embedding_vector in zip(keys, embeddings):
                ent = pending[key]
                # The Dummy Update to force RETURNING, ignores new embeddings/descriptions on conflict
                entity_uuid = await conn.fetchval("""
                    INSERT INTO entities (entity_id, user_id, name, canonical_name, category, description, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (user_id, canonical_name) 
                    DO UPDATE SET canonical_name = EXCLUDED.canonical_name
                    RETURNING entity_id;
                """, uuid.uuid4(), user_id, ent["name"], key, ent["category"], ent["description"], embedding_vector)

                translation_dict[key] = entity_uuid

            # Step 3: Provenance Anchoring (Junction Linking)
            for canonical_name, entity_uuid in translation_dict.items():
                await conn.execute("""
                    INSERT INTO chunk_entity_junction (chunk_id, entity_id) 
                    VALUES ($1, $2) 
                    ON CONFLICT DO NOTHING;
                """, chunk_id, entity_uuid)

            # Step 4: Edge Construction (Relationship UPSERTs)
            for rel in json_data.get("relationships", []):
                source_name = rel.get("source")
                target_name = rel.get("target")
                
                if not source_name or not target_name:
                    continue
                    
                source_canonical = canonicalize(source_name)
                target_canonical = canonicalize(target_name)
                
                source_uuid = translation_dict.get(source_canonical)
                target_uuid = translation_dict.get(target_canonical)
                
                # Discard if we couldn't resolve the UUIDs
                if not source_uuid or not target_uuid:
                    continue
                    
                # Self-Loop Protection
                if source_uuid == target_uuid:
                    logger.debug(f"Discarding self-loop relationship on {source_canonical}")
                    continue
                    
                predicate = (rel.get("predicate") or "RELATED_TO").upper().strip().replace(" ", "_")[:100]
                description = rel.get("mention_snippet", "")
                
                # The Weight Increment UPSERT
                await conn.execute("""
                    INSERT INTO relationships (rel_id, user_id, source_entity_id, target_entity_id, predicate, description)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (user_id, source_entity_id, target_entity_id, predicate) 
                    DO UPDATE SET weight = relationships.weight + 1.0;
                """, uuid.uuid4(), user_id, source_uuid, target_uuid, predicate, description)

