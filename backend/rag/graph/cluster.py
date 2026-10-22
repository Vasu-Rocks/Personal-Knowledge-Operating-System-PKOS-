import asyncpg
import networkx as nx
import uuid
import logging
import json

logger = logging.getLogger(__name__)

async def run_louvain_clustering(pool: asyncpg.Pool, user_id: str):
    """
    Phase 4: Community Detection (Clustering Mapper)
    Fetches the user's graph, runs Louvain clustering, and checkpoints the detected
    communities into the database with a NULL summary for the background queue.
    """
    logger.info(f"Starting Graph Clustering for user: {user_id}")
    
    async with pool.acquire() as conn:
        # Step 1: Fetch edges
        edges = await conn.fetch("""
            SELECT source_entity_id, target_entity_id, weight 
            FROM relationships 
            WHERE user_id = $1
        """, uuid.UUID(user_id))
        
        if not edges:
            logger.info("No edges found for user to cluster.")
            return {"status": "no_edges"}

        # Step 2: Build In-Memory Graph
        G = nx.Graph()
        for edge in edges:
            G.add_edge(str(edge['source_entity_id']), str(edge['target_entity_id']), weight=edge['weight'])
            
        logger.info(f"Loaded in-memory graph with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges.")
        
        # Step 3: Louvain Clustering
        try:
            communities = nx.community.louvain_communities(G, weight='weight')
            logger.info(f"Detected {len(communities)} communities.")
        except Exception as e:
            logger.error(f"Failed to run Louvain clustering: {e}")
            raise

        # Step 4: Database Checkpointing
        inserted_count = 0
        async with conn.transaction():
            # Clear existing Level 0 communities for this user for a fresh clustering run.
            await conn.execute("DELETE FROM communities WHERE user_id = $1 AND hierarchy_level = 0", uuid.UUID(user_id))

            for comm in communities:
                member_entities = list(comm)
                
                # Only save communities with more than 1 node to avoid noise
                if len(member_entities) < 2:
                    continue
                    
                await conn.execute("""
                    INSERT INTO communities (community_id, user_id, hierarchy_level, title, summary, embedding, member_entities)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, 
                uuid.uuid4(), 
                uuid.UUID(user_id), 
                0, 
                "Pending Summary", 
                None, 
                None, 
                json.dumps(member_entities))
                
                inserted_count += 1

        logger.info(f"Checkpointed {inserted_count} communities into the database queue.")
        return {"status": "success", "communities_detected": len(communities), "communities_queued": inserted_count}
