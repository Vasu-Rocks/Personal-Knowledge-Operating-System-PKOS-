import asyncpg

from rag.graph.analytics import refresh_analytics
from rag.graph.cluster import run_louvain_clustering
from rag.graph.summarizer import run_community_summarizer


async def rebuild_communities(pool: asyncpg.Pool, user_id: str) -> dict:
    """
    Re-cluster the user's graph, summarise whatever communities are new, then refresh per-entity analytics and
    same-concept suggestions (which need the new community ids). Used by the worker and the API.
    """
    result = await run_louvain_clustering(pool, user_id)
    result.update(await run_community_summarizer(pool, user_id))
    # Analytics need no LLM, so they are refreshed even if summarising stopped early (LLM offline).
    result.update(await refresh_analytics(pool, user_id))
    return result
