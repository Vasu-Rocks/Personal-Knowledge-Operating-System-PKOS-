import React, { useState } from 'react';
import { MessageSquare, Pencil, Plus, Trash2, Check, X, Loader2 } from 'lucide-react';
import { shortDate } from '../../lib/chatView';

const iconButton = {
  background: 'transparent', border: 'none', cursor: 'pointer', padding: '4px', display: 'flex',
  alignItems: 'center', justifyContent: 'center', borderRadius: '4px', color: 'var(--text-secondary)',
};

function ChatRow({ chat, active, onOpen, onRename, onDelete }) {
  const [hover, setHover] = useState(false);
  const [mode, setMode] = useState('view'); // view | rename | confirm
  const [draft, setDraft] = useState(chat.title);
  const [error, setError] = useState('');

  const saveTitle = async () => {
    const title = draft.trim();
    if (!title || title === chat.title) { setMode('view'); return; }
    try {
      await onRename(chat.conversation_id, title);
      setMode('view');
      setError('');
    } catch (err) {
      setError(err.message);
    }
  };

  const confirmDelete = async () => {
    try {
      await onDelete(chat.conversation_id);
    } catch (err) {
      setError(err.message);
      setMode('view');
    }
  };

  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={() => mode === 'view' && onOpen(chat.conversation_id)}
      data-testid="chat-row"
      aria-current={active ? 'true' : undefined}
      style={{
        padding: '8px 10px', borderRadius: 'var(--radius-sm)', cursor: mode === 'view' ? 'pointer' : 'default',
        background: active ? 'var(--accent-glow)' : hover ? 'var(--bg-surface)' : 'transparent',
        border: active ? '1px solid rgba(59,130,246,0.35)' : '1px solid transparent',
        transition: 'background var(--transition-fast)',
      }}
    >
      {mode === 'rename' ? (
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }} onClick={(e) => e.stopPropagation()}>
          <input
            autoFocus value={draft} maxLength={200} aria-label="Chat title"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') saveTitle();
              if (e.key === 'Escape') { setDraft(chat.title); setMode('view'); }
            }}
            style={{ flex: 1, fontSize: '13px', padding: '4px 6px', minWidth: 0 }}
          />
          <button type="button" style={iconButton} onClick={saveTitle} aria-label="Save title"><Check size={14} /></button>
          <button type="button" style={iconButton} onClick={() => { setDraft(chat.title); setMode('view'); }} aria-label="Cancel rename">
            <X size={14} />
          </button>
        </div>
      ) : mode === 'confirm' ? (
        <div onClick={(e) => e.stopPropagation()} style={{ fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <span>Delete "{chat.title}"? This cannot be undone.</span>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button type="button" onClick={confirmDelete}
              style={{ ...iconButton, color: '#ef4444', border: '1px solid rgba(239,68,68,0.4)', padding: '2px 10px' }}>Delete</button>
            <button type="button" onClick={() => setMode('view')} style={{ ...iconButton, padding: '2px 10px' }}>Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <MessageSquare size={14} color={active ? 'var(--accent-blue)' : 'var(--text-muted)'} style={{ flexShrink: 0 }} />
          <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', flex: 1 }}>
            <span style={{ fontSize: '13px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={chat.title}>
              {chat.title}
            </span>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{shortDate(chat.updated_at)}</span>
          </div>
          {(hover || active) && (
            <div style={{ display: 'flex', gap: '2px' }} onClick={(e) => e.stopPropagation()}>
              <button type="button" style={iconButton} title="Rename" aria-label={`Rename ${chat.title}`}
                onClick={() => { setDraft(chat.title); setMode('rename'); }}>
                <Pencil size={13} />
              </button>
              <button type="button" style={{ ...iconButton, color: '#ef4444' }} title="Delete" aria-label={`Delete ${chat.title}`}
                onClick={() => setMode('confirm')}>
                <Trash2 size={13} />
              </button>
            </div>
          )}
        </div>
      )}
      {error && <div role="alert" style={{ color: '#ef4444', fontSize: '11px', marginTop: '4px' }}>{error}</div>}
    </div>
  );
}

/** Left-panel list of saved chats with "New chat"; rename and delete per chat. */
export default function ChatList({ chats, activeId, loading, error, hasMore, onNew, onOpen, onRename, onDelete, onLoadMore }) {
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '16px 12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <button
        type="button" onClick={onNew}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '10px',
          borderRadius: 'var(--radius-sm)', border: '1px dashed rgba(255,255,255,0.15)', fontSize: '13px',
          color: 'var(--text-primary)', background: activeId ? 'transparent' : 'var(--accent-glow)', cursor: 'pointer',
        }}
      >
        <Plus size={15} /> New chat
      </button>
      {error && <div role="alert" style={{ color: '#ef4444', fontSize: '12px' }}>{error}</div>}
      {loading && !chats.length && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '12px' }}><Loader2 size={18} className="loader" /></div>
      )}
      {!loading && !chats.length && !error && (
        <p style={{ fontSize: '12px', color: 'var(--text-muted)', textAlign: 'center', lineHeight: 1.5 }}>
          No chats yet. Ask a question to start one; it is saved here automatically.
        </p>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
        {chats.map((chat) => (
          <ChatRow key={chat.conversation_id} chat={chat} active={chat.conversation_id === activeId}
            onOpen={onOpen} onRename={onRename} onDelete={onDelete} />
        ))}
      </div>
      {hasMore && (
        <button type="button" onClick={onLoadMore} style={{ fontSize: '12px', color: 'var(--accent-blue)', background: 'transparent', border: 'none', cursor: 'pointer' }}>
          Show older chats
        </button>
      )}
    </div>
  );
}
