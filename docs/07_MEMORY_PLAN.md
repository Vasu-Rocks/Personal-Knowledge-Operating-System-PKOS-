# 07 - Conversation memory: sessions, short-term memory (STM), long-term memory (LTM)

Status: plan, 2026-11-23. Part A (sessions + STM) is built first, step by step (section 9). Part B (LTM) follows and is
outlined in section 10 so that Part A's schema and code leave room for it.

## 1. Goal

- **Sessions.** Every chat is a saved conversation: a list of chats that survives restarts, can be reopened, renamed,
  deleted, and started afresh ("New chat").
- **STM.** Inside one conversation the AI understands follow-ups ("what about the second one?", "make it shorter",
  "and in 2023?") because it sees the recent turns, and because the follow-up is rewritten into a complete question
  *before* searching the documents.
- **LTM (Part B).** Facts about the user and conclusions from past chats, kept across conversations, always visible and
  editable by the user.

Non-goals for Part A: memory across conversations, automatic extraction of facts, sharing chats, multi-device sync.

## 2. Current state (what the code does today)

- `POST /api/v1/query/stream` (`backend/api/routes_query.py`) takes only `{query}`. Each question is embedded, searched
  (`rag/query/retrieval.py`: vector + graph + community summaries for broad questions), packed into one system prompt
  (`rag/query/prompt_builder.py`) and answered by the user's provider (`core/llm.py` `chat_stream`). It has no idea any
  earlier question existed.
- The chat on screen lives only in React state (`frontend/src/components/Dashboard.jsx` `messages`). Restarting the app,
  logging out or reloading loses it. Sources and graph data per answer are kept in that state for the X-Ray panel.
- Budget: Ollama runs with `num_ctx` 4096 tokens. Document context is capped at `CONTEXT_MAX_CHARS` 6000 and graph context
  at `GRAPH_CONTEXT_MAX_CHARS` 1800 characters (~4 characters per token), answers at 512 tokens.
- Schema changes go through numbered SQL files in `backend/database/migrations` (`0002_user_llm_settings.sql` is the
  latest), applied once each at start-up.

## 3. Concepts

| Term | Meaning in PKOS |
|---|---|
| Conversation | One chat thread, owned by one user. |
| Turn | One user message and the assistant answer to it. |
| History window | The last few turns, sent to the AI with the new question, cut to a character budget. |
| Running summary | A short summary of the turns that no longer fit the window, updated in the background. |
| Standalone question | The follow-up rewritten so it makes sense on its own; this is what gets searched. |
| needs_search | The rewriter's verdict: does the question need new document search ("and in 2023?": yes) or is it about the previous answer only ("shorter, please": no)? |

## 4. How a question flows (Part A)

```
user question + conversation_id
  1. check the conversation belongs to the user (or create a new one)
  2. save the user message
  3. load history: running summary + last N turns
  4. if there is history: rewrite -> {standalone question, needs_search}     (one short LLM call; fallback: original)
  5. needs_search ? retrieve with the standalone question : reuse the previous answer and its sources
  6. prompt = rules + CONTEXT + (summary + history turns) + the question
  7. stream the answer; save it with its sources, graph, standalone question and status
  8. if many turns are not yet summarised: update the running summary in the background
```

Design rules:
- **Documents stay the only source of facts.** History is there to understand the question, not as evidence. The system
  prompt says so explicitly; the "I cannot find the answer in your documents" rule is unchanged.
- **Citation markers are removed from old answers** before they go into the history. `[Chunk 3]` in an old answer pointed
  at that turn's chunk list; left in, the model would cite chunks that do not exist in the new context.
- **The rewrite never blocks an answer.** Errors, timeouts (8 s), empty or overlong output fall back to the original question.
- **The user can see what was searched.** The standalone question is sent to the UI and shown under the question
  ("Searched for: ...") and in the X-Ray panel, so a bad rewrite is visible instead of silently giving a wrong answer.
- **The first question of a chat costs nothing extra:** no history, no rewrite call.

## 5. Data model (migration `0003_conversations.sql`)

