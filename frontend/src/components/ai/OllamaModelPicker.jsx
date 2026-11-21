import React, { useState } from 'react';
import { Download, Check, Trash2 } from 'lucide-react';
import ModelDownloader from './ModelDownloader';
import { RECOMMENDED_MODELS, formatBytes, isInstalled } from '../../lib/models';

const MODEL_NAME = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$/;

/**
 * Recommended + installed Ollama models. Picking an installed model calls onSelect(name); picking one that is
 * not installed downloads it first. With onDelete, installed models get a remove button (Settings).
 */
export default function OllamaModelPicker({ installed = [], selected, onSelect, onDownloaded, onDelete, selectLabel = 'Use' }) {
  const [downloading, setDownloading] = useState(null);
  const [custom, setCustom] = useState('');
  const installedNames = installed.map((m) => m.name);
  const extra = installed.filter((m) => !RECOMMENDED_MODELS.some((r) => isInstalled(r.name, [m.name])));
  const isActive = (name) => selected && (selected === name || isInstalled(selected, [name]) || isInstalled(name, [selected]));

  if (downloading) {
    return (
      <ModelDownloader
        model={downloading}
        onDone={(name) => { setDownloading(null); if (onDownloaded) onDownloaded(name); }}
        onCancel={() => setDownloading(null)}
      />
    );
  }

  const row = (name, title, meta, have) => (
    <div key={name} className={`ai-model${isActive(name) ? ' active' : ''}`}>
      <div className="ai-model-name">
        {title}
        {have && <span className="ai-tag ai-tag-ok">Installed</span>}
        {isActive(name) && <span className="ai-tag ai-tag-active">In use</span>}
      </div>
      <div className="ai-model-meta">{meta}</div>
      <div className="ai-model-actions">
        {have ? (
          <>
            {!isActive(name) && (
              <button type="button" className="ai-btn" onClick={() => onSelect(name)}><Check size={14} /> {selectLabel}</button>
            )}
            {onDelete && (
              <button type="button" className="ai-btn ai-btn-danger" aria-label={`Remove ${name}`} title="Remove from this PC"
                onClick={() => onDelete(name)}>
                <Trash2 size={14} />
              </button>
            )}
          </>
        ) : (
          <button type="button" className="ai-btn ai-btn-primary" onClick={() => setDownloading(name)}>
            <Download size={14} /> Download
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {RECOMMENDED_MODELS.map((m) => row(m.name, m.title, `${m.size} download · needs ${m.ram} · ${m.note}`,
        isInstalled(m.name, installedNames)))}
      {extra.map((m) => row(m.name, m.name, `${formatBytes(m.size)}${m.parameter_size ? ` · ${m.parameter_size} parameters` : ''}`, true))}
      <form
        className="ai-row"
        onSubmit={(e) => { e.preventDefault(); if (MODEL_NAME.test(custom.trim())) setDownloading(custom.trim()); }}
      >
        <input className="ai-input" value={custom} onChange={(e) => setCustom(e.target.value)}
          placeholder="Other Ollama model, e.g. qwen3:4b" aria-label="Other Ollama model name" />
        <button type="submit" className="ai-btn" disabled={!MODEL_NAME.test(custom.trim())}>
          <Download size={14} /> Download
        </button>
      </form>
    </div>
  );
}
