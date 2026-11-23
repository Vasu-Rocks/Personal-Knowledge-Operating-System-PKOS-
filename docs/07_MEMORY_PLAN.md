# 07 - Conversation memory: sessions, short-term memory (STM), long-term memory (LTM)

Status: Part A (sessions + STM) built, 2026-11-23, in version 0.5.0 (all 7 steps of section 9; results under steps 4
and 5). Part B (LTM) is planned in section 10 (decisions Q3-Q5 in section 11) and built step by step, B1 to B6.

Deviations from the plan as written: users keep their IDs in the import tool, so chats are copied without remapping;
the diagnostics report holds no database content at all, so there were no chat counts to add; the citation rule's
fixed example was replaced by examples from the context (found while checking step 6 in the app).

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

### Step 4 results (2026-11-23, `backend/eval_followups.py`, llama3.2 3B on CPU, bge-small embeddings)

20 short passages, 8 of them deliberate look-alikes (another glacier, the old sensors, last year's budget...);
15 follow-ups after a one-turn chat; "reaches the answer" = in the top 3 *and* under PKOS's 0.35 distance cutoff.

| | as typed | rewritten |
|---|---|---|
| right passage ranked first | 10/15 | 13/15 |
| right passage reaches the answer | **0/15** | **14/15** |
| "shorter / bullet list / simpler / translate" judged as no search | - | 4/4 |
| new-topic follow-ups judged as needing search | - | 2/2 |
| rewrite time (model loaded) | - | median 1.3 s, max 1.5 s |

What the first run changed: the timeout went from 8 to 20 s (a model that must load first took 8.0 s and fell back,
although that load is needed for the answer anyway); the prompt gained a translate example and a rule against joining a
new topic to the old one (one rewrite had produced "the ice loss measurements in the 2024 budget"); and a follow-up
whose search finds nothing now keeps the previous turn's passages instead of ending in "I cannot find the answer".

### Step 5 results (2026-11-23, llama3.2 3B on CPU)

Turns are folded when they no longer fit the history window (by turns or characters), oldest first, at most 10 per
update, in a background task after a complete answer; a failed update keeps the old summary and is retried after the
next answer; a summary is only saved over the version it was built from.

Check on a made-up 11-turn chat folded in 4 rounds: the first prompt produced a transcript ("The user asked... The
assistant found..."), 627 -> 924 characters after two rounds, which would have hit the 1200 cap and been cut. After
asking for a summary rather than a transcript, a target of 80% of the cap and older parts compressed first (plus one
"shorten" call before any cut), the 4 rounds gave 366 / 511 / 678 / 814 characters, all 9 checked facts kept (names,
amounts, dates), nothing invented, 3-4 s per round.

## 10. Part B - long-term memory (plan, 2026-11-23)

### 10.1 Goal and rules

PKOS remembers what matters across chats, and the user stays in control of every word it remembers.

Two kinds of long-term memory:
- **Memories** - short statements about the user: facts ("I am preparing for the GATE exam in February"), preferences
  ("answer in short bullet points"), and conclusions the user chose to keep ("we decided to order the Campbell sensors").
- **Past chats (episodic memory)** - every chat gets a short recap with an embedding, so "what did we conclude about
  the sensors last week?" can find the right earlier chat.

Rules that hold in every step:
1. **Nothing is remembered silently.** A memory exists only because the user added it, or confirmed a suggestion.
2. **Memories are visible and editable.** One page lists all of them; each can be edited, deleted, or all switched off.
3. **Documents stay the source of facts about the documents.** Memories tell the model about the user and how to
   answer. A question about the user themselves ("when is my exam?") may be answered from a memory, and the answer then
   says it comes from their saved memories (decision Q5). Memories are shown to the model in their own section, never
   as a document passage, and are never cited as one.
4. **The user sees what was used.** Every answer lists the memories and past chats it was given (X-Ray panel).
5. **One user's memories never reach another user** (every query scoped by user_id, tested like documents and chats).

### 10.2 Data model (migration `0004_memories.sql`)

```sql
CREATE TABLE memories (
    memory_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    text VARCHAR(300) NOT NULL,
    kind VARCHAR(12) NOT NULL CHECK (kind IN ('fact', 'preference', 'conclusion')),
    origin VARCHAR(10) NOT NULL CHECK (origin IN ('manual', 'suggested')),
    status VARCHAR(10) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'pending')),  -- pending = suggestion
    embedding vector(384),
    source_conversation_id UUID REFERENCES conversations(conversation_id) ON DELETE SET NULL,
    source_message_id UUID REFERENCES messages(message_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    use_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX memories_user_idx ON memories(user_id, status);

CREATE TABLE user_memory_settings (
    user_id UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT true,          -- use memories and past chats in answers
    suggest BOOLEAN NOT NULL DEFAULT true           -- let PKOS propose memories (still confirmed one by one)
);

ALTER TABLE conversations ADD COLUMN recap TEXT;               -- summary, or the turns of a short chat
ALTER TABLE conversations ADD COLUMN recap_embedding vector(384);
ALTER TABLE messages ADD COLUMN memories_used JSONB;            -- assistant: [{memory_id, text}] given to the model
```

Notes: a few hundred memories per user at most, so a sequential scan filtered by user_id is fast and no vector index is
needed. Deleting a chat keeps memories made from it (the link becomes empty). The embedding is computed on every save
and edit with the same bge-small model as the documents.

### 10.3 Adding memories

- **Memory page (Settings):** list grouped by kind, add, edit, delete, delete all, switch memory on/off, switch
  suggestions on/off; shows where a memory came from (a chat, or "added by you") and when it was last used.
- **"Remember this" on a message:** on any question or answer. Opens a small editor prefilled with the text (cut to
  300 characters) and a kind chosen by PKOS's guess; the user edits and saves. Nothing is saved without that click.
- **Suggestions (step B5):** after a chat's running summary is updated, PKOS may propose up to 2 memories from the
  turns it just folded, only facts about the user or stated preferences. They are stored as `pending` and appear as a
  small "Remember this? Keep / Edit / Dismiss" bar in that chat; pending memories are never used in answers. A dismissed
  suggestion is deleted. A suggestion that matches an existing memory (distance < 0.15) is dropped.

### 10.4 Using memories in an answer

Per question, after the follow-up rewrite (the standalone question is the search text):
1. **Preferences are always included** (they are instructions about the answers), newest first, at most 5.
2. **Facts and conclusions by similarity:** the 3 closest active ones with cosine distance < 0.40 (tuned in B2, see
   "Step B2 results"; 0.45 was the first guess).
3. Together at most 600 characters; whatever is used gets `last_used_at` / `use_count` updated and is stored on the
   answer (`memories_used`).
4. In the prompt: a section in the system message, *outside* CONTEXT:
   `ABOUT THE USER (notes the user saved; use them to understand the question and to shape the answer; a question about
   the user may be answered from them, saying "from your saved memories"; never a source of facts about the documents,
   never cited as [Chunk N])`. Rule 1 ("I cannot find the answer in your documents") is reworded to allow that case.
   The shortcut that answers "I cannot find..." without calling the model when no passage is found now applies only
   when no memory was selected either.
5. A new SSE event `{"type":"memories","memories":[{memory_id, text, kind}]}` before `sources`; the X-Ray panel lists
   them under "Memories used".

### 10.5 Past chats (episodic memory, step B3)

- **Recap per chat:** the running summary when there is one, otherwise the chat's first turns (questions and the
  start of the answers, at most 800 characters), plus the title. Re-embedded after every complete answer (embedding
  only, no model call, ~20 ms). The chat being asked in is never its own past chat.
- **When it is searched:** only when the question refers to earlier conversations ("last time", "we discussed",
  "earlier chat", "what did we conclude", "previously", "you told me" ... a transparent keyword list like the one for
  broad questions), or when the rewrite marks it. Ordinary questions never pull in old chats, so they cannot add noise.
- **How it is used:** the best 1-2 past chats under a distance limit become context blocks labelled
  `[Chunk N] Earlier chat: "<title>" (<date>)`, inside the normal 6000-character CONTEXT budget, so they can be cited and
  appear in the sources list (shown as a chat, clicking opens that chat). The prompt rule for them: they record what was
  said before, not what the documents say.

### 10.6 Prompt budget (llama3.2, num_ctx 4096)

rules ~1200 + documents (and past chats) 6000 + graph 1800 + history 2400 + summary 1200 + memories 600 = 13,200
characters, about 3,300 tokens, plus a 512-token answer: ~3,810 of 4,096. Past chats take their room from the documents
budget, not on top of it. If real prompts run long, history is trimmed first (it is the most redundant with the summary).

### 10.7 Backend changes

New: `database/migrations/0004_memories.sql`, `database/memories_db.py` (CRUD, similarity search, usage update,
settings), `api/routes_memories.py` (`GET/POST /memories`, `PATCH/DELETE /memories/{id}`, `DELETE /memories`,
`POST /memories/{id}/confirm`, `GET/PUT /memories/settings`), `rag/memory/ltm.py` (select memories for a question,
format the prompt section), `rag/memory/episodic.py` (recap building, past-chat trigger and search),
`rag/memory/suggest.py` (B5), `eval_memories.py`.

Changed: `routes_query.py` (memories and past chats per question, `memories` event, `memories_used` saved),
`prompt_builder.py` (ABOUT THE USER section and the past-chat rule), `summary.py` (refresh the recap, then suggest),
`import_pkos.py` (memories and settings), `core/config.py` (limits).

### 10.8 Frontend changes

New: `components/memory/MemoryPage.jsx` (in Settings), `components/memory/RememberDialog.jsx`,
`components/memory/SuggestionBar.jsx` (B5), `lib/memoriesApi.js`.
Changed: `Dashboard.jsx` ("Remember this" on messages, `memories` event, X-Ray "Memories used", past-chat sources
that open the chat), `SettingsView.jsx` (Memory section), `CloudKeyForm.jsx` (memories are sent to a cloud provider too).

### 10.9 Privacy and safety

- Memories live in the local database, in backups and in the import tool, like chats.
- With a cloud provider the memories used for a question are sent with it; the notice says so.
- Switching memory off stops their use at once and keeps them; "delete all" removes them (with a confirmation).
- A memory text is limited to 300 characters and cleaned like a question (no prompt fences such as `===`).
- Suggestions only come from the user's own chats and are inert until confirmed.

### 10.10 Work plan, step by step (one step per turn)

| Step | Work | Done when |
|---|---|---|
| B1 | Migration 0004, `memories_db.py`, `/memories` API (CRUD, confirm, settings), embedding on save | API tests incl. isolation between users, 300-character limit, edit re-embeds, delete all |
| B2 | Use memories in answers: selection, prompt section, `memories` event, `memories_used`, usage counts, on/off | Unit and API tests; evaluation with the real embedder (right memory chosen, unrelated ones left out, cutoff tuned); a preference followed by llama3.2 |
| B3 | Past chats: recap and embedding, trigger words, past-chat context blocks | Tests; evaluation: "what did we conclude about X" finds the right chat, ordinary questions pull in none |
| B4 | Frontend: Memory page, "Remember this", X-Ray "Memories used", past-chat sources | Component tests; checked in the dev app |
| B5 | Suggestions: proposed after summary updates, pending until confirmed, suggestion bar | Tests; quality check on llama3.2 (no suggestions from ordinary document questions, sensible ones from "I am a beginner, keep it simple") |
| B6 | Import tool, docs, cloud notice, version 0.6.0, packaged app check | Packaged app: memories survive a restart and an upgrade from 0.5.0 data |

### Step B2 results (2026-11-23, `backend/eval_memories.py`, bge-small; llama3.2 3B for the answers)

Distance cutoff, 10 memories, 10 questions a memory should help with, 10 unrelated questions, 6 first-person document
questions ("summarise my notes on..."):

| cutoff | right memory found | unrelated given a memory | first-person document questions given a memory |
|---|---|---|---|
| 0.35 | 7/10 | 0/10 | 1/6 |
| **0.40** (chosen) | **8/10** | **0/10** | **1/6** |
| 0.45 (planned) | 8/10 | 2/10 | 2/6 |
| 0.50 | 10/10 | 3/10 | 5/6 |

The two misses at 0.40 are short personal questions ("Where do I live?", "Suggest a dinner recipe I can eat", both
0.48). A looser cutoff for first-person questions was rejected: at 0.50 it gives memories to 5 of 6 document questions.

Answers on llama3.2 (3 runs each, temperature 0.1): a preference was followed 3/3 (bullet lists); "When is my exam?"
answered from the memory 3/3; an unrelated memory was never mixed into a document answer 3/3; a document question with no
answer in the passages was still refused 3/3 although a memory was present. Asked to say "From your saved memories",
the model did so 0/3, even as a MUST rule, so the app shows that label itself: the `memories` event carries
`memories_only` (no document passage was used). Found in passing, not caused by memories: "Summarise my notes on
photosynthesis" is refused 3/3 *without* any memory too - the strict "exact answer" rule makes the 3B model refuse
summary requests.

Fixed right after (rule 1 kept, one sentence added: summarise/explain/list/overview requests about something the
CONTEXT covers are not refused). On 10 answerable and 5 unanswerable questions, 3 runs each: current rule 26/30
answered, 15/15 refused; added sentence **30/30 answered, 15/15 refused**. Two rewordings that replaced the rule did
worse (28/30 and 21/30, one 9/30). With memories: the photosynthesis summary 3/3 answered without a memory and 2/3 with
an unrelated one (both 0/3 before); the other memory checks unchanged.

### 10.11 Risks

| Risk | Mitigation |
|---|---|
| A wrong or outdated memory steers answers | Visible "Memories used" per answer; easy edit/delete; never silent writes |
| Memories treated as document facts | Separate section, explicit rule, not citable; tested in the prompt |
| Irrelevant memories add noise | Similarity cutoff tuned by evaluation; at most 3 facts; preferences capped at 5 |
| Old chats pulled into unrelated questions | Past chats searched only on explicit references |
| Small models suggest junk memories | Only facts and preferences the user states about themselves (never document content), at most 2 per update, pending until confirmed, duplicates dropped, can be switched off |
| Prompt overflow | Fixed budgets (10.6); past chats inside the documents budget |

## 11. Decisions (2026-11-23)

- Q1 Chat list: a **"Chats" tab in the left panel**, next to the documents, with a "New chat" button.
- Q2 Rewriting: **every follow-up** is rewritten when the chat has history (the first question never is). Reliability
  over ~1-3 s of extra time on a local model; "Searched for" keeps it visible.

Part B (2026-11-23):
- Q3 Suggestions: **yes** - PKOS proposes at most 2 memories at a time from facts and preferences the user states about
  themselves; each waits for Keep / Edit / Dismiss; can be switched off (step B5 stays).
- Q4 Past chats: **only when the question refers to earlier conversations**; ordinary questions never pull in old chats.
- Q5 Memory facts: **may answer questions about the user**, and the answer says it came from saved memories; questions
  about documents still need the documents.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Small local models rewrite badly | Schema-constrained JSON, validation, fallback to the original, "Searched for" shown to the user, evaluation in step 4 |
| Extra latency from the rewrite | Skipped on the first turn; 8 s cap; token budget 120 |
| History leads the model to answer from memory instead of documents | Explicit rule in the system prompt; citations still required; history answers stripped of citations |
| Prompt overflow on 4096-token models | Fixed character budgets (section 6), history trimmed first, never the documents |
| Long chats get slow to load | Messages loaded per chat; list paged; graph JSON capped |
