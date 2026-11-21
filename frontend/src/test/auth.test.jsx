import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import AuthView from '../components/AuthView';
import { AuthProvider } from '../context/AuthContext';
import { useAuth } from '../context/useAuth';

const json = (status, body) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });

function renderAuth() {
  return render(<AuthProvider><AuthView /></AuthProvider>);
}

function Status() {
  const { isAuthenticated, user } = useAuth();
  return <div>{isAuthenticated ? `in:${user?.username ?? '?'}` : 'out'}</div>;
}

beforeEach(() => {
  vi.restoreAllMocks();
  globalThis.fetch = vi.fn();
});

describe('AuthView', () => {
  it('shows login by default with no password length rule', () => {
    renderAuth();
    expect(screen.getByText('Welcome Back')).toBeInTheDocument();
    expect(document.querySelector('input[type=password]').minLength).toBe(-1);
  });

  it('register mode enforces the server rules in the form', async () => {
    renderAuth();
    await userEvent.click(screen.getByText('Initialize System'));
    expect(document.querySelector('input[type=password]').minLength).toBe(8);
    const username = screen.getByPlaceholderText('johndoe');
    expect(username).toHaveAttribute('pattern', '[A-Za-z0-9_.\\-]{3,32}');
    expect(username).toHaveAttribute('maxlength', '32');
    expect(screen.getByText('At least 8 characters')).toBeInTheDocument();
  });

  it('logs in, stores the token and loads the profile', async () => {
    fetch
      .mockReturnValueOnce(json(200, { access_token: 'tok-123', token_type: 'bearer' })) // /login
      .mockReturnValueOnce(json(200, { username: 'vasu' })); // /me
    render(<AuthProvider><Status /><AuthView /></AuthProvider>);
    await userEvent.type(screen.getByPlaceholderText('user@gmail.com or username'), 'vasu');
    await userEvent.type(document.querySelector('input[type=password]'), 'secret123');
    await userEvent.click(screen.getByText('Access System'));
    await waitFor(() => expect(screen.getByText('in:vasu')).toBeInTheDocument());
    expect(localStorage.getItem('pkos_token')).toBe('tok-123');
    expect(fetch.mock.calls[0][0]).toMatch(/\/api\/v1\/login$/);
    expect(fetch.mock.calls[1][1].headers.Authorization).toBe('Bearer tok-123');
  });

  it('shows the server message on a failed login', async () => {
    fetch.mockReturnValueOnce(json(401, { detail: 'Incorrect credentials.' }));
    renderAuth();
    await userEvent.type(screen.getByPlaceholderText('user@gmail.com or username'), 'x');
    await userEvent.type(document.querySelector('input[type=password]'), 'y');
    await userEvent.click(screen.getByText('Access System'));
    expect(await screen.findByText('Incorrect credentials.')).toBeInTheDocument();
  });

  it('turns FastAPI validation lists into readable text', async () => {
    fetch.mockReturnValueOnce(json(422, { detail: [{ msg: 'Field required' }, { msg: 'Bad value' }] }));
    renderAuth();
    await userEvent.type(screen.getByPlaceholderText('user@gmail.com or username'), 'x');
    await userEvent.type(document.querySelector('input[type=password]'), 'y');
    await userEvent.click(screen.getByText('Access System'));
    expect(await screen.findByText('Field required; Bad value')).toBeInTheDocument();
  });
});

describe('AuthProvider', () => {
  it('logs out when a stored token is rejected with 401', async () => {
    localStorage.setItem('pkos_token', 'stale');
    fetch.mockReturnValueOnce(json(401, { detail: 'Could not validate credentials' }));
    render(<AuthProvider><Status /></AuthProvider>);
    await waitFor(() => expect(screen.getByText('out')).toBeInTheDocument());
    expect(localStorage.getItem('pkos_token')).toBeNull();
  });

  it('keeps a valid stored token and hydrates the user', async () => {
    localStorage.setItem('pkos_token', 'good');
    fetch.mockReturnValueOnce(json(200, { username: 'amy' }));
    render(<AuthProvider><Status /></AuthProvider>);
    await waitFor(() => expect(screen.getByText('in:amy')).toBeInTheDocument());
  });
});
