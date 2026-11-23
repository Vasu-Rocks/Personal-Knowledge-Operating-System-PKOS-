"""
Past chats - episodic memory (docs/07_MEMORY_PLAN.md 10.5, decision Q4).

Every chat keeps a short recap (its running summary, or the first turns of a short chat) with an embedding, refreshed
after each complete answer - an embedding only, no model call. Past chats are searched only when a question refers to
earlier conversations ("last time", "what did we decide", ...), so ordinary document questions never pull them in.
The chosen chats become context blocks of their own ("Earlier chat: ..."), inside the normal context budget.
"""
import logging
import re
import uuid

import asyncpg
from fastapi.concurrency import run_in_threadpool

from core import config
from database import conversations_db
from rag.memory.stm import strip_citations
from rag.vector.embedder import embed_text_batch

logger = logging.getLogger(__name__)

RECAP_MAX_CHARS = 800
ANSWER_EXCERPT = 200
REFUSAL = "I cannot find the answer"   # api/routes_query.py NO_ANSWER: says nothing about the chat, left out

# Transparent and easy to extend, like the broad-question patterns in rag/query/router.py.
_PAST = [re.compile(p, re.IGNORECASE) for p in [
    r"\blast time\b",
    r"\b(earlier|previous|past|other|old|last|another)\s+(chat|chats|conversation|conversations|session|discussion)\b",
    r"\bwe\s+(discussed|talked|spoke|decided|concluded|agreed|said|went over|looked at)\b",
    r"\b(did|have)\s+we\s+(ever\s+)?(discuss|talk|decide|conclude|agree|say|cover)\b",
    r"\bwhat\s+did\s+(we|i|you)\s+(conclude|decide|say|ask|find|tell)\b",
    r"\byou\s+(told|said to|showed|gave)\s+me\b",
    r"\bi\s+(asked|told you|mentioned)\b.*\b(before|earlier|last)\b",
    r"\bremind\s+me\s+(what|of|about)\b",
    r"\b(before|earlier|previously),?\s+(we|you|i)\b",
]]


def refers_to_past_chats(*questions: str) -> bool:
    """Does the question (as typed, or as rewritten) ask about earlier conversations?"""
    return any(p.search(q) for q in questions if q for p in _PAST)


# The look-back wording itself ("remind me what we discussed about ..."), removed before the past-chat search: with
# it, bge-small ranked chats by how alike their wording was, and "Remind me what we discussed about my thesis" was
# closer to the Kyoto chat (0.379) than to the thesis chat (0.436). Searching by the topic alone, against recaps
# embedded without their "The user said / You answered" labels, found the right chat first 10/10 (8/10 before).
_LOOKBACK_WORDS = [re.compile(p, re.IGNORECASE) for p in [
    r"\b(in|from)\s+(our|an|the|my)\s+(earlier|previous|past|last|other|old)\s+(chat|conversation|session|discussion)s?\b",
    r"\b(earlier|previous|past|last|other|old)\s+(chat|conversation|session|discussion)s?\b",
    r"\blast time\b",
    r"\b(before|earlier|previously)\b",
    r"\b(remind me|tell me again)\s+(of|about|what)?\b",
    r"\bwhat\s+(did|have)\s+(we|i|you)\s+(ever\s+)?(discuss|discussed|talk|talked|decide|decided|conclude|concluded|"
    r"agree|agreed|say|said|tell|told|mention|mentioned|plan|planned|find|found)\b(\s+(about|on|for|you|me))?",
    r"\b(did|have)\s+we\s+(ever\s+)?(discuss|talk|decide|conclude|agree|say|cover)(ed)?\b(\s+(about|on))?",
    r"\bwe\s+(discussed|talked|spoke|decided|concluded|agreed|said|went over|looked at)\b(\s+(about|on))?",
    r"\byou\s+(told|said to|showed|gave)\s+me\b(\s+(something\s+)?(about|on))?",
    r"\bi\s+(asked|told you|mentioned|said)\b",
]]
_LABELS = re.compile(r"\b(The user said|You answered): ")


