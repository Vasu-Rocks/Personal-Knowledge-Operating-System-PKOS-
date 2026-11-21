'use strict';
// "Copy diagnostics": versions, service states and the last log lines, with secrets and personal details masked,
// so a bug report never carries API keys, tokens, passwords or email addresses.
const fs = require('fs');
const os = require('os');
const path = require('path');

const LOGS = ['desktop.log', 'backend.log', 'api.log', 'postgres.log', 'ollama.log'];
const TAIL = 40;

const REDACTIONS = [
  [/\b(sk-(?:ant-)?[A-Za-z0-9_-]{6})[A-Za-z0-9_-]+/g, '$1…'], // OpenAI / Anthropic keys
  [/(Bearer\s+)[A-Za-z0-9._-]+/gi, '$1…'],
  [/(\b(?:password|passwd|pwd|secret|token|api[_-]?key|PGPASSWORD|PKOS_SECRET_KEY)\b["']?\s*[:=]\s*["']?)[^\s"',}]+/gi, '$1…'],
  [/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+/g, '…jwt…'],
  [/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, '…@…'],
];

function redact(text) {
  return REDACTIONS.reduce((t, [re, rep]) => t.replace(re, rep), text);
}

function tail(file, lines = TAIL) {
  try {
    const data = fs.readFileSync(file, 'utf8');
    return data.split(/\r?\n/).filter(Boolean).slice(-lines).join('\n');
  } catch {
    return '(no log)';
  }
}

function collectDiagnostics({ appVersion, electronVersion, paths, snapshot }) {
  const out = [];
  out.push(`PKOS ${appVersion} (Electron ${electronVersion})`);
  out.push(`Windows ${os.release()} ${os.arch()}, ${os.cpus().length} CPUs, ${(os.totalmem() / 2 ** 30).toFixed(1)} GB RAM`);
  try {
    const ollamaVersion = fs.readFileSync(path.join(path.dirname(paths.ollamaExe), 'VERSION'), 'utf8').trim();
    out.push(`Bundled Ollama ${ollamaVersion}`);
  } catch { /* dev build */ }
  if (snapshot) {
    out.push(`Ollama mode: ${snapshot.ollamaMode || 'unknown'}${snapshot.fatal ? `; error: ${snapshot.fatal}` : ''}`);
    for (const [name, s] of Object.entries(snapshot.services)) out.push(`  ${name}: ${s.status}${s.detail ? ` (${s.detail})` : ''}`);
  }
  for (const log of LOGS) {
    out.push('', `----- ${log} (last ${TAIL} lines) -----`, tail(path.join(paths.logs, log)));
  }
  return redact(out.join('\n'));
}

module.exports = { collectDiagnostics, redact };
