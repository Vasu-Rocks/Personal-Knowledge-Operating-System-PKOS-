import { call, json } from './apiCall';

// Saved chats (backend/api/routes_conversations.py). Every call throws an Error with a readable message on failure.

export const listConversations = (authFetch, before = null) =>
  call(authFetch, `/conversations?limit=50${before ? `&before=${encodeURIComponent(before)}` : ''}`);

export const getConversation = (authFetch, id) => call(authFetch, `/conversations/${id}`);

export const renameConversation = (authFetch, id, title) => call(authFetch, `/conversations/${id}`, json('PATCH', { title }));

export const deleteConversation = (authFetch, id) => call(authFetch, `/conversations/${id}`, { method: 'DELETE' });
