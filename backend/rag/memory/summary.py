"""
Running summary of a chat (docs/07_MEMORY_PLAN.md, step 5).

The history window holds only the last few turns. Turns that fall out of it are folded into a short summary, so a
long chat keeps its thread ("the budget we discussed at the start") without overflowing a 4096-token model.
The update runs in the background after an answer is saved; it never delays an answer, and when it fails the old
summary stays and the same turns are folded on the next attempt.
"""
import asyncio
import logging
import uuid

import asyncpg

from core import config
from core.llm import LLMSettings, chat_text
from database import conversations_db
from rag.memory.stm import turns_outside_window

logger = logging.getLogger(__name__)

MAX_FOLD_TURNS = 10          # per update; a backlog (after failures) is worked off over the next answers
ANSWER_EXCERPT_CHARS = 600   # long answers are shortened in the summary prompt
SUMMARY_TIMEOUT = 90.0

SYSTEM = """You keep a running summary of a conversation between a user and an assistant that answers questions from the
user's own documents.

Write the updated summary:
- plain text, at most {target} characters, third person;
- keep names, numbers, dates, decisions, and questions that were left open; drop greetings and filler;
- combine the current summary and the new turns into one text; do not invent anything;
- it is a summary, not a transcript: state facts once, without "The user asked... The assistant found...";
- when space runs short, compress the older parts and keep the newest turns more complete.

Reply with the summary only."""

SHORTEN = """Shorten this summary of a conversation to at most {target} characters. Keep names, numbers, dates, decisions
and open questions; keep the most recent points more complete than the older ones. Reply with the summary only."""


def _clip(text: str, limit: int) -> str:
    """Cut at the last sentence end (or space) before limit."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for mark in (". ", "! ", "? ", "\n"):
        if mark in cut[limit // 2:]:
            return cut[:cut.rindex(mark) + 1].strip()
    return cut[:cut.rindex(" ")].rstrip() + "..." if " " in cut else cut


async def summarize(settings: LLMSettings, summary: str | None, turns: list[tuple[str, str, int]],
                    max_chars: int | None = None) -> str | None:
    """The new summary text, or None when the model failed or gave nothing usable."""
    max_chars = config.SUMMARY_MAX_CHARS if max_chars is None else max_chars
    target = int(max_chars * 0.8)  # headroom: small models overshoot length limits
    lines = []
    for question, answer, _seq in turns:
        answer = " ".join(answer.split())
        if len(answer) > ANSWER_EXCERPT_CHARS:
            answer = answer[:ANSWER_EXCERPT_CHARS].rstrip() + "..."
        lines += [f"User: {' '.join(question.split())}", f"Assistant: {answer}"]
    messages = [
        {"role": "system", "content": SYSTEM.format(target=target)},
        {"role": "user", "content": f"Current summary:\n{summary or '(none yet)'}\n\nNew turns:\n" + "\n".join(lines)},
    ]
    text = await _ask(settings, messages, max_chars)
    if text and len(text) > max_chars:
        # Too long: one more call to compress it, so that cutting (which loses whatever is cut) stays a last resort.
        shorter = await _ask(settings, [{"role": "system", "content": SHORTEN.format(target=target)},
                                        {"role": "user", "content": text}], max_chars)
        if shorter and len(shorter) < len(text):
            text = shorter
    return _clip(text, max_chars) if text else None


async def _ask(settings: LLMSettings, messages: list[dict], max_chars: int) -> str | None:
    try:
        text = await asyncio.wait_for(
            chat_text(settings, messages, temperature=0.0, max_tokens=max_chars // 3 + 100, num_ctx=4096),
            timeout=SUMMARY_TIMEOUT)
    except Exception as e:
        logger.warning("Chat summary failed (%s); keeping the previous one", e)
        return None
    text = text.strip()
    for prefix in ("Updated summary:", "Summary:"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
    return text or None


async def update_summary(pool: asyncpg.Pool, settings: LLMSettings, user_id: str,
                         conversation_id: uuid.UUID) -> bool:
    """Folds the turns that fell out of the history window into the chat's summary. True when it changed."""
    if not config.MEMORY_ENABLED:
        return False
    conversation = await conversations_db.get_owned_conversation(pool, user_id, conversation_id)
    if conversation is None:
        return False
    messages = await conversations_db.get_messages(pool, user_id, conversation_id,
                                                   after_seq=conversation["summary_upto_seq"])
    outside = turns_outside_window(messages)[:MAX_FOLD_TURNS]
    if not outside:
        return False
    text = await summarize(settings, conversation["summary"], outside)
    if text is None:
        return False
    # Only if nobody else summarised this chat meanwhile (two answers in quick succession).
    saved = await conversations_db.save_summary(pool, user_id, conversation_id, text, upto_seq=outside[-1][2],
                                                expected_upto_seq=conversation["summary_upto_seq"])
    if saved:
        logger.info("Chat %s: summary now covers up to message %d", conversation_id, outside[-1][2])
    return saved
