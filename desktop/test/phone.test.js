'use strict';
// Phone access server (docs/08_PHONE_ACCESS_PLAN.md, step P1). fixtures/phone-cert is a test-only certificate for
// 127.0.0.1 made with `desktop_entry.py --make-cert`; nothing outside these tests uses it.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const https = require('node:https');
const os = require('node:os');
const path = require('node:path');
const { test, before, after } = require('node:test');
const {
  LAPTOP_ONLY, NOT_PAIRED, PhoneServer, certificateFits, ensureCertificate, isAllowed, localAddresses, readCertificate,
} = require('../src/phone');
const { Pairing } = require('../src/pairing');

const FIXTURE = path.join(__dirname, 'fixtures', 'phone-cert');
const TLS = readCertificate(FIXTURE);

// ------------------------------------------------------------------------------------------- what a phone may do

test('everyday use is allowed from a phone', () => {
  for (const [m, p] of [
    ['POST', '/login'], ['POST', '/register'], ['GET', '/me'], ['POST', '/query/stream'], ['GET', '/documents'],
    ['POST', '/upload'], ['DELETE', '/documents/abc'], ['GET', '/conversations'], ['PATCH', '/conversations/x'],
    ['GET', '/memories'], ['POST', '/memories/m1/confirm'], ['PUT', '/memories/settings'], ['DELETE', '/memories'],
    ['POST', '/transcribe'], ['POST', '/ocr'], ['GET', '/graph/map'], ['GET', '/graph/entity/e1'],
    ['POST', '/graph/rebuild'], ['GET', '/llm/status'], ['GET', '/settings/llm'],
  ]) assert.ok(isAllowed(m, p), `${m} ${p} should be allowed`);
});

test('laptop-only settings and unknown paths are refused', () => {
  for (const [m, p] of [
    ['PUT', '/settings/llm'], ['POST', '/settings/llm/test'], ['POST', '/ollama/pull'],
    ['DELETE', '/ollama/models/llama3.2'], ['POST', '/import/pkos'], ['GET', '/something-new'],
    ['GET', '/memories/../settings/llm'], ['POST', '/me'], ['GET', '/conversations/a/b'],
  ]) assert.ok(!isAllowed(m, p), `${m} ${p} should be refused`);
});

test('the laptop addresses: IPv4 on real adapters, the Mobile Hotspot address first', () => {
  const found = localAddresses({
    'Wi-Fi': [{ family: 'IPv4', address: '10.0.0.7', internal: false }, { family: 'IPv6', address: 'fe80::1', internal: false }],
    'Loopback': [{ family: 'IPv4', address: '127.0.0.1', internal: true }],
    'Local Area Connection* 2': [{ family: 'IPv4', address: '192.168.137.1', internal: false }],
    'Ethernet': [{ family: 'IPv4', address: '169.254.3.4', internal: false }],
    'vEthernet (WSL (Hyper-V firewall))': [{ family: 'IPv4', address: '172.29.128.1', internal: false }],
    'CloudflareWARP': [{ family: 'IPv4', address: '172.16.0.2', internal: false }],
  });
  assert.deepEqual(found, [{ address: '192.168.137.1', name: 'Local Area Connection* 2' }, { address: '10.0.0.7', name: 'Wi-Fi' }]);
});

// ------------------------------------------------------------------------------------------- certificate

test('the certificate is renewed when an address is new or it expires soon', () => {
  const soon = { meta: { addresses: ['127.0.0.1', '192.168.137.1'], not_after: new Date(Date.now() + 5 * 86400000).toISOString() } };
  const later = { meta: { ...soon.meta, not_after: new Date(Date.now() + 200 * 86400000).toISOString() } };
  assert.equal(certificateFits(later, ['192.168.137.1']), true);
  assert.equal(certificateFits(later, ['192.168.137.1', '10.0.0.7']), false);
  assert.equal(certificateFits(soon, ['192.168.137.1']), false);
  assert.equal(certificateFits(null, []), false);
});

