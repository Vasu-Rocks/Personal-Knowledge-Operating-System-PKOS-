'use strict';
// Phone access (docs/08_PHONE_ACCESS_PLAN.md): an https server on the local network that serves the PKOS screens to a
// phone's browser and forwards its API calls to the backend, which itself keeps listening on 127.0.0.1 only. This is
// the only door from the network: it is off until the user switches it on, and it forwards only the paths a phone may
// use (laptop-only settings are refused here, not just hidden).
const fs = require('fs');
const http = require('http');
const https = require('https');
const os = require('os');
const path = require('path');
const { execFile } = require('child_process');

const DEFAULT_PORT = 47100;   // fixed, so a bookmark on the phone keeps working
const RENEW_BEFORE_DAYS = 30;
const LAPTOP_ONLY = 'This can only be changed on the laptop.';
const NOT_REACHABLE = 'PKOS on the laptop is starting or not reachable. Try again in a moment.';

// What a phone may call: everyday use (decision P-Q4). Anything not listed - changing the AI model or API keys,
// downloading or deleting models, importing another database - is refused. New endpoints are refused until added.
const ALLOWED = [
  ['POST', /^\/login$/], ['POST', /^\/register$/], ['GET', /^\/me$/],
  ['GET', /^\/documents$/], ['POST', /^\/upload$/], ['DELETE', /^\/documents\/[^/]+$/],
  ['POST', /^\/query\/stream$/],
  ['GET', /^\/conversations$/], ['POST', /^\/conversations$/],
  ['GET', /^\/conversations\/[^/]+$/], ['PATCH', /^\/conversations\/[^/]+$/], ['DELETE', /^\/conversations\/[^/]+$/],
  ['GET', /^\/memories(\/settings)?$/], ['PUT', /^\/memories\/settings$/], ['POST', /^\/memories$/],
  ['PATCH', /^\/memories\/[^/]+$/], ['POST', /^\/memories\/[^/]+\/confirm$/], ['DELETE', /^\/memories(\/[^/]+)?$/],
  ['POST', /^\/transcribe$/], ['POST', /^\/ocr$/],
  ['GET', /^\/graph\/[a-z-]+$/], ['GET', /^\/graph\/entity\/[^/]+$/],
  ['POST', /^\/graph\/(rebuild|cluster|summarize)$/], ['POST', /^\/graph\/jobs\/[^/]+\/(start|pause)$/],
  ['POST', /^\/graph\/same-concepts\/[^/]+$/],
  // Read-only views the screens need (status badge, settings shown read-only); changing them is laptop-only.
  ['GET', /^\/llm\/status$/], ['GET', /^\/system\/status$/], ['GET', /^\/settings\/llm$/], ['GET', /^\/ollama\/models$/],
];

/** May a phone call this API path (the part after /api/v1)? */
function isAllowed(method, apiPath) {
  return ALLOWED.some(([m, re]) => m === method && re.test(apiPath));
}

// Adapters a phone can never reach: virtual machines, WSL/Docker switches, VPN tunnels.
const VIRTUAL = /vEthernet|WSL|Hyper-V|VirtualBox|VMware|Docker|WARP|Cloudflare|Tailscale|ZeroTier|OpenVPN|WireGuard|TAP-|Npcap|Loopback/i;

/** The laptop's IPv4 addresses on local networks (Wi-Fi, Mobile Hotspot, Ethernet), with the adapter name. */
function localAddresses(interfaces = os.networkInterfaces()) {
  const found = [];
  for (const [name, list] of Object.entries(interfaces || {})) {
    if (VIRTUAL.test(name)) continue;
    for (const a of list || []) {
      const v4 = a.family === 'IPv4' || a.family === 4;
      if (v4 && !a.internal && !a.address.startsWith('169.254.')) found.push({ address: a.address, name });
    }
  }
  // The Windows Mobile Hotspot address first: it is the one a phone on the laptop's hotspot uses.
  return found.sort((x, y) => (y.address === '192.168.137.1') - (x.address === '192.168.137.1'));
}

function readCertificate(dir) {
  try {
    return {
      key: fs.readFileSync(path.join(dir, 'key.pem')),
      cert: fs.readFileSync(path.join(dir, 'cert.pem')),
      meta: JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8')),
    };
  } catch {
    return null;
  }
}

