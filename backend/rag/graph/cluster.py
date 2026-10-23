import asyncpg
import networkx as nx
import uuid
import logging
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

MIN_COMMUNITY_SIZE = 3  # a 2-node 'community' is just an edge; summarising it wastes an LLM call
LOUVAIN_SEED = 42  # fixed so re-running on an unchanged graph gives the same communities


def _detect(edges) -> list[frozenset]:
    G = nx.Graph()
    for e in edges:
        a, b, w = e['source_entity_id'], e['target_entity_id'], float(e['weight'] or 1.0)
        # Several predicates can link the same pair; their weights add up instead of overwriting each other.
        if G.has_edge(a, b):
            G[a][b]['weight'] += w
        else:
            G.add_edge(a, b, weight=w)
    communities = nx.community.louvain_communities(G, weight='weight', seed=LOUVAIN_SEED)
    return [frozenset(c) for c in communities if len(c) >= MIN_COMMUNITY_SIZE]


async def run_louvain_clustering(pool: asyncpg.Pool, user_id: str):
    """
    Phase 4: Community Detection (Clustering Mapper)
    Runs Louvain on the user's graph and syncs level-0 communities with the result. A community whose member
    set is unchanged keeps its row (and its summary); the rest are replaced and queued for summarisation.
    """
    logger.info(f"Starting Graph Clustering for user: {user_id}")
    uid = uuid.UUID(user_id)

    async with pool.acquire() as conn:
        edges = await conn.fetch("""
            SELECT source_entity_id, target_entity_id, weight
            FROM relationships
            WHERE user_id = $1
        """, uid)

        if not edges:
            logger.info("No edges found for user to cluster.")
            await conn.execute("DELETE FROM communities WHERE user_id = $1 AND hierarchy_level = 0", uid)
            return {"status": "no_edges"}

        detected = await run_in_threadpool(_detect, edges)
        logger.info(f"Detected {len(detected)} communities of size >= {MIN_COMMUNITY_SIZE}.")

        existing = {}
        for r in await conn.fetch("""
            SELECT c.community_id, c.summary IS NOT NULL AS summarised,
                   array_agg(m.entity_id) AS members
            FROM communities c JOIN community_members m USING (community_id)
            WHERE c.user_id = $1 AND c.hierarchy_level = 0
            GROUP BY c.community_id, c.summary""", uid):
            existing[frozenset(r['members'])] = (r['community_id'], r['summarised'])

        kept = created = 0
        async with conn.transaction():
            keep_ids = []
            for members in detected:
                prior = existing.get(members)
                if prior and prior[1]:
                    keep_ids.append(prior[0])
                    kept += 1
                    continue
                if prior:  # same members but never summarised: keep the row, it is still queued
                    keep_ids.append(prior[0])
                    continue
                community_id = uuid.uuid4()
                await conn.execute("""
                    INSERT INTO communities (community_id, user_id, hierarchy_level, title, summary, embedding)
                    VALUES ($1, $2, 0, 'Pending Summary', NULL, NULL)
                """, community_id, uid)
                await conn.executemany(
                    "INSERT INTO community_members (community_id, entity_id) VALUES ($1, $2)",
                    [(community_id, e) for e in members])
                keep_ids.append(community_id)
                created += 1

            removed = await conn.fetchval("""
                WITH gone AS (
                    DELETE FROM communities
                    WHERE user_id = $1 AND hierarchy_level = 0 AND community_id <> ALL($2::uuid[])
                    RETURNING 1)
                SELECT COUNT(*) FROM gone""", uid, keep_ids)
            await conn.execute("UPDATE communities SET is_stale = FALSE WHERE user_id = $1", uid)

        logger.info(f"Communities: {kept} kept, {created} new (queued for summary), {removed} replaced.")
        return {"status": "success", "communities_detected": len(detected), "communities_kept": kept,
                "communities_queued": created, "communities_replaced": removed}
