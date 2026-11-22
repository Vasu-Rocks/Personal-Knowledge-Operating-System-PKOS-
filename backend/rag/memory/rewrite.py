"""
Follow-up questions -> standalone questions, before the documents are searched (docs/07_MEMORY_PLAN.md, step 4).

"And when does he come?" searched as typed finds nothing; "When does the surveyor visit the glacier station?" does.
One short model call turns the follow-up into a complete question and also says whether new search is needed at all
("make it shorter" only reworks the previous answer). It never blocks an answer: any failure, a timeout or an
unusable reply falls back to the question as typed, with search.
"""
import asyncio
import logging
from dataclasses import dataclass

from core import config
from core.llm import LLMError, LLMSettings, chat_json

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 300
ANSWER_EXCERPT_CHARS = 400   # old answers are shortened in the rewrite prompt: the gist is enough to resolve references

SCHEMA = {
    "type": "object",
    "properties": {"question": {"type": "string"}, "needs_search": {"type": "boolean"}},
    "required": ["question", "needs_search"],
}

SYSTEM = """You turn the user's latest message into a complete, standalone question for searching their documents.

Rules:
- Use the conversation only to resolve what the latest message refers to ("it", "he", "that", "the second one", "and in 2023?").
- Keep the user's language and wording where possible. Do not answer the question. Do not add facts.
- If the latest message is already understandable on its own, or starts a new topic, return it unchanged. Never join
  a new topic to the previous one.
- needs_search is false ONLY when the user asks to rework the previous answer itself (shorter, simpler, a list, a table,
  translate it, explain it again) and no new information is needed. Otherwise it is true.

Reply with JSON only: {"question": "...", "needs_search": true}

Examples:
Conversation: User: Who visits the glacier station? / Assistant: The surveyor visits it.
Latest message: When does he come?
{"question": "When does the surveyor visit the glacier station?", "needs_search": true}

Conversation: User: What did the March notes say about sensors? / Assistant: Order 12 temperature sensors.
Latest message: Make that a bullet list
{"question": "Make the answer about what the March notes said about sensors a bullet list", "needs_search": false}

Conversation: User: What is the project budget? / Assistant: 120,000 euros for 2024.
Latest message: Translate that into Hindi
{"question": "Translate the answer about the 2024 project budget into Hindi", "needs_search": false}

Conversation: User: How do I make the tomato pasta? / Assistant: Simmer tomatoes with garlic.
Latest message: What about the bread recipe?
{"question": "What about the bread recipe?", "needs_search": true}"""


@dataclass
class Rewrite:
    question: str          # what to search with
    needs_search: bool
    rewritten: bool        # False when the original question is used because the rewrite was skipped or failed


def _transcript(history: list[dict], summary: str | None) -> str:
    lines = [f"(Earlier: {summary.strip()})"] if summary else []
    for message in history:
        text = " ".join(message["content"].split())
        if message["role"] == "assistant" and len(text) > ANSWER_EXCERPT_CHARS:
            text = text[:ANSWER_EXCERPT_CHARS].rstrip() + "..."
        lines.append(f"{'User' if message['role'] == 'user' else 'Assistant'}: {text}")
    return "\n".join(lines)


def _validate(reply, original: str) -> Rewrite | None:
    if not isinstance(reply, dict):
        return None
    question = reply.get("question")
    if not isinstance(question, str):
        return None
    question = " ".join(question.split())  # one line
    if not question or len(question) > MAX_QUESTION_CHARS:
        return None
    needs_search = reply.get("needs_search")
    return Rewrite(question, needs_search if isinstance(needs_search, bool) else True, question != original)


async def rewrite_question(settings: LLMSettings, history: list[dict], summary: str | None, question: str,
                           timeout: float | None = None) -> Rewrite:
    """The question to search with. Without history (the first question of a chat) no model call is made."""
    fallback = Rewrite(question, True, False)
    if not history and not summary:
        return fallback
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Conversation:\n{_transcript(history, summary)}\n\nLatest message: {question}"},
    ]
    try:
        reply = await asyncio.wait_for(
            chat_json(settings, messages, schema=SCHEMA, temperature=0.0, max_tokens=120, num_ctx=2048),
            timeout=config.REWRITE_TIMEOUT if timeout is None else timeout)
    except asyncio.TimeoutError:
        logger.warning("Question rewrite timed out; searching with the question as typed")
        return fallback
    except LLMError as e:
        logger.warning("Question rewrite failed (%s); searching with the question as typed", e)
        return fallback
    except Exception:
        logger.exception("Question rewrite failed; searching with the question as typed")
        return fallback
    result = _validate(reply, question)
    if result is None:
        logger.warning("Question rewrite gave an unusable reply %r; searching with the question as typed", reply)
        return fallback
    return result
