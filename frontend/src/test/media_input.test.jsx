import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import MediaInput from '../components/MediaInput';

const reply = (status, body) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });

afterEach(() => { vi.unstubAllGlobals(); });

describe('MediaInput', () => {
  it('turns a photo of notes into query text via /ocr', async () => {
    const authFetch = vi.fn(() => reply(200, { text: 'Order 12 sensors' }));
    const onText = vi.fn();
    render(<MediaInput authFetch={authFetch} onText={onText} />);
    const file = new File(['x'], 'notes.png', { type: 'image/png' });
    fireEvent.change(screen.getByTestId('image-input'), { target: { files: [file] } });
    await waitFor(() => expect(onText).toHaveBeenCalledWith('Order 12 sensors'));
    expect(authFetch.mock.calls[0][0]).toMatch(/\/ocr$/);
    expect(authFetch.mock.calls[0][1].body.get('file').name).toBe('notes.png');
  });

  it('shows the server message when the image cannot be read, and an empty result as a hint', async () => {
    const authFetch = vi.fn()
      .mockImplementationOnce(() => reply(422, { detail: 'This file is not a readable image (PNG, JPG, WebP, BMP or TIFF).' }))
      .mockImplementationOnce(() => reply(200, { text: '' }));
    const onText = vi.fn();
    render(<MediaInput authFetch={authFetch} onText={onText} />);
    const pick = (name) => fireEvent.change(screen.getByTestId('image-input'), { target: { files: [new File(['x'], name)] } });
    pick('a.png');
    expect(await screen.findByRole('alert')).toHaveTextContent('not a readable image');
    pick('b.png');
    expect(await screen.findByText('No text was found in the image.')).toBeInTheDocument();
    expect(onText).not.toHaveBeenCalled();
  });

  it('rejects an unsupported image type without calling the server', () => {
    const authFetch = vi.fn();
    render(<MediaInput authFetch={authFetch} onText={vi.fn()} />);
    fireEvent.change(screen.getByTestId('image-input'), { target: { files: [new File(['x'], 'doc.exe')] } });
    expect(screen.getByRole('alert')).toHaveTextContent('Unsupported image type ".exe"');
    expect(authFetch).not.toHaveBeenCalled();
  });

  it('records, stops, and sends the audio to /transcribe', async () => {
    const stopTrack = vi.fn();
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(() => Promise.resolve({ getTracks: () => [{ stop: stopTrack }] })) } });
    class FakeRecorder {
      static isTypeSupported() { return true; }
      constructor() { this.state = 'inactive'; this.mimeType = 'audio/webm;codecs=opus'; }
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable({ data: new Blob(['voice'], { type: 'audio/webm' }) });
        this.onstop();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeRecorder);
    const authFetch = vi.fn(() => reply(200, { text: 'what did the surveyor say' }));
    const onText = vi.fn();
    render(<MediaInput authFetch={authFetch} onText={onText} />);
    fireEvent.click(screen.getByLabelText('Ask with voice or a photo'));
    fireEvent.click(screen.getByRole('menuitem', { name: /Ask by voice/ }));
    fireEvent.click(await screen.findByLabelText('Stop recording'));
    await waitFor(() => expect(onText).toHaveBeenCalledWith('what did the surveyor say'));
    expect(authFetch.mock.calls[0][0]).toMatch(/\/transcribe$/);
    expect(authFetch.mock.calls[0][1].body.get('file').name).toBe('question.webm');
    expect(stopTrack).toHaveBeenCalled(); // the microphone is released
  });

  it('explains a blocked microphone', async () => {
    const denied = Object.assign(new Error('denied'), { name: 'NotAllowedError' });
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(() => Promise.reject(denied)) } });
    vi.stubGlobal('MediaRecorder', class { static isTypeSupported() { return true; } });
    render(<MediaInput authFetch={vi.fn()} onText={vi.fn()} />);
    fireEvent.click(screen.getByLabelText('Ask with voice or a photo'));
    fireEvent.click(screen.getByRole('menuitem', { name: /Ask by voice/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Microphone access is blocked');
  });
});
