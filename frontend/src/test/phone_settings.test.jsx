import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AuthProvider } from '../context/AuthContext';
import SettingsView from '../components/SettingsView';
import Dashboard from '../components/Dashboard';
import { jsonResponse, routeFetch } from './helpers';

// This file runs as if the page was served to a phone by the laptop's phone server.
vi.mock('../api', () => ({ API: 'https://192.168.137.1:47100/api/v1', API_BASE: 'https://192.168.137.1:47100', IS_DESKTOP: false, IS_PHONE_ACCESS: true }));
vi.mock('react-force-graph-2d', () => ({ default: () => null }));

const SYSTEM = { database: true, ollama: true, embedder_ready: true, graph_worker_running: true, graph_jobs: { pending: 0, processing: 0, failed: 0 } };
const routes = {
  'GET /me': jsonResponse(200, { username: 'u', name: 'U' }),
  'GET /settings/llm': jsonResponse(200, { provider: 'ollama', saved: true, effective_model: 'llama3.2', openai_key_set: false, anthropic_key_set: false }),
  'GET /ollama/models': jsonResponse(200, { models: [] }),
  'GET /graph/status': jsonResponse(200, { entities: 0, relationships: 0, communities: 0, pending_summaries: 0, active_jobs: 0 }),
  'GET /memories/settings': jsonResponse(200, { enabled: true, suggest: true }),
  'GET /memories': jsonResponse(200, { memories: [] }),
  'GET /documents': jsonResponse(200, { documents: [] }),
  'GET /llm/status': jsonResponse(200, { ready: false, configured: false, provider: 'ollama', model: 'llama3.2', message: 'not set up' }),
  'GET /system/status': jsonResponse(200, SYSTEM),
  'GET /conversations': jsonResponse(200, { conversations: [], next_before: null }),
};

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('pkos_token', 'tok');
  sessionStorage.clear();
});

describe('Settings on a phone', () => {
  it('shows the AI model read-only, without Save; memory settings stay usable', async () => {
    routeFetch(routes);
    render(<AuthProvider><SettingsView onClose={vi.fn()} onOpenSetup={undefined} /></AuthProvider>);
    expect(await screen.findByTestId('phone-ai-readonly')).toHaveTextContent('llama3.2 · on the laptop');
    expect(screen.getByText(/Choose the model or add API keys there/)).toBeInTheDocument();
    expect(screen.queryByRole('tablist', { name: 'AI provider' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Save$/ })).not.toBeInTheDocument();
    expect(screen.queryByText('Run setup again')).not.toBeInTheDocument();
    expect(await screen.findByRole('checkbox', { name: /Use memories and past chats/ })).toBeInTheDocument();
    expect(screen.queryByText(/Let paired phones/)).not.toBeInTheDocument(); // phone access is managed on the laptop
  });

  it('never opens the AI setup wizard on a phone, even when the AI is not set up', async () => {
    routeFetch(routes);
    render(<AuthProvider><Dashboard /></AuthProvider>);
    await screen.findByPlaceholderText('Ask about your documents...');
    await new Promise((r) => setTimeout(r, 200));
    await waitFor(() => expect(screen.queryByText(/Set up your AI/)).not.toBeInTheDocument());
  });
});
