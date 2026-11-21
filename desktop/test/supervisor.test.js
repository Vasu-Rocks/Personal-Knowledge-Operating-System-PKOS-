'use strict';
const assert = require('node:assert/strict');
const EventEmitter = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');
const { Supervisor } = require('../src/services');
const { getFreePort, waitFor } = require('../src/net-util');
const { openLog } = require('../src/process');

/** A fake service whose "process" can be crashed on demand. */
function fakeService(name, { optional = false, failStart = false } = {}) {
  const svc = {
    name, label: name, optional, starts: 0, stops: 0, proc: null, log: { write() {} },
    async start() {
      svc.starts += 1;
      if (failStart) throw new Error(`${name} broke`);
      svc.proc = Object.assign(new EventEmitter(), { running: true });
      return svc.proc;
    },
    async stop() { svc.stops += 1; if (svc.proc) svc.proc.running = false; },
    crash() { svc.proc.running = false; svc.proc.emit('exit', { code: 1, expected: false }); },
  };
  return svc;
}

function supervisorWith(services) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'pkos-sup-'));
  const sup = new Supervisor({ paths: { logs: tmp, dataDir: tmp }, cfg: {}, origins: [] });
  sup.services = services;
  sup.backend = { url: 'http://127.0.0.1:1' };
  sup.ollama = services.find((s) => s.name === 'ollama') || {};
  sup.state = Object.fromEntries(services.map((s) => [s.name, { label: s.label, status: 'pending', detail: '' }]));
  sup.crashes = Object.fromEntries(services.map((s) => [s.name, []]));
  return sup;
}

const tick = () => new Promise((r) => setImmediate(r));

test('starts services in order and reports running', async () => {
  const order = [];
  const a = fakeService('postgres');
  const b = fakeService('backend');
  const origA = a.start; a.start = async () => { order.push('postgres'); return origA(); };
  const origB = b.start; b.start = async () => { order.push('backend'); return origB(); };
  const sup = supervisorWith([a, b]);
  await sup.startAll();
  assert.deepEqual(order, ['postgres', 'backend']);
  assert.equal(sup.snapshot().services.backend.status, 'running');
});

test('a required service failing stops startup with an error', async () => {
  const sup = supervisorWith([fakeService('postgres', { failStart: true }), fakeService('backend')]);
  await assert.rejects(sup.startAll(), /postgres broke/);
  assert.equal(sup.snapshot().services.postgres.status, 'failed');
  assert.equal(sup.snapshot().services.backend.status, 'pending');
});

test('an optional service failing only degrades', async () => {
  const sup = supervisorWith([fakeService('ollama', { optional: true, failStart: true }), fakeService('backend')]);
  await sup.startAll();
  assert.equal(sup.snapshot().services.ollama.status, 'degraded');
  assert.equal(sup.snapshot().services.backend.status, 'running');
});

test('crashed services restart, then give up after 3 crashes in 10 minutes', async () => {
  const svc = fakeService('backend');
  const sup = supervisorWith([svc]);
  await sup.startAll();
  for (let i = 1; i <= 3; i += 1) {
    svc.crash();
    await tick(); await tick();
    assert.equal(svc.starts, i + 1);
    assert.equal(sup.snapshot().services.backend.status, 'running');
  }
  svc.crash();
  await tick();
  assert.equal(svc.starts, 4);
  assert.equal(sup.snapshot().services.backend.status, 'failed');
  assert.match(sup.snapshot().fatal, /keeps crashing/);
});

test('an expected exit (stop) is not treated as a crash', async () => {
  const svc = fakeService('backend');
  const sup = supervisorWith([svc]);
  await sup.startAll();
  await sup.stopAll();
  svc.proc.emit('exit', { code: 0, expected: true });
  await tick();
  assert.equal(svc.starts, 1);
  assert.equal(sup.snapshot().services.backend.status, 'stopped');
});

test('retry skips services that are already running', async () => {
  const pg = fakeService('postgres');
  const be = fakeService('backend', { failStart: true });
  const sup = supervisorWith([pg, be]);
  await assert.rejects(sup.startAll());
  await assert.rejects(sup.startAll());
  assert.equal(pg.starts, 1);
  assert.equal(be.starts, 2);
});

test('getFreePort returns a usable port and waitFor times out with the reason', async () => {
  const port = await getFreePort();
  assert.ok(port > 1024 && port < 65536);
  await assert.rejects(waitFor(async () => { throw new Error('nope'); }, { timeoutMs: 300, intervalMs: 50, what: 'Thing' }),
    /Thing did not become ready within 0 s \(nope\)/);
});

test('logs rotate once they pass 10 MB', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pkos-log-'));
  fs.writeFileSync(path.join(dir, 'x.log'), Buffer.alloc(11 * 1024 * 1024));
  const stream = openLog(dir, 'x');
  await new Promise((r) => stream.end(r));
  assert.ok(fs.existsSync(path.join(dir, 'x.log.1')));
  assert.ok(fs.statSync(path.join(dir, 'x.log')).size < 1024);
});
