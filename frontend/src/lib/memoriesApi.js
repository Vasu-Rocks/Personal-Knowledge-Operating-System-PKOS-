import { call, json } from './apiCall';

// Long-term memories (backend/api/routes_memories.py, docs/07_MEMORY_PLAN.md 10.3).

export const MEMORY_MAX_CHARS = 300;

export const KINDS = [
  { id: 'fact', label: 'Fact about me', hint: 'e.g. "My GATE exam is on 14 February"' },
  { id: 'preference', label: 'How to answer', hint: 'e.g. "Answer in short bullet points"' },
  { id: 'conclusion', label: 'Something we decided', hint: 'e.g. "We chose the Campbell sensors"' },
];

export const listMemories = async (authFetch, status = 'active') =>
  (await call(authFetch, `/memories?status=${status}`)).memories;

export const addMemory = (authFetch, memory) => call(authFetch, '/memories', json('POST', memory));

export const editMemory = (authFetch, id, changes) => call(authFetch, `/memories/${id}`, json('PATCH', changes));

export const deleteMemory = (authFetch, id) => call(authFetch, `/memories/${id}`, { method: 'DELETE' });

export const deleteAllMemories = (authFetch) => call(authFetch, '/memories?confirm=true', { method: 'DELETE' });

export const getMemorySettings = (authFetch) => call(authFetch, '/memories/settings');

export const saveMemorySettings = (authFetch, changes) => call(authFetch, '/memories/settings', json('PUT', changes));

/** The text "Remember this" starts with: one line, citations removed, cut at a word to fit 300 characters. */
export function memoryDraft(text) {
  const clean = String(text || '')
    .replace(/\[(chunk\s*\d+|graph entity\s*:[^\]]*)\]/gi, '')
    .replace(/[*_#`>]/g, '')
    .replace(/\s+([.,;:!?])/g, '$1')
    .split(/\s+/).filter(Boolean).join(' ');
  if (clean.length <= MEMORY_MAX_CHARS) return clean;
  const cut = clean.slice(0, MEMORY_MAX_CHARS - 1);
  const space = cut.lastIndexOf(' ');
  return `${space > 200 ? cut.slice(0, space) : cut}…`;
}

const PREFERENCE = /\b(prefer|always|never|please|keep (it|answers)|answer (in|with)|explain .*\b(simply|simple)|in (short|bullet)|bullet points|i (like|want|need) (you|answers|short|simple|it)|use (examples|simple))\b/i;
const CONCLUSION = /\b(we (decided|agreed|chose|concluded|will)|decided|agreed|conclusion|the plan is)\b/i;

/** PKOS's guess at the kind; the user can change it before saving. An answer is most often a conclusion. */
export function guessKind(text, role) {
  if (PREFERENCE.test(text)) return 'preference';
  if (CONCLUSION.test(text) || role === 'ai') return 'conclusion';
  return 'fact';
}

/** Keeps a suggestion (optionally edited first): from then on it is used like any other memory. */
export const confirmMemory = (authFetch, id, changes = {}) => call(authFetch, `/memories/${id}/confirm`, json('POST', changes));
