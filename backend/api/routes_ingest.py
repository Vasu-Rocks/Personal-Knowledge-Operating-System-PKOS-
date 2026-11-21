import uuid
import logging
from fastapi import APIRouter, File, UploadFile, HTTPException, Request, BackgroundTasks, Depends
import asyncpg

from rag.ingestion.pipeline import process_file_stream
from rag.vector.queue_batcher import batch_generator
from rag.vector.embedder import embed_text_batch
from rag.vector.vector_db_pg import (
    create_document_anchor_async, ingest_vector_batch_async,
    get_user_documents_async, delete_document_async, create_graph_job_async
)
from api.dependencies import get_current_user, get_db
from fastapi.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_FILE_SIZE = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {"pdf", "txt", "py", "js", "md"}


async def _run_indexing(pool: asyncpg.Pool, doc_id: uuid.UUID, user_id: str,
                        file_bytes: bytes, filename: str, build_graph: bool, app_state):
    """Background task: embed chunks, store vectors, queue graph extraction."""
    import io
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE documents SET index_status = 'INDEXING' WHERE doc_id = $1", doc_id
            )
        file_stream = io.BytesIO(file_bytes)
        page_generator_stream = process_file_stream(
            file_stream=file_stream, filename=filename, doc_id=str(doc_id)
        )
        batched_loops = batch_generator(page_generator_stream, batch_size=32)
        total_chunks = 0
        for batch in batched_loops:
            texts = [chunk["text"] for chunk in batch]
            embedded_vectors = await run_in_threadpool(embed_text_batch, texts)
            await ingest_vector_batch_async(pool, doc_id, batch, embedded_vectors)
            total_chunks += len(batch)

        if total_chunks == 0:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE documents SET index_status = 'FAILED', index_error = 'No extractable text found.' WHERE doc_id = $1",
                    doc_id
                )
            return

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE documents SET index_status = 'READY', chunk_count = $2 WHERE doc_id = $1",
                doc_id, total_chunks
            )
        await create_graph_job_async(pool, doc_id, user_id, total_chunks, start=build_graph)
        if build_graph and hasattr(app_state, 'graph_worker'):
            app_state.graph_worker.notify()
        logger.info("Indexing complete for doc %s: %d chunks", doc_id, total_chunks)

    except Exception:
        logger.exception("Background indexing failed for doc %s", doc_id)
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE documents SET index_status = 'FAILED', index_error = 'Indexing failed. Please retry.' WHERE doc_id = $1",
                    doc_id
                )
        except Exception:
            pass


@router.get("/documents")
async def fetch_vault_documents(
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    try:
        active_user_id = current_user["user_id"]
        docs = await get_user_documents_async(pool, active_user_id)
        return {"documents": docs}
    except Exception:
        logger.exception("Failed to fetch documents for user %s", current_user.get("user_id"))
        raise HTTPException(status_code=500, detail="Failed to load documents.")


@router.post("/upload", status_code=202)
async def ingest_document(
    request: Request,
    background_tasks: BackgroundTasks,
    build_graph: bool = True,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    if not file.filename or "." not in file.filename:
        raise HTTPException(status_code=400, detail="File must have an extension.")

    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '.{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    active_user_id = current_user["user_id"]

    # Size check
    file.file.seek(0, 2)
    actual_size = file.file.tell()
    file.file.seek(0)
    if actual_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds the 50 MB limit.")

    file_bytes = await file.read()
    doc_id = uuid.uuid4()

    try:
        await create_document_anchor_async(pool, doc_id, active_user_id, file.filename)
    except Exception:
        logger.exception("Failed to create document anchor for user %s", active_user_id)
        raise HTTPException(status_code=500, detail="Failed to register document. Please try again.")

    background_tasks.add_task(
        _run_indexing, pool, doc_id, active_user_id, file_bytes, file.filename, build_graph, request.app.state
    )

    return {
        "message": "File received. Indexing is running in the background.",
        "document_id": str(doc_id),
        "filename": file.filename,
    }


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    active_user_id = current_user["user_id"]
    try:
        deleted = await delete_document_async(pool, active_user_id, str(doc_id))
    except Exception:
        logger.exception("Delete failed for doc %s user %s", doc_id, active_user_id)
        raise HTTPException(status_code=500, detail="Failed to delete document.")
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found or access denied.")
    return {"message": "Document and all associated data deleted successfully."}
