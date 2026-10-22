from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
import asyncpg
import uuid
from api.dependencies import get_current_user, get_db
from rag.graph.cluster import run_louvain_clustering
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
