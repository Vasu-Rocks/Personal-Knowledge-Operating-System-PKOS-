import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AuthProvider } from '../context/AuthContext';
import Dashboard from '../components/Dashboard';
import { jsonResponse, routeFetch, sse, streamResponse } from './helpers';

vi.mock('react-force-graph-2d', () => ({ default: () => null })); // canvas-based; not needed here

const SYSTEM = { database: true, ollama: true, embedder_ready: true, graph_worker_running: true, graph_jobs: { pending: 0, processing: 0, failed: 0 } };
const SETTINGS = { provider: 'ollama', saved: false, openai_key_set: false, anthropic_key_set: false, effective_model: 'llama3.2' };

function routes(llmStatus, extra = {}) {
  return {
    'GET /me': jsonResponse(200, { username: 'u', name: 'U' }),
    'GET /documents': jsonResponse(200, { documents: [] }),
    'GET /graph/status': jsonResponse(200, { entities: 0, relationships: 0, communities: 0, pending_summaries: 0, active_jobs: 0 }),
    'GET /llm/status': jsonResponse(200, llmStatus),
    'GET /system/status': jsonResponse(200, SYSTEM),
    'GET /settings/llm': jsonResponse(200, SETTINGS),
    'GET /ollama/models': jsonResponse(200, { models: [] }),
    'GET /conversations': jsonResponse(200, { conversations: [], next_before: null }),
    'GET /memories': jsonResponse(200, { memories: [] }),
    ...extra,
  };
}

const renderDashboard = () => render(<AuthProvider><Dashboard /></AuthProvider>);

beforeEach(() => {
  localStorage.setItem('pkos_token', 'tok');
});

describe('Dashboard', () => {
  it('opens AI setup on first run when no AI is usable', async () => {
    routeFetch(routes({ ready: false, configured: false, provider: 'ollama', model: 'llama3.2', message: "Model 'llama3.2' is not downloaded yet." }));
    renderDashboard();
    expect(await screen.findByText('Set up your AI')).toBeInTheDocument();
    expect(screen.getByText('AI not set up')).toBeInTheDocument();
  });

  it('stays out of the way when the AI is ready', async () => {
    routeFetch(routes({ ready: true, configured: false, provider: 'ollama', model: 'llama3.2', message: 'Ready' }));
    renderDashboard();
    expect(await screen.findByText('llama3.2 · on this PC')).toBeInTheDocument();
    expect(screen.queryByText('Set up your AI')).not.toBeInTheDocument();
  });

  it('does not reopen setup after it was skipped in this session', async () => {
    sessionStorage.setItem('pkos_ai_setup_skipped', '1');
    routeFetch(routes({ ready: false, configured: false, provider: 'ollama', model: 'llama3.2', message: 'x' }));
    renderDashboard();
    expect(await screen.findByText('AI not set up')).toBeInTheDocument();
    expect(screen.queryByText('Set up your AI')).not.toBeInTheDocument();
  });

  it('sends questions without any provider or key headers and streams the answer', async () => {
    localStorage.setItem('openai_api_key', 'sk-legacy-should-not-be-sent');
    const fetch = routeFetch(routes({ ready: true, configured: true, provider: 'ollama', model: 'llama3.2', message: 'Ready' }, {
      'PUT /settings/llm': (body) => jsonResponse(200, { ...SETTINGS, ...body, saved: true }),
      'POST /query/stream': () => streamResponse([
        sse({ type: 'sources', sources: [] }, { type: 'graph', data: { nodes: [], links: [] } }),
        sse({ type: 'token', content: 'Hello ' }), sse({ type: 'token', content: 'world' }, '[DONE]'),
      ]),
    }));
    renderDashboard();
    await screen.findByText('llama3.2 · on this PC');
    await waitFor(() => expect(localStorage.getItem('openai_api_key')).toBeNull()); // migrated off the browser
    await userEvent.type(screen.getByPlaceholderText('Ask about your documents...'), 'hi{enter}');
    expect(await screen.findByText('Hello world')).toBeInTheDocument();
    const [, init] = fetch.mock.calls.find(([url]) => String(url).endsWith('/query/stream'));
    expect(Object.keys(init.headers).map((h) => h.toLowerCase()).sort()).toEqual(['authorization', 'content-type']);
  });
});
