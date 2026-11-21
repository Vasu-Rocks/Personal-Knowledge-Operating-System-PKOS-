'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { test } = require('node:test');
const { resolvePaths } = require('../src/paths');

const env = { LOCALAPPDATA: 'C:\\Users\\u\\AppData\\Local' };

test('packaged app uses bundled runtimes and %LOCALAPPDATA%\\PKOS', () => {
  const p = resolvePaths({ packaged: true, resourcesPath: 'C:\\Program Files\\PKOS\\resources', env });
  assert.equal(p.dataDir, path.join(env.LOCALAPPDATA, 'PKOS'));
  assert.equal(p.pgBin, path.join('C:\\Program Files\\PKOS\\resources', 'pgsql', 'bin'));
  assert.equal(p.backend.command, path.join('C:\\Program Files\\PKOS\\resources', 'pkos-api', 'pkos-api.exe'));
  assert.equal(p.devUrl, null);
  assert.equal(p.embedModelDir, path.join('C:\\Program Files\\PKOS\\resources', 'models', 'bge-small-en-v1.5'));
});

test('dev run uses repo runtimes and a separate data folder', () => {
  const p = resolvePaths({ packaged: false, repoRoot: 'D:\\repo', env });
  assert.equal(p.dataDir, path.join(env.LOCALAPPDATA, 'PKOS-dev'));
  assert.equal(p.backend.command, path.join('D:\\repo', 'venv', 'Scripts', 'python.exe'));
  assert.deepEqual(p.backend.args, [path.join('D:\\repo', 'backend', 'desktop_entry.py')]);
  assert.equal(p.webDir, path.join('D:\\repo', 'frontend', 'dist'));
});

test('environment overrides win', () => {
  const p = resolvePaths({
    packaged: true, resourcesPath: 'R', env: { ...env, PKOS_DATA_DIR: 'E:\\vault', PKOS_PG_DIR: 'E:\\pg', PKOS_PYTHON: 'E:\\py.exe' },
  });
  assert.equal(p.dataDir, 'E:\\vault');
  assert.equal(p.pgBin, path.join('E:\\pg', 'bin'));
  assert.equal(p.backend.command, 'E:\\py.exe');
  assert.equal(p.configFile, path.join('E:\\vault', 'config.json'));
});