test('ensureCertificate asks for a new one only when needed, keeping known addresses', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pkos-cert-'));
  const asked = [];
  const makeCert = async (d, addresses) => {
    asked.push(addresses);
    for (const f of ['key.pem', 'cert.pem']) fs.copyFileSync(path.join(FIXTURE, f), path.join(d, f));
    fs.writeFileSync(path.join(d, 'meta.json'), JSON.stringify({
      addresses: ['127.0.0.1', ...addresses], not_after: new Date(Date.now() + 300 * 86400000).toISOString(), sha256: String(asked.length),
    }));
  };
  await ensureCertificate({ dir, addresses: ['192.168.137.1'], makeCert });
  await ensureCertificate({ dir, addresses: ['192.168.137.1'], makeCert });
  await ensureCertificate({ dir, addresses: ['10.0.0.7'], makeCert });
  assert.deepEqual(asked, [['192.168.137.1'], ['10.0.0.7', '192.168.137.1']]);
});

// ------------------------------------------------------------------------------------------- the server

let backend;
let backendUrl;
let seen;
let phone;
let base;
let webDir;
let aborted;
let pairing;
let cookie; // the paired test phone's device cookie

before(async () => {
  webDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pkos-web-'));
  fs.writeFileSync(path.join(webDir, 'index.html'), '<!doctype html><html><head><title>PKOS</title></head><body></body></html>');
  fs.mkdirSync(path.join(webDir, 'assets'));
  fs.writeFileSync(path.join(webDir, 'assets', 'app.js'), 'console.log(1)');
  fs.writeFileSync(path.join(path.dirname(webDir), 'pkos-secret.txt'), 'secret');

  seen = [];
  aborted = 0;
  backend = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      seen.push({ method: req.method, url: req.url, headers: req.headers, body });
      if (req.url === '/api/v1/query/stream') {
        res.writeHead(200, { 'Content-Type': 'text/event-stream' });
        res.write('data: {"type":"token","content":"first"}\n\n');
        const timer = setTimeout(() => res.end('data: [DONE]\n\n'), 400);
        res.on('close', () => { if (!res.writableFinished) { aborted += 1; clearTimeout(timer); } });
      } else if (req.url === '/api/v1/slow') {
        res.writeHead(200, { 'Content-Type': 'text/plain' });
      } else {
        res.writeHead(200, { 'Content-Type': 'application/json', 'Set-Cookie': 'a=b' });
        res.end(JSON.stringify({ ok: true, url: req.url }));
      }
    });
  });
  await new Promise((r) => backend.listen(0, '127.0.0.1', r));
  backendUrl = `http://127.0.0.1:${backend.address().port}`;
  pairing = new Pairing();
  phone = new PhoneServer({ webDir, getApiBase: () => backendUrl, pairing });
  const port = await phone.start({ port: 0, host: '127.0.0.1', tls: TLS });
  base = `https://127.0.0.1:${port}`;
  const paired = pairing.tryCode(pairing.newCode().code, { address: 'test', userAgent: 'test' });
  cookie = `pkos_device=${paired.cookie}`;
});

after(async () => {
  await phone.stop();
  await new Promise((r) => backend.close(r));
});

/** A request to the phone server; resolves { status, headers, body, firstChunkMs }. */
function call(method, urlPath, { headers = {}, body = null, paired = true } = {}) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const all = paired ? { Cookie: cookie, ...headers } : headers;
    const req = https.request(`${base}${urlPath}`, { method, headers: all, rejectUnauthorized: false }, (res) => {
      let text = '';
      let firstChunkMs = null;
      res.setEncoding('utf8');
      res.on('data', (c) => { if (firstChunkMs === null) firstChunkMs = Date.now() - started; text += c; });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: text, firstChunkMs, totalMs: Date.now() - started }));
    });
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

