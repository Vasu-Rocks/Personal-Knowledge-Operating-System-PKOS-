'use strict';
const http = require('http');
const net = require('net');

/** A free TCP port on 127.0.0.1, chosen by the OS. */
function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

/** GET a URL on localhost; resolves { status, body } or rejects on connection errors/timeouts. */
function httpGet(url, timeoutMs = 2000) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (c) => { body += c; });
      res.on('end', () => resolve({ status: res.statusCode, body }));
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

/** Polls check() until it resolves truthy, or throws after timeoutMs. */
async function waitFor(check, { timeoutMs = 60000, intervalMs = 500, what = 'service', isAborted = () => false } = {}) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    if (isAborted()) throw new Error(`${what} stopped while starting`);
    try {
      if (await check()) return;
    } catch (e) {
      lastError = e;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`${what} did not become ready within ${Math.round(timeoutMs / 1000)} s${lastError ? ` (${lastError.message})` : ''}`);
}

module.exports = { getFreePort, httpGet, waitFor };
