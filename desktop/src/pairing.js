'use strict';
// Phone pairing (docs/08_PHONE_ACCESS_PLAN.md, step P2). A phone gets in once: the laptop shows a one-time code (as a QR
// code and as 6 digits); the phone that enters it gets a random device key in a cookie. The laptop keeps only the key's
// hash. A device that is not paired sees nothing but the pairing page. Removing a phone makes its key worthless at once.
const crypto = require('crypto');

const CODE_TTL_MS = 5 * 60 * 1000;        // a code is valid for 5 minutes and one phone
const CODE_TRIES = 5;                     // wrong entries before a code is thrown away
const GUESS_WINDOW_MS = 10 * 60 * 1000;   // per network address: this many wrong codes in this window ...
const GUESS_LIMIT = 10;
const GUESS_BLOCK_MS = 10 * 60 * 1000;    // ... blocks pairing from it for this long
const LOGIN_WINDOW_MS = 10 * 60 * 1000;   // per paired phone: this many wrong passwords in this window ...
const LOGIN_LIMIT = 5;
const LOGIN_BLOCK_MS = 10 * 60 * 1000;    // ... blocks login from it for this long
const SEEN_SAVE_MS = 5 * 60 * 1000;       // "last used" is written to disk at most this often
const COOKIE = 'pkos_device';
const COOKIE_MAX_AGE = 400 * 24 * 3600;   // the longest browsers keep a cookie

const sha256 = (text) => crypto.createHash('sha256').update(text).digest('hex');

/** "Android phone · Chrome", "iPhone · Safari": enough to tell paired phones apart. */
function deviceName(userAgent = '') {
  const ua = String(userAgent);
  const kind = /iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) ? 'iPad' : /Android/.test(ua)
    ? (/Mobile/.test(ua) ? 'Android phone' : 'Android tablet') : /Windows/.test(ua) ? 'Windows PC'
      : /Macintosh/.test(ua) ? 'Mac' : /Linux/.test(ua) ? 'Linux device' : 'Device';
  const browser = /EdgA?\//.test(ua) ? 'Edge' : /SamsungBrowser/.test(ua) ? 'Samsung Internet' : /Firefox|FxiOS/.test(ua)
    ? 'Firefox' : /CriOS|Chrome/.test(ua) ? 'Chrome' : /Safari/.test(ua) ? 'Safari' : 'browser';
  return `${kind} · ${browser}`;
}

function parseCookies(header = '') {
  const out = {};
  for (const part of String(header).split(';')) {
    const at = part.indexOf('=');
    if (at > 0) out[part.slice(0, at).trim()] = part.slice(at + 1).trim();
  }
  return out;
}

/** Recent attempts per key (address or device), for simple sliding-window limits. */
class Attempts {
  constructor(windowMs, limit, blockMs, now) {
    Object.assign(this, { windowMs, limit, blockMs, now, failures: new Map(), blocked: new Map() });
  }

  /** Seconds left while blocked, else 0. */
  blockedFor(key) {
    const until = this.blocked.get(key) || 0;
    const left = until - this.now();
    if (left <= 0) { this.blocked.delete(key); return 0; }
    return Math.ceil(left / 1000);
  }

  fail(key) {
    const t = this.now();
    const recent = (this.failures.get(key) || []).filter((x) => t - x < this.windowMs);
    recent.push(t);
    this.failures.set(key, recent);
    if (recent.length >= this.limit) {
      this.blocked.set(key, t + this.blockMs);
      this.failures.delete(key);
    }
  }

  clear(key) {
    this.failures.delete(key);
  }
}

class Pairing {
  /**
   * devices: the stored list [{ id, name, keyHash, pairedAt, lastSeenAt }]; save(devices) persists it.
   * now and randomBytes are replaceable for tests.
   */
  constructor({ devices = [], save = () => {}, now = () => Date.now(), randomBytes = crypto.randomBytes } = {}) {
    this.devices = devices.map((d) => ({ ...d }));
    this.save = save;
    this.now = now;
    this.randomBytes = randomBytes;
    this.code = null; // { code, expiresAt, triesLeft }
    this.guesses = new Attempts(GUESS_WINDOW_MS, GUESS_LIMIT, GUESS_BLOCK_MS, now);
    this.logins = new Attempts(LOGIN_WINDOW_MS, LOGIN_LIMIT, LOGIN_BLOCK_MS, now);
    this.lastSaved = 0;
  }

  /** A fresh one-time code (the previous one stops working). */
  newCode() {
    const n = this.randomBytes(4).readUInt32BE(0) % 1000000;
    this.code = { code: String(n).padStart(6, '0'), expiresAt: this.now() + CODE_TTL_MS, triesLeft: CODE_TRIES };
    return this.activeCode();
  }

  activeCode() {
    if (this.code && (this.code.expiresAt <= this.now() || this.code.triesLeft <= 0)) this.code = null;
    return this.code ? { ...this.code } : null;
  }

  cancelCode() {
    this.code = null;
  }

