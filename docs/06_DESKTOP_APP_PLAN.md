# PKOS Desktop App: Implementation Plan

Goal: ship PKOS as a single Windows installer. After install the app runs with nothing else to set up: the database,
the local AI runtime and the embedding model all live inside the app, and answers can come from local Ollama or a cloud API.

## 1. Decisions

| Topic | Decision |
|---|---|
| Platform | Windows 10/11 x64 only (other OSes later) |
| Database | Bundled portable PostgreSQL 16 + pgvector, started by the app in the background |
| Ollama | Ollama program bundled; the model is optional. First run offers: download a model, or use an API key |
| Login | Keep the register/login screen (several people can share one PC) |
| Desktop shell | Electron (Node is already in the toolchain, no Rust needed; installer size is dominated by Postgres/Ollama/Python anyway) |
| Backend packaging | PyInstaller "onedir" build of the FastAPI app, run as a child process |
| Embeddings | Keep sentence-transformers (`BAAI/bge-small-en-v1.5`, 384-d) with CPU-only PyTorch. Larger backend, no change to embedding code or vectors |
| GPU | Bundled Ollama includes the NVIDIA (CUDA) libraries; CPU fallback; AMD/ROCm libraries are dropped |
| Signing | Unsigned builds for now (SmartScreen "unknown publisher" warning); signing can be added later |
| Existing data | One-time import tool from the current PKOS database (`localhost:5433`) |

## 2. Target architecture

```
PKOS.exe (Electron main process)
 ├─ splash/status window  →  main window (React UI, loaded from bundled files)
 ├─ child: postgres.exe   127.0.0.1:<free port>, data in %LOCALAPPDATA%\PKOS\pgdata
 ├─ child: ollama.exe     127.0.0.1:<free port>, models in %LOCALAPPDATA%\PKOS\ollama
 └─ child: pkos-api.exe   127.0.0.1:<free port>  (FastAPI + graph worker)
```

- Every service binds to 127.0.0.1 only, on ports chosen at startup, so the app never clashes with an existing Postgres/Ollama.
- Electron passes the ports, paths and secrets to the backend as environment variables, so the existing env-driven config keeps working.
- The UI gets the API URL at runtime through the Electron preload script (`window.pkos.apiBase`) instead of the build-time `VITE_API_BASE_URL`.

### App data layout (`%LOCALAPPDATA%\PKOS\`)
```
pgdata\        Postgres cluster
ollama\        downloaded Ollama models
models\        embedding model cache
logs\          app.log, api.log, postgres.log, ollama.log (rotated)
config.json    generated secrets (DB password, PKOS_SECRET_KEY), chosen model, window state
backups\       exports
```
Uninstalling keeps this folder by default (the uninstaller offers to delete it).

## 3. Startup and shutdown sequence

1. Single-instance lock (a second launch focuses the existing window).
2. First run only: create the data folders, generate a random DB password and `PKOS_SECRET_KEY`, run `initdb` (UTF-8, scram auth, listen on localhost).
3. Start Postgres, wait for `pg_isready`, create the `pkos` database if missing. The backend creates the `vector` extension and runs migrations, as it already does.
4. Start Ollama with `OLLAMA_HOST` and `OLLAMA_MODELS` pointing into the app folder. If a user-installed Ollama is already running on 11434, offer to use it instead (saves disk if models already exist).
5. Start the backend, wait for `/health`.
6. Open the main window. The splash shows each step and a clear error with "Open logs" if one fails.
7. On quit: stop the backend (graceful), `pg_ctl stop -m fast`, stop Ollama. If a child crashes while running, restart it up to 3 times, then show an error banner.

## 4. Work breakdown

### Phase 0: Spikes (de-risk first, about 2 days)
- D0-1 pgvector on Windows: get a `vector.dll` + control/SQL files for PG16 (build with MSVC `nmake /F Makefile.win`, or a verified prebuilt). Confirm `CREATE EXTENSION vector` and an HNSW index work on the portable Postgres.
- D0-2 PyInstaller: build the backend onedir, confirm it starts, embeds text, connects to the DB and streams a query. Measure size.
- D0-3 Portable Ollama: run the official Windows zip with custom `OLLAMA_HOST`/`OLLAMA_MODELS`; check GPU detection and which GPU libraries can be dropped to shrink it.
- Exit: all three run from a plain folder with no installs; sizes recorded.

