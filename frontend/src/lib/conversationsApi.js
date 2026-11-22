import { API } from '../api';

// Saved chats (backend/api/routes_conversations.py). Every call throws an Error with a readable message on failure.

async function call(authFetch, path, init = {}) {
  const res = await authFetch(`${API}${path}`, init);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : null;
    throw Object.assign(new Error(detail || `Request failed (${res.status}).`), { status: res.status });
  }
  return data;
}

const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export const listConversations = (authFetch, before = null) =>
  call(authFetch, `/conversations?limit=50${before ? `&before=${encodeURIComponent(before)}` : ''}`);

export const getConversation = (authFetch, id) => call(authFetch, `/conversations/${id}`);

export const renameConversation = (authFetch, id, title) => call(authFetch, `/conversations/${id}`, json('PATCH', { title }));

export const deleteConversation = (authFetch, id) => call(authFetch, `/conversations/${id}`, { method: 'DELETE' });
