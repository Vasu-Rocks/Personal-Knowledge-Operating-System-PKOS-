import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AuthProvider } from '../context/AuthContext';
import Dashboard from '../components/Dashboard';
import { shortDate, toUiMessages } from '../lib/chatView';
import { jsonResponse, routeFetch, sentTo, sse, streamResponse } from './helpers';

vi.mock('react-force-graph-2d', () => ({ default: () => null }));

const SYSTEM = { database: true, ollama: true, embedder_ready: true, graph_worker_running: true, graph_jobs: { pending: 0, processing: 0, failed: 0 } };
const SETTINGS = { provider: 'ollama', saved: true, openai_key_set: false, anthropic_key_set: false, effective_model: 'llama3.2' };
const NOW = new Date().toISOString();

const CHAT_A = { conversation_id: 'aaaa', title: 'Glacier station', message_count: 4, created_at: NOW, updated_at: NOW };
const CHAT_B = { conversation_id: 'bbbb', title: 'Exam prep', message_count: 2, created_at: NOW, updated_at: '2025-03-12T10:00:00Z' };

const OPENED_A = {
  ...CHAT_A,
  messages: [
    { message_id: 'm1', seq: 1, role: 'user', content: 'Who visits the station?', standalone_query: null, needs_search: null, sources: null, graph: null, status: 'complete' },
    { message_id: 'm2', seq: 2, role: 'assistant', content: 'The surveyor [Chunk 1].', sources: [{ chunk_id: 1, filename: 'station.txt', page: 1, text: 'The surveyor visits', via: 'vector' }], graph: { nodes: [], links: [] }, status: 'complete' },
    { message_id: 'm3', seq: 3, role: 'user', content: 'When does he come?', standalone_query: 'When does the surveyor visit the station?', needs_search: true, sources: null, graph: null, status: 'complete' },
    { message_id: 'm4', seq: 4, role: 'assistant', content: 'Every Tues', sources: [], graph: null, status: 'partial' },
  ],
};

function routes(extra = {}) {
  return {
    'GET /me': jsonResponse(200, { username: 'u', name: 'U' }),
    'GET /documents': jsonResponse(200, { documents: [] }),
    'GET /graph/status': jsonResponse(200, { entities: 0, relationships: 0, communities: 0, pending_summaries: 0, active_jobs: 0 }),
    'GET /llm/status': jsonResponse(200, { ready: true, configured: true, provider: 'ollama', model: 'llama3.2', message: 'Ready' }),
    'GET /system/status': jsonResponse(200, SYSTEM),
    'GET /settings/llm': jsonResponse(200, SETTINGS),
    'GET /ollama/models': jsonResponse(200, { models: [] }),
    'GET /conversations': jsonResponse(200, { conversations: [CHAT_A, CHAT_B], next_before: null }),
    'GET /memories': jsonResponse(200, { memories: [] }),
    'GET /conversations/aaaa': jsonResponse(200, OPENED_A),
    ...extra,
  };
}

const renderDashboard = () => render(<AuthProvider><Dashboard /></AuthProvider>);

async function openChatsTab() {
  await userEvent.click(await screen.findByRole('tab', { name: 'Chats' }));
}

const answer = (conversationId, title, extra = []) => () => streamResponse([
  sse({ type: 'conversation', conversation_id: conversationId, title }, ...extra,
    { type: 'sources', sources: [] }, { type: 'graph', data: { nodes: [], links: [] } }),
  sse({ type: 'token', content: 'Answer text' }, { type: 'saved', question_id: 'q', answer_id: 'a' }, '[DONE]'),
]);

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('pkos_token', 'tok');
  sessionStorage.setItem('pkos_ai_setup_skipped', '1');
});

