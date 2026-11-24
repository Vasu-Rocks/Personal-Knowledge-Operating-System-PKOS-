import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { AuthProvider } from '../context/AuthContext';
import Dashboard from '../components/Dashboard';
import { jsonResponse, routeFetch, sentTo } from './helpers';

vi.mock('react-force-graph-2d', () => ({ default: () => null }));

const NOW = new Date().toISOString();
const SYSTEM = { database: true, ollama: true, embedder_ready: true, graph_worker_running: true, graph_jobs: { pending: 0, processing: 0, failed: 0 } };
const CHAT = { conversation_id: 'aaaa', title: 'Glacier station', message_count: 2, created_at: NOW, updated_at: NOW };
const DOC = { doc_id: 'd1', filename: 'station.txt', index_status: 'READY', graph_status: 'COMPLETED', graph_processed: 1, graph_total: 1 };

function routes(extra = {}) {
  return {
    'GET /me': jsonResponse(200, { username: 'u', name: 'U' }),
    'GET /documents': jsonResponse(200, { documents: [DOC] }),
    'GET /graph/status': jsonResponse(200, { entities: 0, relationships: 0, communities: 0, pending_summaries: 0, active_jobs: 0 }),
    'GET /llm/status': jsonResponse(200, { ready: true, configured: true, provider: 'ollama', model: 'llama3.2', message: 'Ready' }),
    'GET /system/status': jsonResponse(200, SYSTEM),
    'GET /settings/llm': jsonResponse(200, { provider: 'ollama', saved: true, effective_model: 'llama3.2' }),
    'GET /ollama/models': jsonResponse(200, { models: [] }),
    'GET /conversations': jsonResponse(200, { conversations: [CHAT], next_before: null }),
    'GET /conversations/aaaa': jsonResponse(200, { ...CHAT, messages: [
      { message_id: 'm1', role: 'user', content: 'Who visits the station?' },
      { message_id: 'm2', role: 'assistant', content: 'The surveyor [Chunk 1].', status: 'complete', graph: null,
        sources: [{ chunk_id: 1, filename: 'station.txt', page: 1, text: 'The surveyor visits', distance: 0.14 }] },
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

const shell = () => document.querySelector('.app-shell');
const sidebar = () => screen.getByRole('navigation', { name: 'PKOS' });
const sources = () => screen.queryByRole('complementary', { name: 'Sources' });

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('pkos_token', 'tok');
  sessionStorage.setItem('pkos_ai_setup_skipped', '1');
});
afterEach(() => { delete window.matchMedia; });

describe('the main screen', () => {
  it('a new chat is calm: sidebar, an empty-chat hint, the question box, and no sources panel', async () => {
    screenIsPhone(false);
    routeFetch(routes());
    render(<AuthProvider><Dashboard /></AuthProvider>);
    expect(await screen.findByTestId('chat-empty')).toHaveTextContent('Ask anything about your documents');
    expect(screen.getByPlaceholderText('Ask about your documents...')).toBeInTheDocument();
    expect(within(sidebar()).getByText('Glacier station')).toBeInTheDocument();
    expect(sources()).not.toBeInTheDocument();
    expect(screen.queryByText(/Generative Inference Core|RAG X-Ray|Extracted Vectors|HNSW/)).not.toBeInTheDocument();
  });

  it('Sources opens only when asked for, shows file, page and match, and closes again', async () => {
    screenIsPhone(false);
    localStorage.setItem('pkos_last_chat', 'aaaa');
    routeFetch(routes());
    render(<AuthProvider><Dashboard /></AuthProvider>);
    await screen.findByText('Who visits the station?');
    expect(sources()).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Sources (1)' }));
    const panel = sources();
    expect(within(panel).getByTestId('source-card')).toHaveTextContent('station.txt · page 1');
    expect(within(panel).getByTestId('source-card')).toHaveTextContent('Match 86%');
    await userEvent.click(within(panel).getByRole('button', { name: 'Close sources' }));
    expect(sources()).not.toBeInTheDocument();
  });

  it('tapping a citation opens Sources at that passage', async () => {
    screenIsPhone(false);
    localStorage.setItem('pkos_last_chat', 'aaaa');
    routeFetch(routes());
    render(<AuthProvider><Dashboard /></AuthProvider>);
    // A tap is hover + click at once: the badge must survive the hover's re-render to receive the click.
    const badge = await screen.findByRole('button', { name: 'Chunk 1' });
    expect(badge).toHaveClass('citation-badge');
    await userEvent.click(badge);
    expect(sources()).toBeInTheDocument();
    expect(document.getElementById('source-card-1')).toHaveClass('focused');
  });

  it('Documents is a page of its own, opened from the sidebar; New chat goes back to the chat', async () => {
    screenIsPhone(false);
    const fetch = routeFetch(routes({ 'DELETE /documents/d1': { ok: true, status: 200, json: () => Promise.resolve({}) } }));
    render(<AuthProvider><Dashboard /></AuthProvider>);
    await userEvent.click(await screen.findByRole('button', { name: /Documents/ }));
    expect(await screen.findByRole('heading', { name: 'Documents' })).toBeInTheDocument();
    const row = await screen.findByTestId('doc-row');
    expect(row).toHaveTextContent('station.txt');
    expect(row).toHaveTextContent('Ready to ask · map ready');
    expect(screen.queryByPlaceholderText('Ask about your documents...')).not.toBeInTheDocument();

    await userEvent.click(within(row).getByRole('button', { name: 'Delete station.txt' }));
    expect(sentTo(fetch, 'DELETE', '/documents/d1')).toHaveLength(0); // asks first
    await userEvent.click(within(row).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(screen.queryByTestId('doc-row')).not.toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /New chat/ }));
    expect(await screen.findByPlaceholderText('Ask about your documents...')).toBeInTheDocument();
  });
});

describe('on a phone', () => {
  it('the sidebar is a menu that slides in, and closes when a chat is opened', async () => {
    screenIsPhone(true);
    routeFetch(routes());
    render(<AuthProvider><Dashboard /></AuthProvider>);
    await screen.findByPlaceholderText('Ask about your documents...');
    expect(shell()).toHaveClass('phone');
    expect(sidebar()).not.toHaveClass('open');
    await userEvent.click(screen.getByRole('button', { name: 'Open menu' }));
    expect(sidebar()).toHaveClass('open');
    await userEvent.click(within(sidebar()).getByText('Glacier station'));
    await waitFor(() => expect(sidebar()).not.toHaveClass('open'));
    expect(await screen.findByText('Who visits the station?')).toBeInTheDocument();
  });

  it('a big question box font, so phones do not zoom in on it', async () => {
    screenIsPhone(true);
    routeFetch(routes());
    render(<AuthProvider><Dashboard /></AuthProvider>);
    expect(await screen.findByPlaceholderText('Ask about your documents...')).toHaveStyle({ fontSize: '16px' });
  });

  it('a laptop has no menu button: the sidebar is always there', async () => {
    screenIsPhone(false);
    routeFetch(routes());
    render(<AuthProvider><Dashboard /></AuthProvider>);
    await screen.findByPlaceholderText('Ask about your documents...');
    expect(shell()).not.toHaveClass('phone');
    expect(screen.queryByRole('button', { name: 'Open menu' })).not.toBeInTheDocument();
    expect(sidebar()).toHaveClass('open');
  });
});
