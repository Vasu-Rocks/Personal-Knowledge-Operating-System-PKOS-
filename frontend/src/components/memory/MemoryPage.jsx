import React, { useEffect, useState } from 'react';
import { Brain, Pencil, Trash2, Plus, AlertTriangle, Check, X } from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { shortDate } from '../../lib/chatView';
import {
  KINDS, MEMORY_MAX_CHARS, addMemory, deleteAllMemories, deleteMemory, editMemory, getMemorySettings, listMemories,
  saveMemorySettings,
} from '../../lib/memoriesApi';
import '../ai/ai.css';

const GROUP_TITLES = { preference: 'How to answer', fact: 'Facts about you', conclusion: 'Things you decided' };
const ORDER = ['preference', 'fact', 'conclusion'];

function Toggle({ id, label, checked, onChange, children }) {
  return (
    <label htmlFor={id} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer' }}>
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} style={{ marginTop: 3 }} />
      <span>
        <span style={{ fontSize: 13, color: 'var(--text-primary)' }}>{label}</span>
        <span className="ai-muted" style={{ display: 'block' }}>{children}</span>
      </span>
    </label>
  );
}

function KindSelect({ value, onChange, label = 'Kind' }) {
  return (
    <select aria-label={label} className="ai-input" value={value} onChange={(e) => onChange(e.target.value)}
      style={{ width: 'auto', flex: 'none' }}>
      {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
    </select>
  );
}

function MemoryRow({ memory, onSave, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(memory.text);
  const [kind, setKind] = useState(memory.kind);
  const [error, setError] = useState('');

  const save = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await onSave(memory.memory_id, { text: text.trim(), kind });
      setEditing(false);
    } catch (err) {
      setError(err.message);
    }
  };

  const cancel = () => {
    setEditing(false);
    setText(memory.text);
    setKind(memory.kind);
    setError('');
  };

  const origin = memory.origin === 'suggested' ? 'Suggested by PKOS' : 'Added by you';
  const from = memory.source_title ? ` from the chat "${memory.source_title}"` : '';
  const used = memory.last_used_at ? `last used ${shortDate(memory.last_used_at)} (${memory.use_count}×)` : 'not used yet';

  if (editing) {
    return (
      <li className="memory-row">
        <form onSubmit={save} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <textarea aria-label="Memory text" className="ai-input" rows={2} maxLength={MEMORY_MAX_CHARS} value={text}
            onChange={(e) => setText(e.target.value)} style={{ resize: 'vertical', fontFamily: 'inherit' }} autoFocus />
          <div className="ai-row">
            <KindSelect value={kind} onChange={setKind} />
            <span style={{ flex: 1 }} />
            <button type="button" className="ai-btn" onClick={cancel}><X size={14} /> Cancel</button>
            <button type="submit" className="ai-btn ai-btn-primary" disabled={!text.trim()}><Check size={14} /> Save</button>
          </div>
          {error && <div className="ai-alert ai-alert-error" role="alert">{error}</div>}
        </form>
      </li>
    );
  }
  return (
    <li className="memory-row" data-testid="memory-row">
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <span style={{ flex: 1, fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.5 }}>{memory.text}</span>
        <button type="button" className="ai-btn-link ai-btn" aria-label={`Edit "${memory.text}"`} onClick={() => setEditing(true)}>
          <Pencil size={13} />
        </button>
        <button type="button" className="ai-btn-link ai-btn" aria-label={`Delete "${memory.text}"`}
          onClick={() => onDelete(memory.memory_id)} style={{ color: '#fca5a5' }}>
          <Trash2 size={13} />
        </button>
      </div>
      <div className="ai-muted" style={{ fontSize: 11 }}>{origin}{from} · {used}</div>
    </li>
  );
}

