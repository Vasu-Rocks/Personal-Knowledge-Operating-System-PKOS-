'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');
const { loadOrCreateConfig } = require('../src/config');

// Stands in for Electron safeStorage (DPAPI): reversible, but not plain text.
const fakeSafeStorage = (available = true) => ({
  isEncryptionAvailable: () => available,
  encryptString: (s) => Buffer.from(`enc:${Buffer.from(s).toString('hex')}`),
  decryptString: (b) => Buffer.from(b.toString().slice(4), 'hex').toString(),
});

const tmp = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'pkos-cfg-')), 'config.json');

test('first run creates strong secrets and stores them encrypted', () => {
  const file = tmp();
  const cfg = loadOrCreateConfig(file, fakeSafeStorage());
  assert.equal(cfg.firstRun, true);
  assert.match(cfg.secretKey, /^[0-9a-f]{64}$/);
  assert.match(cfg.dbPassword, /^[0-9a-f]{48}$/);
  const raw = fs.readFileSync(file, 'utf8');
  assert.ok(!raw.includes(cfg.secretKey) && !raw.includes(cfg.dbPassword));
  assert.equal(JSON.parse(raw).secretKey.enc, 'dpapi');
});

test('second run returns the same secrets', () => {
  const file = tmp();
  const a = loadOrCreateConfig(file, fakeSafeStorage());
  const b = loadOrCreateConfig(file, fakeSafeStorage());
  assert.equal(b.firstRun, false);
  assert.equal(b.secretKey, a.secretKey);
  assert.equal(b.dbPassword, a.dbPassword);
  assert.equal(b.ollamaMode, 'auto');
});

test('falls back to plain storage when encryption is unavailable', () => {
  const file = tmp();
  const cfg = loadOrCreateConfig(file, fakeSafeStorage(false));
  assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).secretKey.enc, 'plain');
  assert.equal(loadOrCreateConfig(file, fakeSafeStorage(false)).secretKey, cfg.secretKey);
});

test('refuses to invent new secrets when the stored ones cannot be decrypted', () => {
  const file = tmp();
  loadOrCreateConfig(file, fakeSafeStorage());
  assert.throws(() => loadOrCreateConfig(file, fakeSafeStorage(false)), /Cannot decrypt/);
});
