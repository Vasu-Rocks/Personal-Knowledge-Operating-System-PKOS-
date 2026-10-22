# PKOS — Product Requirements Document (PRD)

| Field | Value |
|---|---|
| Product | PKOS — Personal Knowledge Operating System (repo: `pkos_v2`) |
| Document | 01 — PRD |
| Version | 1.0 (baseline written from code inspection) |
| Date | 2026-10-23 |
| Related docs | [02_SRS](02_SRS.md) · [03_Architecture](03_ARCHITECTURE.md) · [04_UI_UX](04_UI_UX.md) · [05_Dev_Plan](05_DEVELOPMENT_PLAN.md) |

> **Status legend used across all docs**
> ✅ Implemented and verified in code · 🟡 Partially implemented / has known gaps · ❌ Not implemented (planned)

---

## 1. Product summary

PKOS is a local-first, privacy-focused AI knowledge assistant. A user uploads their own documents (PDF, text, Markdown, Python, JavaScript), PKOS indexes them into PostgreSQL + pgvector using a local embedding model, and the user asks natural-language questions that are answered by a local LLM (Ollama) **strictly from the user's own content**, with citations and a transparent "X-Ray" view of the evidence used.

On top of classic vector RAG, PKOS is building **Graph RAG**: an LLM extracts entities and relationships from every chunk into a per-user knowledge graph, which is used at query time to add relationship context and is visualised as an interactive entity map.

## 2. Problem statement

Knowledge workers and students accumulate notes, papers, textbooks and code across many files. Finding *what they already know* is slow:

- Keyword search misses meaning and connections across documents.
- Cloud AI assistants require uploading private material to third parties.
- Generic chatbots answer from general training data and hallucinate instead of grounding in the user's own sources.
- Users cannot see *why* an AI answered the way it did.

## 3. Target users

| Persona | Description | Primary need |
|---|---|---|
| **Privacy-conscious student / researcher** (primary) | Has many PDFs, lecture notes, papers. Runs a laptop/desktop with ~16 GB RAM, optional modest GPU. | Ask questions across their study material without data leaving the machine. |
| **Developer** | Keeps project notes, READMEs, `.py`/`.js` snippets. | Ask "how did I implement X" questions over own code and notes. |
| **Power user / tinkerer** | Comfortable running Postgres + Ollama locally. | Inspect retrieval quality, see the knowledge graph, switch models. |

Assumed environment: single machine, one or a few local accounts (e.g., family members or separate personas). Not a multi-tenant SaaS.

## 4. Goals and non-goals

### Goals
1. **G1 — Grounded answers:** answers come only from the user's documents, with citations, and say "I cannot find the answer in your documents" when evidence is missing.
2. **G2 — Privacy by default:** with the default configuration, no document content, query or embedding leaves the machine.
3. **G3 — Transparency:** for every answer, the user can see the retrieved chunks (file, page, distance) and the graph neighbourhood used.
4. **G4 — Connected knowledge:** surface relationships between concepts across documents through Graph RAG.
5. **G5 — Runs on consumer hardware:** usable on ~16 GB RAM, CPU embeddings, small local LLM (default `llama3.2`).

### Non-goals (for this product version)
- Multi-tenant cloud hosting, billing, teams, sharing.
- Real-time collaboration.
- Mobile apps.
- Training or fine-tuning models.

## 5. Current implementation snapshot (verified 2026-10-23)

| Capability | Status | Notes |
|---|---|---|
| Register / login / current user (JWT) | ✅ | Email or username login; token valid 30 days. |
| Per-user data isolation | ✅ | All document/graph queries filtered by `user_id`. Exception: community summarizer worker (see risks). |
| Upload PDF/TXT/MD/PY/JS ≤ 50 MB | ✅ | Synchronous chunk + embed inside the request. |
| Document list & delete (cascade) | ✅ | Deletes chunks, junction rows, orphan entities. |
| Vector retrieval (pgvector HNSW, cosine) | ✅ | top-k = 3, distance < 0.35. |
| Streaming answers (SSE) | ✅ | `/query/stream`; sources + graph sent first, then tokens. |
| Citations & X-Ray inspector | ✅ | `[Chunk N]` and `[Graph Entity: X]` badges link to source cards / graph nodes. |
| LLM provider switch (Ollama / OpenAI / Anthropic) | 🟡 | Backend supports all three; UI only exposes Ollama and OpenAI. Cloud modes send document context off-device. |
| Graph extraction (entities + relationships) | ✅ | Background task per upload via Ollama structured output. |
| Graph-augmented retrieval (local search) | 🟡 | Seed entities + edges added to prompt; seed nodes without edges are dropped from prompt and UI. |
| Louvain clustering + community summaries | 🟡 | API-only (`/graph/cluster`, `/graph/summarize`); no UI; summaries not used in retrieval; summarizer is not user-scoped. |
| Extraction status visible to user | ❌ | Stored in DB (`extraction_status`) but not returned or shown; UI shows a hard-coded "Synced". |
| Chat history persistence / multi-turn memory | ❌ | Messages live in React state only; each question is answered independently. |
| Automated tests | ❌ | Only a manual `test_distance.py` script. |
| Setup docs, env config, packaging | ❌ | No root README, no `.env.example`, secret key hard-coded, schema must be created by running a script manually. |

