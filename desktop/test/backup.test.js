'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');
const { BackupManager, AUTO_KEEP } = require('../src/backup');
const { redact } = require('../src/diagnostics');
const { loadOrCreateConfig, updateConfig, isUpgrade } = require('../src/config');

/** Fake pg tools: records calls; pg_dump writes its -f file; failures injected by predicate. */
function fakeRunner({ fail = () => false } = {}) {
  const calls = [];
  const runner = async (cmd, args) => {
    const tool = path.basename(cmd).replace(/\.exe$/, '');
    const sql = args.includes('-c') ? args[args.indexOf('-c') + 1] : null;
    calls.push({ tool, args, sql });
    if (fail(tool, args, sql)) return { code: 1, stdout: '', stderr: 'boom' };
    if (tool === 'pg_dump') fs.writeFileSync(args[args.indexOf('-f') + 1], 'PGDMP fake');
    return { code: 0, stdout: '', stderr: '' };
  };
  return { runner, calls };
}

function manager(opts = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pkos-bk-'));
  const { runner, calls } = fakeRunner(opts);
  const m = new BackupManager({
    pgBin: 'C:\\pg\\bin', backupsDir: path.join(dir, 'backups'), runner,
    getConn: () => ({ port: 5555, user: 'pkos', password: 'pw', db: 'pkos' }),
  });
  return { m, calls, dir };
}

test('create writes a named, complete dump and lists it', async () => {
  const { m, calls } = manager();
  const b = await m.create();
  assert.match(b.name, /^pkos-\d{8}-\d{6}-manual\.dump$/);
  assert.equal(b.kind, 'manual');
  assert.deepEqual(m.list().map((x) => x.name), [b.name]);
  const dump = calls.find((c) => c.tool === 'pg_dump');
  assert.deepEqual(dump.args.slice(0, 8), ['-h', '127.0.0.1', '-p', '5555', '-U', 'pkos', '-d', 'pkos']);
  assert.ok(dump.args.includes('-Fc'));
  assert.ok(!fs.readdirSync(path.dirname(b.path)).some((n) => n.endsWith('.partial')));
});

test('a failed dump leaves no file behind', async () => {
  const { m } = manager({ fail: (tool) => tool === 'pg_dump' });
  await assert.rejects(m.create(), /backup failed/);
  assert.deepEqual(m.list(), []);
});

test('automatic backups are pruned per kind; manual ones are kept', async () => {
  const { m } = manager();
  fs.mkdirSync(m.backupsDir, { recursive: true });
  for (let i = 0; i < AUTO_KEEP + 3; i += 1) {
    fs.writeFileSync(path.join(m.backupsDir, `pkos-2026010${i % 10}-00000${i % 10}-before-update.dump`), 'x');
    fs.writeFileSync(path.join(m.backupsDir, `pkos-2026010${i % 10}-00000${i % 10}-manual.dump`), 'x');
  }
  m.prune();
  const kinds = m.list().reduce((acc, b) => ({ ...acc, [b.kind]: (acc[b.kind] || 0) + 1 }), {});
  assert.deepEqual(kinds, { 'before-update': AUTO_KEEP, manual: AUTO_KEEP + 3 });
  assert.ok(m.list().find((b) => b.kind === 'before-update').name.startsWith('pkos-20260107'), 'newest kept');
});

