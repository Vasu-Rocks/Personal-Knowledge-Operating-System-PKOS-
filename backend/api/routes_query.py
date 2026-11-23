import asyncio
import json
import logging
import uuid

import anyio
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import get_current_user, get_db
from core import config
from core.llm import LLMSettings
from database import conversations_db
from database.llm_settings_db import load_llm_settings
from database import memories_db
from rag.memory.episodic import lookback_topic, past_chat_blocks, refers_to_past_chats, update_recap
from rag.memory.ltm import answers_about_the_user, select_memories
from rag.memory.rewrite import rewrite_question
from rag.memory.stm import build_history
from rag.memory.summary import update_summary
from rag.query.generator import generate_rag_response_stream
from rag.query.prompt_builder import build_rag_prompt
from rag.query.retrieval import retrieve_context
from rag.query.retriever import format_context_blocks
from rag.vector.embedder import embed_query

logger = logging.getLogger(__name__)

router = APIRouter()

NO_ANSWER = "I cannot find the answer in your documents."
ERROR_PREFIX = "System Error:"   # generate_rag_response_stream reports provider failures as a token starting with this
GRAPH_SNAPSHOT_MAX_NODES = 80    # what is kept of the graph for reopening a chat; the X-Ray panel shows far fewer


class QueryRequest(BaseModel):
    query: str = Field(..., max_length=1000)
    # The chat this question belongs to. Without it a new chat is started (clients from before saved chats keep working).
    conversation_id: uuid.UUID | None = None


def _sse(event) -> str:
    return f"data: {event if isinstance(event, str) else json.dumps(event)}\n\n"


# Background summary updates: references keep the tasks alive; one at a time per chat.
_summary_tasks: set[asyncio.Task] = set()
_summarizing: set[uuid.UUID] = set()


def _summarize_later(pool: asyncpg.Pool, settings: LLMSettings, user_id: str, conversation_id: uuid.UUID):
    """Folds old turns into the chat's running summary after the response, without delaying it."""
    if not config.MEMORY_ENABLED or conversation_id in _summarizing:
        return

    async def run():
        try:
            await update_summary(pool, settings, user_id, conversation_id)
        except Exception:
            logger.exception("Summary update failed for chat %s", conversation_id)
        try:
            await update_recap(pool, user_id, conversation_id)  # past-chat search; an embedding only
        except Exception:
            logger.exception("Recap update failed for chat %s", conversation_id)
        finally:
            _summarizing.discard(conversation_id)

    _summarizing.add(conversation_id)
    task = asyncio.get_running_loop().create_task(run())
    _summary_tasks.add(task)
    task.add_done_callback(_summary_tasks.discard)


def _previous_answer(recent: list[dict]) -> dict | None:
    """The last usable answer of the chat with what it was based on (passages, or saved memories when it answered a
    question about the user), or None (then a new search runs)."""
    for message in reversed(recent):
        if message["role"] == "assistant":
            if message["status"] in ("complete", "partial") and (message.get("sources") or message.get("memories_used")):
                return message
            return None
    return None


def _graph_snapshot(graph: dict) -> dict | None:
    nodes = (graph or {}).get("nodes") or []
    if not nodes:
        return None
    kept = nodes[:GRAPH_SNAPSHOT_MAX_NODES]
    ids = {n.get("id") for n in kept}
    links = [link for link in graph.get("links") or [] if link.get("source") in ids and link.get("target") in ids]
    return {"nodes": kept, "links": links}