test('serves the web UI over https and tells it to use the same address for the API', async () => {
  const page = await call('GET', '/');
  assert.equal(page.status, 200);
  assert.match(page.body, /<head><meta name="pkos-api" content="same-origin">/);
  assert.match(page.headers['content-security-policy'], /connect-src 'self'/);
  assert.equal(page.headers['x-frame-options'], 'DENY');
  assert.equal(page.headers['cache-control'], 'no-store');
  const script = await call('GET', '/assets/app.js');
  assert.equal(script.body, 'console.log(1)');
  assert.match(script.headers['content-type'], /javascript/);
  const deepLink = await call('GET', '/chats/123');
  assert.match(deepLink.body, /pkos-api/); // unknown paths get the app (it routes itself)
});

test('nothing outside the web UI folder is served', async () => {
  const dotted = await call('GET', '/%2e%2e/pkos-secret.txt'); // the URL parser folds this to /pkos-secret.txt
  assert.doesNotMatch(dotted.body, /^secret$/);
  const sneaky = await call('GET', '/assets%2f..%2f..%2fpkos-secret.txt'); // decoded after parsing: caught here
  assert.equal(sneaky.status, 403);
  assert.doesNotMatch(sneaky.body, /secret/);
  assert.equal((await call('POST', '/index.html')).status, 405);
});

test('API calls are forwarded with the login, and marked as coming from a phone', async () => {
  seen.length = 0;
  const r = await call('POST', '/api/v1/memories?x=1', {
    headers: { Authorization: 'Bearer tok', 'Content-Type': 'application/json', 'X-PKOS-Via': 'laptop', Origin: 'https://evil.example' },
    body: '{"text":"hi"}',
  });
  assert.equal(r.status, 200);
  assert.deepEqual(JSON.parse(r.body), { ok: true, url: '/api/v1/memories?x=1' });
  const [got] = seen;
  assert.equal(got.headers.authorization, 'Bearer tok');
  assert.equal(got.headers['x-pkos-via'], 'phone');      // set by the phone server, never taken from the phone
  assert.equal(got.headers.origin, undefined);
  assert.equal(got.headers['x-forwarded-for'], '127.0.0.1');
  assert.equal(got.body, '{"text":"hi"}');
  assert.equal(r.headers['set-cookie'][0], 'a=b');
});

