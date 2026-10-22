import asyncio
import logging
import uuid

import asyncpg
import httpx

from rag.graph.extractor import extract_chunk
from rag.graph.reconciler import reconcile_graph_chunk

logger = logging.getLogger(__name__)

IDLE_POLL_SECONDS = 30
FAILURE_BACKOFF_SECONDS = 30
BATCH_SIZE = 20


class GraphWorker:
    """
    Phase 2 job runner: one asyncio task that processes graph_jobs one document at a time.
    Single-threaded on purpose (one local LLM, 4 GB VRAM). State lives in Postgres, so a restart
    resumes from document_chunks.graph_extracted_at instead of losing the job.
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self):
        # Only this worker moves jobs to PROCESSING, so any PROCESSING row at startup is a leftover.
        async with self.pool.acquire() as conn:
            reset = await conn.execute("UPDATE graph_jobs SET status = 'PENDING', updated_at = now() WHERE status = 'PROCESSING'")
            await conn.execute("""
                UPDATE documents SET extraction_status = 'PENDING'
                WHERE extraction_status = 'PROCESSING'
            """)
        logger.info(f"Graph worker starting ({reset}: interrupted jobs re-queued).")
        self._task = asyncio.create_task(self._run(), name="graph-worker")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def notify(self):
        """Wake the worker after a job was queued."""
        self._wake.set()

    async def _run(self):
        while True:
            try:
                job = await self._claim()
                if job is None:
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=IDLE_POLL_SECONDS)
                    except asyncio.TimeoutError:
                        pass
                    self._wake.clear()
                    continue
                failed = not await self._process(job)
                if failed:
                    await asyncio.sleep(FAILURE_BACKOFF_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Graph worker loop error")
                await asyncio.sleep(FAILURE_BACKOFF_SECONDS)

    async def _claim(self):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE graph_jobs SET status = 'PROCESSING', error = NULL, updated_at = now()
                WHERE doc_id = (
                    SELECT doc_id FROM graph_jobs WHERE status = 'PENDING'
                    ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                RETURNING doc_id
            """)
            if row is None:
                return None
            await conn.execute("UPDATE documents SET extraction_status = 'PROCESSING' WHERE doc_id = $1", row["doc_id"])
            filename = await conn.fetchval("SELECT filename FROM documents WHERE doc_id = $1", row["doc_id"])
            return {"doc_id": row["doc_id"], "filename": filename}

    async def _set_status(self, doc_id: uuid.UUID, status: str, error: str | None = None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE graph_jobs SET status = $2, error = $3, updated_at = now() WHERE doc_id = $1",
                doc_id, status, error)
            await conn.execute("UPDATE documents SET extraction_status = $2 WHERE doc_id = $1", doc_id, status)

    async def _still_running(self, doc_id: uuid.UUID) -> bool:
        """False when the job was paused or its document deleted."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT status = 'PROCESSING' FROM graph_jobs WHERE doc_id = $1", doc_id) is True

    async def _process(self, job: dict) -> bool:
        """Runs one job to completion. Returns False if it failed."""
        doc_id, filename = job["doc_id"], job["filename"]
        logger.info(f"Graph extraction started: {filename} ({doc_id})")
        previous_context = ""
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                while True:
                    async with self.pool.acquire() as conn:
                        rows = await conn.fetch("""
                            SELECT chunk_id, text_content FROM document_chunks
                            WHERE doc_id = $1 AND graph_extracted_at IS NULL
                            ORDER BY chunk_id LIMIT $2
                        """, doc_id, BATCH_SIZE)
                    if not rows:
                        break

                    for row in rows:
                        if not await self._still_running(doc_id):
                            logger.info(f"Graph extraction stopped (paused or deleted): {filename}")
                            return True

                        data = await extract_chunk(client, row["text_content"], filename, previous_context)
                        try:
                            if data:
                                await reconcile_graph_chunk(self.pool, str(doc_id), row["chunk_id"], data)
                        except asyncpg.ForeignKeyViolationError:
                            logger.info(f"Document deleted during extraction: {filename}")
                            return True

                        async with self.pool.acquire() as conn:
                            # Checkpoint + progress in one transaction; this is what makes resume exact.
                            async with conn.transaction():
                                await conn.execute(
                                    "UPDATE document_chunks SET graph_extracted_at = now() WHERE chunk_id = $1",
                                    row["chunk_id"])
                                await conn.execute("""
                                    UPDATE graph_jobs
                                    SET processed_chunks = (SELECT COUNT(*) FROM document_chunks
                                                            WHERE doc_id = $1 AND graph_extracted_at IS NOT NULL),
                                        updated_at = now()
                                    WHERE doc_id = $1
                                """, doc_id)
                        text = row["text_content"]
                        previous_context = text[-150:]

            if await self._still_running(doc_id):
                await self._set_status(doc_id, "COMPLETED")
                logger.info(f"Graph extraction complete: {filename}")
            return True

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"Graph extraction failed for {filename}")
            await self._set_status(doc_id, "FAILED", f"{type(e).__name__}: {e}"[:500])
            return False
