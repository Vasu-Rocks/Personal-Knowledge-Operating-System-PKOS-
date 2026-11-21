'use strict';
// The three background services and the supervisor that starts them in order, restarts crashed ones and stops
// them on quit. Every service listens on 127.0.0.1 only; ports are picked at first start and kept for the
// session, so a restarted service comes back on the same address.
const EventEmitter = require('events');
const fs = require('fs');
const path = require('path');
const { ManagedProcess, killTree, openLog, run } = require('./process');
const { getFreePort, httpGet, waitFor } = require('./net-util');

const isAscii = (p) => /^[\x20-\x7e]*$/.test(p);

/**
 * initdb puts the path of its share folder into SQL (a COPY ... FROM '<share>\postgres.description'), and Windows
 * passes that path in the ANSI codepage: with an install folder like C:\Users\Jürgen\... it fails with "invalid byte
 * sequence for encoding UTF8". The server itself runs fine from such a folder. So when the install path is not plain
 * ASCII, initdb gets a temporary ASCII copy of share (-L). Returns the first ASCII candidate folder, or null.
 */
function asciiScratchDir({ dataDir, tmpDir = require('os').tmpdir(), env = process.env }) {
  const candidates = [
    path.join(dataDir, '.initdb'),
    path.join(tmpDir, 'pkos-initdb'),
    path.join(env.ProgramData || 'C:\\ProgramData', 'PKOS', 'initdb'),
    path.join(env.PUBLIC || 'C:\\Users\\Public', 'PKOS-initdb'),
  ];
  return candidates.find(isAscii) || null;
}

const RESTART_LIMIT = 3;
const RESTART_WINDOW_MS = 10 * 60 * 1000;

class PostgresService {
  constructor({ paths, cfg }) {
    this.name = 'postgres';
    this.label = 'Database';
    this.paths = paths;
    this.cfg = cfg;
    this.port = null;
    this.proc = null;
    this.log = openLog(paths.logs, 'postgres');
  }

  bin(exe) {
    return path.join(this.paths.pgBin, exe);
  }

  get env() {
    return { ...process.env, PGPASSWORD: this.cfg.dbPassword, PGCONNECT_TIMEOUT: '5' };
  }

  async ensureCluster() {
    if (fs.existsSync(path.join(this.paths.pgData, 'PG_VERSION'))) return;
    fs.mkdirSync(path.dirname(this.paths.pgData), { recursive: true });
    const pwfile = path.join(this.paths.dataDir, `.pw-${process.pid}`);
    fs.writeFileSync(pwfile, this.cfg.dbPassword, { mode: 0o600 });
    const args = ['-D', this.paths.pgData, '-U', this.cfg.dbUser, `--pwfile=${pwfile}`, '-E', 'UTF8', '--locale=C', '-A', 'scram-sha-256'];
    let shareCopy = null;
    try {
      const share = path.join(this.paths.pgBin, '..', 'share');
      if (!isAscii(path.resolve(share))) {
        const scratch = asciiScratchDir({ dataDir: this.paths.dataDir });
        if (!scratch) throw new Error('PKOS is installed in a folder whose name has non-English characters, and no plain folder was found for database setup. Reinstall PKOS into a folder like C:\\PKOS.');
        shareCopy = path.join(scratch, `share-${process.pid}`);
        fs.rmSync(shareCopy, { recursive: true, force: true });
        fs.cpSync(share, shareCopy, { recursive: true });
        args.push('-L', shareCopy);
        this.log.write(`[pkos] install path is not ASCII; initdb uses a copy of share in ${shareCopy}\n`);
      }
      const r = await run(this.bin('initdb.exe'), args, { env: this.env, log: this.log, timeoutMs: 180000 });
      if (r.code !== 0) throw new Error(`initdb failed (code ${r.code}); see logs/postgres.log`);
    } finally {
      fs.rmSync(pwfile, { force: true });
      if (shareCopy) fs.rmSync(shareCopy, { recursive: true, force: true });
    }
  }

