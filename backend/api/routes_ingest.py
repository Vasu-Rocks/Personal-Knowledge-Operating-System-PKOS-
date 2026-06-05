from fastapi import APIRouter, File, UploadFile, HTTPException
import uuid
import asyncpg

# Phase 1 Imports
from rag.ingestion.pipeline import process_file_stream

# Phase 2 Imports natively bound to Phase 5's Async PostgeSQL logic
from rag.vector.queue_batcher import batch_generator
from rag.vector.embedder import embed_text_batch
from rag.vector.vector_db_pg import create_document_anchor_async, ingest_vector_batch_async, get_user_documents_async
from fastapi import Depends
from api.dependencies import get_current_user, get_db
from fastapi.concurrency import run_in_threadpool

router = APIRouter()

@router.get("/documents")
async def fetch_vault_documents(
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """
    Phase 6 Step 0: The Roster Pipeline
    Returns all uploaded documents specifically owned by the active user to hydrate the UI.
    """
    try:
        active_user_id = current_user["user_id"]
        docs = await get_user_documents_async(pool, active_user_id)
        return {"documents": docs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

MAX_FILE_SIZE = 50 * 1024 * 1024 
ALLOWED_EXTENSIONS = {"pdf", "txt", "py", "js", "md"}

@router.post("/upload")
async def ingest_document(
    file: UploadFile = File(...), 
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """
    Sub-Module 1.1: File Intake & Master Orchestration (Phase 1 -> Phase 2 -> Phase 5)
    """
    ext = file.filename.split(".")[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File extension '{ext}' is not supported.")
        
    doc_id = uuid.uuid4()
    
    # Phase 4 Stage 2: Dynamic Cryptographic Isolation hook
    active_user_id = current_user["user_id"]
    
    # Fast, O(1) OS-level size check without flooding RAM
    if file.size and file.size > MAX_FILE_SIZE:
         raise HTTPException(status_code=413, detail="File size exceeds 50MB limit.")
         
    try:
        # Phase 5 Stage 3: The Relational Anchor
        # Fails the entire file out proactively if constraint logic breaks!
        await create_document_anchor_async(pool, doc_id, active_user_id, file.filename)
        
        # Phase 1: Create the sequential generator Stream leveraging the SpooledTemporaryFile
        page_generator_stream = process_file_stream(
            file_stream=file.file, 
            filename=file.filename, 
            doc_id=str(doc_id) # Needs to be str here for metadata tracking legacy pipeline
        )
        
        # Phase 2 Module 2.1: Slice the continuous generator into lists of 32
        batched_loops = batch_generator(page_generator_stream, batch_size=32)
        
        total_chunks = 0
        
        # Process each batch immediately (keeping RAM flatlined)
        for batch in batched_loops:
            # Module 2.2: Math extraction mathematically locked against Threadpool limits
            texts = [chunk["text"] for chunk in batch]
            embedded_vectors = await run_in_threadpool(embed_text_batch, texts)
            
            # Phase 5 Stage 3: Direct Async Database Batch Transmission 
            await ingest_vector_batch_async(pool, doc_id, batch, embedded_vectors)
            
            total_chunks += len(batch)
            
        return {
            "message": "File indexed securely into the Vector Store.",
            "document_id": str(doc_id),
            "filename": file.filename,
            "total_chunks_processed": total_chunks
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
