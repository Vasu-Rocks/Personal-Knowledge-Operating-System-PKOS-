import React, { useState } from 'react';
import { Lock, PlugZap, ExternalLink } from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { testLlm } from '../../lib/llmApi';
import { CLOUD_PROVIDERS } from '../../lib/models';

/**
 * API key + model for one cloud provider. `saved` is the server's public view (it never contains the key itself),
 * `draft` holds what the user typed ({ key, model }); onChange(draft) reports edits.
 */
export default function CloudKeyForm({ provider, saved, draft, onChange }) {
  const { authFetch } = useAuth();
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState(null);
  const info = CLOUD_PROVIDERS[provider];
  const keySet = saved && saved[`${provider}_key_set`];
  const hint = saved && saved[`${provider}_key_hint`];
  const canTest = Boolean(draft.key || keySet);

  const runTest = async () => {
    setTesting(true);
    setResult(null);
    try {
      const body = { provider, [`${provider}_model`]: draft.model || null };
      if (draft.key) body[`${provider}_key`] = draft.key;
      setResult(await testLlm(authFetch, body));
    } catch (err) {
      setResult({ ok: false, detail: err.message });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div>
        <label className="ai-label" htmlFor={`${provider}-key`} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Lock size={12} /> {info.label} API key
          {keySet && <span className="ai-tag ai-tag-ok" style={{ marginLeft: 'auto' }}>Saved {hint}</span>}
        </label>
        <input id={`${provider}-key`} className="ai-input" type="password" autoComplete="off" spellCheck={false}
          value={draft.key} placeholder={keySet ? 'Leave empty to keep the saved key' : info.keyPlaceholder}
          onChange={(e) => { setResult(null); onChange({ ...draft, key: e.target.value.trim() }); }} />
        <p className="ai-muted" style={{ marginTop: 8 }}>
          Stored encrypted on this computer and never shown again. Get one from{' '}
          <a href={info.keyUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-blue)' }}>
            {new URL(info.keyUrl).hostname} <ExternalLink size={10} />
          </a>.
        </p>
      </div>
      <div>
        <label className="ai-label" htmlFor={`${provider}-model`}>Model</label>
        <input id={`${provider}-model`} className="ai-input" value={draft.model} placeholder={info.defaultModel}
          onChange={(e) => { setResult(null); onChange({ ...draft, model: e.target.value.trim() }); }} />
      </div>
      <div className="ai-row">
        <button type="button" className="ai-btn" onClick={runTest} disabled={!canTest || testing}>
          <PlugZap size={14} className={testing ? 'loader' : undefined} /> {testing ? 'Testing…' : 'Test connection'}
        </button>
      </div>
      {result && (
        <div className={`ai-alert ${result.ok ? 'ai-alert-ok' : 'ai-alert-error'}`} role="status">
          {result.ok ? `Connected: ${result.model} answered.` : result.detail}
        </div>
      )}
      <div className="ai-alert ai-alert-warn">
        With a cloud provider, the text of your questions, the matching passages and the documents you add to the
        knowledge map are sent to {info.label}. Building the map for large documents uses many requests, which your
        {` ${info.label}`} account is billed for.
      </div>
    </div>
  );
}