  /**
   * A phone enters a code. Returns { ok: true, cookie, device } or { ok: false, error }.
   * address: the phone's network address (for the guessing limit); userAgent names the device.
   */
  tryCode(entered, { address = '', userAgent = '' } = {}) {
    const wait = this.guesses.blockedFor(address);
    if (wait) return { ok: false, error: `Too many wrong codes. Try again in ${Math.ceil(wait / 60)} minutes.` };
    const active = this.activeCode();
    const clean = String(entered || '').replace(/\D/g, '');
    const right = active && clean.length === 6
      && crypto.timingSafeEqual(Buffer.from(clean), Buffer.from(active.code));
    if (!right) {
      this.guesses.fail(address);
      if (active) {
        this.code.triesLeft -= 1;
        if (this.code.triesLeft <= 0) this.code = null;
      }
      return {
        ok: false,
        error: !active ? 'No pairing code is active. On the laptop: Settings > Phone access > Pair a phone.'
          : (this.code ? `That code is not right. ${this.code.triesLeft} tries left.`
            : 'That code is not right, and it has now expired. Make a new one on the laptop.'),
      };
    }
    this.code = null; // one phone per code
    this.guesses.clear(address);
    const id = this.randomBytes(8).toString('hex');
    const key = this.randomBytes(32).toString('base64url');
    const device = { id, name: deviceName(userAgent), keyHash: sha256(key), pairedAt: new Date(this.now()).toISOString(),
      lastSeenAt: new Date(this.now()).toISOString() };
    this.devices.push(device);
    this.persist();
    return { ok: true, device: this.publicDevice(device), cookie: `${id}.${key}` };
  }

  /** The paired device a request comes from (by its cookie), or null. */
  deviceFor(cookieHeader) {
    const value = parseCookies(cookieHeader)[COOKIE];
    if (!value || !value.includes('.')) return null;
    const [id, key] = value.split('.', 2);
    const device = this.devices.find((d) => d.id === id);
    if (!device || !key) return null;
    const a = Buffer.from(sha256(key), 'hex');
    const b = Buffer.from(device.keyHash, 'hex');
    if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
    device.lastSeenAt = new Date(this.now()).toISOString();
    if (this.now() - this.lastSaved > SEEN_SAVE_MS) this.persist();
    return device;
  }

  remove(id) {
    const before = this.devices.length;
    this.devices = this.devices.filter((d) => d.id !== id);
    if (this.devices.length === before) return false;
    this.logins.blocked.delete(id);
    this.persist();
    return true;
  }

  list() {
    return this.devices.map((d) => this.publicDevice(d));
  }

  publicDevice(d) {
    return { id: d.id, name: d.name, pairedAt: d.pairedAt, lastSeenAt: d.lastSeenAt };
  }

  /** Seconds a phone must wait before trying to log in again (too many wrong passwords), else 0. */
  loginBlockedFor(deviceId) {
    return this.logins.blockedFor(deviceId);
  }

  loginResult(deviceId, ok) {
    if (ok) this.logins.clear(deviceId);
    else this.logins.fail(deviceId);
  }

  persist() {
    this.lastSaved = this.now();
    this.save(this.devices.map((d) => ({ ...d })));
  }
}

/** Set-Cookie value for a paired device (only over https; never readable by page scripts). */
function deviceCookie(value) {
  return `${COOKIE}=${value}; Path=/; Max-Age=${COOKIE_MAX_AGE}; HttpOnly; Secure; SameSite=Strict`;
}

const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

/** The only page a device that is not paired can see: enter the code from the laptop. */
function pairingPage({ error = '', code = '' } = {}) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Pair with PKOS</title>
<style>
  body { margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px;
         box-sizing: border-box; background: #0f1115; color: #e5e7eb; font: 15px/1.5 system-ui, sans-serif; }
  main { width: 100%; max-width: 380px; background: #161a22; border: 1px solid #262b36; border-radius: 16px; padding: 28px; }
  h1 { font-size: 20px; margin: 0 0 8px; } p { color: #9ca3af; margin: 0 0 18px; }
  input { width: 100%; box-sizing: border-box; font-size: 28px; letter-spacing: 8px; text-align: center; padding: 12px;
          border-radius: 10px; border: 1px solid #374151; background: #0f1115; color: #fff; }
  button { width: 100%; margin-top: 14px; padding: 14px; font-size: 16px; border: 0; border-radius: 10px;
           background: #3b82f6; color: #fff; }
  .error { color: #fecaca; background: rgba(127,29,29,.35); border: 1px solid rgba(248,113,113,.3); padding: 10px;
           border-radius: 8px; margin-bottom: 14px; }
  small { display: block; margin-top: 16px; color: #6b7280; }
</style></head><body><main>
<h1>Pair this phone with PKOS</h1>
<p>On the laptop, open PKOS &gt; Settings &gt; Phone access &gt; Pair a phone, then scan the QR code or type the 6-digit code here.</p>
${error ? `<div class="error" role="alert">${escapeHtml(error)}</div>` : ''}
<form method="post" action="/pair">
  <input name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]{6,7}" maxlength="7" required
         aria-label="Pairing code" value="${escapeHtml(code)}" autofocus>
  <button type="submit">Pair</button>
</form>
<small>Pairing is needed once per phone. Your documents and chats stay on the laptop.</small>
</main></body></html>`;
}

module.exports = {
  Pairing, deviceCookie, deviceName, pairingPage, parseCookies, COOKIE, CODE_TRIES, CODE_TTL_MS, LOGIN_LIMIT, GUESS_LIMIT,
};
