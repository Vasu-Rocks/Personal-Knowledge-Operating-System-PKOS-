# PKOS — Development Plan

| Field | Value |
|---|---|
| Document | 05 — Development Plan |
| Version | 1.0 (2026-10-23) |
| Inputs | [01_PRD](01_PRD.md) · [02_SRS](02_SRS.md) · [03_Architecture](03_ARCHITECTURE.md) · [04_UI_UX](04_UI_UX.md) |

---

## 1. Where the project is

PKOS is **not** a greenfield build. Verified state:

| Area | Done | Remaining for MVP |
|---|---|---|
| Setup / config | Postgres DSN from env; Vite on 3000 | `.env`, config module, auto schema, pinned deps, README, `.gitignore` |
| Auth | Register, login (email/username), `/me`, JWT, bcrypt | Secret from env, password min length, username rule |
| Ingestion | PDF/TXT/MD/PY/JS → clean → chunk → embed → pgvector | Status exposure, safe errors, zero-chunk handling, background indexing |
| Query | Dual-track retrieval, strict prompt, SSE streaming, 3 providers | Chunk labels, seed-only graph, non-stream parity |
| Graph RAG | Schema, extraction, reconciliation, Louvain, summaries | User-scoped summarizer, parameterised SQL, resumable jobs |
| Frontend | Auth, 3-pane dashboard, upload, delete, chat, X-Ray, settings | Status badges, error UI, per-message graph, a11y, copy, config URL |
| Quality | — | Test suite, eval set, lint |
| Delivery | — | Docker Compose, release checklist |

The plan therefore starts with **stabilisation**, then closes MVP gaps, then extends Graph RAG.

### Status update (2026-11-21)

Done since the baseline: M0 (except moving the scripts into `backend/scripts/`), M1-2/M1-3/M1-4/M1-5, M2-1 to M2-13 (M2-10 by deleting `/query`),
M3-1 to M3-4 and M3-6 (background indexing and a resumable single worker), M5-1 to M5-3, M5-4 (API tests incl. user isolation), M5-5 (auth only), M5-6, M5-8, and M6-1/M6-2
(compose and CI are written; the backend image build is verified separately, see CHANGELOG). Still open: M1-1 (pydantic-settings module), M3-5, M3-7, M3-8, M4-1 to M4-12
(frontend MVP polish, incl. the Dashboard refactor), M5-2 (fake Ollama server), M5-7 (eval corpus), M6-3 (changelog/tag).

## 2. Priorities

- **P0 — must for MVP** (security, correctness, isolation, reproducible setup)
- **P1 — must for MVP UX** (honest status, errors, per-message evidence)
- **P2 — post-MVP** (global graph search, chat history, more formats)

## 3. Milestones overview

```
M0 Baseline & hygiene ─▶ M1 Config & DB ─▶ M2 Backend hardening ─┬─▶ M4 Frontend MVP ─▶ M5 Testing & eval ─▶ M6 Packaging & release (MVP)
                                                                 └─▶ M3 Ingestion status & jobs ─┘
                                                                                                       └─▶ M7 Graph RAG v2 (post-MVP) ─▶ M8 v1.1 features
```

| Milestone | Goal | Priority | Depends on | Est. effort* |
|---|---|---|---|---|
| M0 | Repo is clean and anyone can run it | P0 | – | 0.5–1 day |
| M1 | Centralised config, auto schema, migrations | P0 | M0 | 1–2 days |
| M2 | Security & correctness fixes in backend | P0 | M1 | 2–3 days |
| M3 | Document status, background indexing, resumable graph jobs | P0/P1 | M1 | 3–4 days |
| M4 | Frontend MVP gaps | P1 | M2 (API shapes), M3 (status) | 3–4 days |
| M5 | Automated tests + RAG eval set | P0 | M2, M3 (can start in parallel) | 3–4 days |
| M6 | Docker Compose, README, release v1.0.0 | P0 | M4, M5 | 1–2 days |
| M7 | Graph RAG v2: community/global search, graph UI | P2 | M6 | 5–7 days |
| M8 | v1.1: chat history, follow-ups, more formats | P2 | M6 | ongoing |

