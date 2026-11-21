"""
AI readiness, Ollama model management and system status (desktop app plan D1-5, D1-6).
Ollama models are shared by everyone on this machine, so any signed-in user can download or remove them.
"""
import json
import logging
import re
import shutil
import uuid
from pathlib import Path

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import get_current_user, get_db
from core import config
from core.llm import LLMSettings, make_client
from database.llm_settings_db import load_llm_settings
from rag.vector import embedder

logger = logging.getLogger(__name__)
router = APIRouter()

MODEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$"


class PullIn(BaseModel):
    model: str = Field(..., pattern=MODEL_PATTERN)


async def _ollama_models() -> list[dict] | None:
    """Installed models, or None if Ollama is unreachable."""
    try:
        async with make_client(timeout=3.0) as client:
            resp = await client.get(f"{config.OLLAMA_BASE_URL}/api/tags")
        resp.raise_for_status()
    except Exception:
        return None
    return [
        {
            "name": m.get("name"),
            "size": m.get("size"),
            "modified_at": m.get("modified_at"),
            "parameter_size": (m.get("details") or {}).get("parameter_size"),
        }
        for m in resp.json().get("models", [])
    ]


def _installed(model: str, names: list[str]) -> bool:
    """'llama3.2' matches 'llama3.2:latest'."""
    wanted = model if ":" in model else f"{model}:latest"
    return model in names or wanted in names


@router.get("/llm/status")
async def llm_status(current_user: dict = Depends(get_current_user), pool: asyncpg.Pool = Depends(get_db)):
    """Is the user's chosen provider ready to answer? Drives the first-run wizard and the header indicator."""
    s = await load_llm_settings(pool, current_user["user_id"])
    configured = s is not None
    s = s or LLMSettings()
    models = await _ollama_models()
    names = [m["name"] for m in models or []]

    if s.provider == "ollama":
        if models is None:
            ready, message = False, "Ollama is not running."
        elif not _installed(s.model, names):
            ready, message = False, f"Model '{s.model}' is not downloaded yet. Download it or use a cloud API key."
        else:
            ready, message = True, f"Ready: {s.model} on Ollama."
    else:
        has_key = bool(s.openai_key if s.provider == "openai" else s.anthropic_key)
        ready = has_key
        message = f"Ready: {s.model} on {s.label}." if has_key else f"{s.label} API key is missing. Add it in Settings."

    return {
        "configured": configured,
        "provider": s.provider,
        "model": s.model,
        "ready": ready,
        "message": message,
        "ollama": {"reachable": models is not None, "models": names},
    }


@router.get("/ollama/models")
async def list_ollama_models(current_user: dict = Depends(get_current_user)):
    models = await _ollama_models()
    if models is None:
        raise HTTPException(status_code=503, detail="Ollama is not running.")
    return {"models": models}


@router.post("/ollama/pull")
async def pull_ollama_model(payload: PullIn, request: Request, current_user: dict = Depends(get_current_user)):
    """
    Downloads a model, streaming progress as SSE: data: {"status", "completed", "total", "percent"}.
    Ends with {"status": "success"} or {"status": "error", "error": "..."}. Closing the connection cancels it.
    """
    async def events():
        try:
            async with make_client(timeout=httpx.Timeout(30.0, read=None)) as client, client.stream(
                    "POST", f"{config.OLLAMA_BASE_URL}/api/pull", json={"model": payload.model, "stream": True}) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="ignore")
                    logger.error(f"Ollama pull {payload.model} failed: {resp.status_code} {body[:300]}")
                    yield _sse({"status": "error", "error": f"Ollama could not download '{payload.model}'."})
                    return
                async for line in resp.aiter_lines():
                    if await request.is_disconnected():
                        logger.info(f"Model download cancelled by the client: {payload.model}")
                        return
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        yield _sse({"status": "error", "error": str(data["error"])[:300]})
                        return
                    event = {"status": data.get("status", "")}
                    if data.get("total"):
                        event.update(total=data["total"], completed=data.get("completed", 0),
                                     percent=round(100 * data.get("completed", 0) / data["total"], 1))
                    yield _sse(event)
        except httpx.ConnectError:
            yield _sse({"status": "error", "error": "Ollama is not running."})
        except Exception:
            logger.exception(f"Model download failed: {payload.model}")
            yield _sse({"status": "error", "error": "Download failed. See the server log for details."})

    return StreamingResponse(events(), media_type="text/event-stream")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.delete("/ollama/models/{name:path}")
async def delete_ollama_model(name: str, current_user: dict = Depends(get_current_user)):
    if not re.fullmatch(MODEL_PATTERN, name):
        raise HTTPException(status_code=422, detail="Invalid model name.")
    try:
        async with make_client(timeout=30.0) as client:
            resp = await client.request("DELETE", f"{config.OLLAMA_BASE_URL}/api/delete", json={"model": name})
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama is not running.")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Model '{name}' is not installed.")
    if resp.status_code != 200:
        logger.error(f"Ollama delete {name} failed: {resp.status_code} {resp.text[:300]}")
        raise HTTPException(status_code=502, detail="Ollama could not remove the model.")
    return {"deleted": name}


@router.get("/system/status")
async def system_status(request: Request, current_user: dict = Depends(get_current_user),
                        pool: asyncpg.Pool = Depends(get_db)):
    """Everything the header status indicator needs in one call."""
    db_ok, jobs = False, {}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT status, COUNT(*) AS n FROM graph_jobs WHERE user_id = $1 GROUP BY status",
                uuid.UUID(current_user["user_id"]))
        jobs = {r["status"].lower(): r["n"] for r in rows}
        db_ok = True
    except Exception:
        logger.exception("System status: database query failed")

    worker = getattr(request.app.state, "graph_worker", None)
    disk_path = config.DATA_DIR or Path.cwd()
    try:
        disk_free = shutil.disk_usage(disk_path).free
    except OSError:
        disk_free = None

    return {
        "database": db_ok,
        "ollama": await _ollama_models() is not None,
        "embedder_ready": embedder.is_ready(),
        "graph_worker_running": bool(worker and worker.is_running()),
        "graph_jobs": {"pending": jobs.get("pending", 0), "processing": jobs.get("processing", 0),
                       "failed": jobs.get("failed", 0)},
        "disk_free_bytes": disk_free,
        "env": config.ENV,
    }
