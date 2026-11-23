"""
Memory suggestions (docs/07_MEMORY_PLAN.md 10.3, step B5).

After an answer, PKOS may propose up to 2 memories from what the user said in their question: lasting facts about
themselves ("I am preparing for the GATE exam in February") or how they want answers ("keep answers simple"). They are
stored as `pending`: never used in answers until the user keeps them, deleted when dismissed.

Only the user's own words are read, never the answer or the documents, so document content cannot become a memory.
A transparent first-person/preference pattern decides whether the model is asked at all, so ordinary questions cost
nothing. The statements themselves are cut from the user's sentences by rule, and the model only labels each one
fact / preference / none: llama3.2 asked to write memories itself invented some ("I am a software engineer") and
reversed others ("short bullet points" became "Answer should be detailed"). One that matches an existing memory is
dropped.
"""
import asyncio
import logging
import re
import uuid

import asyncpg
from fastapi.concurrency import run_in_threadpool

from core.llm import LLMSettings, chat_json
from database import memories_db
from rag.memory.episodic import refers_to_past_chats
from rag.vector.embedder import embed_text_batch

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 2
MAX_STATEMENTS = 4         # statements of one question shown to the model
MAX_PENDING = 6            # unanswered suggestions per user; beyond that PKOS stops proposing until some are answered
DUPLICATE_DISTANCE = 0.15  # closer than this to an existing memory (kept or pending): the same memory
SUGGEST_TIMEOUT = 25.0

# Statements about the user, or about how to answer. Transparent and easy to extend (like the past-chat triggers).
_ABOUT_ME = [re.compile(p, re.IGNORECASE) for p in [
    r"\bi\s+(am|have|work|study|teach|use|prefer|like|love|hate|want|need|live|plan|will be|only|usually|always|never|"
    r"can't|cannot|don't|do not)\b",
    r"\b(i'm|i've|i'll)\b",
    r"\bmy\s+[\w-]+(\s+[\w-]+)?\s+(is|are|was|will be|starts?|ends?)\b",
    r"\b(please\s+)?(always|never)\s+(answer|explain|use|give|write|reply|include|keep)\b",
    r"\b(keep|make)\s+(it|answers?|them|your answers?|things)\s+(short|simple|brief|concise|basic|detailed)\b",
    r"\banswer\s+(in|with)\b",
    r"\bexplain\s+(it\s+|things\s+)?(simply|like|as if|in simple)\b",
    r"\bin\s+(short\s+)?bullet\s*points\b",
]]

# Never worth remembering, whatever the model says: they announce a question, not a fact.
_NOT_A_MEMORY = re.compile(
    r"^(i\s+(want|need|would like|wanted)\s+to\s+(know|understand|ask|learn about)|i'd like to know|"
    r"i\s+have\s+a\s+(question|doubt|problem)|i\s+(think|guess|wonder|believe|feel|mean)|"
    r"i\s+need\s+(the|a|an|some|help)|my\s+question)\b", re.IGNORECASE)
_ABBREVIATION = re.compile(r"\b(Dr|Mr|Mrs|Ms|Prof|St|Jr|Sr|vs|etc|e\.g|i\.e)\.\s+", re.IGNORECASE)
_DOT = chr(0x2024)  # ONE DOT LEADER: not a sentence end for the split below
_LEAD = re.compile(r"^(so|and|but|also|then|please|ok|okay|well|now)[\s,]+", re.IGNORECASE)
_VAGUE_IT = [(re.compile(r"^(keep|make)\s+it\b", re.IGNORECASE), r"\1 answers"),
             (re.compile(r"^explain\s+it\b", re.IGNORECASE), "explain things")]

SYSTEM = """You help a personal assistant decide what to remember about its user. Below are numbered statements \
the user made in a message. Label each one:
- "fact": stays true about the user for weeks or longer (their job, studies, level, what they are preparing for or \
working on such as an exam, a thesis or a project, deadlines, people they work with, tools they use);
- "preference": how the user wants answers in general (length, style, level, format);
- "none": anything else - a request about this one answer, what they want to know right now, an opinion, a question, \
something about documents or other people.

Reply with JSON: {"labels": [{"n": 1, "kind": "fact" | "preference" | "none"}, ...]} with one label per statement."""