## 6. Core features

### F1. Account & isolation ✅
Local accounts (email, username, name, password). Each user's documents, chunks, entities, relationships and communities are private to that user.

### F2. Knowledge Vault (document ingestion) ✅/🟡
Drag-and-drop or browse to upload a file. PKOS extracts text page-by-page, cleans it, splits into ~1,200-character chunks (200 overlap), embeds with `BAAI/bge-small-en-v1.5` (384-d) and stores in pgvector. The vault lists documents and allows deletion.
Gap: no per-document processing status, no error feedback in UI.

### F3. Grounded Q&A with streaming ✅
User types a question; PKOS embeds it, retrieves top chunks and relevant graph edges, builds a strict prompt, and streams the answer token-by-token. If nothing relevant is found, the LLM is skipped and a fixed "cannot find" message is returned.

### F4. RAG X-Ray Inspector ✅/🟡
Right-hand panel showing, for the selected answer: retrieved chunks (file, page, cosine distance, text) and an interactive force-directed entity map. Citation badges in the answer highlight/scroll to the corresponding chunk or graph node.
Gap: the graph shown is always the latest query's graph, not the selected message's.

### F5. Knowledge Graph (Graph RAG) 🟡
Per-chunk LLM extraction of entities (name, category, description) and relationships (source, predicate, target, snippet), merged per user by canonical (lower-cased) name; repeated relationships increase edge weight. Louvain community detection and LLM summaries exist server-side.

### F6. Inference settings 🟡
Modal to choose provider and Ollama model name; API keys kept in browser `localStorage` and sent per request as headers (never stored in the DB).

## 7. MVP scope

The MVP is **"private, trustworthy Q&A over my own documents, with visible evidence."** Most of it already exists; the MVP is complete when the gaps below are closed.

**In MVP**
1. F1 Accounts & isolation (harden secret handling).
2. F2 Ingestion for PDF/TXT/MD/PY/JS with **visible per-document status** (indexing → graph extraction pending/processing/completed/failed) and **visible upload errors**.
3. F3 Streaming grounded Q&A with Ollama as the default and only *required* provider.
4. F4 X-Ray inspector with **per-message** sources and graph.
5. F5 Graph-augmented **local** retrieval (already wired) including seed-only nodes.
6. Reproducible setup: `.env`-based config, automatic schema creation, root README, pinned requirements.
7. Baseline automated tests for auth, isolation, ingestion and query.

**Post-MVP (v1.1+)**
- Community summaries used for "global" questions; UI to trigger/re-run clustering.
- Persistent chat history and follow-up questions with conversation memory.
- Full-graph explorer view.
- Anthropic option in Settings UI (backend exists), configurable cloud model names.
- More file types (DOCX, HTML, PPTX), OCR for scanned PDFs.
- Re-indexing/duplicate detection, hybrid (BM25 + vector) search, re-ranking.
- Docker Compose one-command install.

## 8. User stories

| ID | As a… | I want to… | So that… | Priority | Status |
|---|---|---|---|---|---|
| US-01 | new user | create an account with email, username, name, password | my knowledge base is private to me | Must | ✅ |
| US-02 | returning user | log in with email **or** username | I don't need to remember which | Must | ✅ |
| US-03 | user | stay logged in across browser restarts | I'm not interrupted constantly | Should | ✅ (30-day token) |
| US-04 | user | upload a PDF/TXT/MD/PY/JS by drag-and-drop | it becomes searchable | Must | ✅ |
| US-05 | user | see whether a document is indexed, still building its graph, or failed | I know when answers will include it | Must | ❌ |
| US-06 | user | see a clear message when an upload fails (type, size, server error) | I can fix the problem | Must | ❌ |
| US-07 | user | delete a document and everything derived from it | my data is truly removed | Must | ✅ |
| US-08 | user | ask a question and see the answer stream in | it feels responsive | Must | ✅ |
| US-09 | user | be told plainly when my documents don't contain the answer | I'm not misled by hallucinations | Must | ✅ |
| US-10 | user | click a citation to see the exact source passage and page | I can verify the answer | Must | ✅ |
| US-11 | user | see the entities and relationships related to my question | I discover connections | Should | 🟡 |
| US-12 | user | click an older answer and see *its* sources and graph | I can review past evidence | Should | 🟡 (sources yes, graph no) |
| US-13 | user | choose which local Ollama model to use | I can trade speed for quality | Should | ✅ |
| US-14 | user | optionally use a cloud LLM with my own key, with a clear warning | I can get better answers when I accept the trade-off | Could | 🟡 |
| US-15 | user | ask a follow-up question that refers to the previous answer | conversations feel natural | Could | ❌ |
| US-16 | user | ask broad "what themes are in my notes?" questions | I get an overview of my knowledge | Could | ❌ |
| US-17 | user | see my chat history after reloading | I don't lose work | Could | ❌ |

