import { describe, it, expect, vi } from 'vitest';
import { readSSE, splitFrames } from '../lib/sse';
import { migrateLegacySettings, pullModel, settingsBody } from '../lib/llmApi';
import { isInstalled, formatBytes } from '../lib/models';
import { jsonResponse, streamResponse, sse } from './helpers';

describe('SSE reader', () => {
  it('keeps an unfinished frame for the next chunk', () => {
    expect(splitFrames('data: a\n\ndata: b')).toEqual([['a'], 'data: b']);
  });

  it('handles frames split across chunks, stops at [DONE]', async () => {
    const got = [];
    await readSSE(streamResponse(['data: {"n":', '1}\n\nda', 'ta: {"n":2}\n\ndata: [DONE]\n\ndata: {"n":3}\n\n']), (p) => got.push(JSON.parse(p).n));
    expect(got).toEqual([1, 2]);
  });

  it('delivers a last frame without the trailing blank line', async () => {
    const got = [];
    await readSSE(streamResponse(['data: x\n\ndata: y']), (p) => got.push(p));
    expect(got).toEqual(['x', 'y']);
  });
});

describe('pullModel', () => {
  it('reports progress and resolves on success', async () => {
    const authFetch = vi.fn().mockResolvedValue(streamResponse([
      sse({ status: 'pulling manifest' }, { status: 'downloading', percent: 50, total: 10, completed: 5 }, { status: 'success' }),
    ]));
    const progress = [];
    await pullModel(authFetch, 'llama3.2', { onProgress: (p) => progress.push(p.percent ?? p.status) });
    expect(progress).toEqual(['pulling manifest', 50]);
    expect(JSON.parse(authFetch.mock.calls[0][1].body)).toEqual({ model: 'llama3.2' });
  });

  it('rejects with the server message', async () => {
    const authFetch = vi.fn().mockResolvedValue(streamResponse([sse({ status: 'error', error: 'no space left' })]));
    await expect(pullModel(authFetch, 'x')).rejects.toThrow('no space left');
  });

  it('rejects when the stream ends without success', async () => {
    const authFetch = vi.fn().mockResolvedValue(streamResponse([sse({ status: 'downloading' })]));
    await expect(pullModel(authFetch, 'x')).rejects.toThrow('ended unexpectedly');
  });
});

describe('settingsBody', () => {
  it('keeps the other providers\' models and only sends keys that are given', () => {
    const saved = { provider: 'ollama', ollama_model: 'llama3.2', openai_model: 'gpt-4o', anthropic_model: null, openai_key_set: true };
    expect(settingsBody(saved, { provider: 'anthropic', anthropic_model: '' })).toEqual({
      provider: 'anthropic', ollama_model: 'llama3.2', openai_model: 'gpt-4o', anthropic_model: null,
    });
  });
});

describe('migrateLegacySettings', () => {
  const storage = (items) => {
    const m = new Map(Object.entries(items));
    return { getItem: (k) => (m.has(k) ? m.get(k) : null), removeItem: (k) => m.delete(k), m };
  };

  it('moves browser-stored keys to the server once and deletes them', async () => {
    const s = storage({ llm_provider: 'openai', openai_api_key: 'sk-old-123456789', ollama_model: 'llama3.2' });
    const authFetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse(200, { saved: false }))
      .mockResolvedValueOnce(jsonResponse(200, { saved: true }));
    expect(await migrateLegacySettings(authFetch, s)).toBe(true);
    expect(JSON.parse(authFetch.mock.calls[1][1].body)).toEqual({
      provider: 'openai', ollama_model: 'llama3.2', openai_key: 'sk-old-123456789', anthropic_key: null,
    });
    expect(s.m.size).toBe(0);
  });

  it('never overwrites settings already saved on the server, but still clears the browser copy', async () => {
    const s = storage({ anthropic_api_key: 'sk-ant-old' });
    const authFetch = vi.fn().mockResolvedValueOnce(jsonResponse(200, { saved: true }));
    expect(await migrateLegacySettings(authFetch, s)).toBe(false);
    expect(authFetch).toHaveBeenCalledTimes(1);
    expect(s.m.size).toBe(0);
  });

  it('does nothing when there is nothing to migrate', async () => {
    const authFetch = vi.fn();
    expect(await migrateLegacySettings(authFetch, storage({}))).toBe(false);
    expect(authFetch).not.toHaveBeenCalled();
  });
});

describe('model helpers', () => {
  it('matches untagged names to :latest', () => {
    expect(isInstalled('llama3.2', ['llama3.2:latest'])).toBe(true);
    expect(isInstalled('llama3.2:1b', ['llama3.2:latest'])).toBe(false);
  });

  it('formats sizes', () => {
    expect(formatBytes(2_000_000_000)).toBe('1.9 GB');
    expect(formatBytes(512)).toBe('512 B');
  });
});
