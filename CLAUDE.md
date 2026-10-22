# PKOS — notes for Claude

Read `docs/README.md` first. The five docs in `docs/` (PRD, SRS, Architecture, UI/UX, Development Plan) describe the verified state of this repo as of 2026-10-23, so you don't need to re-scan the whole codebase.

- Status markers: ✅ implemented · 🟡 partial · ❌ not implemented. Don't assume a ❌ feature exists.
- Repo map and API table: `docs/03_ARCHITECTURE.md` §3 and §5. Known tech debt: §14.
- Next work items have IDs (M0-1 … M8) in `docs/05_DEVELOPMENT_PLAN.md`. Refer to them in branches and commits.
- After changing behaviour, update the matching SRS requirement status and the Architecture tables.
- Invariants: every DB query is scoped by `user_id`. Ollama is the default provider, and with default settings no document data leaves the machine. Embeddings are 384-d (`BAAI/bge-small-en-v1.5`).
- Run: Postgres+pgvector on :5433 (db `pkos_v2`), `python database/postgres_core.py` once to create the schema, `uvicorn main:app` from `backend/`, `npm run dev` in `frontend/` (:3000), Ollama on :11434.
