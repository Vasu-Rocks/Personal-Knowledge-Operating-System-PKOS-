import math
import re
from collections import Counter
from typing import Iterable

EDGE_LINES = 3  # running heads and footers sit in the first/last few lines of a page
MAX_HEADER_CHARS = 80
MIN_LINES_FOR_HEADERS = 12  # shorter pages are never searched for running heads
MIN_PAGES = 8  # too few pages to tell a running header from repeated content
MIN_REPEATS = 4
MIN_REPEAT_SHARE = 0.08  # chapter-titled running heads only cover one chapter's pages

_CODE_PROMPT = re.compile(r"^(in|out)\s?\[#\]:?$")  # Jupyter-style listings put these at page edges
_ROMAN = re.compile(r"^m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$")


def normalize(line: str) -> str:
    """Page-independent form of a line: 'Page 42' and 'Page 43' (or '4 Chapter 1...' and '6 Chapter 1...') match."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", line.lower())).strip()


def is_page_number(norm_line: str) -> bool:
    """'#', 'page #', '# of #', '# / #' or a roman numeral on its own."""
    if re.fullmatch(r"(page )?#( (of|/) #)?", norm_line):
        return True
    return 2 <= len(norm_line) <= 6 and bool(_ROMAN.fullmatch(norm_line))


def _edge_indices(lines: list[str], top: bool = True, bottom: bool = True) -> list[int]:
    """
    Indices (into lines) of the first and last EDGE_LINES non-empty lines. On a short page those zones would
    cover the body, so only the very first and last line are considered there (enough for a page number).
    top/bottom restrict which edge is returned (for a chunk that is only the start or end of a page).
    """
    nonempty = [i for i, l in enumerate(lines) if l.strip()]
    n = EDGE_LINES if len(nonempty) >= MIN_LINES_FOR_HEADERS else 1
    return sorted(set((nonempty[:n] if top else []) + (nonempty[-n:] if bottom else [])))


def detect_repeating_edges(page_texts: Iterable[str]) -> set[str]:
    """
    Normalised lines that sit at the top or bottom of many pages: running heads, footers, book titles.
    Returns an empty set for short documents.
    """
    pages = 0
    counts: Counter = Counter()
    for text in page_texts:
        pages += 1  # every page counts toward the threshold, including short ones that cannot vote
        lines = text.splitlines()
        if sum(1 for l in lines if l.strip()) < MIN_LINES_FOR_HEADERS:
            continue
        seen = {normalize(lines[i]) for i in _edge_indices(lines)}
        # Needs a letter: a repeated bare '#.#' is a section number (content), not a running head.
        counts.update(n for n in seen
                      if 2 <= len(n) <= MAX_HEADER_CHARS and not is_page_number(n) and re.search(r"[a-z]", n)
                      and not _CODE_PROMPT.match(n))
    if pages < MIN_PAGES:
        return set()
    threshold = max(MIN_REPEATS, math.ceil(MIN_REPEAT_SHARE * pages))
    return {n for n, c in counts.items() if c >= threshold}


def strip_edges(text: str, headers: set[str], top: bool = True, bottom: bool = True) -> tuple[str, list[str]]:
    """Removes known running heads and bare page numbers from a page's edges. Returns (text, removed_lines)."""
    lines = text.splitlines()
    drop = [i for i in _edge_indices(lines, top, bottom)
            if normalize(lines[i]) in headers or is_page_number(normalize(lines[i]))]
    if not drop:
        return text, []
    removed = [lines[i].strip() for i in drop]
    drop = set(drop)
    return "\n".join(l for i, l in enumerate(lines) if i not in drop), removed
