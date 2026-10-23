import asyncpg
import httpx
import json
import logging
import uuid
from starlette.concurrency import run_in_threadpool
from core.config import OLLAMA_CHAT_URL, get_ollama_model
from rag.vector.embedder import embed_text_batch

logger = logging.getLogger(__name__)

MAX_CONTEXT_ENTITIES = 25
MAX_CONTEXT_EDGES = 30
MAX_CONTEXT_CHARS = 3500  # with num_ctx 4096 this leaves room for the prompt and a ~400 token answer

SYSTEM_PROMPT = (
    "You summarise one cluster of a knowledge graph extracted from a person's documents. "
    "Write a short title naming the shared topic, and a 2-4 sentence summary of what the cluster is about, "
    "which concepts it groups together and how they relate. Use only the facts given. "
    'Reply as JSON: {"title": "...", "summary": "..."}.'
)


async def _build_context(conn, member_ids: list, user_uuid: uuid.UUID) -> str:
    """Most important facts first (by connections inside the cluster), so truncation drops the least useful."""
    entities = await conn.fetch("""
        SELECT e.name, e.description,
               (SELECT COUNT(*) FROM relationships r
                WHERE r.user_id = $2 AND (r.source_entity_id = e.entity_id OR r.target_entity_id = e.entity_id)
                  AND r.source_entity_id = ANY($1::uuid[]) AND r.target_entity_id = ANY($1::uuid[])) AS degree
        FROM entities e
        WHERE e.user_id = $2 AND e.entity_id = ANY($1::uuid[])
        ORDER BY degree DESC, e.name
        LIMIT $3""", member_ids, user_uuid, MAX_CONTEXT_ENTITIES)
    edges = await conn.fetch("""
        SELECT r.predicate, s.name AS source_name, t.name AS target_name
        FROM relationships r
        JOIN entities s ON s.entity_id = r.source_entity_id
        JOIN entities t ON t.entity_id = r.target_entity_id
        WHERE r.user_id = $2 AND r.source_entity_id = ANY($1::uuid[]) AND r.target_entity_id = ANY($1::uuid[])
        ORDER BY r.weight DESC
        LIMIT $3""", member_ids, user_uuid, MAX_CONTEXT_EDGES)
    sources = await conn.fetch("""
        SELECT d.filename, COUNT(*) AS n
        FROM chunk_entity_junction j
        JOIN document_chunks dc ON dc.chunk_id = j.chunk_id
        JOIN documents d ON d.doc_id = dc.doc_id
        WHERE j.entity_id = ANY($1::uuid[])
        GROUP BY d.filename ORDER BY n DESC LIMIT 3""", member_ids)

    lines = ["Documents: " + ", ".join(s["filename"] for s in sources), "--- ENTITIES ---"]
    lines += [f"{e['name']}: {e['description']}" if e["description"] else e["name"] for e in entities]
    lines.append("--- RELATIONSHIPS ---")
    lines += [f"{e['source_name']} {e['predicate']} {e['target_name']}" for e in edges]
    return "\n".join(lines)[:MAX_CONTEXT_CHARS]


async def run_community_summarizer(pool: asyncpg.Pool, user_id: str) -> dict:
    """
    Phase 4: Global Summarization (Reducer)
    Pulls the user's pending communities from the database queue, builds their context,
    runs them through the LLM for summarization, embeds the summary, and upserts.
    Returns {"summarised", "remaining"}; stops early (leaving the rest queued) if the LLM is unreachable.
    """
    user_uuid = uuid.UUID(user_id)
    done = 0
    async with httpx.AsyncClient(timeout=300.0) as client:
        while True:
            try:
                async with pool.acquire() as conn:
                    community_id = await conn.fetchval("""
                        SELECT community_id FROM communities
                        WHERE summary IS NULL AND user_id = $1 LIMIT 1
                    """, user_uuid)
                    if community_id is None:
                        break

                    member_ids = [r['entity_id'] for r in await conn.fetch(
                        "SELECT entity_id FROM community_members WHERE community_id = $1", community_id)]
                    if not member_ids:
                        await conn.execute("DELETE FROM communities WHERE community_id = $1", community_id)
                        continue
                    context = await _build_context(conn, member_ids, user_uuid)

                response = await client.post(OLLAMA_CHAT_URL, json={
                    "model": get_ollama_model(),
                    "stream": False,
                    "format": "json",
                    "keep_alive": "15m",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": context},
                    ],
                    "options": {"temperature": 0.2, "num_ctx": 4096, "num_predict": 400},
                })
                response.raise_for_status()
                content = response.json().get("message", {}).get("content", "{}")

                try:
                    result = json.loads(content)
                    title = str(result.get("title") or "Unnamed Community").strip()
                    summary = str(result.get("summary") or "").strip() or "No summary generated."
                except Exception:
                    title, summary = "Unnamed Community", content.strip() or "No summary generated."
                title = title[:255]

                # Documents are embedded without the query prefix, matching chunk/entity embeddings.
                vector = (await run_in_threadpool(embed_text_batch, [f"{title}. {summary}"]))[0].tolist()
                async with pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE communities SET title = $1, summary = $2, embedding = $3
                        WHERE community_id = $4 AND user_id = $5
                    """, title, summary, vector, community_id, user_uuid)
                done += 1
                logger.info(f"Summarised community {community_id}: '{title}'")

            except Exception:
                logger.exception("Community summarizer stopped (LLM offline?); remaining communities stay queued")
                break

    async with pool.acquire() as conn:
        remaining = await conn.fetchval(
            "SELECT COUNT(*) FROM communities WHERE summary IS NULL AND user_id = $1", user_uuid)
    return {"summarised": done, "remaining": remaining}
