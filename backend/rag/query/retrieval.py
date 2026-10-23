import asyncio

import asyncpg

from core import config
from rag.graph.search import retrieve_graph_context
from rag.vector.vector_db_pg import retrieve_similar_chunks_async, retrieve_relevant_graph_async

VECTOR_TOP_K = 3


async def retrieve_context(pool: asyncpg.Pool, user_id: str, query: str, query_vector: list,
                           expansion: bool | None = None, vector_k: int = VECTOR_TOP_K) -> tuple[list[dict], dict]:
    """
    Dual-track retrieval shared by /query and /query/stream.
    Track A: top-k chunks by embedding. Track B: graph seeds -> ranked edges -> extra chunks found via the graph.
    Returns (chunks, graph_data); every chunk carries via='vector'|'graph'.
    """
    expansion = config.GRAPH_LOCAL_EXPANSION if expansion is None else expansion

    if not expansion:
        chunks, graph = await asyncio.gather(
            retrieve_similar_chunks_async(pool, user_id, query_vector, k=vector_k),
            retrieve_relevant_graph_async(pool, user_id, query_vector),
        )
        for c in chunks:
            c["via"] = "vector"
        return chunks, graph

    # Both tracks run concurrently, so ask the graph for a few spare chunks and drop duplicates afterwards.
    chunks, graph = await asyncio.gather(
        retrieve_similar_chunks_async(pool, user_id, query_vector, k=vector_k),
        retrieve_graph_context(
            pool, user_id, query, query_vector,
            num_seeds=config.GRAPH_SEEDS, max_edges=config.GRAPH_MAX_EDGES,
            seed_max_distance=config.GRAPH_SEED_MAX_DISTANCE,
            extra_chunks=config.GRAPH_EXTRA_CHUNKS + vector_k,
            chunk_max_distance=config.GRAPH_CHUNK_MAX_DISTANCE),
    )
    for c in chunks:
        c["via"] = "vector"
    seen = {c["chunk_id"] for c in chunks}
    extra = [c for c in graph.pop("chunks") if c["chunk_id"] not in seen][:config.GRAPH_EXTRA_CHUNKS]
    return chunks + extra, graph