```sql
CREATE TABLE conversations (
    conversation_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL DEFAULT 'New chat',
    summary TEXT,                         -- running summary of older turns (STM)
    summary_upto_seq INTEGER NOT NULL DEFAULT 0,  -- messages with seq <= this are covered by summary
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX conversations_user_updated_idx ON conversations(user_id, updated_at DESC);

CREATE TABLE messages (
    message_id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,                 -- order inside the conversation
    role VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    standalone_query TEXT,                -- user messages: what was actually searched
    needs_search BOOLEAN,
    sources JSONB,                        -- assistant: the chunks shown in X-Ray (a snapshot: survives document deletion)
    graph JSONB,                          -- assistant: graph nodes/links for X-Ray (capped)
    status VARCHAR(12) NOT NULL DEFAULT 'complete' CHECK (status IN ('complete', 'partial', 'error')),
    provider VARCHAR(20), model VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, seq)
);
```

Notes:
- `user_id` lives only on `conversations`; every query on `messages` joins through it, so another user's chat can never
  be read by guessing an id. A helper `get_owned_conversation(pool, user_id, conversation_id)` is the single gate.
- Sources are a snapshot (filename, page, text, via) because document deletion must not break old chats; a deleted
  document's source stays readable in the chat and is marked "document deleted" when clicked.
- Title: the first question, cut to 60 characters at a word boundary (free, instant); the user can rename. An AI title
  can come later if wanted.
- Part B adds tables, it does not change these (section 10).

## 6. Backend changes

New files:
- `backend/database/conversations_db.py` - create, list (paged, newest first), get with messages, rename, delete,
  append message (assigns `seq` in one statement), update summary. All functions take `user_id`.
