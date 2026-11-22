"""
Short-term memory: the recent turns of one chat, turned into chat messages for the model.

Old answers are passed without their citation markers: "[Chunk 3]" pointed into that turn's list of passages, and
left in, the model would cite passages that are not in the new context. Turns whose answer failed are left out, and
an interrupted answer is marked as such, so the model never mistakes it for a complete reply.
"""
import re

from core import config

INTERRUPTED = " (this answer was interrupted)"
TRUNCATED = " [...]"

# [Chunk 3], [chunk 1, chunk 2], [Chunk 1][Chunk 2], [Graph Entity: FastAPI], in any case, also as markdown links.
_CITATION = re.compile(r"\[(?:chunk\s*\d+(?:\s*(?:,|and)\s*(?:chunk\s*)?\d+)*|graph\s+entity\s*:[^\]]*)\](?:\([^)]*\))?",
                       re.IGNORECASE)
_EMPTY_EMPHASIS = re.compile(r"(\*{1,2}|_{1,2})\s*(?:[,;]\s*)*\1")   # *[Chunk 1]* leaves "**" behind
_EMPTY_BRACKETS = re.compile(r"\(\s*(?:[,;]\s*)*\)")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([.,;:!?])")


def strip_citations(text: str) -> str:
    text = _CITATION.sub("", text)
    text = _EMPTY_EMPHASIS.sub("", text)
    text = _EMPTY_BRACKETS.sub("", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _turns(messages: list[dict]) -> list[tuple[str, str, int | None]]:
    """(question, answer, seq of the answer) in order. A question without an answer, a failed answer or an empty
    interrupted one drops the whole turn: the model sees strictly alternating user/assistant messages."""
    turns, question = [], None
    for m in messages:
        if m["role"] == "user":
            question = m["content"]
            continue
        if question is None:
            continue  # an answer whose question fell outside the loaded window
        answer = strip_citations(m["content"])
        if m.get("status") == "error" or not answer:
            question = None
            continue
        if m.get("status") == "partial":
            answer += INTERRUPTED
        turns.append((question, answer, m.get("seq")))
        question = None
    return turns


def _window(turns: list[tuple], max_chars: int, max_turns: int) -> list[tuple[str, str]]:
    """The newest turns that fit, oldest first. The newest turn is always kept (its answer shortened if needed)."""
    if max_chars <= 0 or max_turns <= 0:
        return []
    kept, used = [], 0
    for question, answer, _seq in reversed(turns[-max_turns:]):
        size = len(question) + len(answer)
        if used + size > max_chars:
            if kept:
                break
            # The latest turn alone is too long: keep the question and as much of the answer as fits.
            room = max(0, max_chars - len(question) - len(TRUNCATED))
            answer = answer[:room].rstrip() + TRUNCATED
            size = len(question) + len(answer)
        kept.append((question, answer))
        used += size
    return list(reversed(kept))


def build_history(messages: list[dict], max_chars: int | None = None, max_turns: int | None = None) -> list[dict]:
    """Chat messages for the most recent turns that fit the character budget (HISTORY_MAX_CHARS/TURNS), oldest first."""
    max_chars = config.HISTORY_MAX_CHARS if max_chars is None else max_chars
    max_turns = config.HISTORY_MAX_TURNS if max_turns is None else max_turns
    history = []
    for question, answer in _window(_turns(messages), max_chars, max_turns):
        history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    return history


def turns_outside_window(messages: list[dict], max_chars: int | None = None,
                         max_turns: int | None = None) -> list[tuple[str, str, int]]:
    """The older turns that no longer fit the history window: (question, answer, seq of the answer), oldest first.
    These are what the running summary must absorb, or the model would lose them."""
    max_chars = config.HISTORY_MAX_CHARS if max_chars is None else max_chars
    max_turns = config.HISTORY_MAX_TURNS if max_turns is None else max_turns
    turns = _turns(messages)
    kept = len(_window(turns, max_chars, max_turns))
    return turns[:len(turns) - kept] if max_turns > 0 and max_chars > 0 else []
