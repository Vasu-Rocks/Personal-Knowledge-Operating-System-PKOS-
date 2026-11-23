import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MediaInput from '../components/MediaInput';

// Served to a phone by the laptop's phone server (docs/08_PHONE_ACCESS_PLAN.md P4).
vi.mock('../api', () => ({ API: 'https://192.168.137.1:47100/api/v1', API_BASE: 'https://192.168.137.1:47100', IS_DESKTOP: false, IS_PHONE_ACCESS: true }));

const reply = (status, body) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });

function screenIsPhone(yes) {
  window.matchMedia = vi.fn().mockImplementation((q) => ({ matches: yes && q.includes('max-width'), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
}

afterEach(() => { vi.unstubAllGlobals(); delete window.matchMedia; });

describe('photos and voice on a phone', () => {
  it('offers the camera and the gallery separately; the camera input opens the back camera', async () => {
    screenIsPhone(true);
    render(<MediaInput authFetch={vi.fn()} onText={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Ask with voice or a photo' }));
    expect(screen.getByRole('menuitem', { name: /Take a photo of notes/ })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Choose a photo of notes/ })).toBeInTheDocument();
    const camera = screen.getByTestId('camera-input');
    expect(camera).toHaveAttribute('capture', 'environment');
    expect(camera).toHaveAttribute('accept', 'image/*');
  });

  it('a laptop has no camera item', async () => {
    screenIsPhone(false);
    render(<MediaInput authFetch={vi.fn()} onText={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Ask with voice or a photo' }));
    expect(screen.queryByRole('menuitem', { name: /Take a photo/ })).not.toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Ask from a photo of notes/ })).toBeInTheDocument();
  });

  it('a camera photo without a file extension is read as the type it is', async () => {
    screenIsPhone(true);
    const authFetch = vi.fn(() => reply(200, { text: 'Exam on 14 February' }));
    const onText = vi.fn();
    render(<MediaInput authFetch={authFetch} onText={onText} />);
    fireEvent.change(screen.getByTestId('camera-input'), { target: { files: [new File(['x'], 'image', { type: 'image/jpeg' })] } });
    await waitFor(() => expect(onText).toHaveBeenCalledWith('Exam on 14 February'));
    expect(authFetch.mock.calls[0][1].body.get('file').name).toBe('photo.jpg');
  });

  it('explains HEIC photos instead of failing on the laptop', () => {
    screenIsPhone(true);
    const authFetch = vi.fn();
    render(<MediaInput authFetch={authFetch} onText={vi.fn()} />);
    fireEvent.change(screen.getByTestId('image-input'), { target: { files: [new File(['x'], 'IMG_0042.HEIC')] } });
    expect(screen.getByRole('alert')).toHaveTextContent('HEIC photos cannot be read');
    expect(authFetch).not.toHaveBeenCalled();
  });

  it('voice says why it is unavailable without https, and a blocked microphone points at the browser', async () => {
    screenIsPhone(true);
    vi.stubGlobal('isSecureContext', false);
    const { unmount } = render(<MediaInput authFetch={vi.fn()} onText={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Ask with voice or a photo' }));
    const voice = screen.getByRole('menuitem', { name: /Ask by voice/ });
    expect(voice).toBeDisabled();
    expect(voice).toHaveTextContent('Voice needs the secure (https) address.');
    unmount();

    vi.stubGlobal('isSecureContext', true);
    vi.stubGlobal('MediaRecorder', Object.assign(function MediaRecorder() {}, { isTypeSupported: () => false }));
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: () => Promise.reject(Object.assign(new Error('denied'), { name: 'NotAllowedError' })) },
    });
    render(<MediaInput authFetch={vi.fn()} onText={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Ask with voice or a photo' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Ask by voice' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Allow the microphone for this site in the browser');
    delete navigator.mediaDevices;
  });
});
