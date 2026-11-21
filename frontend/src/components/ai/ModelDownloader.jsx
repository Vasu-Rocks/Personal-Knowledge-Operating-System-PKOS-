import React, { useEffect, useRef, useState } from 'react';
import { Download, X, RotateCcw } from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { pullModel } from '../../lib/llmApi';
import { formatBytes } from '../../lib/models';

/** Downloads one Ollama model with a progress bar; cancel and retry included. Calls onDone() on success. */
export default function ModelDownloader({ model, onDone, onCancel, autoStart = true }) {
  const { authFetch } = useAuth();
  const [progress, setProgress] = useState(autoStart ? { status: 'Starting download…' } : null);
  const [error, setError] = useState('');
  const [running, setRunning] = useState(autoStart);
  const controller = useRef(null);

  const start = async (isUnmounted = () => false) => {
    const ctrl = new AbortController();
    controller.current = ctrl;
    setError('');
    setProgress({ status: 'Starting download…' });
    setRunning(true);
    try {
      await pullModel(authFetch, model, { onProgress: (p) => !isUnmounted() && setProgress(p), signal: ctrl.signal });
      if (isUnmounted()) return;
      setRunning(false);
      if (onDone) onDone(model);
    } catch (err) {
      if (isUnmounted()) return; // closed while downloading: nothing to show
      setRunning(false);
      if (err.name === 'AbortError') {
        if (onCancel) onCancel();
        return;
      }
      setError(err.message || 'Download failed.');
    }
  };

  // Start on mount; leaving the screen aborts the request, which stops the download on the server.
  useEffect(() => {
    if (!autoStart) return undefined;
    let unmounted = false;
    queueMicrotask(() => { if (!unmounted) start(() => unmounted); });
    return () => {
      unmounted = true;
      if (controller.current) controller.current.abort();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const percent = progress && typeof progress.percent === 'number' ? progress.percent : null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }} aria-live="polite">
      <div className="ai-row" style={{ justifyContent: 'space-between' }}>
        <span style={{ fontSize: '13px', fontWeight: 600 }}>
          <Download size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
          Downloading {model}
        </span>
        <span className="ai-muted">
          {percent !== null ? `${percent.toFixed(0)}%` : ''}
          {progress && progress.total ? ` · ${formatBytes(progress.completed)} of ${formatBytes(progress.total)}` : ''}
        </span>
      </div>
      <div className={`ai-progress${percent === null && running ? ' indeterminate' : ''}`} role="progressbar"
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? undefined}>
        <div style={percent !== null ? { width: `${percent}%` } : undefined} />
      </div>
      {progress && !error && <span className="ai-muted">{progress.status}</span>}
      {error && <div className="ai-alert ai-alert-error">{error}</div>}
      <div className="ai-row">
        {running && (
          <button type="button" className="ai-btn" onClick={() => controller.current.abort()}>
            <X size={14} /> Cancel
          </button>
        )}
        {!running && error && (
          <>
            <button type="button" className="ai-btn ai-btn-primary" onClick={() => start()}><RotateCcw size={14} /> Try again</button>
            {onCancel && <button type="button" className="ai-btn" onClick={onCancel}>Back</button>}
          </>
        )}
      </div>
    </div>
  );
}
