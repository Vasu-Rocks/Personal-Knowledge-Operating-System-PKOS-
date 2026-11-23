import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AuthProvider } from '../context/AuthContext';
import SetupWizard from '../components/ai/SetupWizard';
import SettingsView from '../components/SettingsView';
import StatusBadge from '../components/ai/StatusBadge';
import { jsonResponse, routeFetch, sentTo, sse, streamResponse } from './helpers';

const DEFAULTS = {
  provider: 'ollama', ollama_model: null, openai_model: null, anthropic_model: null, effective_model: 'llama3.2',
  openai_key_set: false, openai_key_hint: null, anthropic_key_set: false, anthropic_key_hint: null, saved: false,
};
const MODELS = { models: [{ name: 'llama3.2:latest', size: 2_000_000_000, parameter_size: '3.2B' }] };
const saved = (body) => jsonResponse(200, { ...DEFAULTS, ...body, saved: true });

const withAuth = (ui) => render(<AuthProvider>{ui}</AuthProvider>);

beforeEach(() => {
  localStorage.setItem('pkos_token', 'tok');
});

describe('SetupWizard', () => {
  it('uses an installed local model and saves it', async () => {
    const fetch = routeFetch({
      'GET /me': jsonResponse(200, { username: 'u' }),
      'GET /settings/llm': jsonResponse(200, DEFAULTS),
      'GET /ollama/models': jsonResponse(200, MODELS),
      'PUT /settings/llm': (body) => saved(body),
    });
    const onClose = vi.fn();
    withAuth(<SetupWizard status={{ ready: false, message: 'Model not downloaded' }} onClose={onClose} />);
    await userEvent.click(await screen.findByText('On this computer'));
    const row = (await screen.findByText('Llama 3.2 (3B)')).closest('.ai-model');
    expect(within(row).getByText('Installed')).toBeInTheDocument();
    await userEvent.click(within(row).getByText('Use'));
    expect(await screen.findByText("You're all set")).toBeInTheDocument();
    expect(sentTo(fetch, 'PUT', '/settings/llm')).toEqual([
      { provider: 'ollama', ollama_model: 'llama3.2', openai_model: null, anthropic_model: null },
    ]);
    await userEvent.click(screen.getByText('Start using PKOS'));
    expect(onClose).toHaveBeenCalledWith(true);
  });

  it('downloads a model with progress, then saves it', async () => {
    const fetch = routeFetch({
      'GET /me': jsonResponse(200, { username: 'u' }),
      'GET /settings/llm': jsonResponse(200, DEFAULTS),
      'GET /ollama/models': jsonResponse(200, { models: [] }),
      'POST /ollama/pull': () => streamResponse([sse({ status: 'downloading', percent: 40, total: 100, completed: 40 }), sse({ status: 'success' })]),
      'PUT /settings/llm': (body) => saved(body),
    });
    withAuth(<SetupWizard status={null} onClose={vi.fn()} />);
    await userEvent.click(await screen.findByText('On this computer'));
    const row = (await screen.findByText('Llama 3.2 (1B)')).closest('.ai-model');
    await userEvent.click(within(row).getByText('Download'));
    expect(await screen.findByText("You're all set")).toBeInTheDocument();
    expect(sentTo(fetch, 'POST', '/ollama/pull')).toEqual([{ model: 'llama3.2:1b' }]);
    expect(sentTo(fetch, 'PUT', '/settings/llm')[0].ollama_model).toBe('llama3.2:1b');
  });

  it('disables the local option when Ollama is not running', async () => {
    routeFetch({
      'GET /me': jsonResponse(200, { username: 'u' }),
      'GET /settings/llm': jsonResponse(200, DEFAULTS),
      'GET /ollama/models': jsonResponse(503, { detail: 'Ollama is not running.' }),
    });
    withAuth(<SetupWizard status={null} onClose={vi.fn()} />);
    expect(await screen.findByText('The local AI engine (Ollama) is not running.')).toBeInTheDocument();
    expect(screen.getByText('On this computer').closest('button')).toBeDisabled();
  });

  it('saves a cloud key after a successful test', async () => {
    const fetch = routeFetch({
      'GET /me': jsonResponse(200, { username: 'u' }),
      'GET /settings/llm': jsonResponse(200, DEFAULTS),
      'GET /ollama/models': jsonResponse(200, MODELS),
      'POST /settings/llm/test': (body) => jsonResponse(200, { ok: true, provider: body.provider, model: 'claude-haiku-5-5', reply: 'OK' }),
      'PUT /settings/llm': (body) => saved({ ...body, anthropic_key_set: true }),
    });
    withAuth(<SetupWizard status={null} onClose={vi.fn()} />);
    await userEvent.click(await screen.findByText('Cloud API'));
    await userEvent.click(screen.getByRole('tab', { name: 'Anthropic' }));
    const save = screen.getByText('Save and continue');
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Anthropic API key/), 'sk-ant-abc123456789');
    await userEvent.click(screen.getByText('Test connection'));
    expect(await screen.findByText('Connected: claude-haiku-5-5 answered.')).toBeInTheDocument();
    await userEvent.click(save);
    expect(await screen.findByText(/from Anthropic/)).toBeInTheDocument();
    expect(sentTo(fetch, 'POST', '/settings/llm/test')[0]).toEqual({ provider: 'anthropic', anthropic_model: null, anthropic_key: 'sk-ant-abc123456789' });
    expect(sentTo(fetch, 'PUT', '/settings/llm')[0]).toMatchObject({ provider: 'anthropic', anthropic_key: 'sk-ant-abc123456789' });
  });

  it('can be skipped', async () => {
    routeFetch({
      'GET /me': jsonResponse(200, { username: 'u' }),
      'GET /settings/llm': jsonResponse(200, DEFAULTS),
      'GET /ollama/models': jsonResponse(200, MODELS),
    });
    const onClose = vi.fn();
    withAuth(<SetupWizard status={null} onClose={onClose} />);
    await userEvent.click(await screen.findByText('Skip for now'));
    expect(onClose).toHaveBeenCalledWith(false);
  });
});

