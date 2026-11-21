import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { AuthProvider } from '../context/AuthContext';
import DesktopDataSection from '../components/ai/DesktopDataSection';
import { jsonResponse, routeFetch, sentTo } from './helpers';

const BACKUP = { name: 'pkos-20261121-120000-manual.dump', kind: 'manual', size: 2_000_000, created: '2026-11-21T12:00:00Z' };
const PREVIEW = {
  imported_users: ['old_alice'], skipped_users: [{ username: 'vasu', reason: 'a user with this email or username already exists' }],
  rows: { documents: 3, document_chunks: 120, entities: 40, relationships: 25 }, note: 'AI settings and API keys are not imported; set them again in Settings.',
  dry_run: true,
};

function fakeDesktop() {
  return {
    isDesktop: true, dataDir: 'C:\\Users\\u\\AppData\\Local\\PKOS', version: '0.1.0',
    openDataFolder: vi.fn(), openLogs: vi.fn(),
    copyDiagnostics: vi.fn().mockResolvedValue({ copied: true }),
    backups: {
      list: vi.fn().mockResolvedValue([BACKUP]),
      create: vi.fn().mockImplementation(async (kind = 'manual') => ({ ...BACKUP, kind, name: `pkos-x-${kind}.dump` })),
      restore: vi.fn().mockResolvedValue({ restored: BACKUP.name, safetyBackup: 'pkos-y-before-restore.dump' }),
      openFolder: vi.fn(),
    },
  };
}

const renderSection = (desktop) => render(<AuthProvider><DesktopDataSection desktop={desktop} /></AuthProvider>);

beforeEach(() => {
  localStorage.setItem('pkos_token', 'tok');
});

describe('DesktopDataSection', () => {
  it('backs up now and lists recent backups', async () => {
    routeFetch({ 'GET /me': jsonResponse(200, { username: 'u' }) });
    const desktop = fakeDesktop();
    renderSection(desktop);
    expect(await screen.findByText(/Manual · 1.9 MB/)).toBeInTheDocument();
    await userEvent.click(screen.getByText('Back up now'));
    expect(await screen.findByText(/Backup saved: pkos-x-manual.dump/)).toBeInTheDocument();
    expect(desktop.backups.create).toHaveBeenCalledWith();
  });

  it('restores a listed backup and reports the safety copy', async () => {
    routeFetch({ 'GET /me': jsonResponse(200, { username: 'u' }) });
    const desktop = fakeDesktop();
    renderSection(desktop);
    await userEvent.click(await screen.findByText('Restore'));
    expect(desktop.backups.restore).toHaveBeenCalledWith(BACKUP.name);
    expect(await screen.findByText(/previous data was saved as pkos-y-before-restore.dump/)).toBeInTheDocument();
  });

  it('says nothing when a restore is cancelled, and shows main-process errors readably', async () => {
    routeFetch({ 'GET /me': jsonResponse(200, { username: 'u' }) });
    const desktop = fakeDesktop();
    desktop.backups.restore.mockResolvedValueOnce({ canceled: true })
      .mockRejectedValueOnce(new Error("Error invoking remote method 'pkos:backup-restore': Error: This file is not a PKOS backup."));
    renderSection(desktop);
    await userEvent.click(await screen.findByText('Restore from file…'));
    await waitFor(() => expect(desktop.backups.restore).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('Restore from file…'));
    expect(await screen.findByText('This file is not a PKOS backup.')).toBeInTheDocument();
  });

  it('checks, then imports after a before-import backup', async () => {
    const fetch = routeFetch({
      'GET /me': jsonResponse(200, { username: 'u' }),
      'POST /import/pkos': (body) => jsonResponse(200, { ...PREVIEW, dry_run: body.dry_run }),
    });
    const desktop = fakeDesktop();
    renderSection(desktop);
    await userEvent.click(await screen.findByText('Import…'));
    const importBtn = screen.getByRole('button', { name: 'Import' });
    expect(importBtn).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Password'), 'postgres');
    await userEvent.click(screen.getByText('Check'));
    expect(await screen.findByText('old_alice')).toBeInTheDocument();
    expect(screen.getByText(/vasu \(a user with this email/)).toBeInTheDocument();
    await userEvent.click(importBtn);
    expect(await screen.findByText(/Each person signs in with their old username and password/)).toBeInTheDocument();
    expect(desktop.backups.create).toHaveBeenCalledWith('before-import');
    expect(sentTo(fetch, 'POST', '/import/pkos')).toEqual([
      { host: 'localhost', port: 5433, database: 'pkos_v2', user: 'postgres', password: 'postgres', dry_run: true },
      { host: 'localhost', port: 5433, database: 'pkos_v2', user: 'postgres', password: 'postgres', dry_run: false },
    ]);
  });

  it('shows the server message when the old database cannot be reached', async () => {
    routeFetch({
      'GET /me': jsonResponse(200, { username: 'u' }),
      'POST /import/pkos': jsonResponse(400, { detail: 'Cannot connect to localhost:5433. Is the old database running?' }),
    });
    renderSection(fakeDesktop());
    await userEvent.click(await screen.findByText('Import…'));
    await userEvent.click(screen.getByText('Check'));
    expect(await screen.findByText(/Is the old database running\?/)).toBeInTheDocument();
  });

  it('copies diagnostics', async () => {
    routeFetch({ 'GET /me': jsonResponse(200, { username: 'u' }) });
    const desktop = fakeDesktop();
    renderSection(desktop);
    await userEvent.click(await screen.findByText('Copy diagnostics'));
    expect(await screen.findByText(/Diagnostics copied/)).toBeInTheDocument();
  });
});
