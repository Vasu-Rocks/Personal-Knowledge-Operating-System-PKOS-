"""
Long-term memories in answers (docs/07_MEMORY_PLAN.md 10.4).

Preferences ("answer in short bullet points") shape every answer, so the newest few are always included. Facts and
conclusions are included when they are close to the question. Together they stay within MEMORY_MAX_CHARS, and the
prompt shows them in a section of their own, never as document passages.
"""
import asyncpg

from core import config
from database import memories_db


async def select_memories(pool: asyncpg.Pool, user_id: str, query_vector: list | None) -> list[dict]:
    """The memories to give the model for this question: [{memory_id, text, kind}], preferences first.
    Without a query vector (the previous answer is only being reworked) only preferences are chosen."""
    preferences = await memories_db.active_preferences(pool, user_id, config.MEMORY_MAX_PREFERENCES)
    facts = []
    if query_vector is not None and config.MEMORY_MAX_FACTS > 0:
        facts = await memories_db.closest_facts(pool, user_id, query_vector, config.MEMORY_MAX_FACTS,
                                                config.MEMORY_MAX_DISTANCE)
    chosen, used = [], 0
    for memory in preferences + facts:
        size = len(memory["text"]) + 16
        if used + size > config.MEMORY_MAX_CHARS:
            continue  # a shorter one later may still fit
        chosen.append({"memory_id": memory["memory_id"], "text": memory["text"], "kind": memory["kind"]})
        used += size
    return chosen


def answers_about_the_user(memories: list[dict]) -> bool:
    """Facts and conclusions can answer a question by themselves (decision Q5); preferences cannot."""
    return any(m["kind"] != "preference" for m in memories)
