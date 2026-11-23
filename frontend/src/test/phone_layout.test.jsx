import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { AuthProvider } from '../context/AuthContext';
import Dashboard from '../components/Dashboard';
import { jsonResponse, routeFetch, sse, streamResponse } from './helpers';

vi.mock('react-force-graph-2d', () => ({ default: () => null }));

const NOW = new Date().toISOString();
const SYSTEM = { database: true, ollama: true, embedder_ready: true, graph_worker_running: true, graph_jobs: { pending: 0, processing: 0, failed: 0 } };
const CHAT = { conversation_id: 'aaaa', title: 'Glacier station', message_count: 2, created_at: NOW, updated_at: NOW };

function routes(extra = {}) {
  return {
    'GET /me': jsonResponse(200, { username: 'u', name: 'U' }),
    'GET /documents': jsonResponse(200, { documents: [] }),
    'GET /graph/status': jsonResponse(200, { entities: 0, relationships: 0, communities: 0, pending_summaries: 0, active_jobs: 0 }),
    'GET /llm/status': jsonResponse(200, { ready: false, configured: false, provider: 'ollama', model: 'llama3.2', message: 'not set up' }),
    'GET /system/status': jsonResponse(200, SYSTEM),
    'GET /settings/llm': jsonResponse(200, { provider: 'ollama', saved: true, effective_model: 'llama3.2' }),
    'GET /ollama/models': jsonResponse(200, { models: [] }),
    'GET /conversations': jsonResponse(200, { conversations: [CHAT], next_before: null }),
    'GET /conversations/aaaa': jsonResponse(200, { ...CHAT, messages: [
      { message_id: 'm1', role: 'user', content: 'Who visits the station?' },
      { message_id: 'm2', role: 'assistant', content: 'The surveyor [Chunk 1].', status: 'complete', graph: null,
        sources: [{ chunk_id: 1, filename: 'station.txt', page: 1, text: 'The surveyor visits', distance: 0.2 }] },
    ] }),
    'GET /memories': jsonResponse(200, { memories: [] }),
    ...extra,
  };
}

/** Pretends the screen is phone-sized (or not) for useIsPhone. */
function screenIsPhone(yes) {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: yes && query.includes('max-width: 767px'), media: query,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  }));
}

const shell = () => document.querySelector('.os-shell');
const tab = (name) => within(screen.getByRole('tablist', { name: 'PKOS sections' })).getByRole('tab', { name: new RegExp(name) });

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('pkos_token', 'tok');
  sessionStorage.clear();
});
afterEach(() => { delete window.matchMedia; });

describe('phone layout', () => {
  it('shows one panel at a time with Chat / Sources / Library tabs', async () => {
    screenIsPhone(true);
    routeFetch(routes());
    render(<AuthProvider><Dashboard /></AuthProvider>);
    await screen.findByPlaceholderText('Query the unified database...');
    expect(shell()).toHaveClass('phone');
    expect(shell()).toHaveAttribute('data-tab', 'chat');
    expect(tab('Chat')).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByText('Generative Inference Core')).not.toBeInTheDocument(); // no room for the long label

    await userEvent.click(tab('Library'));
    expect(shell()).toHaveAttribute('data-tab', 'library');
    await userEvent.click(await screen.findByRole('tab', { name: 'Chats' }));
    await userEvent.click(await screen.findByText('Glacier station'));
    await waitFor(() => expect(shell()).toHaveAttribute('data-tab', 'chat')); // opening a chat shows it
    expect(await screen.findByText('Who visits the station?')).toBeInTheDocument();
    expect(tab('Sources')).toHaveTextContent('Sources (1)');
  });

  it('tapping a citation opens the Sources tab', async () => {
    screenIsPhone(true);
    localStorage.setItem('pkos_last_chat', 'aaaa');
    routeFetch(routes());
    render(<AuthProvider><Dashboard /></AuthProvider>);
    // A tap is hover + click at once: the badge must survive the hover's re-render to receive the click.
    const badge = await screen.findByRole('button', { name: 'Chunk 1' });
    expect(badge).toHaveClass('citation-badge'); // a real citation, not a plain link
    await userEvent.click(badge);
    expect(shell()).toHaveAttribute('data-tab', 'sources');
  });

  it('a laptop-sized screen keeps the three panels and no tab bar', async () => {
    screenIsPhone(false);
    routeFetch(routes());
    render(<AuthProvider><Dashboard /></AuthProvider>);
    await screen.findByPlaceholderText('Query the unified database...');
    expect(shell()).not.toHaveClass('phone');
    expect(screen.queryByRole('tablist', { name: 'PKOS sections' })).not.toBeInTheDocument();
    expect(screen.getByText('Generative Inference Core')).toBeInTheDocument();
  });

  it('a big question box font, so phones do not zoom in on it', async () => {
    screenIsPhone(true);
    routeFetch(routes({ 'POST /query/stream': () => streamResponse([sse({ type: 'token', content: 'ok' }, '[DONE]')]) }));
    render(<AuthProvider><Dashboard /></AuthProvider>);
    expect(await screen.findByPlaceholderText('Query the unified database...')).toHaveStyle({ fontSize: '16px' });
  });
});
