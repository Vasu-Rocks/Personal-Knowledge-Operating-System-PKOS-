"""
Text extraction for the ingestion pipeline.

PDFs are read with pypdfium2 (Google's PDFium; permissive Apache-2.0/BSD licence). PDFium's own page text is used as is
when it looks sane. It has one known weakness: on some pages, mostly tables, it drops the spaces between words
("Mer de Glace 2.7 315" comes out as "MerdeGlace2.7315") or breaks lines after every character. Such pages are detected
(abnormally long words) and their text is rebuilt from PDFium's per-character positions, keeping PDFium's reading order.
"""
import logging
import re

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from .headers import detect_repeating_edges, strip_edges

logger = logging.getLogger(__name__)


class UnreadableFile(ValueError):
    """The file cannot be read at all; the message is safe to show to the user."""


class PdfReadError(UnreadableFile):
    """The PDF cannot be read at all; the message is safe to show to the user."""


# Rebuild tuning (see the module docstring). Measured against PyMuPDF on 43 test pages: every SPACE_GAP from 0.06 to
# 0.12 reproduces its words exactly; 0.15 and above start gluing words together.
SPACE_GAP = 0.10         # gap between neighbouring characters, in line heights, above which a space is inserted
LINE_SHIFT = 0.55        # baseline move, in line heights, that starts a new line
SUSPECT_MEAN_WORD = 9.0  # a page whose words average longer than this probably lost its spaces
MIN_GAIN = 0.8           # keep the rebuilt text only if its mean word length is at most this fraction of PDFium's
MIN_WORDS_TO_JUDGE = 8
# Scripts written without spaces between words: long "words" are normal there.
_NO_SPACE_SCRIPTS = re.compile(r"[฀-๿぀-ヿ㐀-鿿가-힯]")


def _normalize(text: str) -> str:
    """PDFium returns CRLF line endings."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _mean_word_length(text: str) -> float:
    words = text.split()
    return sum(map(len, words)) / len(words) if words else 0.0


def _looks_merged(text: str) -> bool:
    """True when the words are so long on average that spaces were probably lost (not for CJK/Thai text)."""
    words = text.split()
    if len(words) < MIN_WORDS_TO_JUDGE:
        return False
    chars = sum(map(len, words))
    if len(_NO_SPACE_SCRIPTS.findall(text)) > 0.3 * chars:
        return False
    return chars / len(words) > SUSPECT_MEAN_WORD


def _rebuild_text(textpage) -> str:
    """Page text from per-character boxes: spaces and line breaks come from geometry, the order from PDFium."""
    count = textpage.count_chars()
    raw = textpage.get_text_range()
    out: list[str] = []
    prev = None  # (left, bottom, right, top) of the last glyph written
    for i in range(count):
        ch = raw[i]
        if ch in "\r\n" or pdfium_c.FPDFText_IsGenerated(textpage.raw, i):
            continue  # PDFium's own separators are the unreliable part
        left, bottom, right, top = textpage.get_charbox(i, loose=True)
        if ch.isspace():
            if out and out[-1] not in " \n":
                out.append(" ")
            continue
        if prev is not None:
            height = max(top - bottom, prev[3] - prev[1], 1e-3)
            if abs(bottom - prev[1]) > LINE_SHIFT * height or left < prev[0] - height:  # new baseline, or jumped back left
                if out and out[-1] == " ":
                    out.pop()
                out.append("\n")
            elif left - prev[2] > SPACE_GAP * height and out and out[-1] not in " \n":
                out.append(" ")
        out.append(ch)
        prev = (left, bottom, right, top)
    return "".join(out)


def _page_text(page) -> str:
    textpage = page.get_textpage()
    try:
        # get_text_bounded() (whole page) derives line breaks from character positions; get_text_range() can emit one
        # character per line on pages whose glyphs are positioned individually.
        text = _normalize(textpage.get_text_bounded())
        if _looks_merged(text):
            rebuilt = _rebuild_text(textpage)
            if _mean_word_length(rebuilt) <= MIN_GAIN * _mean_word_length(text):
                return rebuilt
        return text
    finally:
        textpage.close()


def _explain(error: Exception) -> str:
    if "password" in str(error).lower():
        return "This PDF is password-protected. Remove the password and upload it again."
    return "This PDF is damaged or is not a valid PDF file."


def extract_pdf_stream(file_stream):
    """
    Sub-Module 1.2: PDF Extraction (Generator)
    Yields (page_number, text_content). Pages without text are skipped, running heads and page numbers removed.
    Raises PdfReadError (user-presentable message) when the file cannot be opened.
    """
    try:
        pdf = pdfium.PdfDocument(file_stream.read())
    except pdfium.PdfiumError as e:
        logger.warning("Cannot open PDF: %s", e)
        raise PdfReadError(_explain(e)) from None

    def pages_text():
        for index in range(len(pdf)):
            try:
                page = pdf[index]
                try:
                    yield _page_text(page)
                finally:
                    page.close()
            except pdfium.PdfiumError:
                logger.warning("Skipping unreadable PDF page %d", index + 1, exc_info=True)
                yield ""

    try:
        # First pass: find running heads/footers (lines repeated at page edges). The text is extracted twice rather
        # than kept, so memory stays flat for 500-page books.
        headers = detect_repeating_edges(pages_text())
        for page_num, raw in enumerate(pages_text(), start=1):
            text, _ = strip_edges(raw, headers)
            if text.strip():
                yield (page_num, text)
    finally:
        pdf.close()


def extract_image_stream(file_stream):
    """Photo or scan of notes -> one 'page' of recognised text (OCR, on this machine)."""
    from .media import ocr_image
    text = ocr_image(file_stream.read())
    if text.strip():
        yield (1, text)


def extract_audio_stream(file_stream):
    """Voice note or recording -> one 'page' per minute of transcript, each starting with its [mm:ss] time."""
    from .media import transcribe, transcript_pages
    segments, _language, _duration = transcribe(file_stream.read())
    yield from transcript_pages(segments)


def extract_text_stream(file_stream):
    """
    Sub-Module 1.2: Text/Code Extraction
    Reads standard UTF-8 files dynamically. Treats the file as a single 'page'
    but preserves exact whitespace logic essential for code snippets.
    """
    # Decoding strictly with utf-8, ignoring fatal errors gracefully
    text = file_stream.read().decode('utf-8', errors='ignore')
    if text.strip():
        yield (1, text)