## 9. Success metrics

Because PKOS is local-first with no telemetry, metrics are measured with a local evaluation set and manual testing, not analytics.

| Metric | Target (MVP) | How measured |
|---|---|---|
| Groundedness — answers whose claims are supported by cited chunks | ≥ 90% | 30-question eval set over a fixed sample corpus, manual review |
| Correct refusal — unanswerable questions answered with the "cannot find" message | ≥ 95% | 10 unanswerable questions in eval set |
| Retrieval hit rate — at least one correct chunk in top-3 | ≥ 85% | eval set with labelled source pages |
| Time to first token (Ollama `llama3.2`, warm model, 16 GB RAM laptop) | ≤ 4 s p50 | timing logs |
| Ingestion throughput (vector indexing only) | ≥ 20 pages/s for text PDFs on CPU | timing a 100-page PDF |
| Cross-user leakage | 0 incidents | automated isolation tests |
| Default-config network egress of document data | 0 bytes to non-localhost hosts | review + packet capture spot check |
| Setup time for a new developer following README | ≤ 30 min | dry run on clean machine |

## 10. Assumptions

- A1. Users can install and run PostgreSQL 15+ with the `pgvector` extension (default port in code: **5433**) and Ollama on the same machine.
- A2. The default Ollama model (`llama3.2`) is pulled locally; ~16 GB RAM available.
- A3. Documents are primarily English (the embedding model is English-focused).
- A4. PDFs contain extractable text (no OCR in MVP).
- A5. App is accessed from `http://localhost:3000` (frontend) and `http://localhost:8000` (API) on the same machine.
- A6. A small number of local users; concurrency is low.

## 11. Risks

| ID | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | JWT secret is hard-coded in source | Token forgery if the API is ever exposed beyond localhost | Med | Load from env; refuse to start without it in non-dev mode |
| R2 | Cloud provider mode sends retrieved document text to OpenAI/Anthropic | Contradicts privacy promise | Med | Explicit warning + opt-in; keep Ollama default |
| R3 | Community summarizer processes **all users'** pending communities when any user triggers it | Cross-user processing (data is written back to the owning row, but violates isolation principle) | Med | Scope worker by `user_id` |
| R4 | Graph extraction is slow (one LLM call per chunk) and runs in-process | Long waits; jobs lost on restart, left as `PROCESSING` | High | Status UI, resumable job queue, retry on startup |
| R5 | Small local LLM ignores instructions / returns invalid JSON | Hallucination, missing graph data | Med | Strict prompts, JSON schema output, validation, eval set |
| R6 | Synchronous embedding in upload request | Large PDFs make the browser request hang for minutes | Med | Move indexing to background with status polling |
| R7 | No automated tests | Regressions in isolation/security | High | Test suite in Dev Plan M5 |
| R8 | Destructive legacy-schema migration drops tables | Data loss on upgrade | Low | Replace with versioned migrations |
| R9 | Text cleaner replaces all URLs with `[URL]` | Users can't retrieve links they saved | Low | Keep URLs (or keep domain) in cleaned text |

## 12. Out of scope

- Hosted SaaS, payments, organisations/teams, sharing documents between users.
- Admin console / user management UI.
- Password reset by email, OAuth/SSO, MFA.
- OCR, audio/video ingestion, web-page crawling, connectors (Drive, Notion…).
- Fine-tuning, model training.
- Mobile/native apps.
- Internationalisation of the UI.

## 13. Acceptance criteria (MVP)

The MVP is accepted when **all** of the following pass on a clean machine following the README:

1. **Setup:** `docker compose up` *or* documented manual steps start Postgres+pgvector, API and frontend; the schema is created automatically on first start; no secrets in source.
2. **Auth:** registering creates a user and logs them in; duplicate email/username are rejected with a clear message; wrong credentials give a generic error; requests without a valid token get 401.
3. **Isolation:** user B cannot list, query, or delete user A's documents, chunks, or graph (automated tests).
4. **Upload:** valid files ≤ 50 MB appear in the vault with status progressing to "Ready"; graph status progresses to "Graph ready" or "Graph failed"; unsupported type, oversize, and server errors each show a visible error message.
5. **Q&A:** a question answerable from an uploaded document streams an answer containing at least one citation that maps to a shown source card; an unanswerable question returns "I cannot find the answer in your documents."
6. **X-Ray:** selecting any AI message shows that message's sources **and** graph; clicking a chunk citation scrolls to its card; clicking an entity citation focuses the node.
7. **Delete:** deleting a document removes it from the vault and subsequent answers can no longer cite it.
8. **Privacy:** with default settings, no outbound request goes to a non-localhost host during upload or query.
9. **Quality:** eval-set targets in §9 met for groundedness and correct refusal.