\*Single developer, part-time estimates; adjust to your pace.

---

## 4. Milestone details

Each task: **ID · description · files · done when**.

### M0 — Baseline & hygiene (P0)
| ID | Task | Files | Done when |
|---|---|---|---|
| M0-1 | Add root `.gitignore` (venv/, node_modules/, `__pycache__/`, `.env`, `dist/`, HF cache) and untrack `venv` if committed | `/.gitignore` | `git status` clean after install |
| M0-2 | Fix `requirements.txt`: add `networkx`, `httpx`; remove `faiss-cpu`; pin versions (`pip freeze` subset) | `backend/requirements.txt` | fresh venv install + app import succeeds |
| M0-3 | Delete legacy `backend/data/users/`; move `test_distance.py`, `backfill.py` into `backend/scripts/` | backend | scripts still run from `backend/` |
| M0-4 | Root `README.md` with prerequisites and run steps (Arch §9) | `/README.md` | new dev runs app in ≤ 30 min |
| M0-5 | Set `<title>PKOS</title>` | `frontend/index.html` | – |
| M0-6 | Create `main`-protected workflow: feature branches + PRs (even solo) | – | – |

### M1 — Config & database (P0)
| ID | Task | Files | Done when |
|---|---|---|---|
| M1-1 | `core/config.py` using pydantic-settings: DB vars, `PKOS_SECRET_KEY`, `TOKEN_TTL_MINUTES`, `CORS_ORIGINS`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, retrieval params (`TOP_K`, `MAX_DISTANCE`, `GRAPH_SEEDS`, `GRAPH_MAX_EDGES`), cloud model names, `ENV=dev|prod` | new `backend/core/config.py`, `.env.example` | no constants left in `security.py`, `main.py`, `extractor.py`, `summarizer.py`, `generator.py`, `vector_db_pg.py` |
| M1-2 | Startup refuses to boot if `PKOS_SECRET_KEY` missing and `ENV=prod`; in dev, generates a random key and warns | `main.py` | test covers both |
| M1-3 | Run schema creation on startup (idempotent) inside lifespan; create extension before pool | `main.py`, `postgres_core.py` | fresh DB works with only `uvicorn main:app` |
| M1-4 | Remove destructive legacy-drop block; introduce a `schema_version` table (simple numbered SQL migrations applied in order) | `database/migrations/*.sql`, `postgres_core.py` | upgrading never drops data |
| M1-5 | Frontend `VITE_API_BASE_URL` + `src/api.js` (`apiFetch` with base URL, auth header, 401 → logout) | `AuthContext.jsx`, `VaultView.jsx`, `Dashboard.jsx` | no `localhost:8000` string in `src/` except default |

