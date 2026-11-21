// AI provider settings, model management and status (backend: routes_settings.py, routes_llm.py).
import { API } from '../api';
import { readSSE } from './sse';

async function json(res, fallback) {
  let body = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    const detail = body && body.detail;
    const message = typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map((d) => d.msg).join('; ') : fallback;
    throw new Error(message);
  }
  return body;
}

const jsonBody = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

/**
 * PUT /settings/llm replaces all model fields, so a change to one provider must resend the others.
 * Keys are only sent when given (omitted = keep the saved key, '' = remove it).
 */
export function settingsBody(saved, changes) {
  const body = {
    provider: (saved && saved.provider) || 'ollama',
    ollama_model: (saved && saved.ollama_model) || null,
    openai_model: (saved && saved.openai_model) || null,
    anthropic_model: (saved && saved.anthropic_model) || null,
    ...changes,
  };
  for (const k of ['ollama_model', 'openai_model', 'anthropic_model']) if (body[k] === '') body[k] = null;
  return body;
}

export const getLlmSettings = async (authFetch) => json(await authFetch(`${API}/settings/llm`), 'Could not load AI settings.');
export const saveLlmSettings = async (authFetch, settings) =>
  json(await authFetch(`${API}/settings/llm`, jsonBody('PUT', settings)), 'Could not save AI settings.');
export const testLlm = async (authFetch, settings) =>
  json(await authFetch(`${API}/settings/llm/test`, jsonBody('POST', settings)), 'Connection test failed.');
export const getLlmStatus = async (authFetch) => json(await authFetch(`${API}/llm/status`), 'Could not check the AI status.');
export const getSystemStatus = async (authFetch) => json(await authFetch(`${API}/system/status`), 'Could not load the system status.');
export const getOllamaModels = async (authFetch) =>
  (await json(await authFetch(`${API}/ollama/models`), 'Ollama is not running.')).models;
export const deleteOllamaModel = async (authFetch, name) =>
  json(await authFetch(`${API}/ollama/models/${encodeURIComponent(name)}`, { method: 'DELETE' }), 'Could not remove the model.');

/**
 * Downloads an Ollama model. onProgress({ status, percent, completed, total }) is called as it goes.
 * Resolves when the download succeeds; rejects with the server's message on failure, or with an
 * AbortError when `signal` is aborted (which also cancels the download on the server).
 */
export async function pullModel(authFetch, model, { onProgress, signal } = {}) {
  const res = await authFetch(`${API}/ollama/pull`, { ...jsonBody('POST', { model }), signal });
  if (!res.ok) await json(res, 'Download failed.');
  let result = null;
  await readSSE(res, (payload) => {
    const event = JSON.parse(payload);
    if (event.status === 'error') result = new Error(event.error || 'Download failed.');
    else if (event.status === 'success') result = true;
    else if (onProgress) onProgress(event);
  });
  if (result instanceof Error) throw result;
  if (result !== true) throw new Error('The download ended unexpectedly.');
}

const LEGACY_KEYS = ['llm_provider', 'ollama_model', 'openai_api_key', 'anthropic_api_key'];

/**
 * Older versions kept the provider and API keys in browser storage. Moves them to the encrypted server-side
 * settings once (only if the user has not saved settings there yet), then deletes them from the browser.
 * Returns true if something was migrated.
 */
export async function migrateLegacySettings(authFetch, storage = window.localStorage) {
  const legacy = Object.fromEntries(LEGACY_KEYS.map((k) => [k, storage.getItem(k)]));
  if (!Object.values(legacy).some(Boolean)) return false;
  const current = await getLlmSettings(authFetch);
  let migrated = false;
  if (!current.saved) {
    const provider = ['ollama', 'openai', 'anthropic'].includes(legacy.llm_provider) ? legacy.llm_provider : 'ollama';
    await saveLlmSettings(authFetch, {
      provider,
      ollama_model: legacy.ollama_model || null,
      openai_key: legacy.openai_api_key || null,
      anthropic_key: legacy.anthropic_api_key || null,
    });
    migrated = true;
  }
  LEGACY_KEYS.forEach((k) => storage.removeItem(k));
  return migrated;
}
