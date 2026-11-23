import { API } from '../api';

// JSON calls to the backend. Throws an Error with a readable message (and .status) on failure; 204 gives null.
export async function call(authFetch, path, init = {}) {
  const res = await authFetch(`${API}${path}`, init);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : null;
    throw Object.assign(new Error(detail || `Request failed (${res.status}).`), { status: res.status });
  }
  return data;
}

export const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
