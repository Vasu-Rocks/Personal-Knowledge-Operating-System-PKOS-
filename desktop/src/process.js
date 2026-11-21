'use strict';
// Child process plumbing: spawn without a console window, append output to a log file, kill whole process trees.
const { spawn, execFile } = require('child_process');
const EventEmitter = require('events');
const fs = require('fs');
const path = require('path');

const MAX_LOG_BYTES = 10 * 1024 * 1024;

/** Opens logs/<name>.log for appending, rotating it to <name>.log.1 once it passes 10 MB. */
function openLog(logDir, name) {
  fs.mkdirSync(logDir, { recursive: true });
  const file = path.join(logDir, `${name}.log`);
  try {
    if (fs.statSync(file).size > MAX_LOG_BYTES) fs.renameSync(file, `${file}.1`);
  } catch { /* no log yet */ }
  const stream = fs.createWriteStream(file, { flags: 'a' });
  stream.write(`\n===== ${new Date().toISOString()} =====\n`);
  return stream;
}

/** Runs a command to completion (initdb, createdb, pg_ctl ...). Resolves { code, stdout, stderr }. */
function run(command, args, { env, cwd, timeoutMs = 120000, log } = {}) {
  return new Promise((resolve) => {
    execFile(command, args, { env, cwd, timeout: timeoutMs, windowsHide: true, maxBuffer: 10 * 1024 * 1024 },
      (err, stdout, stderr) => {
        if (log) log.write(`$ ${path.basename(command)} ${args.join(' ')}\n${stdout}${stderr}`);
        resolve({ code: err ? (typeof err.code === 'number' ? err.code : 1) : 0, stdout, stderr, error: err });
      });
  });
}

/** Kills a process and all its children (Ollama spawns runner processes; plain kill would orphan them). */
function killTree(pid) {
  return new Promise((resolve) => {
    if (!pid) return resolve();
    if (process.platform === 'win32') {
      execFile('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true }, () => resolve());
    } else {
      try { process.kill(pid, 'SIGTERM'); } catch { /* already gone */ }
      resolve();
    }
  });
}

/**
 * A long-running child process. Emits 'exit' ({ code, signal, expected }) when it ends;
 * `expected` is true when stop() was called.
 */
class ManagedProcess extends EventEmitter {
  constructor({ name, command, args = [], env, cwd, log }) {
    super();
    Object.assign(this, { name, command, args, env, cwd, log });
    this.child = null;
    this.stopping = false;
  }

  start() {
    if (!fs.existsSync(this.command)) throw new Error(`${this.name}: ${this.command} not found`);
    this.stopping = false;
    const child = spawn(this.command, this.args, {
      env: this.env, cwd: this.cwd, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    });
    this.child = child;
    child.stdout.pipe(this.log, { end: false });
    child.stderr.pipe(this.log, { end: false });
    child.on('error', (err) => this.log.write(`[pkos] spawn error: ${err.message}\n`));
    child.on('exit', (code, signal) => {
      this.log.write(`[pkos] ${this.name} exited (code ${code}, signal ${signal})\n`);
      if (this.child === child) this.child = null;
      this.emit('exit', { code, signal, expected: this.stopping });
    });
    return child;
  }

  get running() {
    return this.child !== null;
  }

  /** Optional graceful step first (e.g. pg_ctl stop), then the process tree is killed if still alive. */
  async stop({ graceful, timeoutMs = 15000 } = {}) {
    this.stopping = true;
    const child = this.child;
    if (!child) return;
    const exited = new Promise((r) => child.once('exit', r));
    if (graceful) {
      try { await graceful(); } catch (e) { this.log.write(`[pkos] graceful stop failed: ${e.message}\n`); }
      const done = await Promise.race([exited.then(() => true), new Promise((r) => setTimeout(() => r(false), timeoutMs))]);
      if (done) return;
    }
    await killTree(child.pid);
    await Promise.race([exited, new Promise((r) => setTimeout(r, 5000))]);
  }
}

module.exports = { ManagedProcess, openLog, run, killTree };
