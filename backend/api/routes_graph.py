from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Request
import asyncpg
import uuid
from api.dependencies import get_current_user, get_db
from rag.graph.cluster import run_louvain_clustering
from rag.graph.connections import find_connection, lookup_term
from rag.graph.summarizer import run_community_summarizer

router = APIRouter()

@router.post("/graph/jobs/{doc_id}/start")
async def start_graph_job(
    doc_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """Queues (or resumes, from its last checkpoint) graph extraction for one of the caller's documents."""
    async with pool.acquire() as conn:
        status = await conn.fetchval("""
            UPDATE graph_jobs SET status = 'PENDING', error = NULL, updated_at = now()
            WHERE doc_id = $1 AND user_id = $2 AND status IN ('PAUSED', 'FAILED')
            RETURNING status
        """, uuid.UUID(doc_id), uuid.UUID(current_user["user_id"]))
        if status is None:
            raise HTTPException(status_code=409, detail="Job not found or not startable.")
        await conn.execute("UPDATE documents SET extraction_status = 'PENDING' WHERE doc_id = $1", uuid.UUID(doc_id))
    request.app.state.graph_worker.notify()
    return {"status": "PENDING"}

@router.post("/graph/jobs/{doc_id}/pause")
async def pause_graph_job(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """Pauses a queued or running job; a running one stops after its current chunk."""
    async with pool.acquire() as conn:
        status = await conn.fetchval("""
            UPDATE graph_jobs SET status = 'PAUSED', updated_at = now()
            WHERE doc_id = $1 AND user_id = $2 AND status IN ('PENDING', 'PROCESSING')
            RETURNING status
        """, uuid.UUID(doc_id), uuid.UUID(current_user["user_id"]))
        if status is None:
            raise HTTPException(status_code=409, detail="Job not found or not pausable.")
        await conn.execute("UPDATE documents SET extraction_status = 'PAUSED' WHERE doc_id = $1", uuid.UUID(doc_id))
    return {"status": "PAUSED"}

@router.post("/graph/cluster")
async def trigger_graph_clustering(
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """
    Phase 4: Manual Trigger for Louvain Clustering
    Groups all entities for the user into communities and queues them for summarization.
    """
    try:
        active_user_id = current_user["user_id"]
        result = await run_louvain_clustering(pool, active_user_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/graph/summarize")
async def trigger_graph_summarization(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """
    Phase 4: Manual Trigger for Summarization Queue
    Spawns a background task to process the queued communities.
    """
    try:
        # We start it in the background so the endpoint returns immediately
        background_tasks.add_task(run_community_summarizer, pool=pool, user_id=current_user["user_id"])
        return {"message": "Community summarization worker started in the background."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/graph/rebuild")
async def rebuild_knowledge_map(
    request: Request,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """G5: flags the caller's graph as changed; the graph worker re-clusters and re-summarises once none of
    their extraction jobs are running. Unchanged communities keep their summaries."""
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO graph_state (user_id, dirty, updated_at) VALUES ($1, TRUE, now())
            ON CONFLICT (user_id) DO UPDATE SET dirty = TRUE, updated_at = now()
        """, uuid.UUID(current_user["user_id"]))
    request.app.state.graph_worker.notify()
    return {"status": "queued"}

@router.get("/graph/status")
async def graph_status(
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """Counts for the Settings panel: how big the graph is and whether its communities are up to date."""
    uid = uuid.UUID(current_user["user_id"])
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
              (SELECT COUNT(*) FROM entities WHERE user_id = $1) AS entities,
              (SELECT COUNT(*) FROM relationships WHERE user_id = $1) AS relationships,
              (SELECT COUNT(*) FROM communities WHERE user_id = $1) AS communities,
              (SELECT COUNT(*) FROM communities WHERE user_id = $1 AND summary IS NULL) AS pending_summaries,
              (SELECT COUNT(*) FROM communities WHERE user_id = $1 AND is_stale) AS stale_communities,
              COALESCE((SELECT dirty FROM graph_state WHERE user_id = $1), FALSE) AS rebuild_queued,
              (SELECT COUNT(*) FROM graph_jobs WHERE user_id = $1 AND status IN ('PENDING', 'PROCESSING')) AS active_jobs
        """, uid)
    return dict(row)


@router.get("/graph/lookup")
async def lookup_word(
    term: str = Query(..., min_length=1, max_length=100),
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """Where a word appears across the caller's documents (per book: pages, linked concepts, passages)."""
    term = term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="Term cannot be empty.")
    return await lookup_term(pool, current_user["user_id"], term)


@router.get("/graph/connection")
async def connect_words(
    a: str = Query(..., min_length=1, max_length=100),
    b: str = Query(..., min_length=1, max_length=100),
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """The shortest chains of relationships linking two words, and the books that support each link."""
    a, b = a.strip(), b.strip()
    if not a or not b:
        raise HTTPException(status_code=400, detail="Both words are required.")
    return await find_connection(pool, current_user["user_id"], a, b)
