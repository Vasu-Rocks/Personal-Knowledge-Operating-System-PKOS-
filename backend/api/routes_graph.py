from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Request
import asyncpg
import uuid
from typing import Literal
from pydantic import BaseModel
from api.dependencies import get_current_user, get_db
from rag.graph.cluster import run_louvain_clustering
from rag.graph.analytics import decide_same_concept, list_bridges, list_same_concepts
from rag.graph.connections import entity_detail, find_connection, get_evidence, lookup_term
from rag.graph.map import MAX_NODES, DEFAULT_LIMIT, build_map
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


@router.get("/graph/evidence")
async def relationship_evidence(
    rel: str = Query(..., description="rel_id from a connection or lookup result"),
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """The passages (book, page, excerpt) a relationship was extracted from."""
    try:
        uuid.UUID(rel)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid relationship id.")
    evidence = await get_evidence(pool, current_user["user_id"], rel)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Relationship not found.")
    return evidence


@router.get("/graph/same-concepts")
async def same_concept_suggestions(
    status: Literal["suggested", "confirmed", "rejected"] = "suggested",
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """Pairs of concepts from different documents that look like the same thing under different names."""
    return {"links": await list_same_concepts(pool, current_user["user_id"], status)}


class SameConceptDecision(BaseModel):
    status: Literal["suggested", "confirmed", "rejected"]


@router.post("/graph/same-concepts/{link_id}")
async def decide_same_concept_link(
    link_id: str,
    decision: SameConceptDecision,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """Confirm or reject a suggestion (nothing is merged; a rejected pair is never suggested again)."""
    try:
        uuid.UUID(link_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid link id.")
    if not await decide_same_concept(pool, current_user["user_id"], link_id, decision.status):
        raise HTTPException(status_code=404, detail="Suggestion not found.")
    return {"link_id": link_id, "status": decision.status}


@router.get("/graph/bridges")
async def bridge_concepts(
    limit: int = Query(20, ge=1, le=100),
    category: str | None = Query(None, max_length=50),
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """Concepts shared by 2+ documents that connect the most other concepts (from precomputed entity_stats)."""
    return {"bridges": await list_bridges(pool, current_user["user_id"], limit, category.upper() if category else None)}


def _csv(value: str | None) -> list[str] | None:
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


@router.get("/graph/map")
async def knowledge_map(
    mode: Literal["backbone", "full", "communities"] = "backbone",
    books: str | None = Query(None, description="comma-separated doc_ids; default all"),
    min_support: int | None = Query(None, ge=1, le=50),
    categories: str | None = Query(None, max_length=300),
    cross_book: bool = False,
    hide_generic: bool = True,
    community: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_NODES),
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """The relations between concepts across the caller's documents, filtered to a drawable size."""
    doc_ids = _csv(books)
    for value in (doc_ids or []) + ([community] if community else []):
        try:
            uuid.UUID(value)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid document or community id.")
    return await build_map(pool, current_user["user_id"], mode=mode, doc_ids=doc_ids, min_support=min_support,
                           categories=_csv(categories), cross_book=cross_book, hide_generic=hide_generic,
                           community_id=community, limit=limit)


@router.get("/graph/entity/{entity_id}")
async def concept_detail(
    entity_id: str,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """One concept: stats, per-document passages and links, same-concept suggestions."""
    try:
        uuid.UUID(entity_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid concept id.")
    detail = await entity_detail(pool, current_user["user_id"], entity_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Concept not found.")
    return detail
