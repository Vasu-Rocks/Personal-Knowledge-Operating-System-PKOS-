# Building the PKOS Windows installer

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1            # full build -> build\installer\PKOS-Setup-<version>.exe
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Unpacked  # app folder only -> build\installer\win-unpacked
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Skip web,backend,pgsql,ollama,models,licenses   # re-package staged files
```
`npm run dist` in `desktop/` runs the same script.

## What it needs on the build machine
| Input | Default | Notes |
|---|---|---|
| Python venv with backend deps + PyInstaller | `venv\` | `pip install -r backend\requirements.txt pyinstaller` |
| PostgreSQL 16 (EDB) | `C:\Program Files\PostgreSQL\16` (`-PgSource`) | its `include\` is needed to compile pgvector |
| pgvector | compiled from source (`-PgvectorVersion 0.8.1`) | needs VS Build Tools with "Desktop development with C++"; or pass `-PgvectorStage` with a copy that already has it |
| Ollama | `%LOCALAPPDATA%\Programs\Ollama` (`-OllamaSource`) | copies `ollama.exe`, CPU libs, `cuda_v13`, `vulkan` (no ROCm, no CUDA 12) |
| Embedding model | Hugging Face cache (`-HfCache`) | `BAAI/bge-small-en-v1.5`; run the backend once to cache it |
| Node 20+ | | `desktop\` and `frontend\` dependencies (`npm ci`) |

## Steps and output
1. **web**: `npm run build` in `frontend\` → `build\stage\web`
2. **backend**: PyInstaller with `packaging\pkos-api.spec` (onedir) → `build\stage\pkos-api`, then
   `pkos-api.exe --smoke-test` (imports everything, checks the SQL migrations are bundled)
3. **pgsql**: `bin`, `lib`, `share` (+ pgvector) without `.pdb`/`.lib`, plus `vcruntime140*.dll` and `msvcp140.dll`
   (the EDB binaries otherwise depend on a system-wide VC++ runtime) → `build\stage\pgsql`
4. **ollama** → `build\stage\ollama` (with a `VERSION` file)
5. **models** → `build\stage\models\bge-small-en-v1.5` (loaded offline: `HF_HUB_OFFLINE=1`)
6. **licenses**: `packaging\THIRD_PARTY_NOTICES.txt` → `build\stage\licenses`
7. **package**: electron-builder (config in `desktop\package.json` → `build`), NSIS per-user installer
   (no admin rights), install folder selectable, Start menu + desktop shortcuts. `desktop\build-resources\installer.nsh`
   stops PKOS's own background processes before install/uninstall (matched by path, so other PostgreSQL/Ollama
   installs are never touched) and asks on uninstall whether to delete `%LOCALAPPDATA%\PKOS` (default: keep).

Sizes (2026-11-21): web 1 MB, pkos-api 671 MB, pgsql 107 MB, ollama 753 MB, model 128 MB; 1.66 GB staged.

## Other scripts
- `packaging\audit-dlls.ps1 -AppDir build\installer\win-unpacked`: fails if any bundled binary imports a DLL that is
  neither shipped nor part of a clean Windows (e.g. the VC++ runtime). Runs in the release workflow.
- `packaging\make-icon.ps1`: regenerates `desktop\build-resources\icon.ico`/`icon.png`.
- `.github/workflows/release.yml`: builds the installer on a clean GitHub Windows runner on `v*` tags or manually,
  downloading the official PostgreSQL 16 binaries and Ollama; the installer is a workflow artifact.

## Testing a build without installing
```powershell
$env:PKOS_DATA_DIR = "$env:LOCALAPPDATA\PKOS-packtest"   # keep the real vault folder untouched
$env:PKOS_OLLAMA_MODE = "bundled"                         # ignore an installed Ollama
build\installer\win-unpacked\PKOS.exe
```

## Not done yet
- Code signing (installs show the SmartScreen "unknown publisher" warning; "More info" → "Run anyway").
- Auto-update.
- PyMuPDF is AGPL-3.0: distributing the installer to others requires AGPL-compatible terms for PKOS (or a
  commercial PyMuPDF license, or replacing it with a permissively licensed PDF library).
