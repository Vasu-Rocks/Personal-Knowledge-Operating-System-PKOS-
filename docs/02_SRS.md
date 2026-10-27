# PKOS — Software Requirements Specification (SRS)

| Field | Value |
|---|---|
| Document | 02 — SRS |
| Version | 1.0 (baseline from code inspection, 2026-10-23) |
| Scope | Backend API (FastAPI), RAG/Graph pipeline, React frontend |
| Related | [01_PRD](01_PRD.md) · [03_Architecture](03_ARCHITECTURE.md) · [04_UI_UX](04_UI_UX.md) · [05_Dev_Plan](05_DEVELOPMENT_PLAN.md) |

Requirement keywords: **SHALL** = mandatory, **SHOULD** = recommended, **MAY** = optional.
Each requirement has a status: ✅ implemented · 🟡 partial · ❌ not implemented. Every requirement is written so it can be verified by a test or a manual check.

---

## 1. Introduction

### 1.1 Purpose
Defines what PKOS must do and the constraints it must respect, so that development and testing can proceed without guessing. It reflects the code as of 2026-10-23 and marks the gaps that remain.

### 1.2 Definitions
| Term | Meaning |
|---|---|
| Chunk | A ≤1,200-character text segment of a document page, with a 384-d embedding. |
| Distance | pgvector cosine distance (`<=>`); 0 = identical, 2 = opposite. |
| Entity / Node | A concept extracted by the LLM (name, category, description, embedding). |
| Relationship / Edge | Directed `source —PREDICATE→ target` link between two entities with a weight. |
| Community | A Louvain cluster of entities with an LLM-generated title and summary. |
| Seed entity | An entity whose embedding is close to the query embedding. |
| Provider | LLM backend used for answering: `ollama` (default), `openai`, `anthropic`. |

## 2. Overall description

### 2.1 User roles and permissions

PKOS has exactly two roles. There is no administrator role.

| Role | Description | Permissions |
|---|---|---|
| **Anonymous visitor** | Not logged in | `POST /register`, `POST /login`, `GET /health`. Nothing else. |
| **Authenticated user** | Holds a valid JWT | Full CRUD on **own** documents; query **own** knowledge base; trigger clustering/summarisation of **own** graph; read **own** profile. No access to any other user's data. |

**Permission matrix**