#### Phase 0 results (2026-11-21, RTX 3050 Laptop 4 GB, 16 GB RAM, Windows 11)

| Spike | Result |
|---|---|
| D0-1 Portable Postgres | PASS: `bin`+`lib`+`share` copied from the local EDB 16.13 install (137 MB incl. headers, about 125 MB without) run from a plain folder: `initdb` (scram, UTF-8), start on a custom port bound to 127.0.0.1, connect, create DB, fast stop. pgvector 0.8.1 compiled from source with MSVC (VS Build Tools 2026, C++ workload; `nmake /F Makefile.win` with `PGROOT` pointing at the portable copy): `vector.dll` 272 KB + 36 extension files; `CREATE EXTENSION vector` and an HNSW cosine index work (index scan confirmed). Final check, fully Docker-free: frozen backend + portable Postgres + portable Ollama → health, register, upload, indexed in 13.6 s, cited streamed answer. Note: `pg_ctl start` keeps the parent's output handles open, so the app must spawn `postgres.exe` directly (or detach) |
| D0-2 PyInstaller backend | PASS: onedir build is 723 MB (torch 360, scipy 53, faiss 49, pymupdf 36, transformers 35). End-to-end against pgvector: `/health` ok, register, upload → indexed in 13 s, streamed query with a correct cited answer. Startup: 76 s on first launch (Defender scanning new files), 13.7 s warm, the same as the unfrozen venv (14.2 s, dominated by importing torch) |
| D0-3 Portable Ollama | PASS: `ollama.exe` + core libs + `cuda_v13` + `vulkan` = 753 MB (the full install is 2.8 GB; ROCm 926 MB and CUDA 12 1.1 GB dropped). Runs with custom `OLLAMA_HOST`/`OLLAMA_MODELS`, detects the RTX 3050 (CUDA, driver 13.3), llama3.2 at 71 tokens/s with 26/29 layers on the GPU, 7.4 s model load |

Follow-ups found by the spikes:
- `generator.py` reads `OLLAMA_API_URL` separately from `OLLAMA_BASE_URL`; unify in D1-1 so one setting moves all Ollama calls.
- Load torch/the embedder lazily (or in a warm-up task after `/health` is up) so the window opens faster; show "Preparing AI engine…" until ready.
- Exclude unused heavy packages from the PyInstaller build (check whether `faiss`, `scipy`, `sympy` are really needed) to shrink the 723 MB.
- Decide CUDA 12 vs 13: CUDA 13 libraries need a recent NVIDIA driver; shipping `cuda_v12` too (+1.1 GB) covers older drivers. Proposal: ship CUDA 13 only and let older drivers fall back to Vulkan/CPU.
- Queries took 24–30 s while the graph worker was extracting the just-uploaded document on the same 4 GB GPU; measure query latency with the worker idle, and consider pausing extraction while a query is generating.
- Installed size estimate updated: Electron 90 + backend 723 + Postgres 125 + Ollama 753 ≈ 1.7 GB before trimming.

### Phase 1: Backend changes for app mode

