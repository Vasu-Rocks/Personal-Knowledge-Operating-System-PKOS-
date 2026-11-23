import React from 'react';
import { CLOUD_PROVIDERS } from '../../lib/models';
import './ai.css';

/**
 * Header pill: which model answers, and whether anything needs attention. Clicking it opens AI setup.
 * compact (phone layout): the model name only; the full text stays in the tooltip and the accessible name.
 */
export default function StatusBadge({ llm, system, error, onClick, compact = false }) {
  let tone = 'warn';
  let text = 'Checking AI…';
  let title = '';
  let short = null;

  if (error) {
    tone = 'err';
    text = 'PKOS engine not reachable';
    title = error;
  } else if (llm) {
    const providerLabel = llm.provider === 'ollama' ? 'on this PC' : CLOUD_PROVIDERS[llm.provider]?.label;
    if (llm.ready) {
      tone = 'ok';
      text = `${llm.model} · ${providerLabel}`;
      short = llm.model;
    } else {
      tone = 'warn';
      text = 'AI not set up';
    }
    title = llm.message;
    if (system && system.database === false) {
      tone = 'err';
      text = 'Database unavailable';
    } else if (system) {
      const busy = (system.graph_jobs?.processing || 0) + (system.graph_jobs?.pending || 0);
      if (busy) text += ` · building map (${busy})`;
      if (system.graph_jobs?.failed) title += ` ${system.graph_jobs.failed} document(s) failed to build their map.`;
    }
  }

  return (
    <button type="button" className="ai-status" onClick={onClick} title={title} aria-label={`AI status: ${text}. ${title}`}>
      <span className={`ai-dot ${tone}`} />
      <span className="ai-status-text">{compact && short ? short : text}</span>
    </button>
  );
}