describe('chat list', () => {
  it('lists saved chats and opens one with its history, searched question and interrupted answer', async () => {
    routeFetch(routes());
    renderDashboard();
    await openChatsTab();
    const rows = await screen.findAllByTestId('chat-row');
    expect(rows.map((r) => r.textContent)).toEqual([expect.stringContaining('Glacier station'), expect.stringContaining('Exam prep')]);

    await userEvent.click(screen.getByText('Glacier station'));
    expect(await screen.findByText('Who visits the station?')).toBeInTheDocument();
    expect(screen.getByText('Searched for: When does the surveyor visit the station?')).toBeInTheDocument();
    expect(screen.getByText('(This answer was interrupted.)')).toBeInTheDocument();
    expect(screen.getByTestId('chat-title')).toHaveTextContent('Glacier station');
    expect(screen.getAllByTestId('chat-row')[0]).toHaveAttribute('aria-current', 'true');
    expect(localStorage.getItem('pkos_last_chat')).toBe('aaaa');
  });

  it('starts a chat with the first question, then sends follow-ups into it', async () => {
    let calls = 0;
    const fetch = routeFetch(routes({
      'GET /conversations': jsonResponse(200, { conversations: [], next_before: null }),
      'POST /query/stream': () => (++calls === 1
        ? answer('cccc', 'How many sensors?')()
        : answer('cccc', 'How many sensors?', [{ type: 'rewrite', standalone: 'When will the 12 sensors arrive?', needs_search: true, rewritten: true }])()),
    }));
    renderDashboard();
    await openChatsTab();
    expect(await screen.findByText(/No chats yet/)).toBeInTheDocument();

    const box = screen.getByPlaceholderText('Query the unified database...');
    await userEvent.type(box, 'How many sensors?{enter}');
    await screen.findAllByText('Answer text');
    expect(within(await screen.findByTestId('chat-row')).getByText('How many sensors?')).toBeInTheDocument();
    expect(screen.getByTestId('chat-title')).toHaveTextContent('How many sensors?');

    await userEvent.type(box, 'When will they arrive?{enter}');
    expect(await screen.findByText('Searched for: When will the 12 sensors arrive?')).toBeInTheDocument();
    expect(sentTo(fetch, 'POST', '/query/stream')).toEqual([
      { query: 'How many sensors?' },
      { query: 'When will they arrive?', conversation_id: 'cccc' },
    ]);
  });

  it('shows when the previous answer is reworked instead of searched', async () => {
    routeFetch(routes({
      'POST /query/stream': answer('aaaa', 'Glacier station', [{ type: 'rewrite', standalone: 'Make the answer shorter', needs_search: false, rewritten: true }]),
    }));
    renderDashboard();
    await openChatsTab();
    await userEvent.click(await screen.findByText('Glacier station'));
    await screen.findByText('Who visits the station?');
    await userEvent.type(screen.getByPlaceholderText('Query the unified database...'), 'shorter{enter}');
    expect(await screen.findByText('Reworking the previous answer (same sources)')).toBeInTheDocument();
  });

  it('"New chat" empties the view and the next question starts a new chat', async () => {
    const fetch = routeFetch(routes({ 'POST /query/stream': answer('dddd', 'Fresh start') }));
    renderDashboard();
    await openChatsTab();
    await userEvent.click(await screen.findByText('Glacier station'));
    await screen.findByText('Who visits the station?');
    await userEvent.click(screen.getByRole('button', { name: /New chat/ }));
    expect(screen.queryByText('Who visits the station?')).not.toBeInTheDocument();
    expect(screen.getByTestId('chat-title')).toHaveTextContent('New chat');
    expect(localStorage.getItem('pkos_last_chat')).toBeNull();
    await userEvent.type(screen.getByPlaceholderText('Query the unified database...'), 'Fresh start{enter}');
    await screen.findAllByText('Answer text');
    expect(sentTo(fetch, 'POST', '/query/stream')).toEqual([{ query: 'Fresh start' }]);
  });

  it('renames a chat inline', async () => {
    const fetch = routeFetch(routes({
      'PATCH /conversations/bbbb': (body) => jsonResponse(200, { ...CHAT_B, title: body.title }),
    }));
    renderDashboard();
    await openChatsTab();
    await userEvent.hover(await screen.findByText('Exam prep')); // the row's buttons appear on hover
    await userEvent.click(await screen.findByRole('button', { name: 'Rename Exam prep' }));
    const input = screen.getByRole('textbox', { name: 'Chat title' });
    await userEvent.clear(input);
    await userEvent.type(input, 'GATE revision{enter}');
    expect(await screen.findByText('GATE revision')).toBeInTheDocument();
    expect(sentTo(fetch, 'PATCH', '/conversations/bbbb')).toEqual([{ title: 'GATE revision' }]);
  });

  it('deletes a chat only after confirming, and leaves the open chat when it is deleted', async () => {
    const fetch = routeFetch(routes({ 'DELETE /conversations/aaaa': { ok: true, status: 204, json: () => Promise.resolve(null) } }));
    renderDashboard();
    await openChatsTab();
    await userEvent.click(await screen.findByText('Glacier station'));
    await screen.findByText('Who visits the station?');

    await userEvent.click(screen.getByRole('button', { name: 'Delete Glacier station' }));
    expect(screen.getByText(/This cannot be undone/)).toBeInTheDocument();
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(screen.queryByText('Glacier station')).not.toBeInTheDocument());
    expect(screen.queryByText('Who visits the station?')).not.toBeInTheDocument();
    expect(screen.getByTestId('chat-title')).toHaveTextContent('New chat');
  });

  it('reopens the chat that was open last time, and forgets one that is gone', async () => {
    localStorage.setItem('pkos_last_chat', 'aaaa');
    routeFetch(routes());
    const first = renderDashboard();
    expect(await screen.findByText('Who visits the station?')).toBeInTheDocument();
    first.unmount();

    localStorage.setItem('pkos_last_chat', 'gone');
    routeFetch(routes({ 'GET /conversations/gone': jsonResponse(404, { detail: 'Chat not found.' }) }));
    renderDashboard();
    await waitFor(() => expect(localStorage.getItem('pkos_last_chat')).toBeNull());
    expect(screen.getByTestId('chat-title')).toHaveTextContent('New chat');
  });
});

describe('chat view helpers', () => {
  it('turns stored messages into view messages', () => {
    const ui = toUiMessages(OPENED_A.messages);
    expect(ui.map((m) => m.type)).toEqual(['user', 'ai', 'user', 'ai']);
    expect(ui[0].searched).toBeNull();
    expect(ui[1].sources[0].filename).toBe('station.txt');
    expect(ui[2].searched).toBe('When does the surveyor visit the station?');
    expect(ui[3].text).toBe('Every Tues\n\n*(This answer was interrupted.)*');
    expect(toUiMessages([{ message_id: 'x', role: 'user', content: 'shorter', standalone_query: 'Make it shorter', needs_search: false }])[0])
      .toMatchObject({ searched: null, reused: true });
  });

  it('formats chat dates briefly', () => {
    const now = new Date(2026, 10, 23, 15, 0);
    expect(shortDate(new Date(2026, 10, 22, 9, 0).toISOString(), now)).toBe('Yesterday');
    expect(shortDate(new Date(2026, 10, 23, 9, 5).toISOString(), now)).toMatch(/9|09/);
    expect(shortDate(new Date(2025, 2, 12).toISOString(), now)).toMatch(/2025/);
    expect(shortDate('not a date', now)).toBe('');
  });
});
