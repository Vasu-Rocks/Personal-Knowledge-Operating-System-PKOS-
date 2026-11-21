# PKOS v2: Personal Knowledge OS

Local-first Graph RAG: upload documents, ask questions, get cited answers, and explore the knowledge graph built from them.
With default settings (Ollama) no document data leaves your machine.

Docs: see [`docs/README.md`](docs/README.md) (PRD, SRS, architecture, UI/UX, development plan).

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

## Configuration
All backend settings are environment variables; see `backend/.env.example` (database, Ollama, secret key, CORS origins, token lifetime, graph tuning).

## Backup
```bash
pg_dump -h localhost -p 5433 -U postgres pkos_v2 > pkos_backup.sql
```

## Troubleshooting
- **Tests**: `pip install -r requirements-dev.txt && pytest` from `backend/` (no DB or Ollama needed).
- **Health shows `ollama: false`**: start Ollama and check `OLLAMA_BASE_URL`.
- **Cannot connect to the database**: verify port 5433 and the `POSTGRES_*` variables.
- **Logged out after every restart**: `PKOS_SECRET_KEY` is not set.
- Do not bind uvicorn to `0.0.0.0` unless you understand the exposure; the app is built for single-machine use.