test('restore: verify, safety backup, restore into a temp db, swap, start, drop the old one', async () => {
  const { m, calls } = manager();
  const file = (await m.create()).path;
  calls.length = 0; // only look at what restore does
  const order = [];
  const result = await m.restore(file, {
    stopBackend: async () => order.push('stop'),
    startBackend: async () => order.push('start'),
  });
  assert.equal(result.restored, path.basename(file));
  assert.match(result.safetyBackup, /before-restore\.dump$/);
  const steps = calls.map((c) => c.sql || `${c.tool}${c.args.includes('--list') ? ' --list' : ''}`);
  const idx = (re) => steps.findIndex((s) => re.test(s));
  assert.ok(idx(/pg_restore --list/) < idx(/^pg_dump$/) && idx(/^pg_dump$/) >= 0, 'verify before safety backup');
  assert.ok(idx(/CREATE DATABASE "pkos_restore"/) < idx(/^pg_restore$/));
  assert.ok(idx(/RENAME TO "pkos_old_/) < idx(/"pkos_restore" RENAME TO "pkos"/));
  assert.match(steps[steps.length - 1], /DROP DATABASE IF EXISTS "pkos_old_/);
  assert.deepEqual(order, ['stop', 'start']);
});

test('restore refuses files pg_restore cannot read, before touching anything', async () => {
  const { m, calls } = manager({ fail: (tool, args) => tool === 'pg_restore' && args.includes('--list') });
  const bogus = path.join(m.backupsDir, 'x.dump');
  fs.mkdirSync(m.backupsDir, { recursive: true });
  fs.writeFileSync(bogus, 'not a dump');
  await assert.rejects(m.restore(bogus, { stopBackend: async () => assert.fail(), startBackend: async () => assert.fail() }),
    /not a PKOS backup/);
  assert.ok(!calls.some((c) => c.tool === 'pg_dump' || c.sql));
});

test('a failing pg_restore leaves the current database alone', async () => {
  const { m, calls } = manager({ fail: (tool, args) => tool === 'pg_restore' && !args.includes('--list') });
  const file = (await m.create()).path;
  await assert.rejects(m.restore(file, { stopBackend: async () => assert.fail('must not stop'), startBackend: async () => {} }),
    /data was not changed/);
  assert.ok(!calls.some((c) => c.sql && /RENAME/.test(c.sql)));
  assert.ok(calls.some((c) => c.sql === 'DROP DATABASE IF EXISTS "pkos_restore"'));
});

test('if the engine cannot start on the restored data, the old database is put back', async () => {
  const { m, calls } = manager();
  const file = (await m.create()).path;
  let starts = 0;
  await assert.rejects(m.restore(file, {
    stopBackend: async () => {},
    startBackend: async () => { starts += 1; if (starts === 1) throw new Error('migration failed'); },
  }), /previous data was put back/);
  const renames = calls.filter((c) => c.sql && /RENAME/.test(c.sql)).map((c) => c.sql);
  assert.equal(renames.length, 4);
  assert.match(renames[3], /^ALTER DATABASE "pkos_old_\w+" RENAME TO "pkos"$/);
  assert.equal(starts, 2);
});

test('only one backup or restore at a time', async () => {
  const { m } = manager();
  const first = m.create();
  await assert.rejects(m.create(), /already running/);
  await first;
});

test('diagnostics mask keys, tokens, passwords and emails', () => {
  const text = redact([
    'OpenAI said: Incorrect API key provided: sk-proj-abcdefghijklmnop1234',
    'anthropic key sk-ant-api03-ZZZZZZZZZZZZZZZZ',
    'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghij',
    'PGPASSWORD=supersecret password: hunter2',
    'registered vasu.goyal@example.com',
  ].join('\n'));
  for (const secret of ['abcdefghijklmnop1234', 'ZZZZZZZZZZZZZZZZ', 'eyJzdWIiOiIxMjM0NTY3ODkwIn0', 'supersecret', 'hunter2', 'vasu.goyal']) {
    assert.ok(!text.includes(secret), `leaked ${secret}`);
  }
  assert.ok(text.includes('sk-proj-a…') && text.includes('…@…'));
});

test('updateConfig keeps secrets sealed; isUpgrade detects a version change', () => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'pkos-cfg-')), 'config.json');
  const safe = { isEncryptionAvailable: () => false };
  const cfg = loadOrCreateConfig(file, safe);
  assert.equal(isUpgrade(cfg, '0.1.0'), false, 'first run is not an upgrade');
  updateConfig(file, { lastVersion: '0.1.0' });
  const again = loadOrCreateConfig(file, safe);
  assert.equal(again.secretKey, cfg.secretKey);
  assert.equal(isUpgrade(again, '0.1.0'), false);
  assert.equal(isUpgrade(again, '0.2.0'), true);
  assert.throws(() => updateConfig(file, { secretKey: 'x' }), /cannot change/);
});
