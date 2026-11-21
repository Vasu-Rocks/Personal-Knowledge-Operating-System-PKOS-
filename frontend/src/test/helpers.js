import { vi } from 'vitest';

export const jsonResponse = (status, body) => ({
  ok: status < 400, status, json: () => Promise.resolve(body),
});

/** A fetch Response whose body streams the given text chunks (for SSE endpoints). */
export function streamResponse(chunks, status = 200) {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    ok: status < 400,
    status,
    json: () => Promise.reject(new Error('stream')),
    body: {
      getReader: () => ({
        read: () => Promise.resolve(i < chunks.length ? { done: false, value: encoder.encode(chunks[i++]) } : { done: true }),
        cancel: () => Promise.resolve(),
      }),
    },
  };
}

export const sse = (...events) => events.map((e) => `data: ${typeof e === 'string' ? e : JSON.stringify(e)}\n\n`).join('');

/**
 * Installs globalThis.fetch that routes by "METHOD /path" (path after /api/v1). Handlers get (body, init)
 * and return a response. Unrouted calls fail the test loudly. Returns the mock, whose .calls are inspectable.
 */
export function routeFetch(routes) {
  const mock = vi.fn(async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase();
    const path = String(url).replace(/^.*\/api\/v1/, '').replace(/^https?:\/\/[^/]+/, '');
    const key = `${method} ${path}`;
    const handler = routes[key] ?? routes[`${method} ${path.split('?')[0]}`];
    if (handler === undefined) throw new Error(`Unexpected fetch: ${key}`);
    const body = init.body && typeof init.body === 'string' ? JSON.parse(init.body) : init.body;
    return typeof handler === 'function' ? handler(body, init) : handler;
  });
  globalThis.fetch = mock;
  return mock;
}

/** Bodies sent to one route, parsed. */
export const sentTo = (mock, method, path) => mock.mock.calls
  .filter(([url, init = {}]) => (init.method || 'GET').toUpperCase() === method && String(url).endsWith(path))
  .map(([, init]) => (init.body ? JSON.parse(init.body) : undefined));
