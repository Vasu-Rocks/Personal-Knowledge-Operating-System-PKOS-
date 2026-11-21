'use strict';
// config.json in the data folder: generated on first run, holds the database password and the backend's
// PKOS_SECRET_KEY (which also encrypts users' API keys). Secrets are encrypted with Electron safeStorage
// (Windows DPAPI, tied to this Windows user) when available, so copying the data folder to another account or PC
// does not reveal them.
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const SECRET_FIELDS = ['dbPassword', 'secretKey'];

function randomSecret(bytes = 32) {
  return crypto.randomBytes(bytes).toString('hex');
}

function seal(value, safeStorage) {
  if (safeStorage && safeStorage.isEncryptionAvailable()) {
    return { enc: 'dpapi', value: safeStorage.encryptString(value).toString('base64') };
  }
  return { enc: 'plain', value };
}

function unseal(sealed, safeStorage) {
  if (!sealed || typeof sealed !== 'object') return null;
  if (sealed.enc === 'plain') return sealed.value;
  if (sealed.enc === 'dpapi' && safeStorage && safeStorage.isEncryptionAvailable()) {
    return safeStorage.decryptString(Buffer.from(sealed.value, 'base64'));
  }
  return null;
}

/**
 * Reads config.json, creating it (with fresh secrets) on first run. Returns plain values:
 * { dbUser, dbName, dbPassword, secretKey, ollamaMode, created, firstRun }.
 * Throws if the secrets exist but cannot be decrypted (e.g. the folder was copied from another Windows user):
 * regenerating them would lock the user out of their own database.
 */
function loadOrCreateConfig(configFile, safeStorage) {
  if (fs.existsSync(configFile)) {
    const raw = JSON.parse(fs.readFileSync(configFile, 'utf8'));
    const out = { ...raw, firstRun: false };
    for (const field of SECRET_FIELDS) {
      const value = unseal(raw[field], safeStorage);
      if (!value) throw new Error(`Cannot decrypt ${field} in ${configFile}. Was the data folder copied from another Windows user?`);
      out[field] = value;
    }
    return out;
  }

  const plain = {
    version: 1,
    created: new Date().toISOString(),
    dbUser: 'pkos',
    dbName: 'pkos',
    dbPassword: randomSecret(24),
    secretKey: randomSecret(32),
    // "auto": use an Ollama already running on 11434 if there is one, else start the bundled one.
    // "bundled": always start the bundled one. "external": never start one.
    ollamaMode: 'auto',
  };
  const stored = { ...plain };
  for (const field of SECRET_FIELDS) stored[field] = seal(plain[field], safeStorage);
  fs.mkdirSync(path.dirname(configFile), { recursive: true });
  fs.writeFileSync(configFile, JSON.stringify(stored, null, 2), { encoding: 'utf8', mode: 0o600 });
  return { ...plain, firstRun: true };
}

/** Merges non-secret fields (e.g. lastVersion) into config.json, keeping the sealed secrets as they are. */
function updateConfig(configFile, patch) {
  for (const field of SECRET_FIELDS) if (field in patch) throw new Error(`updateConfig cannot change ${field}`);
  const raw = JSON.parse(fs.readFileSync(configFile, 'utf8'));
  const next = { ...raw, ...patch };
  const tmp = `${configFile}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(next, null, 2), { encoding: 'utf8', mode: 0o600 });
  fs.renameSync(tmp, configFile);
  return next;
}

/** True when this start is an upgrade over an existing vault, so a backup should run before migrations. */
function isUpgrade(cfg, appVersion) {
  return !cfg.firstRun && cfg.lastVersion !== appVersion;
}

module.exports = { loadOrCreateConfig, updateConfig, isUpgrade, randomSecret, seal, unseal };
