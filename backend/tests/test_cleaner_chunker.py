from rag.ingestion.chunker import split_text_into_chunks
from rag.ingestion.cleaner import clean_text

LONG = "This is a sentence that is comfortably longer than fifty characters in total length."


def test_short_text_is_dropped_as_ghost_chunk():
    assert clean_text("too short", ".txt") == ""


def test_prose_collapses_spaces_and_newlines():
    out = clean_text(f"{LONG}\n\n\n\n{LONG}   with    spaces", ".txt")
    assert "\n\n\n" not in out
    assert "  " not in out


def test_pdf_hyphenated_line_breaks_are_joined():
    assert "information" in clean_text(f"{LONG} infor-\nmation", ".pdf")


def test_code_keeps_indentation():
    code = "def f():\n    return 1\n" + "# " + "x" * 60
    assert "    return 1" in clean_text(code, ".py")


def test_control_characters_removed():
    assert "\x00" not in clean_text(f"{LONG}\x00\x07", ".txt")


def test_urls_are_kept():
    assert "https://example.com/a/b?c=d" in clean_text(f"{LONG} see https://example.com/a/b?c=d now", ".txt")


def test_chunks_respect_size_limit():
    text = ". ".join(f"Sentence number {i} with some filler words" for i in range(200))
    chunks = split_text_into_chunks(text)
    assert len(chunks) > 1
    assert all(len(c) <= 1200 for c in chunks)


def test_short_text_gives_single_chunk():
    assert split_text_into_chunks(LONG) == [LONG]