@router.post("/query/stream")
async def process_query_stream(
    payload: QueryRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db)
):
    """
    Answers one question as Server-Sent Events, in this order: conversation (the chat it was saved in), rewrite
    (follow-ups only: the question actually searched), memories (when saved memories were used), sources, graph,
    token..., saved (the ids of the stored question and answer), [DONE].
    The question and the answer are stored in the chat; an answer cut short by the client is stored as 'partial',
    a provider failure as 'error'.
    """
    user_query = payload.query.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    active_user_id = current_user["user_id"]
    history, summary, recent = [], None, []
    if payload.conversation_id:
        existing = await conversations_db.get_owned_conversation(pool, active_user_id, payload.conversation_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        if config.MEMORY_ENABLED:
            # Short-term memory: the recent turns not yet folded into the running summary (docs/07_MEMORY_PLAN.md).
            summary = existing["summary"]
            recent = await conversations_db.get_messages(
                pool, active_user_id, payload.conversation_id, after_seq=existing["summary_upto_seq"],
                last=2 * config.HISTORY_MAX_TURNS + 1)
            history = build_history(recent)

    # Saved per-user settings (Settings page) win. The X-LLM-* headers are the legacy path for clients that
    # still keep provider and keys in the browser; they are used only until the user saves settings.
    settings = await load_llm_settings(pool, active_user_id)
    if settings is None:
        settings = LLMSettings.from_dict({
            "provider": request.headers.get("x-llm-provider"),
            "ollama_model": request.headers.get("x-ollama-model"),
            "openai_key": request.headers.get("x-openai-key"),
            "anthropic_key": request.headers.get("x-anthropic-key"),
        })

    try:
        use_memories = config.MEMORY_ENABLED and (await memories_db.get_settings(pool, active_user_id))["enabled"]
        query_vector_list = None
        # Follow-ups are searched as a complete question ("when does he come?" -> "when does the surveyor visit
        # the station?"); the model still sees the question as typed, with the history around it.
        rewrite = await rewrite_question(settings, history, summary, user_query)
        previous = _previous_answer(recent) if not rewrite.needs_search else None
        if previous is not None:
            # Only the previous answer is being reworked ("shorter, please"): same passages, no new search.
            raw_chunks = previous["sources"]
            graph_data = previous["graph"] or {"nodes": [], "links": []}
        else:
            rewrite.needs_search = True
            query_vector_np = await run_in_threadpool(embed_query, rewrite.question)
            query_vector_list = query_vector_np.flatten().tolist()
            raw_chunks, graph_data = await retrieve_context(pool, active_user_id, rewrite.question, query_vector_list)
            if use_memories and refers_to_past_chats(user_query, rewrite.question):
                # "What did we decide about the sensors last time?": the closest earlier chats come first, searched
                # by the topic alone ("the sensors"), not by the look-back wording every such question shares.
                topic_vector = (await run_in_threadpool(embed_query, lookback_topic(rewrite.question))).flatten()
                raw_chunks = await past_chat_blocks(pool, active_user_id, topic_vector.tolist(),
                                                    payload.conversation_id) + raw_chunks
            if not raw_chunks and not graph_data.get("nodes") and (history or summary):
                # A follow-up whose search found nothing ("translate that", misjudged as needing search) is most
                # likely still about the previous answer: give the model those passages rather than nothing. The
                # rules still make it say it cannot find the answer if they do not contain it.
                previous = _previous_answer(recent)
                if previous is not None:
                    raw_chunks = previous["sources"]
                    graph_data = previous["graph"] or {"nodes": [], "links": []}

        # Long-term memories: preferences always, facts close to the (standalone) question. When the previous answer
        # is only being reworked there is no new question vector: its facts are carried over instead.
        memories = await select_memories(pool, active_user_id, query_vector_list) if use_memories else []
        if use_memories and query_vector_list is None and previous is not None:
            chosen = {m["memory_id"] for m in memories}
            memories += [m for m in previous.get("memories_used") or []
                         if m["kind"] != "preference" and m["memory_id"] not in chosen]

        # Do all string building and prompt parsing safely inside the try block
        # so any exceptions return a proper 500 status before response headers are sent
        retrieved_context, raw_chunks = format_context_blocks(raw_chunks)
        # A saved fact can answer a question about the user even when no document passage matches (decision Q5).
        has_context = bool(raw_chunks or graph_data.get("nodes") or answers_about_the_user(memories))
        rag_prompt = build_rag_prompt(user_query=user_query, retrieved_context=retrieved_context, graph_data=graph_data,
                                      history=history, summary=summary, memories=memories) if has_context else ""

        # Stored only once the question can be answered, so a failure above leaves no half-written chat behind.
        conversation_id = payload.conversation_id
        if conversation_id is None:
            conversation_id = uuid.UUID((await conversations_db.create_conversation(pool, active_user_id))["conversation_id"])
        question = await conversations_db.append_message(
            pool, active_user_id, conversation_id, "user", user_query,
            standalone_query=rewrite.question if history or summary else None,
            needs_search=rewrite.needs_search if history or summary else None)
        conversation = await conversations_db.get_owned_conversation(pool, active_user_id, conversation_id)
        if question is None or conversation is None:  # deleted between the check above and now
            raise HTTPException(status_code=404, detail="Chat not found.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] Engine Core Failed to Process Query Stream: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal RAG Engine Execution Error.")

    async def save_answer(text: str, status: str) -> dict | None:
        # Shielded: when the client disconnects this runs while the response is being cancelled, and must still finish.
        with anyio.CancelScope(shield=True):
            try:
                return await conversations_db.append_message(
                    pool, active_user_id, conversation_id, "assistant", text, sources=raw_chunks,
                    graph=_graph_snapshot(graph_data), status=status, provider=settings.provider, model=settings.model,
                    memories_used=memories or None)
            except Exception:
                logger.exception("Could not save the answer in chat %s", conversation_id)
                return None

    async def sse_event_generator():
        answer, finished = [], False
        try:
            yield _sse({"type": "conversation", "conversation_id": str(conversation_id), "title": conversation["title"]})
            if history or summary:
                # Shown under the question ("Searched for: ..."), so a poor rewrite is visible, not silent.
                yield _sse({"type": "rewrite", "standalone": rewrite.question, "needs_search": rewrite.needs_search,
                            "rewritten": rewrite.rewritten})
            if memories:
                # Listed in the X-Ray panel ("Memories used"), so the user sees what shaped the answer.
                # memories_only: no document passage was found, so the app labels the answer "Answered from your
                # saved memories" (the model cannot be relied on to say so itself).
                yield _sse({"type": "memories", "memories": memories,
                            "memories_only": not (raw_chunks or graph_data.get("nodes"))})
            # Sources first for the X-Ray sidebar, then the graph.
            yield _sse({"type": "sources", "sources": raw_chunks})
            yield _sse({"type": "graph", "data": graph_data})

            if not has_context:
                answer.append(NO_ANSWER)
                yield _sse({"type": "token", "content": NO_ANSWER})
            else:
                async for token_event_str in generate_rag_response_stream(rag_prompt, settings=settings):
                    try:
                        answer.append(json.loads(token_event_str).get("content", ""))
                    except (ValueError, AttributeError):
                        pass
                    yield _sse(token_event_str)

            text = "".join(answer)
            status = "error" if text.startswith(ERROR_PREFIX) else "complete"
            saved = await save_answer(text, status)
            finished = True
            if saved and status == "complete":
                _summarize_later(pool, settings, active_user_id, conversation_id)
                try:
                    await memories_db.mark_used(pool, active_user_id, [m["memory_id"] for m in memories])
                except Exception:
                    logger.exception("Could not record memory use")
            yield _sse({"type": "saved", "question_id": question["message_id"],
                        "answer_id": saved["message_id"] if saved else None})
            yield _sse("[DONE]")
        except Exception:
            # A failure while answering (not a disconnect: that is GeneratorExit/cancellation, not an Exception).
            logger.exception("Answer stream failed in chat %s", conversation_id)
            if not finished:
                finished = True
                await save_answer("".join(answer), "error")
            raise
        finally:
            if not finished:
                # The client went away (or the stream broke) mid-answer: keep what was generated.
                await save_answer("".join(answer), "partial")

    return StreamingResponse(sse_event_generator(), media_type="text/event-stream")
