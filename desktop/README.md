# PKOS desktop app (Electron shell)

Starts PostgreSQL + pgvector, Ollama and the PKOS backend in the background, then shows the React UI.
Everything listens on 127.0.0.1 only, on ports picked at startup. Plan: [`docs/06_DESKTOP_APP_PLAN.md`](../docs/06_DESKTOP_APP_PLAN.md).

## Run in development
Needs the Phase 0 runtimes in `build/spike/` (portable Postgres with pgvector, portable Ollama), the backend venv and a
built frontend:
```bash
cd frontend && npm run build        # the shell serves frontend/dist via app://pkos
cd ../desktop && npm install
npm run dev                         # data goes to %LOCALAPPDATA%\PKOS-dev, never the real vault
```
Useful environment variables:

| Variable | Effect |
|---|---|
| `PKOS_DEV_URL=http://localhost:3000` | load the Vite dev server (hot reload) instead of `frontend/dist` |
| `PKOS_OLLAMA_MODE=bundled\|external\|auto` | force the bundled Ollama, use only an installed one, or auto (default: an Ollama already on 11434 wins) |
| `PKOS_DATA_DIR`, `PKOS_PG_DIR`, `PKOS_OLLAMA_DIR`, `PKOS_PYTHON`, `PKOS_BACKEND_DIR`, `PKOS_WEB_DIR` | override locations |
| `PKOS_SCREENSHOT=1` | save the main window to `logs/main-window.png` 4 s after it opens |

## How it works
- `src/main.js`: single instance, splash window, `app://pkos` protocol (serves the built UI with a strict CSP),
  blocks navigation and new windows (external links open in the browser), stops everything on quit.
- `src/services.js`: Postgres (`initdb` on first run, stale-pid cleanup, `pg_ctl stop -m fast` on quit), Ollama
  (bundled or an existing install, tree-kill on quit, leftover cleanup), backend (`ENV=desktop`, exits by itself if
  the app dies). Crashed services restart up to 3 times in 10 minutes.
- `src/config.js`: first-run secrets (database password, `PKOS_SECRET_KEY`) in `config.json`, encrypted with
  Windows DPAPI via Electron `safeStorage`.
- `src/preload.js`: the only bridge to the UI, `window.pkos` (`apiBase`, status, open logs, restart services).

Data folder layout: `pgdata/`, `ollama/` (models), `logs/` (`desktop.log`, `postgres.log`, `ollama.log`,
`backend.log`, backend `api.log`), `config.json`, `electron/` (Chromium profile).

## Tests
```bash
npm test     # node:test, no Electron needed
```
