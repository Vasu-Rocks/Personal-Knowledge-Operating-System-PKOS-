"""PDF extraction (pypdfium2) on Chromium-made fixtures in tests/data (see make_pdf_fixtures.js there)."""
import io
import re
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from rag.ingestion import extractors
from rag.ingestion.extractors import PdfReadError, extract_pdf_stream

DATA = Path(__file__).parent / "data"
ROW = re.compile(r"^R\d{3} (Aletsch|Pasterze|Rhone|Mer de Glace) -?\d+\.\d \d+$")


def pages(name):
    return list(extract_pdf_stream(io.BytesIO((DATA / name).read_bytes())))


def test_prose_is_complete_in_order_and_running_heads_are_removed():
    result = pages("prose_headers.pdf")
    assert len(result) >= 8  # header detection needs a few pages to tell a running head from content
    text = "\n".join(t for _, t in result)
    assert "Alpine Glacier Monitoring Handbook" not in text
    assert not re.search(r"Page \d+ of \d+", text)
    ids = [int(x) for x in re.findall(r"S(\d{3})", text)]
    assert ids == list(range(1, 521))  # every sentence once, in reading order
    assert "fox jumps" in text and "foxjumps" not in text  # spaces between words survive
    assert [n for n, _ in result] == list(range(1, len(result) + 1))


def test_table_rows_keep_their_words_and_one_row_per_line():
    (number, text), = pages("table_page.pdf")
    assert number == 1
    rows = [line for line in text.splitlines() if line.startswith("R")]
    assert len(rows) == 25
    assert all(ROW.match(line) for line in rows), [l for l in rows if not ROW.match(l)][:3]
    assert "ID Site Temp Ice" in text


def test_rebuild_repairs_pdfium_text_that_lost_its_spaces():
    pdf = pdfium.PdfDocument((DATA / "table_page.pdf").read_bytes())
    page = pdf[0]
    textpage = page.get_textpage()
    try:
        native = extractors._normalize(textpage.get_text_bounded())
        rebuilt = extractors._rebuild_text(textpage)
    finally:
        textpage.close()
    # What the fallback exists for: PDFium itself glues these words together.
    assert extractors._looks_merged(native), "PDFium no longer loses these spaces; the fallback may be unnecessary"
    assert not extractors._looks_merged(rebuilt)
    assert "Mer de Glace" in rebuilt or "Aletsch" in rebuilt


def test_pages_without_text_are_skipped_and_numbering_is_kept():
    result = pages("image_then_text.pdf")
    assert [n for n, _ in result] == [2]
    assert "S001" in result[0][1]


@pytest.mark.parametrize("text,expected", [
    ("the quick brown fox jumps over the lazy dog while the sensors record data " * 3, False),
    (" ".join(["R001MerdeGlace-3.1209", "R002Pasterze3.0169"] * 8), True),
    ("监测阿尔卑斯山冰川融化的传感器网络并记录温度和湿度数据" * 12 + " " + " ".join(["数据"] * 10), False),  # no spaces by design
    ("R001MerdeGlace", False),  # too little text to judge
    ("", False),
])
def test_merged_word_detection(text, expected):
    assert extractors._looks_merged(text) is expected


def test_unreadable_files_raise_messages_a_user_can_act_on():
    with pytest.raises(PdfReadError, match="damaged or is not a valid PDF"):
        list(extract_pdf_stream(io.BytesIO(b"")))
    with pytest.raises(PdfReadError, match="damaged or is not a valid PDF"):
        list(extract_pdf_stream(io.BytesIO(b"this is not a pdf at all")))
    with pytest.raises(PdfReadError, match="password-protected"):
        list(extract_pdf_stream(io.BytesIO((DATA / "password.pdf").read_bytes())))


def test_a_pdf_never_leaks_a_native_object_when_the_consumer_stops_early():
    generator = extract_pdf_stream(io.BytesIO((DATA / "prose_headers.pdf").read_bytes()))
    next(generator)
    generator.close()  # must run the finally block (closes the document) without raising


# ---------------------------------------------------------------------------------------------- through the API

def test_upload_of_a_pdf_indexes_it(make_user):
    u = make_user("pdfuser")
    assert u.upload("report.pdf", (DATA / "prose_headers.pdf").read_bytes()).status_code == 202
    doc = u.documents()[0]
    assert doc["index_status"] == "READY" and doc["chunk_count"] >= 5, doc


def test_upload_of_a_broken_or_protected_pdf_fails_with_a_clear_message(make_user):
    u = make_user("pdfbad")
    u.upload("broken.pdf", b"%PDF-1.4 this is cut off")
    u.upload("locked.pdf", (DATA / "password.pdf").read_bytes())
    errors = {d["filename"]: d["index_error"] for d in u.documents()}
    assert "damaged or is not a valid PDF" in errors["broken.pdf"]
    assert "password-protected" in errors["locked.pdf"]
