import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AuthProvider } from '../context/AuthContext';
import Dashboard from '../components/Dashboard';
import MemoryPage from '../components/memory/MemoryPage';
import { answeredFromMemories, toUiMessages } from '../lib/chatView';
import { guessKind, memoryDraft } from '../lib/memoriesApi';
import { jsonResponse, routeFetch, sentTo, sse, streamResponse } from './helpers';

vi.mock('react-force-graph-2d', () => ({ default: () => null }));

const NOW = new Date().toISOString();
const NO_CONTENT = { ok: true, status: 204, json: () => Promise.resolve(null) };
const withAuth = (ui) => render(<AuthProvider>{ui}</AuthProvider>);

const EXAM = { memory_id: 'm-exam', text: 'My GATE exam is on 14 February', kind: 'fact', origin: 'manual', status: 'active',
  source_conversation_id: null, source_message_id: null, source_title: null, created_at: NOW, updated_at: NOW,
  last_used_at: null, use_count: 0 };
const BULLETS = { ...EXAM, memory_id: 'm-bul', text: 'Answer in short bullet points', kind: 'preference',
  source_title: 'Exam prep', last_used_at: NOW, use_count: 3 };
const SENSORS = { ...EXAM, memory_id: 'm-sen', text: 'We chose the Campbell sensors', kind: 'conclusion' };

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('pkos_token', 'tok');
  sessionStorage.setItem('pkos_ai_setup_skipped', '1');
});

// ------------------------------------------------------------------------------------------------ helpers

describe('memory helpers', () => {
  it('prepares a draft: citations and markdown removed, one line, cut at a word to 300 characters', () => {
    expect(memoryDraft('The surveyor visits **every Tuesday** [Chunk 2].\n\nSee [Graph Entity: Station].'))
      .toBe('The surveyor visits every Tuesday. See.');
    const long = memoryDraft('word '.repeat(100));
    expect(long.length).toBeLessThanOrEqual(300);
    expect(long.endsWith('word…')).toBe(true);
  });

  it('guesses the kind, which the user can still change', () => {
    expect(guessKind('Please answer in short bullet points', 'user')).toBe('preference');
    expect(guessKind('Explain things simply, I am a beginner', 'user')).toBe('preference');
    expect(guessKind('We decided to order 12 sensors', 'user')).toBe('conclusion');
    expect(guessKind('The surveyor visits on Tuesdays.', 'ai')).toBe('conclusion');
    expect(guessKind('My exam is in February', 'user')).toBe('fact');
  });

  it('labels an answer as from memories only when a fact, and no passage or graph, was used', () => {
    expect(answeredFromMemories([EXAM], [], { nodes: [] })).toBe(true);
    expect(answeredFromMemories([BULLETS], [], null)).toBe(false);
    expect(answeredFromMemories([EXAM], [{ chunk_id: 1 }], null)).toBe(false);
    expect(answeredFromMemories([EXAM], [], { nodes: [{ id: 1 }] })).toBe(false);
    expect(answeredFromMemories(null, [], null)).toBe(false);
  });

  it('stored answers keep the memories they used and their server ids', () => {
    const [q, a] = toUiMessages([
      { message_id: 'q1', role: 'user', content: 'When is my exam?' },
      { message_id: 'a1', role: 'assistant', content: 'On 14 February.', sources: [], graph: null, status: 'complete',
        memories_used: [{ memory_id: 'm-exam', text: EXAM.text, kind: 'fact' }] },
    ]);
    expect(q).toMatchObject({ serverId: 'q1', plain: 'When is my exam?' });
    expect(a).toMatchObject({ serverId: 'a1', memoriesOnly: true, memories: [{ memory_id: 'm-exam' }] });
  });
});

// ------------------------------------------------------------------------------------------------ Memory page