  /** A previous run that crashed can leave postgres running or a stale postmaster.pid behind. */
  async clearLeftovers() {
    const pidFile = path.join(this.paths.pgData, 'postmaster.pid');
    if (!fs.existsSync(pidFile)) return;
    const status = await run(this.bin('pg_ctl.exe'), ['status', '-D', this.paths.pgData], { env: this.env, log: this.log });
    if (status.code === 0) {
      this.log.write('[pkos] a postgres from a previous session is still running; stopping it\n');
      await run(this.bin('pg_ctl.exe'), ['stop', '-D', this.paths.pgData, '-m', 'fast', '-w'], { env: this.env, log: this.log });
    } else if (status.code === 3) {
      fs.rmSync(pidFile, { force: true });
    }
  }

  async start() {
    if (!fs.existsSync(this.bin('postgres.exe'))) throw new Error(`PostgreSQL not found at ${this.paths.pgBin}`);
    await this.ensureCluster();
    await this.clearLeftovers();
    this.port = this.port || await getFreePort();
    this.proc = new ManagedProcess({
      name: 'postgres', command: this.bin('postgres.exe'), env: this.env, cwd: this.paths.pgBin, log: this.log,
      args: ['-D', this.paths.pgData, '-p', String(this.port), '-c', 'listen_addresses=127.0.0.1', '-c', 'max_connections=50'],
    });
    this.proc.start();
    await waitFor(async () => (await run(this.bin('pg_isready.exe'),
      ['-q', '-h', '127.0.0.1', '-p', String(this.port), '-U', this.cfg.dbUser], { env: this.env })).code === 0,
    { timeoutMs: 60000, what: 'Database', isAborted: () => !this.proc.running });
    await this.ensureDatabase();
    return this.proc;
  }

  async ensureDatabase() {
    const conn = ['-h', '127.0.0.1', '-p', String(this.port), '-U', this.cfg.dbUser];
    const q = await run(this.bin('psql.exe'), [...conn, '-d', 'postgres', '-tAc',
      `SELECT 1 FROM pg_database WHERE datname = '${this.cfg.dbName}'`], { env: this.env, log: this.log });
    if (q.code !== 0) throw new Error('Could not query the database server; see logs/postgres.log');
    if (q.stdout.trim() !== '1') {
      const c = await run(this.bin('createdb.exe'), [...conn, this.cfg.dbName], { env: this.env, log: this.log });
      if (c.code !== 0) throw new Error('Could not create the PKOS database; see logs/postgres.log');
    }
  }

  async stop() {
    if (!this.proc) return;
    await this.proc.stop({
      graceful: () => run(this.bin('pg_ctl.exe'), ['stop', '-D', this.paths.pgData, '-m', 'fast', '-w', '-t', '20'],
        { env: this.env, log: this.log }),
      timeoutMs: 25000,
    });
  }
}

class OllamaService {
  constructor({ paths, cfg }) {
    this.name = 'ollama';
    this.label = 'Local AI (Ollama)';
    this.paths = paths;
    this.cfg = cfg;
    this.port = null;
    this.proc = null;
    this.url = null;
    this.mode = null; // 'bundled' | 'external' | 'unavailable'
    this.optional = true; // the app still works with a cloud API key
    this.log = openLog(paths.logs, 'ollama');
  }

  async probe(url) {
    try {
      return (await httpGet(`${url}/api/version`, 1500)).status === 200;
    } catch {
      return false;
    }
  }

