"""Audio and image notes: speech recognition (faster-whisper) and OCR (RapidOCR), on small generated fixtures."""
import io
import struct
import wave
from pathlib import Path

import pytest

from rag.ingestion import media
from rag.ingestion.extractors import UnreadableFile, extract_audio_stream, extract_image_stream
from rag.ingestion.media import MediaReadError, _group_lines, ocr_image, transcript_pages

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def speech_model():
    """The Whisper model is a ~150 MB download on first use; skip the speech tests where it cannot be loaded."""
    try:
        return media._get_whisper()
    except MediaReadError:
        pytest.skip("speech model not available (offline)")


# ------------------------------------------------------------------------------------------------ pure logic

def test_boxes_on_one_visual_line_are_joined_left_to_right():
    items = [(300, 50, 20, "notes"), (40, 52, 20, "Meeting"), (40, 140, 20, "1. Order sensors")]
    assert _group_lines(items) == "Meeting notes\n1. Order sensors"
    assert _group_lines([]) == ""


def test_transcript_pages_group_by_minute_with_timestamps():
    segments = [(0.0, 4.0, "Hello there."), (5.0, 9.0, "Second sentence."), (65.0, 70.0, "A minute later."),
                (130.0, 133.0, "Third minute.")]
    assert list(transcript_pages(segments)) == [
        (1, "[00:00] Hello there. Second sentence."), (2, "[01:05] A minute later."), (3, "[02:10] Third minute.")]
    assert list(transcript_pages([])) == []


# ------------------------------------------------------------------------------------------------ images

def test_ocr_reads_a_photo_of_notes_line_by_line():
    text = ocr_image((DATA / "notes.png").read_bytes())
    lines = text.splitlines()
    assert len(lines) == 4, text
    assert "Meeting notes - 12 March" in lines[0]
    assert "Order 12 temperature sensors" in lines[1]
    assert "surveyor on Tuesday" in lines[2]
    assert "2.7" in lines[3] and "glacier" in lines[3]


def test_ocr_of_a_blank_image_is_empty_not_an_error():
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buffer, "PNG")
    assert ocr_image(buffer.getvalue()) == ""


def test_ocr_of_something_that_is_not_an_image_says_so():
    with pytest.raises(MediaReadError, match="not a readable image"):
        ocr_image(b"definitely not an image")


def test_image_extractor_yields_one_page():
    pages = list(extract_image_stream(io.BytesIO((DATA / "notes.png").read_bytes())))
    assert len(pages) == 1 and pages[0][0] == 1 and "Meeting notes" in pages[0][1]


# ------------------------------------------------------------------------------------------------ audio

def test_speech_is_transcribed(speech_model):
    segments, language, duration = media.transcribe((DATA / "voice.wav").read_bytes())
    text = " ".join(t for _, _, t in segments).lower()
    assert language == "en" and 4 < duration < 12
    assert "surveyor" in text and "tuesday" in text and "temperature sensors" in text, text


def test_audio_extractor_yields_timestamped_pages(speech_model):
    pages = list(extract_audio_stream(io.BytesIO((DATA / "voice.wav").read_bytes())))
    assert len(pages) == 1 and pages[0][1].startswith("[00:00]")


def test_silence_gives_no_text_and_garbage_gives_a_clear_error(speech_model):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(struct.pack("<h", 0) * 16000 * 2)
    assert list(extract_audio_stream(io.BytesIO(buffer.getvalue()))) == []
    with pytest.raises(UnreadableFile, match="not a readable audio"):
        list(extract_audio_stream(io.BytesIO(b"this is not audio")))


def test_overlong_recording_is_refused_for_a_query(speech_model):
    with pytest.raises(MediaReadError, match="minutes long"):
        media.transcribe((DATA / "voice.wav").read_bytes(), max_seconds=3)


# ------------------------------------------------------------------------------------------------ through the API

def test_ocr_endpoint_returns_one_editable_line(make_user):
    u = make_user("ocruser")
    r = u.client.post("/api/v1/ocr", files={"file": ("notes.png", (DATA / "notes.png").read_bytes())}, headers=u.headers)
    assert r.status_code == 200, r.text
    assert "\n" not in r.json()["text"] and "Order 12 temperature sensors" in r.json()["text"]


def test_media_endpoints_need_a_login_and_check_the_file_type(make_user):
    u = make_user("mediabad")
    assert u.client.post("/api/v1/ocr", files={"file": ("n.png", b"x")}).status_code in (401, 403)
    r = u.client.post("/api/v1/ocr", files={"file": ("n.exe", b"x")}, headers=u.headers)
    assert r.status_code == 415
    r = u.client.post("/api/v1/ocr", files={"file": ("n.png", b"not an image")}, headers=u.headers)
    assert r.status_code == 422 and "not a readable image" in r.json()["detail"]
    r = u.client.post("/api/v1/transcribe", files={"file": ("n.txt", b"x")}, headers=u.headers)
    assert r.status_code == 415


def test_transcribe_endpoint(make_user, speech_model):
    u = make_user("voiceuser")
    r = u.client.post("/api/v1/transcribe", files={"file": ("q.wav", (DATA / "voice.wav").read_bytes())}, headers=u.headers)
    assert r.status_code == 200, r.text
    assert "surveyor" in r.json()["text"].lower()


def test_uploaded_image_and_voice_note_are_indexed_and_failures_are_explained(make_user, speech_model):
    u = make_user("mediaupload")
    assert u.upload("whiteboard.png", (DATA / "notes.png").read_bytes()).status_code == 202
    assert u.upload("memo.wav", (DATA / "voice.wav").read_bytes()).status_code == 202
    u.upload("blank.png", _blank_png())
    u.upload("broken.mp3", b"not audio at all")
    docs = {d["filename"]: d for d in u.documents()}
    assert docs["whiteboard.png"]["index_status"] == "READY" and docs["whiteboard.png"]["chunk_count"] >= 1
    assert docs["memo.wav"]["index_status"] == "READY" and docs["memo.wav"]["chunk_count"] >= 1
    assert docs["blank.png"]["index_status"] == "FAILED" and "No extractable text" in docs["blank.png"]["index_error"]
    assert docs["broken.mp3"]["index_status"] == "FAILED" and "not a readable audio" in docs["broken.mp3"]["index_error"]


def _blank_png():
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buffer, "PNG")
    return buffer.getvalue()
