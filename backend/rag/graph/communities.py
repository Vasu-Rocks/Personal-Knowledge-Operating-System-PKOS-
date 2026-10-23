import asyncpg

from rag.graph.cluster import run_louvain_clustering
from rag.graph.summarizer import run_community_summarizer


async def rebuild_communities(pool: asyncpg.Pool, user_id: str) -> dict:
    """Re-cluster the user's graph, then summarise whatever communities are new. Used by the worker and the API."""
    result = await run_louvain_clustering(pool, user_id)
    result.update(await run_community_summarizer(pool, user_id))
    return result