test('answers stream to the phone token by token', async () => {
  const r = await call('POST', '/api/v1/query/stream', { headers: { 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(r.status, 200);
  assert.match(r.body, /first[\s\S]*\[DONE\]/);
  assert.ok(r.firstChunkMs < 300 && r.totalMs >= 380, `first chunk ${r.firstChunkMs} ms, total ${r.totalMs} ms`);
  assert.equal(r.headers['x-accel-buffering'], 'no');
});

test('laptop-only paths are refused without reaching the backend', async () => {
  seen.length = 0;
  for (const [m, p] of [['PUT', '/api/v1/settings/llm'], ['POST', '/api/v1/ollama/pull'], ['POST', '/api/v1/import/pkos']]) {
    const r = await call(m, p, { body: '{}' });
    assert.equal(r.status, 403);
    assert.equal(JSON.parse(r.body).detail, LAPTOP_ONLY);
  }
  assert.equal(seen.length, 0);
});

test('a phone that goes away stops the answer on the laptop', async () => {
  aborted = 0;
  await new Promise((resolve) => {
    const req = https.request(`${base}/api/v1/query/stream`, { method: 'POST', headers: { Cookie: cookie }, rejectUnauthorized: false }, (res) => {
      res.once('data', () => { req.destroy(); setTimeout(resolve, 150); });
    });
    req.on('error', () => {});
    req.end('{}');
  });
  assert.equal(aborted, 1);
});

test('while the engine is not running the phone is told so', async () => {
  const down = new PhoneServer({ webDir, getApiBase: () => null, pairing });
  const port = await down.start({ port: 0, host: '127.0.0.1', tls: TLS });
  const saved = base;
  base = `https://127.0.0.1:${port}`;
  try {
    const r = await call('GET', '/api/v1/me');
    assert.equal(r.status, 503);
    assert.match(JSON.parse(r.body).detail, /not reachable/);
  } finally {
    base = saved;
    await down.stop();
  }
});

test('switching off closes the door at once, even with an answer still streaming', async () => {
  const other = new PhoneServer({ webDir, getApiBase: () => backendUrl, pairing });
  const port = await other.start({ port: 0, host: '127.0.0.1', tls: TLS });
  const pending = new Promise((resolve) => {
    const req = https.request(`https://127.0.0.1:${port}/api/v1/slow`, { headers: { Cookie: cookie }, rejectUnauthorized: false }, (res) => {
      res.on('close', resolve);
      res.resume();
    });
    req.on('error', resolve);
    req.end();
  });
  await new Promise((r) => setTimeout(r, 100));
  const t = Date.now();
  await other.stop();
  await pending;
  assert.ok(Date.now() - t < 1000);
  assert.equal(other.running, false);
  await assert.rejects(new Promise((resolve, reject) => {
    https.get(`https://127.0.0.1:${port}/`, { rejectUnauthorized: false }, resolve).on('error', reject);
  }));
});

// ------------------------------------------------------------------------------------------- pairing (P2)

const FORM = { 'Content-Type': 'application/x-www-form-urlencoded' };
const otherThan = (code) => (code === '000000' ? '111111' : '000000');

test('a device that is not paired sees only the pairing page', async () => {
  seen.length = 0;
  const page = await call('GET', '/', { paired: false });
  assert.equal(page.status, 200);
  assert.match(page.body, /Pair this phone with PKOS/);
  assert.doesNotMatch(page.body, /pkos-api/);
  assert.match((await call('GET', '/assets/app.js', { paired: false })).body, /Pair this phone/);
  const api = await call('GET', '/api/v1/me', { paired: false });
  assert.equal(api.status, 401);
  assert.equal(JSON.parse(api.body).detail, NOT_PAIRED);
  assert.equal((await call('POST', '/api/v1/login', { paired: false, headers: FORM, body: 'username=a&password=b' })).status, 401);
  assert.equal((await call('GET', '/health', { paired: false })).status, 401);
  const forged = await call('GET', '/api/v1/me', { paired: false, headers: { Cookie: 'pkos_device=abc.def' } });
  assert.equal(forged.status, 401);
  assert.equal(seen.length, 0); // nothing reached the backend
});

test('scanning the QR code pairs the phone, and the code works only once', async () => {
  const { code } = pairing.newCode();
  const ua = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36';
  const scan = await call('GET', `/?pair=${code}`, { paired: false, headers: { 'User-Agent': ua } });
  assert.equal(scan.status, 303);
  assert.equal(scan.headers.location, '/');
  const set = scan.headers['set-cookie'][0];
  assert.match(set, /^pkos_device=[0-9a-f]{16}\.[\w-]{43}; Path=\/; Max-Age=\d+; HttpOnly; Secure; SameSite=Strict$/);
  const phoneCookie = set.split(';')[0];
  assert.equal((await call('GET', '/api/v1/me', { paired: false, headers: { Cookie: phoneCookie } })).status, 200);
  assert.ok(pairing.list().some((d) => d.name === 'Android phone · Chrome'));
  const again = await call('GET', `/?pair=${code}`, { paired: false });
  assert.equal(again.status, 400);
  assert.match(again.body, /No pairing code is active/);
  const rescan = await call('GET', `/?pair=${code}`, { paired: false, headers: { Cookie: phoneCookie } });
  assert.equal(rescan.status, 303); // a paired phone scanning again just opens PKOS
});

test('typing the 6-digit code pairs too; wrong codes count down and end the code', async () => {
  const { code } = pairing.newCode();
  const first = await call('POST', '/pair', { paired: false, headers: FORM, body: `code=${otherThan(code)}` });
  assert.equal(first.status, 400);
  assert.match(first.body, /4 tries left/);
  const typed = await call('POST', '/pair', { paired: false, headers: FORM, body: `code=${code.slice(0, 3)}+${code.slice(3)}` });
  assert.equal(typed.status, 303); // a space in the middle is fine

  const next = pairing.newCode();
  for (let i = 0; i < 5; i += 1) await call('POST', '/pair', { paired: false, headers: FORM, body: `code=${otherThan(next.code)}` });
  assert.equal(pairing.activeCode(), null);
  assert.equal((await call('POST', '/pair', { paired: false, headers: FORM, body: `code=${next.code}` })).status, 400);
  pairing.guesses.blocked.clear(); // this test's guesses came from 127.0.0.1, like the others
});

test('a removed phone is locked out at once, even mid-answer', async () => {
  const p = pairing.tryCode(pairing.newCode().code, { address: 'x', userAgent: 'iPhone Safari' });
  const phoneCookie = `pkos_device=${p.cookie}`;
  const streaming = new Promise((resolve) => {
    const req = https.request(`${base}/api/v1/slow`, { headers: { Cookie: phoneCookie }, rejectUnauthorized: false }, (res) => {
      res.on('close', resolve);
      res.resume();
    });
    req.on('error', resolve);
    req.end();
  });
  await new Promise((r) => setTimeout(r, 100));
  assert.equal(phone.removeDevice(p.device.id), true);
  await streaming;
  assert.equal((await call('GET', '/api/v1/me', { paired: false, headers: { Cookie: phoneCookie } })).status, 401);
});

test('too many wrong passwords from one phone make it wait; other phones are not affected', async () => {
  const fake = http.createServer((req, res) => {
    req.resume();
    req.on('end', () => {
      res.writeHead(req.headers['x-test'] === 'ok' ? 200 : 401, { 'Content-Type': 'application/json' });
      res.end('{}');
    });
  });
  await new Promise((r) => fake.listen(0, '127.0.0.1', r));
  const local = new Pairing();
  const server = new PhoneServer({ webDir, getApiBase: () => `http://127.0.0.1:${fake.address().port}`, pairing: local });
  const port = await server.start({ port: 0, host: '127.0.0.1', tls: TLS });
  const saved = base;
  base = `https://127.0.0.1:${port}`;
  try {
    const a = `pkos_device=${local.tryCode(local.newCode().code, { address: '1' }).cookie}`;
    const b = `pkos_device=${local.tryCode(local.newCode().code, { address: '2' }).cookie}`;
    const login = (c, extra = {}) => call('POST', '/api/v1/login', { paired: false, headers: { ...FORM, Cookie: c, ...extra }, body: 'u=x&p=y' });
    for (let i = 0; i < 5; i += 1) assert.equal((await login(a)).status, 401);
    const blocked = await login(a, { 'X-Test': 'ok' });
    assert.equal(blocked.status, 429);
    assert.match(JSON.parse(blocked.body).detail, /Too many wrong passwords from this phone\. Try again in 10 minutes/);
    assert.equal((await login(b, { 'X-Test': 'ok' })).status, 200);
  } finally {
    base = saved;
    await server.stop();
    await new Promise((r) => fake.close(r));
  }
});

// ------------------------------------------------------------------------------------------- home-screen icon (P4)

test('the manifest and icons are served without pairing; nothing else is, and missing ones are not the app', async () => {
  fs.writeFileSync(path.join(webDir, 'manifest.webmanifest'), '{"name":"PKOS"}');
  fs.mkdirSync(path.join(webDir, 'icons'), { recursive: true });
  fs.writeFileSync(path.join(webDir, 'icons', 'pkos-192.png'), 'png');
  const manifest = await call('GET', '/manifest.webmanifest', { paired: false });
  assert.equal(manifest.status, 200);
  assert.equal(manifest.body, '{"name":"PKOS"}');
  assert.equal(manifest.headers['content-type'], 'application/manifest+json');
  assert.equal(manifest.headers['cache-control'], 'no-cache');
  assert.equal((await call('GET', '/icons/pkos-192.png', { paired: false })).body, 'png');
  const missing = await call('GET', '/icons/nope.png', { paired: false });
  assert.equal(missing.status, 404);
  assert.doesNotMatch(missing.body, /pkos-api/);
  assert.match((await call('GET', '/icons/../index.html', { paired: false })).body, /Pair this phone/);
  assert.equal((await call('GET', '/assets/app.js')).headers['cache-control'], 'public, max-age=31536000, immutable');
});
