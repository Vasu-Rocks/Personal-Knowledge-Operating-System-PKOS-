"""Turn a voice recording or a photo of notes into text for the query box. Nothing is stored."""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from api.dependencies import get_current_user
from rag.ingestion.extractors import UnreadableFile
from rag.ingestion.media import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, ocr_image, transcribe

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_QUERY_AUDIO_BYTES = 25 * 1024 * 1024
MAX_QUERY_IMAGE_BYTES = 25 * 1024 * 1024
MAX_QUERY_AUDIO_SECONDS = 5 * 60


async def _read(file: UploadFile, allowed: set[str], limit: int, what: str) -> bytes:
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext not in allowed:
        raise HTTPException(status_code=415, detail=f"Unsupported {what} type '.{ext}'. Allowed: {', '.join(sorted(allowed))}")
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"The {what} is larger than {limit // (1024 * 1024)} MB.")
    return data


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    data = await _read(file, AUDIO_EXTENSIONS, MAX_QUERY_AUDIO_BYTES, "audio")
    try:
        segments, language, duration = await run_in_threadpool(transcribe, data, MAX_QUERY_AUDIO_SECONDS)
    except UnreadableFile as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"text": " ".join(text for _, _, text in segments), "language": language, "seconds": round(duration, 1)}


@router.post("/ocr")
async def read_image(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    data = await _read(file, IMAGE_EXTENSIONS, MAX_QUERY_IMAGE_BYTES, "image")
    try:
        text = await run_in_threadpool(ocr_image, data)
    except UnreadableFile as e:
        raise HTTPException(status_code=422, detail=str(e))
    # A query is one question: line breaks of the notes become spaces so it can be edited as a single sentence.
    return {"text": " ".join(text.split()), "lines": len(text.splitlines())}