  /** A bundled Ollama left running by a previous session that was killed: stop it (only if it is our exe). */
  async clearLeftover() {
    const pidFile = path.join(this.paths.dataDir, 'ollama.pid');
    if (!fs.existsSync(pidFile)) return;
    const pid = Number(fs.readFileSync(pidFile, 'utf8'));
    fs.rmSync(pidFile, { force: true });
    if (!pid || process.platform !== 'win32') return;
    const r = await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
      `(Get-Process -Id ${pid} -ErrorAction SilentlyContinue).Path`]);
    if (r.stdout.trim().toLowerCase() === path.resolve(this.paths.ollamaExe).toLowerCase()) {
      this.log.write(`[pkos] stopping leftover bundled Ollama (pid ${pid})\n`);
      await killTree(pid);
    }
  }

  async start() {
    const mode = process.env.PKOS_OLLAMA_MODE || this.cfg.ollamaMode || 'auto';
    const external = 'http://127.0.0.1:11434';
    await this.clearLeftover();
    if (mode !== 'bundled' && await this.probe(external)) {
      this.log.write('[pkos] using the Ollama already running on 127.0.0.1:11434\n');
      Object.assign(this, { url: external, mode: 'external' });
      return null;
    }
    if (mode === 'external' || !fs.existsSync(this.paths.ollamaExe)) {
      this.log.write(`[pkos] no Ollama available (mode ${mode}, bundled exe ${fs.existsSync(this.paths.ollamaExe) ? 'present' : 'missing'})\n`);
      Object.assign(this, { url: external, mode: 'unavailable' });
      return null;
    }
    this.port = this.port || await getFreePort();
    this.url = `http://127.0.0.1:${this.port}`;
    this.mode = 'bundled';
    fs.mkdirSync(this.paths.ollamaModels, { recursive: true });
    this.proc = new ManagedProcess({
      name: 'ollama', command: this.paths.ollamaExe, args: ['serve'], cwd: path.dirname(this.paths.ollamaExe), log: this.log,
      env: { ...process.env, OLLAMA_HOST: `127.0.0.1:${this.port}`, OLLAMA_MODELS: this.paths.ollamaModels },
    });
    const child = this.proc.start();
    fs.writeFileSync(path.join(this.paths.dataDir, 'ollama.pid'), String(child.pid));
    await waitFor(() => this.probe(this.url), { timeoutMs: 60000, what: 'Ollama', isAborted: () => !this.proc.running });
    return this.proc;
  }

  async stop() {
    if (!this.proc) return;
    await this.proc.stop(); // kills the whole tree, including model runner processes
    fs.rmSync(path.join(this.paths.dataDir, 'ollama.pid'), { force: true });
  }
}

class BackendService {
  constructor({ paths, cfg, getDeps }) {
    this.name = 'backend';
    this.label = 'PKOS engine';
    this.paths = paths;
    this.cfg = cfg;
    this.getDeps = getDeps;
    this.port = null;
    this.proc = null;
    this.log = openLog(paths.logs, 'backend');
  }

  get url() {
    return this.port ? `http://127.0.0.1:${this.port}` : null;
  }

  async start() {
    const { pgPort, ollamaUrl, origins } = this.getDeps();
    this.port = this.port || await getFreePort();
    const env = {
      ...process.env,
      ENV: 'desktop',
      PKOS_SECRET_KEY: this.cfg.secretKey,
      PKOS_DATA_DIR: this.paths.dataDir,
      PKOS_API_PORT: String(this.port),
      POSTGRES_HOST: '127.0.0.1',
      POSTGRES_PORT: String(pgPort),
      POSTGRES_USER: this.cfg.dbUser,
      POSTGRES_PASSWORD: this.cfg.dbPassword,
      POSTGRES_DB: this.cfg.dbName,
      OLLAMA_BASE_URL: ollamaUrl,
      CORS_ORIGINS: origins.join(','),
      PKOS_PARENT_PID: String(process.pid), // backend exits if this app dies without stopping it
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
    };
    if (this.paths.embedModelDir && fs.existsSync(path.join(this.paths.embedModelDir, 'model.safetensors'))) {
      // Load the bundled model from disk and never contact Hugging Face (offline, private).
      env.PKOS_EMBED_MODEL = this.paths.embedModelDir;
      env.HF_HUB_OFFLINE = '1';
      env.TRANSFORMERS_OFFLINE = '1';
      env.HF_HUB_DISABLE_TELEMETRY = '1';
    } else if (!this.paths.packaged) {
      // Dev: reuse the normal Hugging Face cache instead of downloading the embedding model into the dev data folder.
      env.PKOS_EMBED_CACHE_DIR = process.env.PKOS_EMBED_CACHE_DIR
        || path.join(process.env.HF_HOME || path.join(require('os').homedir(), '.cache', 'huggingface'), 'hub');
    }
    const { command, args, cwd } = this.paths.backend;
    this.proc = new ManagedProcess({ name: 'backend', command, args, cwd, env, log: this.log });
    this.proc.start();
    // First launch can be slow: antivirus scans the freshly installed files (measured 76 s in Phase 0).
    await waitFor(async () => (await httpGet(`${this.url}/health`, 3000)).status === 200,
      { timeoutMs: 240000, intervalMs: 700, what: 'PKOS engine', isAborted: () => !this.proc.running });
    return this.proc;
  }

  async stop() {
    if (this.proc) await this.proc.stop(); // state lives in Postgres; the graph worker resumes on next start
  }
}