describe('Memory page', () => {
  const routes = (over = {}) => ({
    'GET /me': jsonResponse(200, { username: 'u' }),
    'GET /memories/settings': jsonResponse(200, { enabled: true, suggest: true }),
    'GET /memories': jsonResponse(200, { memories: [EXAM, BULLETS, SENSORS] }),
    ...over,
  });

  it('lists memories grouped by kind, with where they came from and when they were used', async () => {
    routeFetch(routes());
    withAuth(<MemoryPage />);
    const answering = await screen.findByRole('list', { name: 'How to answer' });
    expect(within(answering).getByText('Answer in short bullet points')).toBeInTheDocument();
    expect(within(answering).getByText(/from the chat "Exam prep" · last used .* \(3×\)/)).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Facts about you' })).getByText(/Added by you · not used yet/)).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Things you decided' })).getByText('We chose the Campbell sensors')).toBeInTheDocument();
  });

  it('adds, edits and deletes a memory', async () => {
    const fetch = routeFetch(routes({
      'GET /memories': jsonResponse(200, { memories: [EXAM] }),
      'POST /memories': (body) => jsonResponse(201, { ...EXAM, memory_id: 'm-new', ...body }),
      'PATCH /memories/m-exam': (body) => jsonResponse(200, { ...EXAM, ...body, updated_at: 'later' }),
      'DELETE /memories/m-new': NO_CONTENT,
    }));
    withAuth(<MemoryPage />);
    await screen.findByText(EXAM.text);

    await userEvent.type(screen.getByRole('textbox', { name: 'New memory' }), 'Keep answers simple');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Kind of the new memory' }), 'preference');
    await userEvent.click(screen.getByRole('button', { name: /Add/ }));
    expect(await screen.findByText('Keep answers simple')).toBeInTheDocument();
    expect(sentTo(fetch, 'POST', '/memories')).toEqual([{ text: 'Keep answers simple', kind: 'preference' }]);

    await userEvent.click(screen.getByRole('button', { name: `Edit "${EXAM.text}"` }));
    const box = screen.getByRole('textbox', { name: 'Memory text' });
    await userEvent.clear(box);
    await userEvent.type(box, 'My GATE exam is on 15 February');
    await userEvent.click(screen.getByRole('button', { name: /Save/ }));
    expect(await screen.findByText('My GATE exam is on 15 February')).toBeInTheDocument();
    expect(sentTo(fetch, 'PATCH', '/memories/m-exam')).toEqual([{ text: 'My GATE exam is on 15 February', kind: 'fact' }]);

    await userEvent.click(screen.getByRole('button', { name: 'Delete "Keep answers simple"' }));
    await waitFor(() => expect(screen.queryByText('Keep answers simple')).not.toBeInTheDocument());
  });

  it('shows why a save was refused', async () => {
    routeFetch(routes({ 'POST /memories': jsonResponse(409, { detail: 'You already saved this memory.' }) }));
    withAuth(<MemoryPage />);
    await screen.findByText(EXAM.text);
    await userEvent.type(screen.getByRole('textbox', { name: 'New memory' }), EXAM.text);
    await userEvent.click(screen.getByRole('button', { name: /Add/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('You already saved this memory.');
  });

  it('deletes all only after confirming', async () => {
    const fetch = routeFetch(routes({ 'DELETE /memories': jsonResponse(200, { deleted: 3 }) }));
    withAuth(<MemoryPage />);
    await userEvent.click(await screen.findByRole('button', { name: /Delete all memories/ }));
    expect(screen.getByText('Delete all 3 memories? This cannot be undone.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Keep them' }));
    expect(sentTo(fetch, 'DELETE', '/memories?confirm=true')).toHaveLength(0);

    await userEvent.click(screen.getByRole('button', { name: /Delete all memories/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Delete all' }));
    expect(await screen.findByText('No memories yet.')).toBeInTheDocument();
    expect(sentTo(fetch, 'DELETE', '/memories?confirm=true')).toHaveLength(1);
  });

  it('switches memory and suggestions on and off at once', async () => {
    const fetch = routeFetch(routes({ 'PUT /memories/settings': (body) => jsonResponse(200, { enabled: true, suggest: true, ...body }) }));
    withAuth(<MemoryPage />);
    const use = await screen.findByRole('checkbox', { name: /Use memories and past chats/ });
    await userEvent.click(use);
    await waitFor(() => expect(use).not.toBeChecked());
    await userEvent.click(screen.getByRole('checkbox', { name: /suggest memories/ }));
    expect(sentTo(fetch, 'PUT', '/memories/settings')).toEqual([{ enabled: false }, { suggest: false }]);
  });
});

// ------------------------------------------------------------------------------------------------ in the chat

const SYSTEM = { database: true, ollama: true, embedder_ready: true, graph_worker_running: true, graph_jobs: { pending: 0, processing: 0, failed: 0 } };

function dashboardRoutes(extra = {}) {
  return {
    'GET /me': jsonResponse(200, { username: 'u', name: 'U' }),
    'GET /documents': jsonResponse(200, { documents: [] }),
    'GET /graph/status': jsonResponse(200, { entities: 0, relationships: 0, communities: 0, pending_summaries: 0, active_jobs: 0 }),
    'GET /llm/status': jsonResponse(200, { ready: true, configured: true, provider: 'ollama', model: 'llama3.2', message: 'Ready' }),
    'GET /system/status': jsonResponse(200, SYSTEM),
    'GET /settings/llm': jsonResponse(200, { provider: 'ollama', saved: true, effective_model: 'llama3.2' }),
    'GET /ollama/models': jsonResponse(200, { models: [] }),
    'GET /conversations': jsonResponse(200, { conversations: [], next_before: null }),
    ...extra,
  };
}

const ask = async (text) => {
  await userEvent.type(screen.getByPlaceholderText('Query the unified database...'), `${text}{enter}`);
};

describe('memories in the chat', () => {
  it('labels an answer that came from saved memories and lists them in the X-Ray panel', async () => {
    routeFetch(dashboardRoutes({
      'POST /query/stream': () => streamResponse([
        sse({ type: 'conversation', conversation_id: 'c1', title: 'When is my exam?' },
          { type: 'memories', memories: [{ memory_id: 'm-exam', text: EXAM.text, kind: 'fact' },
            { memory_id: 'm-bul', text: BULLETS.text, kind: 'preference' }], memories_only: true },
          { type: 'sources', sources: [] }, { type: 'graph', data: { nodes: [], links: [] } }),
        sse({ type: 'token', content: 'On 14 February.' }, { type: 'saved', question_id: 'q1', answer_id: 'a1' }, '[DONE]'),
      ]),
    }));
    withAuth(<Dashboard />);
    await ask('When is my exam?');
    expect(await screen.findByTestId('memory-label')).toHaveTextContent('Answered from your saved memories');
    const used = screen.getByTestId('memories-used');
    expect(used).toHaveTextContent('Memories used (2)');
    expect(within(used).getByText(EXAM.text)).toBeInTheDocument();
    expect(within(used).getByText('how to answer')).toBeInTheDocument();
  });

  it('does not label an answer that also had document passages', async () => {
    routeFetch(dashboardRoutes({
      'POST /query/stream': () => streamResponse([
        sse({ type: 'conversation', conversation_id: 'c1', title: 'Exam topics' },
          { type: 'memories', memories: [{ memory_id: 'm-exam', text: EXAM.text, kind: 'fact' }], memories_only: false },
          { type: 'sources', sources: [{ chunk_id: 1, filename: 'syllabus.pdf', page: 2, text: 'Topics', distance: 0.2 }] },
          { type: 'graph', data: { nodes: [], links: [] } }),
        sse({ type: 'token', content: 'Algorithms [Chunk 1].' }, '[DONE]'),
      ]),
    }));
    withAuth(<Dashboard />);
    await ask('What topics are on my exam?');
    await screen.findByTestId('memories-used');
    expect(screen.queryByTestId('memory-label')).not.toBeInTheDocument();
  });

  it('"Remember this" opens an editor prefilled from the message and saves it with its chat', async () => {
    const fetch = routeFetch(dashboardRoutes({
      'POST /query/stream': () => streamResponse([
        sse({ type: 'conversation', conversation_id: 'c1', title: 'Sensors' },
          { type: 'sources', sources: [] }, { type: 'graph', data: { nodes: [], links: [] } }),
        sse({ type: 'token', content: 'We decided on the Campbell sensors [Chunk 1].' },
          { type: 'saved', question_id: 'q1', answer_id: 'a1' }, '[DONE]'),
      ]),
      'POST /memories': (body) => jsonResponse(201, { ...SENSORS, ...body }),
    }));
    withAuth(<Dashboard />);
    await ask('Which sensors?');
    await screen.findByText(/We decided on the Campbell sensors/);
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Remember this' })).toHaveLength(2));
    await userEvent.click(screen.getAllByRole('button', { name: 'Remember this' })[1]);

    const dialog = screen.getByRole('dialog', { name: /Remember this/ });
    const box = within(dialog).getByRole('textbox', { name: 'Memory' });
    expect(box).toHaveValue('We decided on the Campbell sensors.');
    expect(within(dialog).getByRole('radio', { name: /Something we decided/ })).toBeChecked();
    expect(sentTo(fetch, 'POST', '/memories')).toHaveLength(0); // nothing is saved before the click

    await userEvent.clear(box);
    await userEvent.type(box, 'We chose the Campbell sensors');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save memory' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /Remember this/ })).not.toBeInTheDocument());
    expect(sentTo(fetch, 'POST', '/memories')).toEqual([{
      text: 'We chose the Campbell sensors', kind: 'conclusion', source_conversation_id: 'c1', source_message_id: 'a1',
    }]);
  });

  it('a past chat in the sources opens that chat', async () => {
    routeFetch(dashboardRoutes({
      'POST /query/stream': () => streamResponse([
        sse({ type: 'conversation', conversation_id: 'c2', title: 'What did we decide?' },
          { type: 'sources', sources: [{ chunk_id: 'chat:c1', conversation_id: 'c1', filename: 'Sensor order', page: '2026-11-20',
            text: 'Sensor order. They chose Campbell.', via: 'chat', distance: 0.3 }] },
          { type: 'graph', data: { nodes: [], links: [] } }),
        sse({ type: 'token', content: 'You chose Campbell [Chunk 1].' }, '[DONE]'),
      ]),
      'GET /conversations/c1': jsonResponse(200, {
        conversation_id: 'c1', title: 'Sensor order', created_at: NOW, updated_at: NOW,
        messages: [{ message_id: 'x1', role: 'user', content: 'Which sensors should we order?' },
          { message_id: 'x2', role: 'assistant', content: 'Campbell.', sources: [], graph: null, status: 'complete' }],
      }),
    }));
    withAuth(<Dashboard />);
    await ask('What did we decide about the sensors last time?');
    const card = await screen.findByTestId('past-chat-source');
    expect(card).toHaveTextContent('Earlier chat: Sensor order');
    expect(card).toHaveTextContent('2026-11-20');
    const open = within(card).getByRole('button', { name: 'Open the chat Sensor order' });
    await waitFor(() => expect(open).toBeEnabled());
    await userEvent.click(open);
    expect(await screen.findByText('Which sensors should we order?')).toBeInTheDocument();
    expect(screen.getByTestId('chat-title')).toHaveTextContent('Sensor order');
  });
});
