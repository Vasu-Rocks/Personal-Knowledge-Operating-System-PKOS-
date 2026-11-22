import React, { useEffect, useRef, useState } from 'react';
import { Mic, Square, ImagePlus, Loader2, ChevronRight } from 'lucide-react';
import { API } from '../api';
import { IMAGE_EXTS } from '../lib/fileTypes';

const MAX_RECORD_SECONDS = 5 * 60; // the server refuses longer recordings for a question

function pickMimeType() {
  if (typeof MediaRecorder === 'undefined') return '';
  return ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
    .find((t) => MediaRecorder.isTypeSupported(t)) || '';
}

const extensionFor = (mime) => (mime.includes('ogg') ? 'ogg' : mime.includes('mp4') ? 'mp4' : 'webm');

function explainMicError(err) {
  if (err && (err.name === 'NotAllowedError' || err.name === 'SecurityError')) {
    return 'Microphone access is blocked. Allow it in Windows Settings > Privacy & security > Microphone.';
  }
  if (err && err.name === 'NotFoundError') return 'No microphone found.';
  return 'Could not start the microphone.';
}

/**
 * The arrow at the left of the query box opens a menu: speak a question, or photograph/scan notes. Both are turned into text on this
 * machine (POST /transcribe, /ocr) and handed to onText so the user can correct the words before sending.
 */
export default function MediaInput({ authFetch, onText, disabled }) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const imageInputRef = useRef(null);

  const releaseMic = () => {
    if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  };
  useEffect(() => releaseMic, []);

  useEffect(() => {
    if (!recording) return undefined;
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, [recording]);

  useEffect(() => {
    if (recording && seconds >= MAX_RECORD_SECONDS) stopRecording();
  }, [recording, seconds]);

  async function send(path, blob, filename, what) {
    setBusy(what);
    setError('');
    try {
      const form = new FormData();
      form.append('file', blob, filename);
      const res = await authFetch(`${API}${path}`, { method: 'POST', body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof data.detail === 'string' ? data.detail : `Could not read the ${what}.`);
      } else if (!data.text || !data.text.trim()) {
        setError(what === 'recording' ? 'No speech was heard.' : 'No text was found in the image.');
      } else {
        onText(data.text.trim());
      }
    } catch {
      setError('Network error. Is the server running?');
    } finally {
      setBusy('');
    }
  }

  async function startRecording() {
    setError('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks = [];
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = () => {
        releaseMic();
        const type = recorder.mimeType || mimeType || 'audio/webm';
        if (chunks.length) send('/transcribe', new Blob(chunks, { type }), `question.${extensionFor(type)}`, 'recording');
      };
      recorderRef.current = recorder;
      recorder.start();
      setSeconds(0);
      setRecording(true);
    } catch (err) {
      releaseMic();
      setError(explainMicError(err));
    }
  }

  function stopRecording() {
    setRecording(false);
    if (recorderRef.current && recorderRef.current.state !== 'inactive') recorderRef.current.stop();
  }

  function onImage(e) {
    const file = e.target.files[0];
    e.target.value = null; // the same photo can be picked again
    if (!file) return;
    const ext = file.name.split('.').pop().toLowerCase();
    if (!IMAGE_EXTS.includes(ext)) { setError(`Unsupported image type ".${ext}". Use PNG, JPG, WebP, BMP or TIFF.`); return; }
    send('/ocr', file, file.name, 'image');
  }

  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (!menuRef.current || !menuRef.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc); };
  }, [open]);

  const button = {
    background: 'transparent', border: 'none', cursor: 'pointer', padding: '8px', display: 'flex',
    alignItems: 'center', borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
  };
  const item = { ...button, width: '100%', gap: '10px', fontSize: '13px', color: 'var(--text-primary)', padding: '10px 14px' };
  const mm = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  const unavailable = disabled || !!busy;

  return (
    <>
      <span ref={menuRef} style={{ display: 'flex' }}>
        <button type="button" onClick={() => (recording ? stopRecording() : setOpen((o) => !o))}
          aria-label={recording ? 'Stop recording' : 'Ask with voice or a photo'} aria-expanded={open} aria-haspopup="menu"
          title={recording ? 'Stop recording' : 'Ask with voice or a photo'}
          style={{ ...button, color: recording ? '#ef4444' : 'var(--text-muted)' }}>
          {recording ? <Square size={18} fill="#ef4444" />
            : <ChevronRight size={20} style={{ transform: open ? 'rotate(-90deg)' : 'none', transition: 'transform 0.15s' }} />}
        </button>
        {open && (
          <div role="menu" style={{ position: 'absolute', bottom: '100%', left: '8px', marginBottom: '8px', minWidth: '230px',
            background: 'var(--bg-core, #0b1020)', border: 'var(--pane-border)', borderRadius: 'var(--radius-md)',
            boxShadow: '0 8px 28px rgba(0,0,0,0.45)', padding: '4px', zIndex: 20 }}>
            <button type="button" role="menuitem" disabled={unavailable} style={{ ...item, opacity: unavailable ? 0.4 : 1 }}
              onClick={() => { setOpen(false); startRecording(); }}>
              <Mic size={18} /> Ask by voice
            </button>
            <button type="button" role="menuitem" disabled={unavailable} style={{ ...item, opacity: unavailable ? 0.4 : 1 }}
              onClick={() => { setOpen(false); imageInputRef.current.click(); }}>
              <ImagePlus size={18} /> Ask from a photo of notes
            </button>
          </div>
        )}
      </span>
      <input type="file" ref={imageInputRef} style={{ display: 'none' }} onChange={onImage} data-testid="image-input"
        accept={IMAGE_EXTS.map((e) => `.${e}`).join(',')} />
      {busy && (
        <span style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', gap: '6px', alignItems: 'center' }}>
          <Loader2 size={14} className="loader" /> {busy === 'recording' ? 'Writing it down...' : 'Reading the image...'}
        </span>
      )}
      {recording && <span style={{ fontSize: '12px', color: '#ef4444' }}>Recording {mm} - click the square to stop</span>}
      {error && (
        <div role="alert" style={{ position: 'absolute', bottom: '100%', left: 0, right: 0, marginBottom: '8px',
          color: '#ef4444', fontSize: '12px', textAlign: 'center' }}>
          {error}
        </div>
      )}
    </>
  );
}