describe('SettingsView', () => {
  const routes = (over = {}) => ({
    'GET /me': jsonResponse(200, { username: 'u' }),
    'GET /settings/llm': jsonResponse(200, { ...DEFAULTS, saved: true, provider: 'openai', openai_key_set: true, openai_key_hint: '…9876', ollama_model: 'llama3.2' }),
    'GET /ollama/models': jsonResponse(200, MODELS),
    'GET /graph/status': jsonResponse(200, { entities: 1, relationships: 2, communities: 0, pending_summaries: 0, active_jobs: 0 }),
    'PUT /settings/llm': (body) => saved(body),
    'GET /memories/settings': jsonResponse(200, { enabled: true, suggest: true }),
    'GET /memories': jsonResponse(200, { memories: [] }),
    ...over,
  });

  it('shows that a key is saved without ever putting it in the form', async () => {
    routeFetch(routes());
    withAuth(<SettingsView onClose={vi.fn()} />);
    expect(await screen.findByText('Saved …9876')).toBeInTheDocument();
    expect(screen.getByLabelText(/OpenAI API key/)).toHaveValue('');
  });

  it('saves without resending the key when it was not changed', async () => {
    const fetch = routeFetch(routes());
    const onSaved = vi.fn();
    withAuth(<SettingsView onClose={vi.fn()} onSaved={onSaved} />);
    await screen.findByText('Saved …9876');
    await userEvent.click(screen.getByRole('tab', { name: /Anthropic/ }));
    await userEvent.type(screen.getByLabelText(/Anthropic API key/), 'sk-ant-new-0000');
    await userEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const body = sentTo(fetch, 'PUT', '/settings/llm')[0];
    expect(body).toMatchObject({ provider: 'anthropic', anthropic_key: 'sk-ant-new-0000', ollama_model: 'llama3.2' });
    expect(body).not.toHaveProperty('openai_key');
  });

  it('lists installed Ollama models and selects one', async () => {
    routeFetch(routes());
    withAuth(<SettingsView onClose={vi.fn()} />);
    await screen.findByText('Saved …9876');
    await userEvent.click(screen.getByRole('tab', { name: /On this PC/ }));
    const row = (await screen.findByText('Llama 3.2 (3B)')).closest('.ai-model');
    expect(within(row).getByText('In use')).toBeInTheDocument();
  });

  it('removes a saved key', async () => {
    const fetch = routeFetch(routes());
    withAuth(<SettingsView onClose={vi.fn()} />);
    await userEvent.click(await screen.findByText('Remove saved OpenAI key'));
    await waitFor(() => expect(sentTo(fetch, 'PUT', '/settings/llm')).toHaveLength(1));
    expect(sentTo(fetch, 'PUT', '/settings/llm')[0].openai_key).toBe('');
  });
});

describe('StatusBadge', () => {
  it('shows the active model when ready', () => {
    render(<StatusBadge llm={{ ready: true, provider: 'ollama', model: 'llama3.2', message: 'Ready' }}
      system={{ database: true, graph_jobs: { pending: 1, processing: 1, failed: 0 } }} />);
    expect(screen.getByText('llama3.2 · on this PC · building map (2)')).toBeInTheDocument();
  });

  it('asks for setup when not ready and reports engine errors', async () => {
    const onClick = vi.fn();
    const { rerender } = render(<StatusBadge llm={{ ready: false, provider: 'openai', model: 'gpt-4o-mini', message: 'key missing' }} onClick={onClick} />);
    await userEvent.click(screen.getByText('AI not set up'));
    expect(onClick).toHaveBeenCalled();
    rerender(<StatusBadge error="Failed to fetch" />);
    expect(screen.getByText('PKOS engine not reachable')).toBeInTheDocument();
  });
});
