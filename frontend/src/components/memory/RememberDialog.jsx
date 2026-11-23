import React, { useState } from 'react';
import { X, Bookmark, AlertTriangle } from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { KINDS, MEMORY_MAX_CHARS, addMemory } from '../../lib/memoriesApi';
import '../ai/ai.css';

/**
 * "Remember this": a small editor prefilled from a message. Nothing is saved until the user clicks Save
 * (docs/07_MEMORY_PLAN.md 10.1 rule 1). `source` = { conversationId, messageId } links the memory to its chat.
 */
export default function RememberDialog({ initialText, initialKind = 'fact', source = {}, onClose, onSaved }) {
  const { authFetch } = useAuth();
  const [text, setText] = useState(initialText || '');
  const [kind, setKind] = useState(initialKind);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const trimmed = text.trim();

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      const body = { text: trimmed, kind };
      if (source.conversationId) body.source_conversation_id = source.conversationId;
      if (source.conversationId && source.messageId) body.source_message_id = source.messageId;
      const memory = await addMemory(authFetch, body);
      if (onSaved) onSaved(memory);
      onClose();
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  return (
    <div className="ai-backdrop" role="dialog" aria-modal="true" aria-labelledby="remember-title"
      onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}>
      <form className="ai-card glass-panel" style={{ maxWidth: 520 }} onSubmit={save}>
        <div className="ai-card-header">
          <h2 id="remember-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Bookmark size={16} /> Remember this</h2>
          <button type="button" onClick={onClose} aria-label="Close" style={{ color: 'var(--text-muted)' }}><X size={20} /></button>
        </div>
        <div className="ai-card-body">
          <p className="ai-muted">
            PKOS will use this in later answers. Keep it short and about you or how you want answers - edit it as you like.
          </p>
          <div>
            <label className="ai-label" htmlFor="memory-text">Memory</label>
            <textarea id="memory-text" className="ai-input" rows={4} autoFocus maxLength={MEMORY_MAX_CHARS} value={text}
              onChange={(e) => setText(e.target.value)} style={{ resize: 'vertical', width: '100%', fontFamily: 'inherit' }} />
            <div className="ai-muted" style={{ textAlign: 'right' }}>{text.length}/{MEMORY_MAX_CHARS}</div>
          </div>
          <fieldset style={{ border: 'none', padding: 0, margin: 0 }}>
            <legend className="ai-label">Kind</legend>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {KINDS.map((k) => (
                <label key={k.id} style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 13, cursor: 'pointer' }}>
                  <input type="radio" name="memory-kind" value={k.id} checked={kind === k.id} onChange={() => setKind(k.id)} />
                  <span>{k.label} <span className="ai-muted">{k.hint}</span></span>
                </label>
              ))}
            </div>
          </fieldset>
          {error && <div className="ai-alert ai-alert-error" role="alert"><AlertTriangle size={16} /> {error}</div>}
        </div>
        <div className="ai-card-footer">
          <button type="button" className="ai-btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="ai-btn ai-btn-primary" disabled={saving || !trimmed}>
            {saving ? 'Saving…' : 'Save memory'}
          </button>
        </div>
      </form>
    </div>
  );
}
