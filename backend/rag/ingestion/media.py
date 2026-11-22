"""
Audio and image notes -> text, entirely on this machine.

Speech: faster-whisper (MIT) running the Whisper "base" model on the CPU. Images: RapidOCR (Apache-2.0), PP-OCR models on
onnxruntime. Both load lazily on first use, so the app starts as fast as before and users who never use them pay nothing.
Neither contacts the network when PKOS_WHISPER_MODEL points at a bundled model (the desktop app does that).
"""
import io
import logging
import os
import threading

from .extractors import UnreadableFile

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "ogg", "oga", "opus", "flac", "webm", "aac", "mp4"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}

MAX_IMAGE_PIXELS = 80_000_000   # refuse decompression bombs; phone photos are 12-50 MP
OCR_MAX_SIDE = 2600             # larger photos are shrunk first: no accuracy gain, much slower
MIN_OCR_CONFIDENCE = 0.35
TRANSCRIPT_WINDOW_SECONDS = 60  # transcripts are grouped into one "page" per minute so sources can point at a time


class MediaReadError(UnreadableFile):
    """The audio or image cannot be turned into text; the message is safe to show to the user."""


_ocr = None
_whisper = None
_ocr_lock = threading.Lock()
_whisper_lock = threading.Lock()


def _get_ocr():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def _get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        model = os.environ.get("PKOS_WHISPER_MODEL") or os.environ.get("PKOS_WHISPER_SIZE", "base")
        try:
            _whisper = WhisperModel(
                model, device="cpu", compute_type="int8", cpu_threads=min(8, os.cpu_count() or 4),
                download_root=os.environ.get("PKOS_WHISPER_CACHE_DIR") or None,
            )
        except Exception as e:
            logger.exception("Cannot load the speech model %r", model)
            raise MediaReadError(
                "The speech-to-text model is not available. Reinstall PKOS, or connect to the internet once so it "
                "can be downloaded.") from e
    return _whisper


def _group_lines(items: list[tuple[float, float, float, str]]) -> str:
    """items: (x_left, y_center, height, text). Boxes on the same visual line are joined left to right."""
    if not items:
        return ""
    heights = sorted(h for _, _, h, _ in items)
    tolerance = max(4.0, 0.6 * heights[len(heights) // 2])
    lines: list[list[tuple[float, float, float, str]]] = []
    for item in sorted(items, key=lambda i: i[1]):
        if lines and abs(item[1] - sum(i[1] for i in lines[-1]) / len(lines[-1])) <= tolerance:
            lines[-1].append(item)
        else:
            lines.append([item])
    return "\n".join(" ".join(i[3] for i in sorted(line, key=lambda i: i[0])) for line in lines)


def ocr_image(data: bytes) -> str:
    """Text found in an image (photo or scan of notes), one visual line per output line. May be empty."""
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
        import numpy as np
        try:
            image = Image.open(io.BytesIO(data))
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise MediaReadError("This image is too large. Use a photo under about 80 megapixels.")
            image = ImageOps.exif_transpose(image).convert("RGB")  # phone photos carry their rotation in EXIF
        except (UnidentifiedImageError, OSError, ValueError) as e:
            raise MediaReadError("This file is not a readable image (PNG, JPG, WebP, BMP or TIFF).") from e
        if max(image.size) > OCR_MAX_SIDE:
            image.thumbnail((OCR_MAX_SIDE, OCR_MAX_SIDE))
        array = np.asarray(image)[:, :, ::-1]  # RapidOCR expects BGR
        with _ocr_lock:
            result, _ = _get_ocr()(array)
    except MediaReadError:
        raise
    except Exception as e:
        logger.exception("Image text recognition failed")
        raise MediaReadError("Could not read text from this image.") from e
    items = []
    for box, text, confidence in result or []:
        if float(confidence) < MIN_OCR_CONFIDENCE or not text.strip():
            continue
        ys = [p[1] for p in box]
        items.append((min(p[0] for p in box), (min(ys) + max(ys)) / 2, max(ys) - min(ys), text.strip()))
    return _group_lines(items)


def transcribe(data: bytes, max_seconds: float | None = None) -> tuple[list[tuple[float, float, str]], str, float]:
    """(segments as (start, end, text), detected language, duration in seconds). Raises MediaReadError."""
    model = _get_whisper()
    try:
        with _whisper_lock:
            segments, info = model.transcribe(io.BytesIO(data), vad_filter=True)
            if max_seconds and info.duration > max_seconds:
                raise MediaReadError(
                    f"This recording is {info.duration / 60:.0f} minutes long; the limit here is {max_seconds / 60:.0f}. "
                    "Upload it to the knowledge base instead, which has no time limit.")
            out = [(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]
    except MediaReadError:
        raise
    except Exception as e:
        logger.exception("Speech recognition failed")
        raise MediaReadError("This file is not a readable audio recording, or it contains no speech.") from e
    return out, info.language, info.duration


def _stamp(seconds: float) -> str:
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def transcript_pages(segments: list[tuple[float, float, str]]):
    """Group segments into one-minute windows -> (window number starting at 1, '[mm:ss] text ...')."""
    window, buffer = None, []
    for start, _end, text in segments:
        number = int(start // TRANSCRIPT_WINDOW_SECONDS) + 1
        if window is not None and number != window:
            yield window, " ".join(buffer)
            buffer = []
        if not buffer:
            buffer.append(f"[{_stamp(start)}]")
        window = number
        buffer.append(text)
    if buffer and window is not None:
        yield window, " ".join(buffer)
