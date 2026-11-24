import React, { useState } from 'react';
import { FileText, Map as MapIcon, Network, Settings, LogOut, X } from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import ChatList from '../chats/ChatList';
import SettingsView from '../SettingsView';
import ConnectionsView from '../ConnectionsView';
import KnowledgeMapView from '../KnowledgeMapView';

/**
 * The left sidebar: New chat and the saved chats, then the few places beside the chat (Documents, Knowledge map,
 * Connections, Settings) and the account. On a phone it slides in over the chat (`open`, `onClose`).
 */
export default function Sidebar({ chats, activeChatId, view, onNewChat, onOpenChat, onRenameChat, onDeleteChat,
  onShowDocuments, onOpenSetup, onAiChanged, open = true, onClose }) {
  const { logout, user } = useAuth();
  const [overlay, setOverlay] = useState(null); // 'settings' | 'map' | 'connections'
  const show = (what) => { setOverlay(what); if (onClose) onClose(); };

  return (
    <>
      {onClose && open && <div className="sidebar-backdrop" onClick={onClose} aria-hidden="true" />}
      <nav className={`app-sidebar${open ? ' open' : ''}`} aria-label="PKOS">
        <div className="sidebar-brand">
          <img src="/icons/pkos-192.png" alt="" width={26} height={26} style={{ borderRadius: '6px' }} />
          <span>PKOS</span>
          {onClose && (
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close menu" style={{ marginLeft: 'auto' }}>
              <X size={18} />
            </button>
          )}
        </div>

        <ChatList
          chats={chats.chats} activeId={view === 'chat' ? activeChatId : null} loading={chats.loading} error={chats.error}
          hasMore={chats.hasMore} onLoadMore={chats.loadMore}
          onNew={onNewChat} onOpen={onOpenChat} onRename={onRenameChat} onDelete={onDeleteChat}
        />

        <div className="sidebar-links">
          <button type="button" className={`sidebar-link${view === 'documents' ? ' active' : ''}`} onClick={onShowDocuments}
            aria-current={view === 'documents' ? 'page' : undefined}>
            <FileText size={16} /> Documents
          </button>
          <button type="button" className="sidebar-link" onClick={() => show('map')}><MapIcon size={16} /> Knowledge map</button>
          <button type="button" className="sidebar-link" onClick={() => show('connections')}><Network size={16} /> Connections</button>
          <button type="button" className="sidebar-link" onClick={() => show('settings')} aria-label="Settings">
            <Settings size={16} /> Settings
          </button>
        </div>

        {user && (
          <div className="sidebar-user">
            <div style={{ minWidth: 0 }}>
              <div className="user-name">{user.name}</div>
              <div className="muted-text" style={{ fontSize: '11px' }}>@{user.username}</div>
            </div>
            <button type="button" className="icon-btn" onClick={logout} aria-label="Log out" title="Log out"><LogOut size={16} /></button>
          </div>
        )}
      </nav>

      {overlay === 'settings' && (
        <SettingsView
          onClose={() => setOverlay(null)}
          onSaved={onAiChanged}
          onOpenSetup={onOpenSetup && (() => { setOverlay(null); onOpenSetup(); })}
        />
      )}
      {overlay === 'connections' && <ConnectionsView onClose={() => setOverlay(null)} />}
      {overlay === 'map' && <KnowledgeMapView onClose={() => setOverlay(null)} />}
    </>
  );
}