/** Does the certificate cover these addresses and stay valid for a while? */
function certificateFits(existing, addresses, now = Date.now()) {
  if (!existing || !existing.meta || !Array.isArray(existing.meta.addresses)) return false;
  const expires = Date.parse(existing.meta.not_after);
  if (!Number.isFinite(expires) || expires - now < RENEW_BEFORE_DAYS * 86400000) return false;
  return addresses.every((a) => existing.meta.addresses.includes(a));
}

/** The certificate for the given addresses; makeCert(dir, addresses) is asked for a new one when needed. */
async function ensureCertificate({ dir, addresses, makeCert }) {
  const existing = readCertificate(dir);
  if (certificateFits(existing, addresses)) return existing;
  // Keep the addresses it already had (a phone that accepted it there need not accept it again soon).
  const keep = existing && existing.meta && Array.isArray(existing.meta.addresses) ? existing.meta.addresses : [];
  await makeCert(dir, [...new Set([...addresses, ...keep])].filter((a) => a !== '127.0.0.1'));
  const made = readCertificate(dir);
  if (!made) throw new Error('PKOS could not create the certificate for phone access.');
  return made;
}

/** makeCert using the bundled backend (`pkos-api.exe --make-cert` / `python desktop_entry.py --make-cert`). */
function backendCertMaker(backend) {
  return (dir, addresses) => new Promise((resolve, reject) => {
    execFile(backend.command, [...backend.args, '--make-cert', dir, addresses.join(',')],
      { cwd: backend.cwd, timeout: 120000, windowsHide: true }, (err, _stdout, stderr) => {
        if (err) reject(new Error(`certificate: ${String(stderr || err.message).trim().split('\n').pop()}`));
        else resolve();
      });
  });
}

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.ico': 'image/x-icon',
  '.woff': 'font/woff', '.woff2': 'font/woff2', '.webmanifest': 'application/manifest+json', '.txt': 'text/plain',
};

const PAGE_HEADERS = {
  'Content-Security-Policy': [
    "default-src 'self'", "script-src 'self'", "style-src 'self' 'unsafe-inline'", "img-src 'self' data: blob:",
    "font-src 'self' data:", "media-src 'self' blob:", "worker-src 'self' blob:", "connect-src 'self'",
    "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
  ].join('; '),
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'no-referrer',
};

// Hop-by-hop headers, and the ones the phone server sets itself (never trusted from the network).
const DROP = new Set(['connection', 'keep-alive', 'proxy-connection', 'transfer-encoding', 'upgrade', 'te', 'trailer',
  'host', 'origin', 'x-pkos-via', 'x-forwarded-for', 'x-forwarded-proto', 'x-forwarded-host']);

function sendJson(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(text), ...PAGE_HEADERS });
  res.end(text);
}

class PhoneServer {
  /**
   * webDir: the built web UI. getApiBase(): the backend's http://127.0.0.1:<port> (null while it is not running).
   * log: { write(line) }.
   */
  constructor({ webDir, getApiBase, log = { write() {} } }) {
    this.webDir = path.resolve(webDir);
    this.getApiBase = getApiBase;
    this.log = log;
    this.server = null;
    this.port = null;
  }

  get running() {
    return Boolean(this.server && this.server.listening);
  }

