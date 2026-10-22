import asyncpg
import uuid
import numpy as np

async def create_document_anchor_async(pool: asyncpg.Pool, doc_id: uuid.UUID, user_id: str, filename: str):
    """
    Sub-Module 2.0: Relational Anchor Layer
    Inserts root document metadata to satisfy PostgreSQL's strict ON DELETE CASCADE
    foreign key structure. Fails forcefully if the User ID is not structurally sound.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO documents (doc_id, user_id, filename) VALUES ($1, $2, $3)",
            doc_id, uuid.UUID(user_id), filename
        )

async def ingest_vector_batch_async(pool: asyncpg.Pool, doc_id: uuid.UUID, batch_payloads: list[dict], embedded_vectors: np.ndarray):
    """
    Sub-Module 2.3: Highly Optimized Vector Batch Transmission!
    Compiles text chunks, relational ID maps, and AI math into a single
    list of tuples to blast via a massive binary transaction securely over the network.
    """
    # 1. Structure the tuple parameters correctly for executemany
    records_to_insert = [
        (
            doc_id,
            chunk["metadata"]["page_number"],
            chunk["text"],
            embedding.tolist() # Math mapping array -> Python standard Array for pgvector bounds
        )
        for chunk, embedding in zip(batch_payloads, embedded_vectors)
    ]
    
    # 2. Acid Compliant Fast Execution
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO document_chunks (doc_id, page_number, text_content, embedding)
            VALUES ($1, $2, $3, $4)
            """,
            records_to_insert
        )

async def retrieve_similar_chunks_async(pool: asyncpg.Pool, user_id: str, query_embedding: list, k: int = 3, max_distance: float = 0.35) -> list[dict]:
    """
    Sub-Module 3.2: Retrieval & Context Assembly (PostgreSQL Optimized)
    Uses native pgvector async serialization to binary-pack the floating point array
    and executes HNSW nearest neighbor cosine distance search on the database.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT d.filename, dc.page_number, dc.text_content, (dc.embedding <=> $1) AS distance
            FROM document_chunks dc
            JOIN documents d ON dc.doc_id = d.doc_id
            WHERE d.user_id = $2 AND (dc.embedding <=> $1) < $3
            ORDER BY distance ASC
            LIMIT $4
            """,
            query_embedding, uuid.UUID(user_id), max_distance, k
        )
        
        return [
            {
                "filename": row["filename"],
                "page": row["page_number"],
                "text": row["text_content"],
                "distance": row["distance"]
            }
            for row in rows
        ]

async def get_user_documents_async(pool: asyncpg.Pool, user_id: str) -> list[dict]:
    """
    Sub-Module 2.4: The Roster Exporter
    Fetches all uploaded documents strictly bound to the active user's cryptographic slice
    to hydrate the React Vault sidebar.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT doc_id, filename, created_at FROM documents WHERE user_id = $1 ORDER BY created_at DESC",
            uuid.UUID(user_id)
        )
        return [{"doc_id": str(row["doc_id"]), "filename": row["filename"], "timestamp": str(row["created_at"])} for row in rows]

async def delete_document_async(pool: asyncpg.Pool, user_id: str, doc_id: str):
    """
    Sub-Module 2.5: Document Purge (Cascading Wiping)
    Removes the root document. PostgreSQL ON DELETE CASCADE will automatically
    wipe all associated vector chunks from the database instantly.
    """
    async with pool.acquire() as conn:
        # Note: We filter by BOTH user_id and doc_id to ensure a malicious user 
        # cannot delete someone else's document by guessing a UUID.
        result = await conn.execute(
            "DELETE FROM documents WHERE user_id = $1 AND doc_id = $2",
            uuid.UUID(user_id), uuid.UUID(doc_id)
        )
        # result looks like 'DELETE 1' or 'DELETE 0'
        if result == 'DELETE 0':
            raise Exception("Document not found or access denied.")

async def retrieve_relevant_graph_async(pool: asyncpg.Pool, user_id: str, query_embedding: list, num_seeds: int = 2, max_edges: int = 20, max_distance: float = 0.35) -> dict:
    """
    Sub-Module 3.3: Dual-Track Graph Retrieval (Track B)
    Finds Seed Entities via HNSW, retrieves bounded bi-directional edges, 
    and fetches complete node metadata to prevent frontend UI crashes.
    """
    async with pool.acquire() as conn:
        # Step 1: Find Seed Entities
        seed_rows = await conn.fetch(
            """
            SELECT entity_id 
            FROM entities 
            WHERE user_id = $2 AND (embedding <=> $1) < $3 
            ORDER BY embedding <=> $1 ASC 
            LIMIT $4
            """,
            query_embedding, uuid.UUID(user_id), max_distance, num_seeds
        )
        
        if not seed_rows:
            return {"nodes": [], "links": []}
            
        seed_ids = [row['entity_id'] for row in seed_rows]
        primary_seed_id = str(seed_ids[0]) if seed_ids else None
        
        # Step 2: Retrieve Bi-Directional Edges (UNION Optimization)
        edge_rows = await conn.fetch(
            """
            SELECT source_entity_id, target_entity_id, predicate, description, weight
            FROM relationships
            WHERE user_id = $1 AND source_entity_id = ANY($2)
            UNION
            SELECT source_entity_id, target_entity_id, predicate, description, weight
            FROM relationships
            WHERE user_id = $1 AND target_entity_id = ANY($2)
            ORDER BY weight DESC
            LIMIT $3
            """,
            uuid.UUID(user_id), seed_ids, max_edges
        )
        
        # Step 3: Extract all unique node IDs involved (Isolated Seed Nodes Fix)
        # Initialize with seed_ids so that even if edge_rows is empty, the LLM receives the matched entities!
        unique_node_ids = set(seed_ids)
        links = []
        
        if edge_rows:
            for row in edge_rows:
                source_id = str(row['source_entity_id'])
                target_id = str(row['target_entity_id'])
                unique_node_ids.add(row['source_entity_id'])
                unique_node_ids.add(row['target_entity_id'])
                
                links.append({
                    "source": source_id,
                    "target": target_id,
                    "predicate": row['predicate'],
                    "description": row['description'],
                    "weight": row['weight']
                })
            
        # Step 4: Fetch complete metadata for all unique nodes
        node_rows = await conn.fetch(
            """
            SELECT entity_id, name, category, description
            FROM entities
            WHERE entity_id = ANY($1)
            """,
            list(unique_node_ids)
        )
        
        nodes = []
        for row in node_rows:
            entity_id_str = str(row['entity_id'])
            node_obj = {
                "id": entity_id_str,
                "name": row['name'],
                "category": row['category'],
                "description": row['description']
            }
            if entity_id_str == primary_seed_id:
                node_obj["isPrimarySeed"] = True
            nodes.append(node_obj)
            
        return {"nodes": nodes, "links": links}