SCHEMA = {
    "type": "object",
    "properties": {"labels": {"type": "array", "items": {
        "type": "object",
        "properties": {"n": {"type": "integer"}, "kind": {"type": "string", "enum": ["fact", "preference", "none"]}},
        "required": ["n", "kind"]}}},
    "required": ["labels"],
}


def says_something_about_the_user(question: str) -> bool:
    """Is it worth asking the model? Look-back questions only repeat earlier chats."""
    return any(p.search(question) for p in _ABOUT_ME) and not refers_to_past_chats(question)


def statements(question: str) -> list[str]:
    """The user's own statements about themselves or how to answer, in their words (questions left out)."""
    found = []
    # "Dr. Rao" is not the end of a sentence: its dot is swapped for a look-alike while splitting.
    question = _ABBREVIATION.sub(lambda m: m.group(1) + _DOT + " ", question.strip())
    for sentence in re.split(r"(?<=[.!?;:])\s+|\n+", question):
        if not sentence or sentence.rstrip().endswith("?"):
            continue
        for clause in re.split(r",\s+", sentence):
            clause = _LEAD.sub("", clause.strip(" .;:!\"'"))
            for pattern, replacement in _VAGUE_IT:
                clause = pattern.sub(replacement, clause)
            if len(clause) < 8 or len(clause) > memories_db.MAX_TEXT or "===" in clause or _NOT_A_MEMORY.match(clause):
                continue
            clause = clause.replace(_DOT, ".")
            if any(p.search(clause) for p in _ABOUT_ME) and clause.lower() not in (f.lower() for f in found):
                found.append(clause[0].upper() + clause[1:])
    return found[:MAX_STATEMENTS]


async def propose(settings: LLMSettings, question: str) -> list[dict]:
    """Suggestions for one question: the user's statements the model labels lasting; [] when none or the model fails."""
    if not says_something_about_the_user(question):
        return []
    candidates = statements(question)
    if not candidates:
        return []
    listing = "\n".join(f"{i}. {c}" for i, c in enumerate(candidates, 1))
    try:
        data = await asyncio.wait_for(chat_json(
            settings, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": listing}],
            schema=SCHEMA, temperature=0.0, max_tokens=150, num_ctx=2048), timeout=SUGGEST_TIMEOUT)
    except Exception as e:
        logger.warning("Memory suggestion failed (%s)", e)
        return []
    found = []
    for label in (data or {}).get("labels") or []:
        if not isinstance(label, dict) or label.get("kind") not in ("fact", "preference"):
            continue
        n = label.get("n")
        if isinstance(n, int) and 1 <= n <= len(candidates) and all(f["text"] != candidates[n - 1] for f in found):
            found.append({"text": candidates[n - 1], "kind": label["kind"]})
    return found[:MAX_SUGGESTIONS]


async def suggest_memories(pool: asyncpg.Pool, settings: LLMSettings, user_id: str, conversation_id: uuid.UUID,
                           question_id: str | None, question: str) -> list[dict]:
    """Stores the suggestions for one question as pending memories and returns them (as the API shows memories)."""
    if not says_something_about_the_user(question):
        return []
    prefs = await memories_db.get_settings(pool, user_id)
    if not (prefs["enabled"] and prefs["suggest"]):
        return []
    if await memories_db.count_memories(pool, user_id, status="pending") >= MAX_PENDING:
        return []
    if await memories_db.count_memories(pool, user_id) >= memories_db.MAX_MEMORIES:
        return []
    proposals = await propose(settings, question)
    if not proposals:
        return []
    vectors = await run_in_threadpool(embed_text_batch, [p["text"] for p in proposals])
    stored, kept = [], []
    for proposal, vector in zip(proposals, vectors):
        vector = [float(x) for x in vector]
        if await memories_db.closest_any(pool, user_id, vector, DUPLICATE_DISTANCE):
            continue  # already remembered, or already suggested
        if any(sum(a * b for a, b in zip(vector, v)) > 1 - DUPLICATE_DISTANCE for v in kept):
            continue  # the two suggestions say the same
        if await memories_db.find_same_text(pool, user_id, proposal["text"]):
            continue
        stored.append(await memories_db.create_memory(
            pool, user_id, proposal["text"], proposal["kind"], vector, origin="suggested", status="pending",
            source_conversation_id=conversation_id,
            source_message_id=uuid.UUID(question_id) if question_id else None))
        kept.append(vector)
    if stored:
        logger.info("Chat %s: %d memory suggestion(s)", conversation_id, len(stored))
    return stored