/** The Memory section of Settings: on/off switches, add, edit, delete, delete all (docs/07_MEMORY_PLAN.md 10.3). */
export default function MemoryPage() {
  const { authFetch } = useAuth();
  const [settings, setSettings] = useState(null);
  const [memories, setMemories] = useState(null);
  const [error, setError] = useState('');
  const [newText, setNewText] = useState('');
  const [newKind, setNewKind] = useState('fact');
  const [confirmAll, setConfirmAll] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [s, list] = await Promise.all([getMemorySettings(authFetch), listMemories(authFetch)]);
        if (!cancelled) {
          setSettings(s);
          setMemories(list);
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    })();
    return () => { cancelled = true; };
  }, [authFetch]);

  const run = async (action) => {
    setError('');
    try {
      await action();
    } catch (err) {
      setError(err.message);
    }
  };

  const toggle = (name, value) => run(async () => setSettings(await saveMemorySettings(authFetch, { [name]: value })));

  const add = (e) => {
    e.preventDefault();
    run(async () => {
      const memory = await addMemory(authFetch, { text: newText.trim(), kind: newKind });
      setMemories((list) => [memory, ...(list || [])]);
      setNewText('');
    });
  };

  const save = async (id, changes) => {
    const memory = await editMemory(authFetch, id, changes);
    setMemories((list) => list.map((m) => (m.memory_id === id ? memory : m)));
  };

  const remove = (id) => run(async () => {
    await deleteMemory(authFetch, id);
    setMemories((list) => list.filter((m) => m.memory_id !== id));
  });

  const removeAll = () => run(async () => {
    await deleteAllMemories(authFetch);
    setMemories([]);
    setConfirmAll(false);
  });

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 12 }} aria-labelledby="memory-title">
      <div className="ai-section-title" id="memory-title"><Brain size={14} /> Memory</div>
      <p className="ai-muted">
        Short notes about you that PKOS uses in every chat. PKOS only remembers what you add here or save with
        "Remember this" on a message. Your documents stay the source for facts about your documents.
      </p>
      {error && <div className="ai-alert ai-alert-error" role="alert"><AlertTriangle size={16} /> {error}</div>}

      {settings && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Toggle id="memory-enabled" label="Use memories and past chats in answers" checked={settings.enabled}
            onChange={(v) => toggle('enabled', v)}>
            When off, nothing below is used and your memories are kept. Saved at once.
          </Toggle>
          <Toggle id="memory-suggest" label="Let PKOS suggest memories" checked={settings.suggest}
            onChange={(v) => toggle('suggest', v)}>
            Suggestions appear in the chat and are only kept if you confirm them.
          </Toggle>
        </div>
      )}

      <form onSubmit={add} className="ai-row" style={{ flexWrap: 'wrap' }}>
        <input aria-label="New memory" className="ai-input" maxLength={MEMORY_MAX_CHARS} value={newText}
          placeholder="e.g. I am preparing for the GATE exam in February" onChange={(e) => setNewText(e.target.value)} />
        <KindSelect label="Kind of the new memory" value={newKind} onChange={setNewKind} />
        <button type="submit" className="ai-btn" disabled={!newText.trim()}><Plus size={14} /> Add</button>
      </form>

      {memories === null && !error && <p className="ai-muted">Loading memories…</p>}
      {memories && memories.length === 0 && <p className="ai-muted">No memories yet.</p>}
      {memories && ORDER.map((kind) => {
        const group = memories.filter((m) => m.kind === kind);
        if (!group.length) return null;
        return (
          <div key={kind}>
            <div className="ai-label" style={{ marginBottom: 6 }}>{GROUP_TITLES[kind]} ({group.length})</div>
            <ul aria-label={GROUP_TITLES[kind]}
              style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {group.map((m) => <MemoryRow key={`${m.memory_id}-${m.updated_at}`} memory={m} onSave={save} onDelete={remove} />)}
            </ul>
          </div>
        );
      })}

      {memories && memories.length > 0 && (confirmAll ? (
        <div className="ai-alert ai-alert-warn" role="alert" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ flex: 1 }}>Delete all {memories.length} memories? This cannot be undone.</span>
          <button type="button" className="ai-btn" onClick={() => setConfirmAll(false)}>Keep them</button>
          <button type="button" className="ai-btn ai-btn-danger" onClick={removeAll}>Delete all</button>
        </div>
      ) : (
        <button type="button" className="ai-btn ai-btn-danger" style={{ alignSelf: 'flex-start' }} onClick={() => setConfirmAll(true)}>
          <Trash2 size={14} /> Delete all memories
        </button>
      ))}
    </section>
  );
}
