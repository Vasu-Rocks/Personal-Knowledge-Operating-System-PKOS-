# PKOS v2: Personal Knowledge OS

Local-first Graph RAG: upload documents, ask questions, get cited answers, and explore the knowledge graph built from them.
With default settings (Ollama) no document data leaves your machine. Chats are saved, and follow-up questions are
understood in the context of the conversation. PKOS can also remember what you choose about yourself and how you want
answers ("I am preparing for the GATE exam", "answer in bullet points"), and finds earlier chats when you ask "what did
we decide last time?" - every memory is visible, editable and can be switched off (see
[`docs/07_MEMORY_PLAN.md`](docs/07_MEMORY_PLAN.md)).

Docs: see [`docs/README.md`](docs/README.md) (PRD, SRS, architecture, UI/UX, development plan).

License: [MIT](LICENSE). Third-party components and their licences: [`packaging/THIRD_PARTY_NOTICES.txt`](packaging/THIRD_PARTY_NOTICES.txt).

## Prerequisites
- Python 3.11+ and Node 20+
- PostgreSQL with the pgvector extension (>= 0.5), listening on `localhost:5433`, database `pkos_v2` created
- [Ollama](https://ollama.com) running on `:11434` with a model pulled: `ollama pull llama3.2`

## Run
```bash
# Backend
cd backend
python -m venv ../venv && ../venv/Scripts/activate   # Windows; use bin/activate on Linux/macOS
pip install -r requirements.txt
cp .env.example .env        # set PKOS_SECRET_KEY (python -c "import secrets; print(secrets.token_hex(32))")
uvicorn main:app --host 127.0.0.1 --port 8000   # schema is created on startup

# Frontend (new terminal)
cd frontend
cp .env.example .env
npm install
npm run dev                 # http://localhost:3000
```

Check `http://localhost:8000/health`: it reports `database` and `ollama` status separately (503 if the database is down).

## Run with Docker
Runs Postgres+pgvector, the API and the web UI together. Ollama stays on your machine (GPU access).
```bash
cp .env.example .env     # set PKOS_SECRET_KEY
docker compose up --build   # UI: http://localhost:3000, API: http://localhost:8000
```
The API container runs with `ENV=prod`, so it refuses to start without `PKOS_SECRET_KEY`. The embedding model (~130 MB) downloads on first use into a volume.
The API URL is baked into the web image at build time (`VITE_API_BASE_URL`); rebuild after changing it.

## Desktop app (Windows)
A single installer that runs everything locally: PostgreSQL + pgvector, Ollama (with NVIDIA GPU support) and the
PKOS engine start in the background; the first-run screen lets you download a local model or use an OpenAI/Anthropic
API key. Data lives in `%LOCALAPPDATA%\PKOS`.
- Development: see [`desktop/README.md`](desktop/README.md) (`npm run dev` in `desktop/`).
- Building the installer: see [`packaging/README.md`](packaging/README.md).
- Unsigned builds show a SmartScreen warning on install: "More info" → "Run anyway".
- **Use it from your phone** (0.7.0+): Settings → Phone access lets paired phones on the same network (the laptop's
  Mobile hotspot or Wi-Fi) open PKOS in their browser, with nothing to install; everything stays on the laptop. See
  [`docs/PHONE_ACCESS.md`](docs/PHONE_ACCESS.md).

## Configuration
All backend settings are environment variables; see `backend/.env.example` (database, Ollama, secret key, CORS origins, token lifetime, graph tuning).

## Backup
```bash
pg_dump -h localhost -p 5433 -U postgres pkos_v2 > pkos_backup.sql
```

## Troubleshooting
- **Tests**: from `backend/` run `pip install -r requirements-dev.txt && pytest`. Unit tests need nothing else. The API tests
  (auth, upload/delete, query, user isolation) need a throwaway pgvector database and are skipped if it is unreachable:
  `docker run -d --name pkos-test-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=pkos_test -p 127.0.0.1:5434:5432 pgvector/pgvector:pg16`
  (override with `TEST_POSTGRES_HOST/PORT/DB/USER/PASSWORD`). The test schema is dropped and recreated each run, so never point it at real data.
  Embeddings and the LLM are faked; Ollama is not needed.
- **Health shows `ollama: false`**: start Ollama and check `OLLAMA_BASE_URL`.
- **Cannot connect to the database**: verify port 5433 and the `POSTGRES_*` variables.
- **Logged out after every restart**: `PKOS_SECRET_KEY` is not set.
- Do not bind uvicorn to `0.0.0.0` unless you understand the exposure; the app is built for single-machine use.