/**
 * Starts postgres -> ollama -> backend, reports progress via 'status' events, restarts crashed services
 * (up to 3 times in 10 minutes) and stops everything in reverse order.
 */
class Supervisor extends EventEmitter {
  constructor({ paths, cfg, origins, beforeStart = async () => {} }) {
    super();
    this.paths = paths;
    this.beforeStart = beforeStart; // async (serviceName) => {}, e.g. a backup before the backend runs migrations
    this.postgres = new PostgresService({ paths, cfg });
    this.ollama = new OllamaService({ paths, cfg });
    this.backend = new BackendService({
      paths, cfg,
      getDeps: () => ({ pgPort: this.postgres.port, ollamaUrl: this.ollama.url, origins }),
    });
    this.services = [this.postgres, this.ollama, this.backend];
    this.state = Object.fromEntries(this.services.map((s) => [s.name, { label: s.label, status: 'pending', detail: '' }]));
    this.crashes = Object.fromEntries(this.services.map((s) => [s.name, []]));
    this.quitting = false;
    this.fatal = null;
  }

  snapshot() {
    return {
      services: JSON.parse(JSON.stringify(this.state)),
      apiBase: this.backend.url,
      ollamaMode: this.ollama.mode,
      fatal: this.fatal,
    };
  }

  set(name, status, detail = '') {
    this.state[name] = { ...this.state[name], status, detail };
    this.emit('status', this.snapshot());
  }

  async startService(svc) {
    if (svc.proc && svc.proc.running && this.state[svc.name].status === 'running') return; // retry after a later step failed
    this.set(svc.name, 'starting');
    try {
      const proc = await svc.start();
      if (proc) proc.once('exit', ({ expected }) => { if (!expected && !this.quitting) this.onCrash(svc); });
      const detail = svc === this.ollama
        ? { bundled: 'Bundled', external: 'Using your installed Ollama', unavailable: 'Not available (cloud API only)' }[svc.mode]
        : '';
      this.set(svc.name, svc === this.ollama && svc.mode === 'unavailable' ? 'degraded' : 'running', detail);
    } catch (e) {
      if (svc.optional) {
        this.set(svc.name, 'degraded', e.message);
        return;
      }
      this.set(svc.name, 'failed', e.message);
      throw e;
    }
  }

  async startAll() {
    this.fatal = null;
    for (const svc of this.services) {
      if (this.quitting) return;
      if (!(svc.proc && svc.proc.running)) await this.beforeStart(svc.name);
      await this.startService(svc);
    }
  }

  async onCrash(svc) {
    const now = Date.now();
    const recent = this.crashes[svc.name].filter((t) => now - t < RESTART_WINDOW_MS);
    recent.push(now);
    this.crashes[svc.name] = recent;
    if (recent.length > RESTART_LIMIT) {
      this.fatal = `${svc.label} keeps crashing. See the logs folder for details.`;
      this.set(svc.name, 'failed', 'Crashed repeatedly');
      return;
    }
    this.set(svc.name, 'restarting', `Restart ${recent.length} of ${RESTART_LIMIT}`);
    try {
      await this.startService(svc);
    } catch (e) {
      this.fatal = `${svc.label} could not be restarted: ${e.message}`;
      this.emit('status', this.snapshot());
    }
  }

  /** Stop/start just the backend (used by restore, which swaps the database underneath it). */
  async stopBackend() {
    await this.backend.stop(); // an expected exit, so it is not treated as a crash
    this.set('backend', 'stopped');
  }

  async startBackend() {
    this.crashes.backend = [];
    await this.startService(this.backend);
  }

  async restartAll() {
    await this.stopAll({ quitting: false });
    for (const name of Object.keys(this.crashes)) this.crashes[name] = [];
    await this.startAll();
  }

  async stopAll({ quitting = true } = {}) {
    this.quitting = quitting;
    for (const svc of [...this.services].reverse()) {
      try {
        await svc.stop();
      } catch (e) {
        svc.log.write(`[pkos] stop failed: ${e.message}\n`);
      }
      this.set(svc.name, 'stopped');
    }
    this.quitting = quitting;
  }
}

module.exports = { Supervisor, PostgresService, OllamaService, BackendService, asciiScratchDir, isAscii };