  /** Listens on every network interface. tls = { key, cert }. */
  start({ port = DEFAULT_PORT, tls, host = '0.0.0.0' }) {
    if (this.running) return Promise.resolve(this.port);
    const server = https.createServer({ key: tls.key, cert: tls.cert, minVersion: 'TLSv1.2' }, (req, res) => this.handle(req, res));
    server.headersTimeout = 30000;
    server.requestTimeout = 0; // answers stream for minutes on a slow model; the backend has its own limits
    return new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(port, host, () => {
        server.off('error', reject);
        server.on('error', (e) => this.log.write(`[phone] server error: ${e.message}\n`));
        server.on('tlsClientError', () => {}); // a phone that has not accepted the certificate yet: not an error
        this.server = server;
        this.port = server.address().port;
        this.log.write(`[phone] listening on port ${this.port}\n`);
        resolve(this.port);
      });
    });
  }

  /** A new certificate (for example when the laptop joined another network) without dropping open connections. */
  updateCertificate(tls) {
    if (this.server) this.server.setSecureContext({ key: tls.key, cert: tls.cert, minVersion: 'TLSv1.2' });
  }

  stop() {
    if (!this.server) return Promise.resolve();
    const server = this.server;
    this.server = null;
    this.port = null;
    return new Promise((resolve) => {
      server.close(() => resolve());
      if (server.closeAllConnections) server.closeAllConnections(); // a streaming answer must not keep the door open
      this.log.write('[phone] stopped\n');
    });
  }

  handle(req, res) {
    let url;
    try {
      url = new URL(req.url, 'https://phone.invalid');
    } catch {
      return sendJson(res, 400, { detail: 'Bad request.' });
    }
    if (url.pathname === '/api/v1' || url.pathname.startsWith('/api/v1/')) {
      const apiPath = url.pathname.slice('/api/v1'.length) || '/';
      if (!isAllowed(req.method, apiPath)) {
        req.resume();
        return sendJson(res, 403, { detail: LAPTOP_ONLY });
      }
      return this.forward(req, res, url);
    }
    if (url.pathname === '/health') return this.forward(req, res, url);
    if (req.method !== 'GET' && req.method !== 'HEAD') return sendJson(res, 405, { detail: 'Not allowed.' });
    return this.serveFile(req, res, url.pathname);
  }

  forward(req, res, url) {
    const base = this.getApiBase();
    if (!base) {
      req.resume();
      return sendJson(res, 503, { detail: NOT_REACHABLE });
    }
    const target = new URL(base);
    const headers = {};
    for (const [k, v] of Object.entries(req.headers)) if (!DROP.has(k.toLowerCase())) headers[k] = v;
    headers['x-pkos-via'] = 'phone';
    headers['x-forwarded-for'] = req.socket.remoteAddress || '';
    const upstream = http.request({
      hostname: target.hostname, port: target.port, method: req.method, path: url.pathname + url.search, headers,
    }, (up) => {
      const out = {};
      for (const [k, v] of Object.entries(up.headers)) if (!DROP.has(k.toLowerCase())) out[k] = v;
      out['X-Content-Type-Options'] = 'nosniff';
      if (String(up.headers['content-type'] || '').startsWith('text/event-stream')) out['X-Accel-Buffering'] = 'no';
      res.writeHead(up.statusCode || 502, out);
      if (res.flushHeaders) res.flushHeaders();
      up.pipe(res); // streamed: tokens reach the phone as they are made
    });
    upstream.on('error', () => {
      if (!res.headersSent) sendJson(res, 502, { detail: NOT_REACHABLE });
      else res.destroy();
    });
    // The phone went away (closed the tab, lost the hotspot): stop the request, so the answer is saved as partial.
    res.on('close', () => { if (!res.writableFinished) upstream.destroy(); });
    req.pipe(upstream);
  }

  serveFile(req, res, pathname) {
    let rel;
    try {
      rel = decodeURIComponent(pathname);
    } catch {
      return sendJson(res, 400, { detail: 'Bad request.' });
    }
    if (rel === '/' || rel === '') rel = '/index.html';
    let file = path.resolve(this.webDir, `.${rel}`);
    if (!file.startsWith(this.webDir + path.sep)) return sendJson(res, 403, { detail: 'Forbidden.' });
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(this.webDir, 'index.html');
    const isIndex = path.basename(file) === 'index.html';
    let body;
    try {
      body = fs.readFileSync(file);
    } catch {
      return sendJson(res, 404, { detail: 'Not found.' });
    }
    if (isIndex) {
      // Tells the web UI to call the API on this same address (frontend/src/api.js).
      body = Buffer.from(body.toString('utf8').replace('<head>', '<head><meta name="pkos-api" content="same-origin">'));
    }
    res.writeHead(200, {
      'Content-Type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream',
      'Content-Length': body.length,
      'Cache-Control': isIndex ? 'no-store' : 'public, max-age=31536000, immutable',
      ...PAGE_HEADERS,
    });
    res.end(req.method === 'HEAD' ? undefined : body);
  }
}

module.exports = {
  DEFAULT_PORT, LAPTOP_ONLY, PhoneServer, isAllowed, localAddresses, certificateFits, ensureCertificate,
  backendCertMaker, readCertificate,
};