### M2 — Backend hardening (P0)
| ID | Task | Files | Done when |
|---|---|---|---|
| M2-1 | Scope summarizer to `user_id`; route passes current user | `summarizer.py`, `routes_graph.py` | isolation test passes (SRS AC-10) |
| M2-2 | Parameterise summarizer SQL with `= ANY($1::uuid[])` | `summarizer.py` | no f-string SQL in repo (`grep "f\"\"\"" -A2 | grep SELECT` empty) |
| M2-3 | Summarizer: use `embed_text_batch` (document embedding, no query prefix) via threadpool | `summarizer.py` | – |
| M2-4 | Extractor/summarizer use `OLLAMA_BASE_URL` from config | `extractor.py`, `summarizer.py` | – |
| M2-5 | Safe errors: replace `detail=str(e)` with generic messages + `logger.exception` | `routes_ingest.py`, `routes_graph.py` | SRS FR-ING-14 |
| M2-6 | `DELETE /documents/{id}`: validate UUID (FastAPI `UUID` type), return 404 when not owned/not found | `routes_ingest.py`, `vector_db_pg.py` | tests for invalid / foreign id |
| M2-7 | Password ≥ 8 chars; username regex `[A-Za-z0-9_.-]{3,32}`; name 1–100; lower-case email before store/lookup | `routes_auth.py`, `auth_db_pg.py` | SRS FR-AUTH-09/16 |
| M2-8 | Label context blocks `[Chunk N]` to match prompt & UI | `retriever.py` | citation numbers align in eval |
| M2-9 | Include seed-only nodes in prompt (`=== KNOWLEDGE GRAPH ENTITIES ===` section listing name: description) | `prompt_builder.py` | unit test with nodes & no links |
| M2-10 | `/query` (non-stream): honour provider headers by reusing the stream generator and joining tokens — or delete the endpoint (UI doesn't use it). **Decision: delete** unless needed by tests | `routes_query.py`, `generator.py` | one code path for generation |
| M2-11 | Keep URLs in cleaned text (drop `[URL]` substitution, or truncate very long query strings only) | `cleaner.py` | test |
| M2-12 | Default bind `127.0.0.1` documented; `/health` checks DB + Ollama | `main.py`, README | – |
| M2-13 | Write `mention_snippet` into junction (or drop the column) | `reconciler.py` | – |

### M3 — Ingestion status & background jobs (P0/P1)
| ID | Task | Files | Done when |
|---|---|---|---|
| M3-1 | Add columns to `documents`: `index_status` (`QUEUED`,`INDEXING`,`READY`,`FAILED`), `chunk_count`, `error_message`, `file_hash` (sha256) — via migration | migrations | – |
| M3-2 | `GET /documents` returns `index_status`, `extraction_status`, `chunk_count`, `error_message` | `vector_db_pg.py` | SRS FR-DOC-02 |
| M3-3 | Upload: read file into a temp file, create doc row, return **202** with `document_id`; indexing runs in background task | `routes_ingest.py` | request returns < 1 s for 50 MB PDF |
| M3-4 | Zero-chunk documents → `index_status=FAILED`, `error_message="No extractable text"` | pipeline / route | SRS E1 |
| M3-5 | On startup, any doc in `INDEXING`/`PROCESSING` → re-queue (or `FAILED` with message "Interrupted") | `main.py` lifespan | restart test |
| M3-6 | Sequential single-worker queue (asyncio task reading `documents` where status queued, `FOR UPDATE SKIP LOCKED`) so only one heavy job runs at a time | new `rag/jobs.py` | two uploads don't run extraction concurrently |
| M3-7 | Duplicate detection: same `file_hash` for same user → 409 with "Already uploaded as {filename}" | `routes_ingest.py` | test |
| M3-8 | Progress: store `extraction_progress` (chunks done / total) for UI | extractor | – |

### M4 — Frontend MVP (P1)
| ID | Task | Files | Done when |
|---|---|---|---|
| M4-1 | `StatusBadge` + polling `GET /documents` every 3 s while any doc non-terminal | `VaultView.jsx` | UI/UX §6 |
| M4-2 | Upload/delete error toasts or inline banners; client pre-checks (type, 50 MB) | `VaultView.jsx` | SRS FR-FE-04 |
| M4-3 | Delete confirmation (inline confirm or 5 s undo) | `VaultView.jsx` | – |
| M4-4 | Store `graph` per message; X-Ray reads selected message's graph; render seed-only graphs | `Dashboard.jsx` | SRS FR-FE-06, FR-GR-08 |
| M4-5 | Settings: Anthropic option, cloud privacy warning, Escape/overlay close, dialog semantics | `SettingsView.jsx` | UI/UX §4.6 |
| M4-6 | Accessibility pass (UI/UX §10 table) | all components, `index.css` | axe DevTools: 0 serious/critical |
| M4-7 | Copy updates (UI/UX §12) | all components | – |
| M4-8 | Empty states (vault, chat greeting) | `VaultView.jsx`, `Dashboard.jsx` | – |
| M4-9 | Stop-generation (AbortController) and query length counter | `Dashboard.jsx` | – |
| M4-10 | Refactor: extract `ChatPane`, `XRayPane`, `useStreamQuery` hook; move repeated inline styles to CSS classes | `src/components/*`, `src/hooks/*` | Dashboard.jsx < 300 lines |
| M4-11 | Responsive drawers below 1200 / 900 px | `Dashboard.jsx`, `index.css` | usable at 360 px |
| M4-12 | Self-host Inter font (strict local-first) | `public/fonts`, `index.css` | no request to fonts.googleapis.com |

### M5 — Testing & evaluation (P0)
| ID | Task | Done when |
|---|---|---|
| M5-1 | `pytest` + `pytest-asyncio` + `httpx.AsyncClient`; test DB via `TEST_POSTGRES_DB`, schema created per session, truncated per test | `pytest` runs green locally |
| M5-2 | Mock LLM: fake Ollama server fixture (respx/httpx mock) returning deterministic tokens and extraction JSON | tests run without Ollama |
| M5-3 | Unit tests: cleaner, chunker, pipeline, batcher, prompt_builder, retriever formatting, SSE parser contract | ≥ 90% on these modules |
| M5-4 | API tests: all SRS §10 acceptance items 1–10 | all pass |
| M5-5 | Frontend: Vitest + React Testing Library for AuthView, VaultView status rendering, citation processing, SSE parsing | `npm test` green |
| M5-6 | Lint: `ruff` (backend), `eslint` (frontend) clean | – |
| M5-7 | RAG eval set: 3–5 sample docs in `eval/corpus`, `eval/questions.yaml` (30 answerable with expected file/page, 10 unanswerable); `scripts/run_eval.py` reports hit-rate, refusal rate; manual groundedness review sheet | PRD §9 targets met |
| M5-8 | Optional CI (GitHub Actions): ruff, pytest with `pgvector/pgvector` service, eslint, vitest | green on PR |

### M6 — Packaging & release (P0)
| ID | Task | Done when |
|---|---|---|
| M6-1 | `backend/Dockerfile`, `frontend/Dockerfile` (build → nginx), `docker-compose.yml` (Arch §11), volumes for PG data + HF cache | `docker compose up` → working app |
| M6-2 | README: Docker path + manual path, Ollama setup, backup/restore (`pg_dump`), troubleshooting (Ollama not running, port 5433, model download) | dry run on clean machine |
| M6-3 | `CHANGELOG.md`, tag `v1.0.0` | – |
| M6-4 | Release checklist (§7) completed | – |

### M7 — Graph RAG v2 (P2, post-MVP)
| ID | Task |
|---|---|
| M7-1 | Auto-trigger clustering + summarisation after N new extractions (debounced) instead of manual endpoints; UI "Rebuild knowledge map" button in Settings | **(done in G5)**
| M7-2 | Global search: query router — if the question is broad ("overview", "themes", "summarise everything"), retrieve top community summaries by embedding; else local search | **(done in G5)**
| M7-3 | Mark communities stale when member entities are deleted; recluster on next run | **(done in G5)**
| M7-4 | Entity resolution improvements: merge near-duplicates by embedding similarity (> 0.92) + same category; update description by summarising multiple mentions |
| M7-5 | Fixed category vocabulary in extraction schema (enum) for consistent colouring |
| M7-6 | Full-graph explorer view in X-Ray (toggle), with search and category filter |
| M7-7 | Eval: compare vector-only vs vector+graph on eval set; keep graph only where it improves metrics |

### K — Cross-book knowledge map and graph reasoning (planned 2026-10-27)
Measured on the 3-book graph: 3,507 entities, ~6,060 linked pairs, one component of 2,817 nodes (so a path almost always exists and evidence strength must drive every feature), 563 concepts with a link backed by 2+ passages ("backbone"), 276 concepts shared by name across books, 22 same-meaning candidates across books (mixed quality, so suggestions only).

| ID | Task | Status |
|---|---|---|
| K1-1 | `entity_stats` analytics recomputed by the worker after each rebuild | ✅ |
| K1-2 | Evidence endpoint (passages behind a relationship); `rel_id` on connection and lookup links | ✅ |
| K1-3 | Same-concept suggestions with confirm/reject (never auto-merged) | ✅ |
| K1-4 | Generic-name list shared via `vocab.is_generic_name`; bridges endpoint | ✅ |
| K2 | Knowledge map API + full-screen map: backbone (default), full (top-N by PageRank), community modes; filters by book, support, category, cross-book only; click node -> concept panel, click link -> evidence | ✅ |
| K3 | Concept view: ego graph by book, shared vs book-specific neighbours, same-concept confirm buttons | ❌ |
| R1 | LLM evidence check per link (supported / unsupported), cached | ❌ |
| R2 | Explain a verified chain with citations | ❌ |
| R3 | Compare a concept across books | ❌ |
| R4 | Relational questions in chat (path + evidence into context) | ❌ |
| R5 | "What connects my books" + suggested links (shown as hypotheses) | ❌ |
| R6 | Reading path / prerequisites (experimental) | ❌ |

### M8 — v1.1 features (P2)
Persistent chat sessions (tables `conversations`, `messages`) and history sidebar; follow-up questions with last-N-turn context + query rewriting; DOCX/HTML ingestion; OCR (Tesseract) opt-in; hybrid BM25 + vector with Postgres full-text; cross-encoder re-ranking; export answer with citations as Markdown.

---

## 5. Dependency map (critical path)

```
M0-2 (deps) ─▶ M1-1 (config) ─▶ M1-3 (auto schema) ─▶ M3-1 (migration) ─▶ M3-2/M3-3 ─▶ M4-1 (status UI) ─▶ M6-1 (compose) ─▶ v1.0.0
                    └─▶ M2-1..M2-13 ─▶ M5-4 (API tests) ─────────────────────────────────────────┘
M1-5 (api.js) ─▶ M4-* (frontend)
M5-2 (LLM mock) ─▶ M5-4
```

Critical path ≈ M0 → M1 → M3 → M4 → M6. M2 and M5 run alongside.

## 6. MVP scope (frozen)

In: everything in M0–M6. Out: everything in M7–M8. Any new idea goes to the M8 backlog unless it fixes a P0 defect.

**MVP exit criteria** = PRD §13 acceptance criteria all pass + SRS §10 checklist all pass.

## 7. Definition of Done

A task is **Done** when:
1. Code is merged to `main` via PR with a short description linking the task ID (e.g., `M2-1`).
2. Behaviour matches the referenced SRS requirement(s); the requirement status in `02_SRS.md` is updated (❌ → ✅).
3. Tests added/updated; `pytest`, `npm test`, `ruff`, `eslint` all pass.
4. No secrets, API keys, or raw exceptions leak into code, logs, or responses.
5. All data access is user-scoped (reviewed explicitly for any new SQL).
6. UI changes: loading, empty, error states implemented; keyboard operable; copy follows UI/UX §12.
7. Docs updated where behaviour, config, or API changed (README, `03_ARCHITECTURE.md` API table, `.env.example`).
8. Manually smoke-tested: register → upload → ask → verify citation → delete.

A **milestone** is Done when all its tasks are Done and its "done when" checks pass on a clean checkout.

## 8. Working conventions
- Branches: `feat/M3-2-doc-status`, `fix/M2-1-summarizer-scope`.
- Commits: Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`).
- Backend style: async everywhere in request path; CPU work via `run_in_threadpool`; SQL only in `database/` or `rag/vector/vector_db_pg.py`-style data modules; every query takes `user_id`.
- Frontend style: function components, hooks; network calls only through `src/api.js`; tokens in `index.css`.
- Keep these five docs as the source of truth; update status markers when work lands.

## 9. Risks to the plan
| Risk | Mitigation |
|---|---|
| Local LLM too slow for extraction on large docs | Job queue (M3-6) + progress; allow disabling graph extraction per upload (setting) |
| Test DB setup friction on Windows | Use Docker `pgvector/pgvector` container for tests on port 5434 |
| Scope creep into Graph RAG v2 before MVP | MVP frozen (§6) |
| HNSW recall with user filter at scale | Monitor eval hit-rate; set `SET hnsw.ef_search = 100` per query if needed |
