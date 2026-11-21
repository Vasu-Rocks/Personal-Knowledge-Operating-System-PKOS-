'use strict';
// Where everything lives. Packaged: bundled runtimes under process.resourcesPath, data in %LOCALAPPDATA%\PKOS.
// Dev (`npm run dev` or an unpackaged run): runtimes from the repo (build/spike from Phase 0, the venv, the backend
// sources), data in %LOCALAPPDATA%\PKOS-dev so development never touches a real vault.
// Every location can be overridden with an environment variable (PKOS_PG_DIR, PKOS_OLLAMA_DIR, ...).
const path = require('path');
const os = require('os');

function resolvePaths({ packaged, resourcesPath, repoRoot = path.resolve(__dirname, '..', '..'), env = process.env }) {
  const localAppData = env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
  const dataDir = env.PKOS_DATA_DIR || path.join(localAppData, packaged ? 'PKOS' : 'PKOS-dev');
  const res = (...p) => path.join(resourcesPath || '', ...p);
  const repo = (...p) => path.join(repoRoot, ...p);

  return {
    packaged,
    dataDir,
    pgData: path.join(dataDir, 'pgdata'),
    ollamaModels: path.join(dataDir, 'ollama'),
    logs: path.join(dataDir, 'logs'),
    backups: path.join(dataDir, 'backups'),
    configFile: path.join(dataDir, 'config.json'),
    electronData: path.join(dataDir, 'electron'),

    pgBin: env.PKOS_PG_DIR ? path.join(env.PKOS_PG_DIR, 'bin') : (packaged ? res('pgsql', 'bin') : repo('build', 'spike', 'pgsql', 'bin')),
    ollamaExe: path.join(env.PKOS_OLLAMA_DIR || (packaged ? res('ollama') : repo('build', 'spike', 'ollama')), 'ollama.exe'),
    // Packaged: the PyInstaller build. Dev: the venv's Python running backend/desktop_entry.py.
    backend: packaged && !env.PKOS_PYTHON
      ? { command: res('pkos-api', 'pkos-api.exe'), args: [], cwd: res('pkos-api') }
      : {
          command: env.PKOS_PYTHON || repo('venv', 'Scripts', 'python.exe'),
          args: [path.join(env.PKOS_BACKEND_DIR || repo('backend'), 'desktop_entry.py')],
          cwd: env.PKOS_BACKEND_DIR || repo('backend'),
        },
    webDir: env.PKOS_WEB_DIR || (packaged ? res('web') : repo('frontend', 'dist')),
    // Bundled embedding model (packaged only); dev uses the normal Hugging Face cache.
    embedModelDir: env.PKOS_EMBED_MODEL_DIR || (packaged ? res('models', 'bge-small-en-v1.5') : null),
    // Dev only: load the Vite dev server (hot reload) instead of the built files.
    devUrl: packaged ? null : (env.PKOS_DEV_URL || null),
  };
}

module.exports = { resolvePaths };
