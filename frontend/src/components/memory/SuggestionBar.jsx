import React, { useState } from 'react';
import { Brain, Check, Pencil, X } from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { confirmMemory, deleteMemory } from '../../lib/memoriesApi';
import RememberDialog from './RememberDialog';

const KIND_LABEL = { fact: 'about you', preference: 'how to answer', conclusion: 'decided' };

/**
 * "Remember this?" for the memories PKOS suggested in this chat (docs/07_MEMORY_PLAN.md 10.3). A suggestion is
 * never used until it is kept; Dismiss deletes it. onDone(memoryId) removes it from the list.
 */
export default function SuggestionBar({ suggestions, onDone }) {
  const { authFetch } = useAuth();
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState('');

  const act = async (memory, action) => {
    setError('');
    try {
      await action();
      onDone(memory.memory_id);
    } catch (err) {
      if (err.status === 404 || err.status === 409) onDone(memory.memory_id); // already answered elsewhere
      else setError(err.message);
    }
  };

  if (!suggestions.length) return null;
  return (
    <div className="suggestion-bar" role="region" aria-label="Memory suggestions">
      {suggestions.map((m) => (
        <div key={m.memory_id} className="suggestion-row" data-testid="suggestion">
          <Brain size={14} color="#c4b5fd" style={{ flexShrink: 0 }} />
          <span style={{ flex: 1, minWidth: 0 }}>
            <span className="ai-muted">Remember this? </span>
            <span style={{ color: 'var(--text-primary)' }}>"{m.text}"</span>
            <span className="ai-muted"> · {KIND_LABEL[m.kind] || m.kind}</span>
          </span>
          <button type="button" className="msg-action" aria-label={`Keep "${m.text}"`}
            onClick={() => act(m, () => confirmMemory(authFetch, m.memory_id))}>
            <Check size={12} /> Keep
          </button>
          <button type="button" className="msg-action" aria-label={`Edit "${m.text}"`} onClick={() => setEditing(m)}>
            <Pencil size={12} /> Edit
          </button>
          <button type="button" className="msg-action" aria-label={`Dismiss "${m.text}"`}
            onClick={() => act(m, () => deleteMemory(authFetch, m.memory_id))}>
            <X size={12} /> Dismiss
          </button>
        </div>
      ))}
      {error && <div className="ai-alert ai-alert-error" role="alert">{error}</div>}
      {editing && (
        <RememberDialog
          initialText={editing.text} initialKind={editing.kind}
          save={(changes) => confirmMemory(authFetch, editing.memory_id, changes)}
          onSaved={() => onDone(editing.memory_id)}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