**Status (2026-11-21): done.** D1-1 to D1-7 implemented; 145 backend tests pass (52 new), run against the portable Postgres
from the spike instead of Docker. Changes vs the original plan: API keys are encrypted with Fernet (`cryptography`)
using a key derived from `PKOS_SECRET_KEY` (or `PKOS_SETTINGS_KEY`) instead of keyring/DPAPI, so the same code works in
Docker; on the desktop, Electron protects that secret with `safeStorage` (DPAPI) in Phase 2. The embedding model is
not bundled yet (D1-2's `PKOS_EMBED_MODEL` accepts a local folder; Phase 4 ships it). Importing the app no longer loads
torch (19 s → 2.4 s); the model warms up in a background thread after startup. The legacy `X-LLM-*` headers still work
until a user saves settings (removed in D3-5). New endpoints: `GET/PUT /settings/llm`, `POST /settings/llm/test`,
`GET /llm/status`, `GET /ollama/models`, `POST /ollama/pull` (SSE), `DELETE /ollama/models/{name}`, `GET /system/status`.

- D1-1 Config: a `PKOS_DATA_DIR` setting; logs to file; embedding model cache under the data dir; `ENV=desktop` behaves like prod (requires secret, no debug).
- D1-2 Embeddings: keep sentence-transformers; build with CPU-only torch; ship the bge-small model files inside the app (no download on first run, works offline); point the cache at the bundled folder.
- D1-3 LLM provider layer: one `LLMClient` interface (`chat`, `chat_stream`, `chat_json`) with Ollama, OpenAI and Anthropic implementations. Today only answer generation supports cloud providers; graph extraction (`extractor.py`) and community summaries (`summarizer.py`) call Ollama directly. Route all three through the client so "API only" users get a working knowledge graph.
- D1-4 Server-side settings: provider, model names and API keys move from browser localStorage/request headers to a per-user settings table. API keys are encrypted with Windows DPAPI (via `keyring`/Credential Manager) and never returned to the UI in full (masked). Needed because background indexing has no request headers to read keys from.
- D1-5 Model management endpoints: `GET /llm/status` (provider reachable, models installed), `GET /ollama/models`, `POST /ollama/pull` (streams download progress as SSE), `DELETE /ollama/models/{name}`, `POST /llm/test` (validates an API key with a tiny call).
- D1-6 `/system/status` for the UI: DB, Ollama, embedding model, graph worker, disk free.
- D1-7 Tests for the provider layer (fake HTTP servers for Ollama/OpenAI/Anthropic), settings encryption, and pull progress.

### Phase 2: Electron shell (`desktop/`)

**Status (2026-11-21): done** (D2-6 tray icon deferred). Electron 45.2.3, plain CommonJS, no build step; see
`desktop/README.md`. Verified on this PC in dev mode: first run (`initdb`, secrets in DPAPI-protected `config.json`),
all three services up, UI served from `app://pkos` with CSP, CORS for that origin, login through the app's backend,
`/llm/status` reporting "model not downloaded" against the bundled Ollama, an existing Ollama on 11434 detected and
reused, normal quit stopping every child (Postgres via `pg_ctl`, Ollama with its runner processes), a stray Postgres
and a stray bundled Ollama from a killed session cleaned up on the next start, and the backend exiting when its
parent dies (Windows handle watchdog in `backend/desktop_entry.py`). 15 `node:test` unit tests (config secrets, paths,
supervisor restart policy, log rotation); a CI job runs them. Findings for Phase 3: the UI loads the Inter font from
Google Fonts, which the CSP blocks (self-host it, M4); the embedding model still makes Hugging Face update checks in
dev (Phase 4 bundles it and can run offline).

- D2-1 Project setup: `electron`, `electron-builder`, TypeScript optional; `npm run dev` starts Electron against the Vite dev server and a dev backend.
- D2-2 Process manager: free-port finder, spawn/stop/restart for postgres, ollama, backend; health checks; log piping to files.
- D2-3 First-run bootstrap: folders, secrets in `config.json` (file ACL limited to the user), `initdb`.
- D2-4 Preload bridge: `apiBase`, app version, "open logs folder", "open data folder", "restart services".
- D2-5 Security: `contextIsolation`, no `nodeIntegration`, strict CSP, block navigation to external URLs (open them in the default browser).
- D2-6 Tray icon (optional): keep the graph worker running in the background while the window is closed.

### Phase 3: Frontend changes

**Status (2026-11-21): done.** New `src/components/ai/` (setup wizard, model picker with download progress/cancel/retry,
cloud key form with connection test and a data/cost notice, header status badge, status polling hook) and `src/lib/`
(`sse.js` shared stream reader now also used by the chat, `llmApi.js`, `models.js`). Settings rewritten: Ollama /
OpenAI / Anthropic tabs (Anthropic was not selectable before), installed models with select/remove, masked saved keys
with remove, "Run setup again", and on the desktop "Open data folder / Open logs". Browser-stored provider and keys
from older versions are moved to the server once and deleted from the browser; the chat no longer sends any
provider/key headers. Inter is bundled (`@fontsource-variable/inter`), so no Google requests. 27 new Vitest tests
(34 total). Verified in the Electron window via the DevTools protocol: first run with the bundled Ollama (no models)
opens the wizard; skip shows "AI not set up"; with an installed Ollama a new user gets no wizard and a green
"llama3.2 · on this PC" badge; Settings lists the installed models; a real question was answered by llama3.2 with a
`[Chunk 1]` citation in 2 s. Not exercised for real: an actual model download (unit-tested only) and real cloud
calls (no keys). Known gap: the document list does not refresh for uploads made outside its own upload button.

- D3-1 `src/api.js` reads `window.pkos?.apiBase` first, then `VITE_API_BASE_URL` (web/Docker builds keep working).
- D3-2 First-run wizard (after register/login): step 1 choose "Local AI (Ollama)" or "Cloud API"; step 2a pick a model (llama3.2 3B recommended, with sizes and RAM needs) and download with progress, cancel and retry; step 2b paste an OpenAI/Anthropic key, test it, pick a model; step 3 done. Can be skipped and reopened from Settings.
- D3-3 Settings rework: provider switch, installed models list (download/delete), API keys (masked, test button), storage usage, data folder location, export/backup.
- D3-4 Status indicator in the header (DB/AI/indexing) using `/system/status`; clear messages like "Ollama has no model yet: download one or add an API key".
- D3-5 Remove the API-key headers and localStorage keys from `Dashboard.jsx`/`SettingsView.jsx`.
- D3-6 Vitest tests for the wizard and settings.

### Phase 4: Packaging
- D4-1 Build pipeline script: `frontend` build → PyInstaller backend → stage Postgres (trimmed: bin, lib, share; drop docs, pgAdmin, StackBuilder) + pgvector files → stage Ollama → electron-builder NSIS installer.
- D4-2 Installer: per-user install (no admin), Start menu + optional desktop shortcut, uninstaller with "also delete my data" checkbox.
- D4-3 Size budget (estimate): Electron 90 MB + backend with CPU torch about 900 MB–1.1 GB + embedding model 130 MB + Postgres 80 MB + Ollama with CUDA libraries about 1–1.3 GB. Expect about 2.2–2.7 GB installed (installer about 1–1.3 GB compressed), not counting the optional chat model.
- D4-4 Code signing: unsigned for now. The README and download page explain the SmartScreen warning ("More info" → "Run anyway"). The build script keeps a signing step that is skipped when no certificate is configured.
- D4-5 Optional auto-update via `electron-updater` + GitHub Releases. The Postgres data folder stays compatible while the bundled major version stays 16.

**Phase 4 status (2026-11-21): installer built, not yet installed.** `packaging\build.ps1` stages every runtime and runs
electron-builder; see `packaging/README.md`. Result: `PKOS-Setup-0.1.0.exe` 845 MB (1.66 GB installed: pkos-api 671 MB,
Ollama 753 MB, pgsql 107 MB, model 128 MB, UI 1 MB); full build ~18 min on this PC (PyInstaller 8 min, NSIS
compression 12 min). Fixed on the way: the SQL migrations were not part of the frozen backend (the spike build only
worked because no migration was required); they are now bundled and the backend refuses to start without them, and
`pkos-api.exe --smoke-test` checks this during the build. The EDB PostgreSQL binaries need the VC++ runtime, now
shipped next to them. Verified with the unpacked build (`win-unpacked`, separate data folder, bundled Ollama): all
services start from the app folder, both migrations applied, the bundled embedding model loads offline in 0.4 s with
no Hugging Face requests, a document indexes, the missing chat model is reported in plain words, quit stops every
child. Install test on this PC (silent, per user): installed in 164 s to `%LOCALAPPDATA%\Programs\PKOS` (2.0 GB),
Start menu + desktop shortcuts and an uninstall entry; first launch reached the login screen in 29 s (new database,
DPAPI-sealed secrets, existing Ollama reused). Uninstalling while the app was running stopped all of PKOS's processes
(and none of the system PostgreSQL service or the user's Ollama), removed the program, shortcuts and uninstall entry,
and kept the data folder; the stale `postmaster.pid` left by the forced stop is handled on the next start. Still open:
the interactive "delete my data" uninstall prompt, a clean-machine test (D6-1), app icon, signing. Licensing: PyMuPDF was
AGPL-3.0; replaced in 0.3.0 (see "PDF engine switch" under Phase 6).

### Phase 5: Data safety and maintenance

**Status (2026-11-21): done.** Backups run in the Electron main process with the bundled `pg_dump`/`pg_restore`
(`desktop/src/backup.js`): custom-format dumps of the whole vault in `<data>\backups`, written to a `.partial` file and
renamed; automatic kinds (`before-update`, `before-restore`, `before-import`) keep the last 5 each, manual backups are
never pruned. Restore: verify the file with `pg_restore --list`, back up the current data, restore into a temporary
database, stop the engine, swap the databases by renaming, start the engine; if the engine fails on the restored data
the previous database is renamed back. Before-update backups run after Postgres starts and before the engine (and its
migrations) when `config.json`'s `lastVersion` differs from the app version. Import (`backend/database/import_pkos.py`,
`POST /import/pkos`, desktop only, localhost only): read-only repeatable-read snapshot of the source, one transaction
on the target, users skipped when their ID, email or username exists, fresh `chunk_id`s with every reference rewritten,
only common columns, AI settings not copied; a dry run reports what would happen. "Copy diagnostics" masks API keys,
tokens, passwords and email addresses. Tests: 7 import (pytest), 10 backup/diagnostics/config (node:test), 6 UI
(Vitest). Real run on this PC (dev vault): automatic pre-update backup, manual backup, import of the old Docker
database (7 accounts, 7 documents, 4,792 passages, 3,522 concepts, 7,418 relationships in 5.6 s; a second run imported
nothing), restore of the pre-import backup (imported accounts gone again), diagnostics free of emails/keys/tokens.

- D5-1 Backup/export: bundled `pg_dump`; "Export vault" in Settings writes to `backups\`; "Restore" with confirmation.
- D5-2 Automatic backup before every app update that includes migrations.
- D5-3 Import tool: Settings → "Import from existing PKOS" asks for host/port/user/password/database (default `localhost:5433`, `pkos_v2`), checks the schema version, then copies users, documents, chunks with their vectors, entities, relations, junctions, communities and graph jobs in one transaction. Vectors are copied as-is (same embedding model, no re-embedding). Rows keep their IDs; a user whose username or email already exists is skipped and reported. The source database is only read, never changed. A backup of the app database is taken first. Tests: import a seeded source DB, re-run (no duplicates), clash handling.
- D5-4 Log viewer / "Copy diagnostics" for bug reports (no API keys or document text in it).

### Phase 6: Verification and release

**Status (2026-11-21): done except a real second PC and a signed release.** App icon (`packaging/make-icon.ps1`), version
0.2.0. Findings and fixes:
- **Unicode install path broke first start**: `initdb` embeds its share path in SQL in the ANSI codepage, so an install
  under `C:\Users\Jürgen\...` failed with "invalid byte sequence for encoding UTF8". Now initdb gets an ASCII copy of
  `share` (`-L`) when needed; the server itself runs fine from such paths. Verified: app in `D:\PKOS Test Ünï`, data in
  `PKOS test ü dir`, user "Jürgen Ünïcode", file `gletscher ü.txt` indexed, backup written.
- **Clean-PC dependencies** (Windows Home has no Sandbox): `packaging/audit-dlls.ps1` reads every bundled binary's import
  and delay-import tables; it found the PL/Perl, PL/Python and PL/Tcl plugins needing Perl/Python/Tcl, now left out.
  Result on 490 binaries: everything bundled or part of Windows (Vulkan from the GPU driver is optional).
- `build.ps1 -Skip a,b` via `powershell -File` was ignored (one string); now split.
Verified on this PC: backend killed mid graph job → supervisor restarted it on the same port, the job resumed at chunk
1/10 and completed (26 concepts, 52 relationships); a second launch exits in 0.5 s without a second database;
**upgrade 0.1.0 → 0.2.0** over an existing vault: one uninstall entry, still signed in, documents intact, automatic
`before-update` backup taken before migrations, migration 0002 applied; silent uninstall keeps the data.
`.github/workflows/release.yml` builds the installer on a clean `windows-2025` runner (official PostgreSQL 16.13
binaries, Ollama 0.32.14, pgvector compiled, DLL audit) and uploads it as an artifact; **not run yet** (needs a push).
Still open: a test on a second PC, the interactive "delete my data" prompt, code signing.

**PDF engine switch (0.3.0, 2026-11-22).** PyMuPDF (AGPL-3.0) was replaced by pypdfium2 5.15.0 (Apache-2.0/BSD), so PKOS
is now MIT-licensed (`LICENSE`). Evidence, on 13 test PDFs made with Chromium (embedded fonts, justified and hyphenated
text, two columns, tables, ligatures, scripts, running heads) run through the real pipeline (extract → header strip →
clean): 7 word-for-word identical to PyMuPDF (prose, two columns, ligatures, code, pages without text), table pages
99.4–99.6% (the few extra tokens are table values the old code dropped as "page numbers"), multilingual 97.9%.
Speed is not a factor: 200 pages / 700k characters take 0.57 s (PDFium) vs 0.44 s (PyMuPDF), against ~30 s to embed the
same text. What was found and handled:
- PDFium's `get_text_range()` returns one character per line on pages with individually positioned glyphs, so
  `get_text_bounded()` is used; it still drops the spaces between words in Chromium-made **tables** (`MerdeGlace2.7315`;
  only 10-20% of the words correct). Pages whose words average over 9 characters are rebuilt from PDFium's per-character
  boxes (spaces and line breaks from geometry, PDFium's order kept); the gap threshold was swept (every value 0.06-0.12
  gives identical words, 0.10 used) and the rebuild is kept only if it is clearly better. Table rows now come out as one
  line each.
- Known remaining differences: right-to-left text (Arabic) comes out in visual instead of logical order, a few Indic
  clusters get extra spaces, and PDFium refuses some truncated PDFs that PyMuPDF repaired. Unreadable and
  password-protected PDFs now fail with a clear message ("This PDF is password-protected...") instead of
  "Indexing failed. Please retry.".
- 13 new pytest tests with committed Chromium fixtures (`backend/tests/data`, regenerate with `make_pdf_fixtures.js`);
  `pkos-api.exe --smoke-test` now reads a PDF, which proves the native PDFium library is bundled.
- Not covered: PDFs from other generators (LaTeX, Word, scanners) were not available as test inputs; scanned PDFs have
  no text layer and need OCR, which neither engine does.

- D6-1 Clean-machine test in Windows Sandbox or a fresh VM: install, first run, register, both wizard paths, upload, query, graph, restart, uninstall.
- D6-2 Edge cases: port already taken, existing Ollama on 11434, no internet during model download, disk full, app killed mid-indexing (worker resumes), PC sleep/resume.
- D6-3 CI: GitHub Actions `windows-latest` job builds the installer as an artifact on tags.
- D6-4 Docs: README "Desktop app" section, update architecture and SRS.

## 5. Order and estimate

| Phase | Depends on | Rough effort |
|---|---|---|
| 0 Spikes | – | 2 days |
| 1 Backend | 0 | 4–5 days |
| 2 Electron shell | 0 | 3–4 days |
| 3 Frontend | 1 (API), 2 (preload) | 3–4 days |
| 4 Packaging | 1–3 | 2–3 days |
| 5 Data safety | 2 | 2 days |
| 6 Verification | all | 2–3 days |

Phases 1 and 2 can run in parallel after the spikes. Docker and the web build keep working throughout; the desktop app is an extra target, not a replacement.

## 6. Risks

| Risk | Mitigation |
|---|---|
| No reliable pgvector build for Windows | Spike D0-1 first; fallback is building it in CI with MSVC |
| Installer large (about 1–1.3 GB) because of torch and CUDA | CPU-only torch, strip unused torch modules and tests in the PyInstaller spec, drop ROCm; fastembed remains a fallback if size becomes a problem |
| Antivirus flags unsigned PyInstaller/Electron binaries | Code signing; onedir (not onefile) builds are flagged less |
| Low-RAM PCs cannot run llama3.2 | Wizard shows RAM needs, offers a smaller model (e.g. `llama3.2:1b`) or the API path |
| Graph extraction cost with cloud APIs | Show a warning with an estimated token count before indexing large uploads in API mode |
| Postgres data corruption on hard power-off | Postgres WAL handles it; plus automatic backups (D5) |

## 7. Answered questions

- Q1 Embeddings: keep sentence-transformers (CPU torch).
- Q2 GPU: include NVIDIA libraries, drop AMD.
- Q3 Signing: unsigned for now.
- Q4 Import: yes, add a one-time import tool (D5-3).