| Action | Anonymous | User (own data) | User (other's data) |
|---|---|---|---|
| Register / login | ✅ | n/a | n/a |
| View profile `/me` | ❌ 401 | ✅ | ❌ |
| List documents | ❌ 401 | ✅ | ❌ (never returned) |
| Upload document | ❌ 401 | ✅ | n/a |
| Delete document | ❌ 401 | ✅ | ❌ 400/404 |
| Query | ❌ 401 | ✅ | ❌ (never retrieved) |
| Graph cluster / summarise | ❌ 401 | ✅ | ❌ (must not process — see FR-GR-09) |

### 2.2 Operating environment
- Backend: Python 3.11+, FastAPI, Uvicorn, asyncpg, PostgreSQL 15+ with `pgvector` (HNSW support ≥ 0.5.0).
- Embeddings: `sentence-transformers` with `BAAI/bge-small-en-v1.5` on CPU.
- LLM: Ollama at `localhost:11434` (default model `llama3.2`); optional OpenAI / Anthropic.
- Frontend: React 19 + Vite 8, served at `http://localhost:3000`; modern Chromium/Firefox/Safari desktop.

### 2.3 Constraints
- C1. Default configuration SHALL make no network calls to non-localhost hosts with user content.
- C2. Must run on a 16 GB RAM machine without a GPU (slow but functional).
- C3. Embedding dimension is fixed at 384; changing the model requires re-embedding all data.

---

## 3. Functional requirements

### 3.1 Authentication (AUTH)

| ID | Requirement | Status |
|---|---|---|
| FR-AUTH-01 | The system SHALL allow registration via `POST /api/v1/register` with JSON `{email, username, name, password}`. | ✅ |
| FR-AUTH-02 | On successful registration the system SHALL return `{access_token, token_type:"bearer"}` so the user is logged in immediately. | ✅ |
| FR-AUTH-03 | The system SHALL reject an email that lacks `@` or whose domain part lacks `.` with HTTP 400 "Invalid email address syntax…". | ✅ |
| FR-AUTH-04 | The system SHALL trim the username and reject an empty username with HTTP 400. | ✅ |
| FR-AUTH-05 | The system SHALL reject an already-registered email (400 "Email is already registered") and an already-taken username (400 "Username is already taken"). | ✅ |
| FR-AUTH-06 | If a unique-constraint race occurs on insert, the system SHALL return HTTP 409. | ✅ |
| FR-AUTH-07 | Passwords SHALL be hashed with bcrypt (random salt); plaintext SHALL never be stored or logged. | ✅ |
| FR-AUTH-08 | Passwords longer than 71 UTF-8 bytes SHALL be rejected at registration (400 "Password is too long.") and SHALL fail verification at login. | ✅ |
| FR-AUTH-09 | Passwords SHALL be at least 8 characters. | ❌ |
| FR-AUTH-10 | Login via `POST /api/v1/login` (form-encoded `username`, `password`) SHALL accept either email or username in the `username` field (email looked up first). | ✅ |
| FR-AUTH-11 | Invalid login SHALL return 401 with a generic message that does not reveal whether the account exists. | ✅ |
| FR-AUTH-12 | Access tokens SHALL be HS256 JWTs with `sub` = user UUID and `exp` = issue time + 30 days. | ✅ |
| FR-AUTH-13 | The JWT signing secret SHALL be read from an environment variable (`PKOS_SECRET_KEY`); the API SHALL refuse to start if it is unset outside dev mode. | ❌ (hard-coded) |
| FR-AUTH-14 | `GET /api/v1/me` SHALL return `{user_id, email, username, name}` and SHALL NOT return the password hash. | ✅ |
| FR-AUTH-15 | Every protected endpoint SHALL return 401 with `WWW-Authenticate: Bearer` when the token is missing, malformed, expired, or references a non-existent user. | ✅ |
| FR-AUTH-16 | Usernames SHOULD be restricted to `[A-Za-z0-9_.-]{3,32}`; name SHOULD be 1–100 chars after trimming. | ❌ |
| FR-AUTH-17 | Login SHOULD be rate-limited (e.g., 10 failed attempts / 15 min per identifier). | ❌ |

### 3.2 Document ingestion (ING)

| ID | Requirement | Status |
|---|---|---|
| FR-ING-01 | `POST /api/v1/upload` (multipart field `file`) SHALL accept files with extensions `pdf, txt, md, py, js` (case-insensitive). | ✅ |
| FR-ING-02 | Files without an extension SHALL be rejected with 400 "File must have an extension."; other extensions with 400 "File extension 'x' is not supported." | ✅ |
| FR-ING-03 | Files larger than 50 MB (measured from the actual stream, not the header) SHALL be rejected with 413. | ✅ |
| FR-ING-04 | The system SHALL create a `documents` row (new UUID, owner, filename, `created_at`, `extraction_status='PENDING'`) before processing chunks. | ✅ |
| FR-ING-05 | PDFs SHALL be extracted page by page (1-based page numbers), skipping empty pages. Text/code files SHALL be decoded as UTF-8 (invalid bytes ignored) and treated as page 1. | ✅ |
| FR-ING-05a | For PDFs of 8+ pages, lines repeated at the top or bottom (first/last 3 lines) of at least max(4, 8%) of pages (running heads, publisher footers) and bare page numbers at page edges SHALL be removed before cleaning. Pages with fewer than 12 non-empty lines, bare section numbers (`2.1`) and notebook prompts (`In[1]:`) are never treated as headers. | ✅ |
| FR-ING-06 | Cleaning SHALL apply NFKD normalisation, remove control characters, and collapse 3+ newlines to 2. For `.py/.js`, indentation SHALL be preserved. For other types, hyphenated line breaks SHALL be joined and runs of spaces/tabs collapsed. | ✅ |
| FR-ING-07 | Pages whose cleaned text is shorter than 50 characters SHALL be skipped. | ✅ |
| FR-ING-08 | Text SHALL be split with a recursive splitter: chunk size 1,200 chars, overlap 200, separators `\n\n`, `\n`, `.`, ` `, ``. Chunks SHALL NOT span pages. | ✅ |
| FR-ING-09 | Chunks SHALL be embedded in batches of 32 with `bge-small-en-v1.5`, L2-normalised, float32, 384-d, in a thread pool (not on the event loop). | ✅ |
| FR-ING-10 | Each chunk SHALL be stored with `doc_id`, `page_number`, `text_content`, `embedding`. | ✅ |
| FR-ING-11 | If any step fails, the system SHALL delete the partially created document (cascading its chunks) and return 500. | ✅ |
| FR-ING-12 | The success response SHALL include `document_id`, `filename`, `total_chunks_processed`. | ✅ |
| FR-ING-13 | After vector indexing, the system SHALL start graph extraction in the background (FR-GR-01). | ✅ |
| FR-ING-14 | Error responses SHALL NOT include raw exception text; they SHALL include a stable error code and user-safe message, and the detail SHALL be logged server-side. | ❌ (returns `str(e)`) |
| FR-ING-15 | URLs in text SHOULD be preserved (currently replaced by `[URL]`). | ❌ |
| FR-ING-16 | A document with zero indexable chunks (e.g., scanned PDF) SHALL be reported to the user as "No extractable text" rather than silently stored empty. | ❌ |
| FR-ING-17 | Vector indexing SHOULD run in the background and the upload endpoint SHOULD return 202 immediately with the `document_id`. | ❌ (synchronous) |

### 3.3 Document management (DOC)

| ID | Requirement | Status |
|---|---|---|
| FR-DOC-01 | `GET /api/v1/documents` SHALL return only the caller's documents, newest first, as `{documents:[{doc_id, filename, timestamp}]}`. | ✅ |
| FR-DOC-02 | The document list SHALL also include the graph job state: `graph_status` (`PENDING`/`PROCESSING`/`PAUSED`/`COMPLETED`/`FAILED`), `graph_processed`, `graph_total`, `graph_error`. | ✅ (no `chunk_count` / index status yet) |
| FR-DOC-03 | `DELETE /api/v1/documents/{doc_id}` SHALL delete only if the document belongs to the caller; otherwise return 404 "Document not found." (currently 400 "…or access denied"). | 🟡 |
| FR-DOC-04 | Deleting a document SHALL cascade to its chunks and junction rows; entities no longer referenced by any chunk SHALL be deleted (DB trigger), which cascades their relationships. | ✅ |
| FR-DOC-05 | After deletion, communities whose members no longer exist SHOULD be marked stale or deleted. | ❌ |
| FR-DOC-06 | An invalid UUID in the path SHALL return 422/404, not 500. | 🟡 (raises ValueError → 400) |

### 3.4 Query & answer generation (QRY)

| ID | Requirement | Status |
|---|---|---|
| FR-QRY-01 | `POST /api/v1/query/stream` with `{query}` SHALL respond with `text/event-stream`. | ✅ |
| FR-QRY-02 | `query` SHALL be 1–1,000 characters after trimming; empty → 400, >1,000 → 422. | ✅ |
| FR-QRY-03 | The query SHALL be embedded with the BGE query instruction prefix `"Represent this sentence for searching relevant passages: "`. | ✅ |
| FR-QRY-04 | Chunk retrieval SHALL return at most **k = 3** of the caller's chunks with cosine distance **< 0.35**, ordered by ascending distance, each with `filename, page, text, distance`. | ✅ |
| FR-QRY-05 | Graph retrieval SHALL run concurrently with chunk retrieval (FR-GR-06). | ✅ |
| FR-QRY-06 | The SSE stream SHALL emit, in order: one `{"type":"sources","sources":[…]}` event, one `{"type":"graph","data":{nodes,links}}` event, zero or more `{"type":"token","content":"…"}` events, then the literal `data: [DONE]`. | ✅ |
| FR-QRY-07 | If no chunks and no graph nodes are found, the system SHALL NOT call the LLM and SHALL stream the single token "I cannot find the answer in your documents." | ✅ |
| FR-QRY-08 | The chunk context SHALL be capped at `CONTEXT_MAX_CHARS` (default 6,000) and the graph context at `GRAPH_CONTEXT_MAX_CHARS` (default 1,800); each chunk SHALL be labelled `[Chunk N]` (1-based, same order as the `sources` event) with filename and page, and `sources` SHALL contain only the chunks that fit the budget. | ✅ |
| FR-QRY-09 | The system prompt SHALL instruct the model to answer only from context, to output exactly "I cannot find the answer in your documents." if the answer is absent, and to cite as `[Chunk N]` or `[Graph Entity: Name]`. | ✅ |
| FR-QRY-10 | Runs of 3+ `=` characters SHALL be stripped from the user query to protect the context delimiters. | ✅ |
| FR-QRY-11 | Provider selection SHALL come from request headers `X-LLM-Provider` (`ollama`\|`openai`\|`anthropic`, default `ollama`), `X-Ollama-Model` (default `llama3.2`), `X-OpenAI-Key`, `X-Anthropic-Key`. | ✅ |
| FR-QRY-12 | Ollama generation SHALL use temperature 0.1, top_p 0.9, `num_predict` 512, `num_ctx` 4096, `keep_alive` 15m. | ✅ |
| FR-QRY-13 | OpenAI SHALL use `gpt-4o-mini`; Anthropic SHALL use `claude-3-haiku-20240307`, `max_tokens` 1024. Model names SHOULD be configurable. | 🟡 |
| FR-QRY-14 | If a cloud provider is selected without a key, the stream SHALL emit a token explaining the key is missing, then `[DONE]`. | ✅ |
| FR-QRY-15 | LLM connection failure, timeout (120 s), or non-200 status SHALL be reported to the user as a token starting with "System Error:" and logged. | ✅ |
| FR-QRY-16 | Errors before streaming starts SHALL return HTTP 500 "Internal RAG Engine Execution Error." | ✅ |
| FR-QRY-17 | The non-streaming `POST /api/v1/query` SHALL honour the same provider headers as the streaming endpoint, or be removed. | ❌ (Ollama only) |
| FR-QRY-18 | API keys received in headers SHALL NOT be logged or persisted server-side. | ✅ (verify in tests) |
| FR-QRY-19 | Multi-turn: the client MAY send up to the last 6 messages; the server SHOULD include them as conversation history while still retrieving fresh context. | ❌ |

### 3.5 Graph RAG (GR)

| ID | Requirement | Status |
|---|---|---|
| FR-GR-01 | After upload, a `graph_jobs` row SHALL be queued; a single in-process worker (`rag/graph/worker.py`) claims `PENDING` jobs (`FOR UPDATE SKIP LOCKED`), sets `PROCESSING`, and processes the document's un-extracted chunks in `chunk_id` order, checkpointing `document_chunks.graph_extracted_at` and `processed_chunks` per chunk. | ✅ |
| FR-GR-02 | For each chunk the system SHALL call Ollama `/api/chat` with a bounded JSON schema (`entities` 1–12 `[name, category∈fixed enum, description]`, `relationships` 0–12 `[source, predicate, target]`), temperature 0, `num_ctx` 2048, `num_predict` 1024, timeout 180 s, including the last 150 chars of the previous chunk for pronoun resolution only. | ✅ |
| FR-GR-03 | Invalid JSON for a chunk SHALL be logged and skipped without failing the document. | ✅ |
| FR-GR-03a | Entities and relationship endpoints whose name does not occur in the chunk text (or its pronoun context) SHALL be discarded before reconciliation (prompt-example leakage / hallucination guard). | ✅ |
| FR-GR-04 | Reconciliation SHALL, in one transaction per chunk: upsert entities by `(user_id, canonical_name)` where `canonical_name` is the squashed name (lower-case, only letters/digits/`+`/`#`, so `tf-idf`, `tf–idf`, `TF_IDF` and `tf idf` are one entity; `C` and `C++` stay distinct), link each entity to the chunk in `chunk_entity_junction`, and upsert relationships by `(user_id, source, target, predicate)`, recording each supporting chunk in `relationship_mentions`; `weight` = number of supporting chunks (re-processing a chunk is idempotent). | ✅ |
| FR-GR-05 | Relationship endpoints missing from the chunk's entity list SHALL be created as entities (category `OTHER`); self-loops, names with no letter/digit or > 100 chars, and noise entities (single letters other than C/R, `x`/`y` data variables such as `X_train`, module aliases such as `plt`, figure/table/chapter references) SHALL be discarded. | ✅ |
| FR-GR-20 | Predicates SHALL be constrained to a 16-value vocabulary at extraction time (JSON-schema enum) and normalised through `rag/graph/vocab.py` (e.g. `IS_USED_BY` becomes `USES` with source and target swapped); unknown legacy predicates are kept. | ✅ |
| FR-GR-21 | `python graph_maintenance.py [--apply]` SHALL re-key, merge duplicates, remove noise entities and normalise predicates on existing graphs (dry run by default; `--apply` first creates `*_bak_<timestamp>` copies of the graph tables and runs in one transaction; communities are marked stale). | ✅ |
| FR-GR-06 | On completion the status SHALL be `COMPLETED`; on any unhandled error `FAILED`. | ✅ |
| FR-GR-07 | Query-time graph retrieval (G4, `GRAPH_LOCAL_EXPANSION`, default on) SHALL pick up to 5 seed entities (exact canonical-name matches of query n-grams first, max 3, then nearest by embedding with distance < 0.35), rank their incident edges by `weight × seed score` with a per-seed cap, return up to 20 edges as `{nodes:[{id,name,category,description,isPrimarySeed?}], links:[{source,target,predicate,description,weight}]}`, and add up to 2 extra chunks (`via:"graph"`, distance < 0.45) that mention a seed or support a selected edge and were not returned by vector search; candidates are ranked round-robin across documents (each document's best chunk before any document's second-best) so one book cannot crowd out the others. With the flag off, the pre-G4 behaviour (2 seeds, 20 edges) applies. | ✅ |
| FR-GR-19 | Every source returned to the client SHALL carry `via` (`vector` or `graph`) and `chunk_id`. | ✅ |
| FR-GR-08 | Seed entities with no edges SHALL still be included in the prompt context and in the UI graph. | 🟡 (prompt: done via `=== KNOWLEDGE GRAPH ENTITIES ===`; UI still hides them) |
| FR-GR-09 | `POST /api/v1/graph/cluster` SHALL run Louvain (fixed seed) on the caller's edges, with weights of parallel edges summed, and sync the caller's level-0 communities: communities of >= 3 members; a community whose member set is unchanged keeps its row and summary, the others are replaced and queued for summarisation; with no edges the caller's communities are deleted. | ✅ |
| FR-GR-10 | `POST /api/v1/graph/summarize` SHALL start a background worker that summarises **only the caller's** pending communities (summary IS NULL), embeds each summary, and stores title, summary, embedding. | ✅ |
| FR-GR-11 | Summariser SQL SHALL use bound parameters (e.g., `= ANY($1::uuid[])`), not string interpolation. | ✅ |
| FR-GR-12 | Graph extraction SHALL use the configured Ollama base URL and model (env), not a hard-coded URL. | ✅ (`core/config.py`; `OLLAMA_BASE_URL`, `OLLAMA_MODEL`) |
| FR-GR-13 | Jobs left in `PROCESSING` at server start SHALL be re-queued and resume from the last checkpoint (no chunk is extracted twice). | ✅ |
| FR-GR-16 | `POST /api/v1/graph/jobs/{doc_id}/start` (from `PAUSED`/`FAILED`) and `/pause` (from `PENDING`/`PROCESSING`) SHALL be scoped to the caller's own jobs and return 409 otherwise; a running job stops after its current chunk. | ✅ |
| FR-GR-17 | Documents that existed before the queue SHALL be backfilled as `COMPLETED` (if finished) or `PAUSED` (never auto-started). Upload accepts `?build_graph=false` to park a new job as `PAUSED`. | ✅ |
| FR-GR-18 | An Ollama/connection error SHALL mark the job `FAILED` with an error message (resumable via `/start`), and the worker SHALL back off 30 s before the next job. | ✅ |
| FR-GR-14 | Broad questions (keyword router `rag/query/router.py`: overview/summary/"what topics does the book cover"/"main themes", excluding section-specific requests such as "chapter 2") SHALL retrieve the closest community summaries (up to 3, distance < 0.5, only communities with >= 10 members; if the best match is worse than 0.36 the 3 largest communities are used instead; flag `GRAPH_GLOBAL_SEARCH`), place them first in the context as `[Chunk N]` sources with `via:"community"`, and still include the top-3 vector chunks. | ✅ |
| FR-GR-22 | When a document's graph job completes, the user's graph SHALL be flagged dirty (`graph_state`); the worker SHALL then re-cluster and summarise once none of that user's jobs are pending or running. Communities that are stale (a member entity was deleted) or unsummarised SHALL also trigger a rebuild. | ✅ |
| FR-GR-23 | `POST /api/v1/graph/rebuild` SHALL flag the caller's graph dirty and wake the worker; `GET /api/v1/graph/status` SHALL return `entities, relationships, communities, pending_summaries, stale_communities, rebuild_queued, active_jobs` for the caller. Settings shows these with a "Rebuild knowledge map" button. | ✅ |
| FR-GR-24 | `GET /api/v1/graph/lookup?term=` (1-100 chars) SHALL resolve the word to the caller's entities (exact squashed name, variant: plural/one-letter difference, whole-word contains, similar by embedding with cosine distance < 0.15; nonsense words return nothing) and return the matches plus, per book, the number of passages, page numbers, up to 10 linked concepts (supported by that book via `relationship_mentions`) and up to 2 prose excerpts centred on the word (index/table pages skipped). | ✅ |
| FR-GR-25 | `GET /api/v1/graph/connection?a=&b=` SHALL return the lowest-cost chain (<= 6 links) between the two words in the caller's graph plus up to 2 alternatives. If a word has an exact or variant match only those are used. Hubs and generic names (`Data`, `Value`, names of 2 characters or fewer) cost more to pass through. Each step lists the books mentioning the concept; each link lists the books supporting it and its passage count. The response flags `crosses_books`, `bridge_concepts`, `strong_links` (links supported by 2+ passages) and `weak` (3+ links with fewer than half strong). | ✅ |
| FR-GR-26 | Both endpoints SHALL be scoped to the caller (another user sees no matches), validate input (400 empty, 422 length) and use bound parameters. | ✅ |
| FR-GR-27 | After every community rebuild the worker SHALL recompute `entity_stats` for the user (degree; strong_degree = links whose entity pair is backed by 2+ distinct passages; PageRank; sampled betweenness, k = 300; mentions; documents; community; generic-name flag). | ✅ |
| FR-GR-28 | `GET /api/v1/graph/evidence?rel=` SHALL return the passages (book, page, excerpt centred on the two names) a relationship was extracted from; 400 for a malformed id, 404 if the relationship does not exist or belongs to another user; pre-provenance relationships return no passages and a note. | ✅ |
| FR-GR-29 | The worker SHALL suggest same-concept pairs: entities never co-occurring in a document, same category, non-generic, embedding distance < 0.10. `GET /api/v1/graph/same-concepts?status=` lists them; `POST /api/v1/graph/same-concepts/{id}` with `confirmed`/`rejected`/`suggested` records the decision. Nothing is merged; decisions survive recomputation and rejected pairs are never re-suggested; stale suggestions are removed. | ✅ |
| FR-GR-30 | `GET /api/v1/graph/bridges?limit=&category=` SHALL list concepts in 2+ documents, non-generic, by betweenness. | ✅ |

### 3.6 Frontend (FE)

| ID | Requirement | Status |
|---|---|---|
| FR-FE-01 | Unauthenticated users SHALL see the Auth screen; authenticated users the Dashboard. | ✅ |
| FR-FE-02 | The token SHALL be stored in `localStorage['pkos_token']`; on load, `/me` SHALL be called and a 401 SHALL log the user out. | ✅ |
| FR-FE-03 | The API base URL SHALL come from `VITE_API_BASE_URL` (default `http://localhost:8000`). | ❌ (hard-coded in 4 places) |
| FR-FE-04 | Upload errors and delete errors SHALL be shown to the user. | ❌ |
| FR-FE-05 | Each document row SHALL show its real status (FR-DOC-02) and poll until terminal. | 🟡 (graph status + progress + polling done; "Indexed" is still static) |
| FR-FE-06 | Each AI message SHALL keep its own `sources` **and** `graph`; selecting it SHALL show both. | 🟡 (graph is global) |
| FR-FE-07 | Citations `[Chunk N]` SHALL render as badges that scroll to source card N; `[Graph Entity: X]` SHALL focus node X. | ✅ |
| FR-FE-08 | Settings SHALL offer Ollama, OpenAI and Anthropic, store choices in `localStorage`, and show a privacy warning when a cloud provider is selected. | 🟡 (no Anthropic, no warning) |
| FR-FE-09 | Panels SHALL be resizable: left 150–500 px, right 200–600 px. | ✅ |

---

## 4. Business rules

| ID | Rule |
|---|---|
| BR-01 | A user can only ever see, query, or delete data where `user_id` = their own id. |
| BR-02 | Email and username are each globally unique (case-sensitive in current DB; SHOULD become case-insensitive). |
| BR-03 | Entities are unique per user by canonical name (lower-cased, trimmed); the same concept in two documents is one node. |
| BR-04 | Relationship weight = number of times the (source, target, predicate) triple was extracted. |
| BR-05 | An answer must be grounded: if retrieval returns nothing, the LLM is not called. |
| BR-06 | Ollama is the default provider; cloud providers are opt-in per browser and require the user's own key. |
| BR-07 | API keys for cloud providers live only in the user's browser and are sent per request; the server never stores them. |
| BR-08 | Deleting a document removes all derived data that is not shared with another of the user's documents. |
| BR-09 | Max upload size 50 MB; max query length 1,000 chars. |

## 5. Data requirements

### 5.1 Entities (PostgreSQL, created by `database/postgres_core.py::configure_unified_schema`)

| Table | Key columns | Constraints |
|---|---|---|
| `users` | `user_id UUID PK`, `email VARCHAR(255) UNIQUE NOT NULL`, `username VARCHAR(255) UNIQUE NOT NULL`, `name VARCHAR(255) NOT NULL`, `hashed_password TEXT NOT NULL` | — |
| `documents` | `doc_id UUID PK`, `user_id → users ON DELETE CASCADE`, `filename VARCHAR(255) NOT NULL`, `created_at TIMESTAMP DEFAULT now`, `extraction_status VARCHAR(50) DEFAULT 'PENDING'` | — |
| `document_chunks` | `chunk_id SERIAL PK`, `doc_id → documents ON DELETE CASCADE`, `page_number INT`, `text_content TEXT`, `embedding vector(384)` | HNSW index `vector_cosine_ops` |
| `entities` | `entity_id UUID PK`, `user_id → users CASCADE`, `name`, `canonical_name`, `category VARCHAR(50)`, `description`, `embedding vector(384)` | `UNIQUE(user_id, canonical_name)`; HNSW index |
| `relationships` | `rel_id UUID PK`, `user_id`, `source_entity_id → entities CASCADE`, `target_entity_id → entities CASCADE`, `predicate VARCHAR(100)`, `description`, `weight FLOAT DEFAULT 1.0` | `UNIQUE(user_id, source, target, predicate)`; indexes on source, target |
| `chunk_entity_junction` | `(chunk_id → document_chunks CASCADE, entity_id → entities CASCADE) PK`, `mention_snippet TEXT` | trigger `trg_delete_orphan_entities` AFTER DELETE |
| `relationship_mentions` | `(rel_id → relationships CASCADE, chunk_id → document_chunks CASCADE) PK`, `snippet TEXT` | trigger `trg_delete_orphan_relationships`: deleting the last mention deletes the edge, otherwise recomputes `weight`. Edges created before G1 have no mentions (legacy) and are never auto-deleted |
| `graph_jobs` | `doc_id UUID PK → documents CASCADE`, `user_id → users CASCADE`, `status` (`PENDING`/`PROCESSING`/`PAUSED`/`COMPLETED`/`FAILED`), `total_chunks`, `processed_chunks`, `error`, `created_at`, `updated_at` | index on `(status, created_at)`; `document_chunks.graph_extracted_at TIMESTAMPTZ` is the per-chunk checkpoint |
| `entity_stats` | `entity_id PK -> entities CASCADE`, `user_id`, `degree`, `strong_degree`, `pagerank`, `betweenness`, `mentions`, `doc_ids UUID[]`, `book_count`, `community_id -> communities SET NULL`, `is_generic`, `updated_at` | index `(user_id, pagerank DESC)`; fully rewritten per user on each rebuild |
| `concept_links` | `link_id PK`, `user_id`, `entity_a`, `entity_b` (-> entities CASCADE, `entity_a < entity_b`), `distance`, `method`, `status` (`suggested`/`confirmed`/`rejected`), `created_at`, `decided_at` | `UNIQUE(user_id, entity_a, entity_b)` |
| `communities` | `community_id UUID PK`, `user_id`, `hierarchy_level INT`, `title`, `summary`, `embedding vector(384)`, `is_stale BOOL`, `member_entities JSONB` (deprecated, no longer written) | HNSW index |
| `community_members` | `(community_id → communities CASCADE, entity_id → entities CASCADE) PK` | trigger `trg_mark_community_stale`: deleting a member flags its community `is_stale` |

### 5.2 Data rules
- DR-01 All embeddings are 384-d, L2-normalised.
- DR-02 `mention_snippet` in the junction table is currently never populated (snippet is stored on the relationship's `description`).
- DR-03 Entity `category` is free text upper-cased by the reconciler (e.g., `TECHNOLOGY`, `PERSON`); no fixed vocabulary.
- DR-04 Schema changes SHALL be applied via versioned migrations (❌ currently ad-hoc `CREATE IF NOT EXISTS` + destructive legacy drop).
- DR-05 Original uploaded files are **not** stored; only extracted chunks. Re-indexing therefore requires re-upload.

## 6. Validation summary

| Field | Rule | Where |
|---|---|---|
| email | contains `@`, domain contains `.`, ≤255 | backend ✅; `type=email` in UI ✅ |
| username | non-empty after trim, ≤255 (target: regex FR-AUTH-16) | backend 🟡 |
| name | required (target: 1–100 chars) | UI required ✅; backend trims only |
| password | ≤71 bytes ✅; ≥8 chars ❌ | backend |
| file | extension whitelist, ≤50 MB | backend ✅; UI `accept` ✅ |
| query | 1–1,000 chars | backend ✅; UI blocks empty ✅ |
| doc_id | UUID | backend 🟡 |

## 7. Error handling

| Situation | HTTP / behaviour | User-visible message |
|---|---|---|
| Missing/invalid/expired token | 401 | Frontend logs out → Auth screen |
| Validation error | 400 / 422 | Specific message from `detail` |
| Duplicate registration race | 409 | "Email or username was just taken. Please try again." |
| File too large | 413 | "File size exceeds 50MB limit." |
| Upload pipeline failure | 500, partial data rolled back | Target: "Upload failed. Please try again." (no raw exception) |
| Query failure before stream | 500 | "Internal RAG Engine Execution Error." → UI system message |
| LLM unavailable during stream | 200 stream with `System Error:` token | e.g. "Cannot connect to … Is Ollama running?" |
| No relevant content | 200 stream | "I cannot find the answer in your documents." |
| Graph extraction failure | background; status `FAILED` | Target: "Graph failed" badge on document |

All server errors SHALL be logged with timestamp, logger name and level (current logging format) and SHALL NOT log passwords, tokens or API keys.

## 8. Edge cases

| # | Case | Required behaviour |
|---|---|---|
| E1 | Scanned/image-only PDF | 0 chunks → user told "No extractable text found" (FR-ING-16). |
| E2 | Same file uploaded twice | Allowed (two documents). Entities merge; relationship weights double. SHOULD warn on duplicate (hash). |
| E3 | Non-UTF-8 text file | Undecodable bytes ignored. |
| E4 | Very large PDF (e.g., 500 pages) | Memory bounded by page-streaming + 32-chunk batches; request may take minutes (FR-ING-17 resolves). |
| E5 | User deletes a document while graph extraction is running | Extraction must not crash the server; reconciler aborts when `user_id` lookup fails; status update affects no rows. |
| E6 | Server restarts during extraction | Job re-queued at startup and resumed from its checkpoint (FR-GR-13). |
| E7 | Ollama not running | Upload still indexes vectors; graph status → `FAILED`; queries stream a "Cannot connect" error. |
| E8 | Query contains prompt-injection text | Delimiters protected by FR-QRY-10; system prompt restricts to context. |
| E9 | Retrieved chunk itself contains instructions | Treated as content; model instructed to only use it as evidence. (Residual risk.) |
| E10 | Graph has seeds but no edges | Must still be shown (FR-GR-08). |
| E11 | Two tabs / users register same username simultaneously | 409 (FR-AUTH-06). |
| E12 | Token expires mid-session | Next request 401 → logout. |
| E13 | Clustering run with no edges | `{status:"no_edges"}`. |
| E14 | Summarizer hits Ollama outage | Worker logs and stops; remaining communities stay pending. |

## 9. Non-functional requirements

### 9.1 Security
| ID | Requirement | Status |
|---|---|---|
| NFR-SEC-01 | Secrets (JWT key, DB password) SHALL come from environment / `.env`, never source. | ❌ |
| NFR-SEC-02 | CORS SHALL allow only the configured frontend origin (default `http://localhost:3000`). | ✅ |
| NFR-SEC-03 | All SQL SHALL use bound parameters. | 🟡 (summarizer f-strings) |
| NFR-SEC-04 | API SHALL bind to `127.0.0.1` by default. | ❌ (documented run command needed) |
| NFR-SEC-05 | Markdown rendering SHALL not execute raw HTML (react-markdown default). | ✅ |
| NFR-SEC-06 | The UI SHALL warn that cloud providers receive the retrieved document text. | ❌ |
| NFR-SEC-07 | Dependencies SHALL be pinned. | ❌ |

### 9.2 Performance (reference machine: 16 GB RAM, 4+ cores, no GPU)
| ID | Requirement |
|---|---|
| NFR-PERF-01 | Retrieval (embed query + 2 DB searches) SHALL complete in ≤ 500 ms p95 for ≤ 100k chunks. |
| NFR-PERF-02 | Time to first token with warm Ollama `llama3.2` SHOULD be ≤ 4 s p50. |
| NFR-PERF-03 | Upload memory usage SHALL stay bounded (page streaming, batches of 32). ✅ |
| NFR-PERF-04 | The event loop SHALL NOT be blocked by embedding or sync HTTP (use thread pool). 🟡 summarizer embeds on loop. |
| NFR-PERF-05 | DB pool: min 1, max 10 connections. ✅ |

### 9.3 Reliability & maintainability
- NFR-REL-01 Background jobs SHALL leave documents in a terminal or resumable state.
- NFR-MNT-01 Backend test coverage ≥ 70% for `api/`, `core/`, `rag/query`, `rag/vector`.
- NFR-MNT-02 Lint passes (`eslint` frontend; `ruff` backend).

### 9.4 Usability & accessibility
See [04_UI_UX](04_UI_UX.md) §10; target WCAG 2.1 AA for contrast, keyboard access and focus visibility.

## 10. Acceptance criteria (test checklist)

Each line maps to automated (A) or manual (M) tests.

1. (A) Register → 200 + token; repeat email → 400; repeat username → 400; bad email → 400; 72-byte password → 400; 7-char password → 400 (after FR-AUTH-09).
2. (A) Login by email and by username → 200; wrong password → 401 generic message.
3. (A) `/me` with no token → 401; with token of deleted user → 401; valid → no `hashed_password` key.
4. (A) Upload `.exe` → 400; 51 MB `.txt` → 413; valid `.md` → 200 with `total_chunks_processed ≥ 1`.
5. (A) User B `GET /documents` never contains user A's doc; B `DELETE` A's doc → 404 and doc still exists.
6. (A) User B query whose text matches only A's document → "I cannot find…" and empty sources.
7. (A) SSE event order is sources → graph → token* → `[DONE]`.
8. (A) Delete doc → its chunks count = 0; orphan entities removed.
9. (A) With Ollama stopped: upload succeeds; doc status eventually `FAILED`; query streams "System Error: Cannot connect…".
10. (A) `/graph/summarize` by user A does not modify user B's communities.
11. (M) UI: upload error visible; status badge transitions; per-message graph; citation click scroll/focus; cloud warning shown.
12. (M) Eval set metrics meet PRD §9 targets.
