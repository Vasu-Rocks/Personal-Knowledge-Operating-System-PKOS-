'use strict';
// Phone pairing rules (docs/08_PHONE_ACCESS_PLAN.md, step P2), with a fake clock.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { Pairing, deviceName, parseCookies, CODE_TTL_MS, GUESS_LIMIT } = require('../src/pairing');

function clock(start = 1_000_000) {
  let t = start;
  return { now: () => t, advance: (ms) => { t += ms; } };
}

test('codes are 6 digits, expire after 5 minutes and a new one replaces the old one', () => {
  const c = clock();
  const p = new Pairing({ now: c.now });
  const first = p.newCode();
  assert.match(first.code, /^\d{6}$/);
  assert.equal(first.triesLeft, 5);
  const second = p.newCode();
  assert.equal(p.tryCode(first.code === second.code ? 'xxxxxx' : first.code, { address: 'a' }).ok, false);
  c.advance(CODE_TTL_MS + 1);
  assert.equal(p.activeCode(), null);
  assert.equal(p.tryCode(second.code, { address: 'a' }).ok, false);
});

test('pairing stores only a hash of the device key, and saves the list', () => {
  const saved = [];
  const p = new Pairing({ save: (d) => saved.push(d) });
  const r = p.tryCode(p.newCode().code, { address: 'a', userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1' });
  assert.equal(r.ok, true);
  const [id, key] = r.cookie.split('.');
  assert.equal(saved.length, 1);
  const stored = saved[0][0];
  assert.equal(stored.id, id);
  assert.equal(stored.name, 'iPhone · Safari');
  assert.ok(!JSON.stringify(saved).includes(key));
  assert.equal(p.deviceFor(`other=1; pkos_device=${r.cookie}`).id, id);
  assert.equal(p.deviceFor(`pkos_device=${id}.${key.slice(0, -1)}x`), null);
  assert.equal(p.deviceFor('pkos_device=nonsense'), null);
  assert.equal(p.deviceFor(''), null);
});

test('paired phones survive a restart (the stored list is loaded back)', () => {
  let stored = [];
  const p = new Pairing({ save: (d) => { stored = d; } });
  const r = p.tryCode(p.newCode().code, { address: 'a' });
  const reborn = new Pairing({ devices: stored });
  assert.equal(reborn.deviceFor(`pkos_device=${r.cookie}`).id, r.device.id);
  assert.equal(reborn.remove(r.device.id), true);
  assert.equal(reborn.deviceFor(`pkos_device=${r.cookie}`), null);
});

test('guessing codes from one address is blocked for a while', () => {
  const c = clock();
  const p = new Pairing({ now: c.now });
  for (let i = 0; i < GUESS_LIMIT; i += 1) {
    p.newCode();
    p.tryCode('999999x', { address: 'guesser' });
  }
  const { code } = p.newCode();
  const blocked = p.tryCode(code, { address: 'guesser' });
  assert.equal(blocked.ok, false);
  assert.match(blocked.error, /Too many wrong codes/);
  assert.equal(p.tryCode(code, { address: 'someone-else' }).ok, true);
  c.advance(10 * 60 * 1000 + 1);
  assert.equal(p.tryCode(p.newCode().code, { address: 'guesser' }).ok, true);
});

test('device names and cookies', () => {
  assert.equal(deviceName('Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 SamsungBrowser/24.0 Chrome/117 Mobile Safari/537.36'), 'Android phone · Samsung Internet');
  assert.equal(deviceName('Mozilla/5.0 (Linux; Android 13; Tab) Chrome/130.0 Safari/537.36'), 'Android tablet · Chrome');
  assert.equal(deviceName(''), 'Device · browser');
  assert.deepEqual(parseCookies('a=1; b=two=2;c'), { a: '1', b: 'two=2' });
});
