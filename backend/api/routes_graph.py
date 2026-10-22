from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
import asyncpg
from api.dependencies import get_current_user, get_db
from rag.graph.cluster import run_louvain_clustering
from rag.graph.summarizer import run_community_summarizer

router = APIRouter()

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