def lookback_topic(question: str) -> str:
    """What a look-back question is about: "What did we decide about the sensors last time?" -> "the sensors"."""
    topic = question
    for pattern in _LOOKBACK_WORDS:
        topic = pattern.sub(" ", topic)
    topic = re.sub(r"^[\s,;:\-]+|[\s,;:\-?]+$", "", " ".join(topic.split()))
    return topic or question


def recap_search_text(recap: str) -> str:
    """The recap as it is embedded: without the turn labels, which every recap shares."""
    return _LABELS.sub("", recap)


def build_recap(title: str, summary: str | None, messages: list[dict]) -> str:
    """
    The chat's recap: its running summary when there is one, otherwise its first turns, at most 800 characters.
    Measured on llama3.2 (docs/07_MEMORY_PLAN.md, step B4 results): "The user said / You answered" labels, no
    "I cannot find..." answers, and no title that only repeats the first question gave answers with all the details
    12/15 times, against 9/15 for "Question: / Answer:" turns after a cut-off copy of the question.
    """
    head = title.rstrip(" .")  # a cut title ends in "..."; no "...." before the body
    if summary:
        return f"{head}. {summary}".strip()[:RECAP_MAX_CHARS].rstrip()
    parts, first, looking_back = [], "", False
    for m in messages:
        if m["role"] == "user":
            # A look-back turn ("what did I tell you last time?") only repeats another chat, and its wording matches
            # every later look-back question: in the dev app it pushed the right chat out (step B4). Left out.
            looking_back = refers_to_past_chats(m["content"])
            first = first or ("" if looking_back else m["content"].strip())
        if looking_back:
            continue
        if m.get("status") == "error" or not m["content"].strip() or m["content"].startswith(REFUSAL):
            continue
        text = " ".join(strip_citations(m["content"]).split())
        if m["role"] == "assistant":
            text = text[:ANSWER_EXCERPT] + ("..." if len(text) > ANSWER_EXCERPT else "")
            parts.append(f"You answered: {text}")
        else:
            parts.append(f"The user said: {text}")
    if not parts:
        return ""   # nothing of its own to recall (for example only look-back questions): not searchable
    body = " ".join(parts)
    if head and not first.startswith(head) and not refers_to_past_chats(head):  # no title that repeats a question
        body = f"{head}. {body}"
    return body.strip()[:RECAP_MAX_CHARS].rstrip()


async def update_recap(pool: asyncpg.Pool, user_id: str, conversation_id: uuid.UUID) -> bool:
    """Refreshes the chat's recap and its embedding. True when stored."""
    conversation = await conversations_db.get_owned_conversation(pool, user_id, conversation_id)
    if conversation is None:
        return False
    messages = await conversations_db.get_messages(pool, user_id, conversation_id, last=12)
    recap = build_recap(conversation["title"], conversation["summary"], messages)
    if not recap:
        return False
    vector = (await run_in_threadpool(embed_text_batch, [recap_search_text(recap)]))[0]
    return await conversations_db.save_recap(pool, user_id, conversation_id, recap, vector)


async def past_chat_blocks(pool: asyncpg.Pool, user_id: str, query_vector: list, current: uuid.UUID | None) -> list[dict]:
    """Context blocks for the earlier chats closest to the question (never the chat being asked in)."""
    found = await conversations_db.search_past_chats(
        pool, user_id, query_vector, exclude=current, limit=config.PAST_CHATS_MAX,
        max_distance=config.PAST_CHATS_MAX_DISTANCE)
    return [{
        "chunk_id": f"chat:{c['conversation_id']}",
        "conversation_id": c["conversation_id"],
        "filename": c["title"],
        "page": c["updated_at"][:10],    # the date, shown in the block header and the sources list
        "text": c["recap"],
        "via": "chat",
        "distance": c["distance"],
    } for c in found]