- `backend/api/routes_conversations.py`
  - `GET /conversations?limit=&before=` - list: id, title, updated_at, message_count.
  - `POST /conversations` - create an empty chat (the UI's "New chat"); returns it.
  - `GET /conversations/{id}` - the chat with its messages (sources and graph included).
  - `PATCH /conversations/{id}` - rename.
  - `DELETE /conversations/{id}` - delete with its messages.
  - 404 for a chat that does not exist *or* belongs to someone else (no information leak).
- `backend/rag/memory/stm.py`
  - `build_history(summary, turns, max_chars)` - newest turns first until the budget is used, then reversed into order;
    strips citation markers; drops `error` answers; keeps `partial` ones marked "(answer was interrupted)".
  - `rewrite_question(settings, summary, turns, question)` -> `(standalone, needs_search)`; JSON output via
    `chat_json` with a schema, `temperature 0`, `max_tokens 120`, `num_ctx 2048`, timeout 8 s; validated (non-empty,
    <= 300 characters, a single line); falls back to `(question, True)`.
  - `update_summary(settings, conversation)` - folds the turns that fell out of the window into `summary`
    (<= 1200 characters); runs after the answer is saved, never delays it; a failure leaves the old summary.
- `backend/rag/memory/__init__.py`

Changed files:
- `backend/api/routes_query.py` - `QueryRequest` gains `conversation_id: UUID | None`. Without it a new conversation is
  created (old clients keep working). New SSE events, all before the existing ones:
  `{"type":"conversation","conversation_id":...,"title":...}` and
  `{"type":"rewrite","standalone":...,"needs_search":...}`; after `[DONE]`-preceding tokens:
  `{"type":"saved","message_id":...}`. The answer text is collected while streaming and saved at the end; if the client
  disconnects mid-answer, what was generated is saved as `partial`; a provider error is saved as `error`.
- `backend/rag/query/prompt_builder.py` - `build_rag_prompt(..., history=None, summary=None)`: the summary goes in the
  system message under "EARLIER IN THIS CONVERSATION", the window turns become real `user`/`assistant` messages before
  the final question, plus one rule: *use the conversation only to understand what the user means; facts must come
  from CONTEXT.* For `needs_search = false` the previous answer becomes the CONTEXT ("[Chunk 1] Your previous answer")
  and its sources are reused.
- `backend/core/config.py` - `HISTORY_MAX_CHARS` 2400, `HISTORY_MAX_TURNS` 6, `SUMMARY_MAX_CHARS` 1200,
  `REWRITE_TIMEOUT` 8, `MEMORY_ENABLED` true. Budget check for Ollama's 4096 tokens: system rules ~1200 + documents 6000 +
  graph 1800 + history 2400 + summary 1200 = 12,600 characters ~ 3,150 tokens, plus 512 answer tokens = ~3,660 < 4096.
  Cloud models could take more; kept equal at first so behaviour is the same for every provider.
- `backend/main.py` - include the new router.
- `backend/database/import_pkos.py` - copy `conversations` and `messages` (remapping user ids like the other tables).
- `backend/eval_graph.py` / tests - unchanged behaviour for single questions (regression check).

## 7. Frontend changes

New files:
- `frontend/src/lib/conversationsApi.js` - list, get, create, rename, delete.
- `frontend/src/components/ChatList.jsx` - "New chat" button and the list (title, relative date); rename inline;
  delete with a confirmation; highlights the open chat.

Changed files:
- `frontend/src/components/Dashboard.jsx`
  - holds `conversationId`; opening a chat loads its messages, including sources and graph for X-Ray.
  - `handleSend` sends `conversation_id`; handles the `conversation`, `rewrite` and `saved` events; a new chat appears
    at the top of the list as soon as the `conversation` event arrives.
  - under each question: "Searched for: ..." when the standalone question differs from what was typed.
  - the last open chat is remembered per user (localStorage, a convenience only; the server is the truth).
- `frontend/src/components/VaultView.jsx` - the left panel gets two tabs, "Documents" and "Chats" (decision Q1).

## 8. Privacy and safety

- Chats are stored in the same local Postgres as the documents and are included in backups and the import tool.
- With a cloud provider, recent turns are now sent along with each question (before: only the question and the
  passages). The provider settings page says so in one line.
- Diagnostics report counts only (number of conversations/messages), never content.
- Deleting a chat deletes its messages (cascade); deleting the user deletes everything.

## 9. Work plan, step by step (one step per turn)

| Step | Work | Done when |
|---|---|---|
| 1 | Migration 0003, `conversations_db.py`, `routes_conversations.py` | API tests: create/list/get/rename/delete, paging, another user's chat gives 404 |
| 2 | `/query/stream` saves both messages; `conversation` and `saved` events; partial/error status | Tests: messages saved in order, disconnect saves `partial`, old clients without `conversation_id` still work |
| 3 | STM: `build_history`, citation stripping, prompt with history | Unit tests for budget, order, stripping; a follow-up answer uses the earlier turn (test with a fake provider) |
| 4 | Query rewriting with `needs_search`, fallback, `rewrite` event | Unit tests for parsing and fallbacks; small evaluation: 15 follow-up questions on the test fixtures, the right passage found with vs without rewriting |
| 5 | Running summary in the background | Tests: summary written after N turns, failure keeps the old one, never delays the answer |
| 6 | Frontend: chat list, opening chats, "Searched for", X-Ray restored | Component tests; checked in the browser |
| 7 | Import tool, docs (03_ARCHITECTURE, README), packaged app check, version 0.5.0 | Packaged app: two chats, restart, follow-ups still understood |

Each step ends with all tests and lint passing and its own commit.

## 10. Part B - long-term memory (outline, built after Part A)

- **Table `memories`:** `memory_id`, `user_id`, `text` (<= 300 characters), `embedding vector(384)`, `kind`
  (`fact` about the user | `preference` | `conclusion` from a chat), `origin` (`manual` | `suggested`), `source_conversation_id`,
  `created_at`, `updated_at`, `last_used_at`, `use_count`.
- **Adding memories:** a "Remember this" action on any message, and a Memory page in Settings to add, edit, delete and
  switch memory off. Later: after a chat the AI *suggests* memories and the user confirms each one - never silent writes.
- **Using memories:** per question, the 3 closest memories within a distance limit (pgvector, same embedder), shown to the
  model under "ABOUT THE USER" in the system message - separate from CONTEXT and never citable as a document - and listed
  in the X-Ray panel so the user sees which memories were used.
- **Episodic memory:** each conversation's running summary is embedded, so "what did we conclude about X last week?"
  can find the right past chat.
- **Why Part A prepares it:** summaries already exist per conversation; memories hang off `user_id` and optionally a
  conversation; the prompt builder already has a separate slot for non-document context.

## 11. Decisions (2026-11-23)

- Q1 Chat list: a **"Chats" tab in the left panel**, next to the documents, with a "New chat" button.
- Q2 Rewriting: **every follow-up** is rewritten when the chat has history (the first question never is). Reliability
  over ~1-3 s of extra time on a local model; "Searched for" keeps it visible.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Small local models rewrite badly | Schema-constrained JSON, validation, fallback to the original, "Searched for" shown to the user, evaluation in step 4 |
| Extra latency from the rewrite | Skipped on the first turn; 8 s cap; token budget 120 |
| History leads the model to answer from memory instead of documents | Explicit rule in the system prompt; citations still required; history answers stripped of citations |
| Prompt overflow on 4096-token models | Fixed character budgets (section 6), history trimmed first, never the documents |
| Long chats get slow to load | Messages loaded per chat; list paged; graph JSON capped |
