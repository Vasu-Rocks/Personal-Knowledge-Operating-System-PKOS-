import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useAuth } from '../context/useAuth';
import { API, IS_PHONE_ACCESS } from '../api';
import useIsPhone from '../lib/useIsPhone';
import { readSSE } from '../lib/sse';
import { migrateLegacySettings } from '../lib/llmApi';
import useAiStatus from './ai/useAiStatus';
import StatusBadge from './ai/StatusBadge';
import SetupWizard from './ai/SetupWizard';
import MediaInput from './MediaInput';
import useChats from './chats/useChats';
import Sidebar from './layout/Sidebar';
import DocumentsView from './DocumentsView';
import SourcesPanel from './chats/SourcesPanel';
import './layout/layout.css';
import { getConversation } from '../lib/conversationsApi';
import { toUiMessages } from '../lib/chatView';
import { guessKind, listMemories, memoryDraft } from '../lib/memoriesApi';
import RememberDialog from './memory/RememberDialog';
import SuggestionBar from './memory/SuggestionBar';
import CitationLink from './chats/CitationLink';
import CitationContext from '../lib/citationContext';
import { Send, Sparkles, Bookmark, Brain, BookOpen, Menu, FileText } from 'lucide-react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';

const SETUP_SKIPPED = 'pkos_ai_setup_skipped'; // sessionStorage: skipping lasts until the app restarts
// The backend's answer when nothing fits (routes_query.NO_ANSWER): such an answer did not come from saved memories either.
const NO_ANSWER = 'I cannot find the answer in your documents.';
const LAST_CHAT_KEY = 'pkos_last_chat'; // a convenience only: the server decides whose chat it is (404 otherwise)
const QUESTION_PLACEHOLDER = 'Ask about your documents...';

function remember(id) {
  try { if (id) localStorage.setItem(LAST_CHAT_KEY, id); else localStorage.removeItem(LAST_CHAT_KEY); } catch { /* ignore */ }
}

function rememberedChat() {
  try { return localStorage.getItem(LAST_CHAT_KEY); } catch { return null; }
}

// react-markdown drops links with unknown schemes; our own citation:// links (made by processCitations) must stay,
// or "[Chunk 1]" shows as a plain link instead of the clickable citation. Every other URL keeps the safe default.
const MARKDOWN_COMPONENTS = { a: CitationLink }; // one stable renderer (see lib/citationContext.js)
const keepCitations = (url) => (url.startsWith('citation://') ? url : defaultUrlTransform(url));

function processCitations(text) {
  if (!text) return text;
  return text.replace(/\[(chunk)\s*(\d+)\]|\[(graph entity)\s*:\s*([^\]]+)\]/gi, (match, p1, chunkId, p3, entityName) => {
    if (p1) return `[Chunk ${chunkId}](citation://chunk/${chunkId})`;
    if (p3) {
      const cleanName = entityName.trim();
      return `[Graph Entity: ${cleanName}](citation://entity/${encodeURIComponent(cleanName)})`;
    }
    return match;
  });
}

/**
 * The main screen: a sidebar (chats and a few links), the chat in the middle, and the Sources panel, which opens
 * only when asked for ("Sources" under an answer, or a citation). Documents are a page of their own.
 */
export default function Dashboard() {
  const { authFetch } = useAuth();
  const ai = useAiStatus(authFetch);
  const [setupOpen, setSetupOpen] = useState(false);
  const isPhone = useIsPhone();
  const [view, setView] = useState('chat');           // 'chat' | 'documents'
  const [menuOpen, setMenuOpen] = useState(false);    // phone: the sidebar slides in over the chat
  const [sourcesOpen, setSourcesOpen] = useState(false);
  // The AI model is chosen on the laptop: a phone never opens the setup wizard (the server refuses it anyway).
  const openSetup = IS_PHONE_ACCESS ? undefined : () => setSetupOpen(true);

  // First load: move provider/keys from old browser storage to the server, then open setup if no AI is usable.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await migrateLegacySettings(authFetch);
      } catch (err) {
        console.error('Could not migrate AI settings from browser storage', err);
      }
      const status = await ai.refresh();
      if (!cancelled && !IS_PHONE_ACCESS && status && !status.ready && !status.configured && !sessionStorage.getItem(SETUP_SKIPPED)) {
        setSetupOpen(true);
      }
    })();
    return () => { cancelled = true; };
  }, [authFetch]); // eslint-disable-line react-hooks/exhaustive-deps

  const closeSetup = (done) => {
    if (!done) sessionStorage.setItem(SETUP_SKIPPED, '1');
    setSetupOpen(false);
    ai.refresh();
  };

  const [messages, setMessages] = useState([]);
  const [inputVal, setInputVal] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [selectedMsgId, setSelectedMsgId] = useState(null); // the answer whose sources are shown
  const [activeFocus, setActiveFocus] = useState(null);     // the citation or concept being pointed at
  const [rememberMsg, setRememberMsg] = useState(null);     // the message "Remember this" was clicked on
  const [suggestions, setSuggestions] = useState([]);       // pending memories PKOS proposed (shown in their own chat)
  const streamRef = useRef(0);                              // the newest question's stream; older ones may still be open
  const messagesEndRef = useRef(null);

  const loadSuggestions = useCallback(async () => {
    try {
      setSuggestions(await listMemories(authFetch, 'pending'));
    } catch (err) {
      console.error('Could not load memory suggestions', err);
    }
  }, [authFetch]);
  const suggestionDone = useCallback((id) => setSuggestions((list) => list.filter((m) => m.memory_id !== id)), []);

  // Saved chats (docs/07_MEMORY_PLAN.md): the open chat, and the list in the sidebar.
  const chats = useChats(authFetch);
  const [conversationId, setConversationId] = useState(null);
  const [chatTitle, setChatTitle] = useState(null);

  const newChat = useCallback(() => {
    setView('chat');
    setMenuOpen(false);
    if (isTyping) return;
    setConversationId(null);
    setChatTitle(null);
    setMessages([]);
    setSelectedMsgId(null);
    setSourcesOpen(false);
    remember(null);
  }, [isTyping]);

  const openChat = useCallback(async (id) => {
    setView('chat');
    setMenuOpen(false);
    if (isTyping) return;
    try {
      const conv = await getConversation(authFetch, id);
      const ui = toUiMessages(conv.messages || []);
      const lastAnswer = [...(conv.messages || [])].reverse().find((m) => m.role === 'assistant');
      setConversationId(conv.conversation_id);
      setChatTitle(conv.title);
      setMessages(ui);
      setSelectedMsgId(lastAnswer ? lastAnswer.message_id : null);
      remember(conv.conversation_id);
    } catch (err) {
      if (err.status === 404) {
        remember(null); // deleted, or another user's chat on this PC
        chats.refresh();
        return;
      }
      setMessages((prev) => [...prev, { id: `err_${Date.now()}`, type: 'system', sources: [],
        text: `Could not open the chat: ${err.message}` }]);
    }
  }, [authFetch, isTyping, chats]);

  const deleteChat = useCallback(async (id) => {
    await chats.remove(id);
    if (id === conversationId) newChat();
  }, [chats, conversationId, newChat]);

  // First load: the chat list, and the chat that was open last time.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    chats.refresh();
    loadSuggestions();
    const last = rememberedChat();
    if (last) openChat(last);
  }, [chats, openChat, loadSuggestions]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const showSources = (msgId, focus = null) => {
    setSelectedMsgId(msgId);
    setSourcesOpen(true);
    setActiveFocus(focus);
    if (focus && focus.type === 'chunk') {
      setTimeout(() => document.getElementById(`source-card-${focus.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60);
    }
  };

  const handleSend = async (e) => {
    e.preventDefault();
    if (!inputVal.trim() || isTyping) return;

    const query = inputVal.trim();
    setInputVal('');
    const userMsgId = Date.now().toString();
    const aiMsgId = (Date.now() + 1).toString();
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, type: 'user', text: query, sources: [] },
      { id: aiMsgId, type: 'ai', text: '', sources: [] },
    ]);
    setSelectedMsgId(aiMsgId);
    setIsTyping(true);
    const stream = ++streamRef.current;
    const finish = () => { if (streamRef.current === stream) setIsTyping(false); };
    const updateAnswer = (patch) => setMessages((prev) => prev.map((m) => (m.id === aiMsgId ? { ...m, ...patch(m) } : m)));

    try {
      // The provider, model and API keys come from the user's saved settings on the server.
      const res = await authFetch(`${API}/query/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // A follow-up goes into the open chat; without an id the server starts a new chat and names it.
        body: JSON.stringify(conversationId ? { query, conversation_id: conversationId } : { query }),
      });
      if (!res.ok) throw new Error('Query streaming failed');

      await readSSE(res, (payloadStr) => {
        try {
          const parsed = JSON.parse(payloadStr);
          if (parsed.type === 'conversation') {
            setConversationId(parsed.conversation_id);
            setChatTitle(parsed.title);
            chats.touch(parsed.conversation_id, parsed.title);
            remember(parsed.conversation_id);
          } else if (parsed.type === 'rewrite') {
            // What was actually searched, shown under the question so a poor rewrite is visible.
            setMessages((prev) => prev.map((m) => (m.id === userMsgId ? {
              ...m,
              searched: parsed.needs_search && parsed.rewritten ? parsed.standalone : null,
              reused: !parsed.needs_search,
            } : m)));
          } else if (parsed.type === 'memories') {
            // Saved memories given to the model, and whether they were all it had to answer from.
            updateAnswer(() => ({ memories: parsed.memories || [], memoriesOnly: Boolean(parsed.memories_only) }));
          } else if (parsed.type === 'saved') {
            // The stored ids, so "Remember this" can link a memory to the message it came from.
            setMessages((prev) => prev.map((m) => {
              if (m.id === userMsgId) return { ...m, serverId: parsed.question_id };
              if (m.id === aiMsgId) return { ...m, serverId: parsed.answer_id };
              return m;
            }));
            finish(); // the answer is complete; memory suggestions may still follow on this stream
          } else if (parsed.type === 'suggestions') {
            setSuggestions((prev) => [...prev, ...(parsed.memories || []).filter((m) => !prev.some((p) => p.memory_id === m.memory_id))]);
          } else if (parsed.type === 'sources') {
            updateAnswer(() => ({ sources: parsed.sources || [] }));
          } else if (parsed.type === 'graph') {
            updateAnswer(() => ({ graph: parsed.data || null }));
          } else if (parsed.type === 'token') {
            updateAnswer((m) => ({ text: m.text + parsed.content }));
          }
        } catch (err) {
          console.error('Could not read part of the answer:', payloadStr, err);
        }
      });
    } catch (err) {
      console.error(err);
      setMessages((prev) => [...prev, { id: Date.now().toString(), type: 'system', sources: [],
        text: 'Could not reach PKOS. Is it still running?' }]);
    } finally {
      finish();
    }
  };

  const selectedMsg = messages.find((m) => m.id === selectedMsgId) || null;
  const streamingId = isTyping ? messages[messages.length - 1]?.id : null;
  const canRemember = (m) => (m.type === 'user' || m.type === 'ai') && !m.failed && m.id !== streamingId
    && Boolean((m.plain ?? m.text ?? '').trim()) && !String(m.text).startsWith('System Error');

  // What a citation does when tapped (CitationLink gets it through CitationContext): show that answer's sources.
  const citationsFor = (msg) => ({
    activeFocus,
    setActiveFocus,
    openChunk: (id) => showSources(msg.id, { type: 'chunk', id }),
    openEntity: (id) => showSources(msg.id, { type: 'entity', id }),
  });

  const sidebar = (
    <Sidebar
      chats={chats} activeChatId={conversationId} view={view}
      onNewChat={newChat} onOpenChat={openChat}
      onRenameChat={async (id, title) => { await chats.rename(id, title); if (id === conversationId) setChatTitle(title); }}
      onDeleteChat={deleteChat}
      onShowDocuments={() => { setView('documents'); setMenuOpen(false); setSourcesOpen(false); }}
      onOpenSetup={openSetup} onAiChanged={ai.refresh}
      open={!isPhone || menuOpen} onClose={isPhone ? () => setMenuOpen(false) : undefined}
    />
  );

  return (
    <div className={`os-shell app-shell${isPhone ? ' phone' : ''}`}>
      {sidebar}
      {setupOpen && <SetupWizard status={ai.llm} onClose={closeSetup} />}

      {view === 'documents' ? (
        <main className="app-main">
          <DocumentsView shown={view === 'documents'} onMenu={isPhone ? () => setMenuOpen(true) : undefined} />
        </main>
      ) : (
        <main className="app-main">
          <header className="chat-header">
            {isPhone && <button type="button" className="icon-btn" onClick={() => setMenuOpen(true)} aria-label="Open menu"><Menu size={20} /></button>}
            <span className="chat-title" data-testid="chat-title" title={chatTitle || 'New chat'}>{chatTitle || 'New chat'}</span>
            <StatusBadge llm={ai.llm} system={ai.system} error={ai.error} onClick={openSetup} compact={isPhone} />
          </header>

          <div className="chat-scroll">
            <div className="chat-column">
              {messages.length === 0 && (
                <div className="chat-empty" data-testid="chat-empty">
                  <BookOpen size={34} />
                  <h2>Ask anything about your documents</h2>
                  <p>Answers come from your own files, with their sources. Everything stays on this computer.</p>
                  <button type="button" className="ai-btn" onClick={() => setView('documents')}>
                    <FileText size={14} /> Add documents
                  </button>
                </div>
              )}

              {messages.map((msg) => {
                const nSources = (msg.sources || []).length;
                const nMemories = (msg.memories || []).length;
                const done = msg.id !== streamingId;
                return (
                  <div key={msg.id} className={`msg msg-${msg.type}`} data-testid={`msg-${msg.type}`}>
                    {msg.type === 'user' ? (
                      <div className="bubble-user">
                        {msg.text}
                        {msg.searched && <div className="searched-for">Searched for: {msg.searched}</div>}
                        {msg.reused && <div className="searched-for">Reworking the previous answer (same sources)</div>}
                      </div>
                    ) : msg.type === 'system' ? (
                      <div className="msg-notice" role="status">{msg.text}</div>
                    ) : String(msg.text).startsWith('System Error:') ? (
                      // The engine could not answer (model missing, Ollama stopped...): a notice, not an answer.
                      <div className="msg-notice" role="status">{String(msg.text).replace(/^System Error:\s*/, '')}</div>
                    ) : (
                      <div className="answer">
                        <div className="markdown-prose">
                          <CitationContext.Provider value={citationsFor(msg)}>
                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS} urlTransform={keepCitations}>
                              {processCitations(msg.text)}
                            </ReactMarkdown>
                          </CitationContext.Provider>
                        </div>
                        {msg.memoriesOnly && !String(msg.text).startsWith(NO_ANSWER) && (
                          <div className="memory-label" data-testid="memory-label">
                            <Brain size={12} /> Answered from your saved memories, not from your documents
                          </div>
                        )}
                      </div>
                    )}

                    {msg.type !== 'system' && (
                      <div className="msg-actions">
                        {msg.type === 'ai' && done && (nSources > 0 || nMemories > 0) && (
                          <button type="button" className="msg-action strong" onClick={() => showSources(msg.id)}
                            aria-label={nSources ? `Sources (${nSources})` : `Memories used (${nMemories})`}>
                            {nSources ? `Sources (${nSources})` : `Memories used (${nMemories})`}
                          </button>
                        )}
                        {canRemember(msg) && (
                          <button type="button" className="msg-action" aria-label="Remember this" onClick={() => setRememberMsg(msg)}>
                            <Bookmark size={11} /> Remember this
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}

              {isTyping && messages[messages.length - 1] && !messages[messages.length - 1].text && (
                <div className="thinking"><Sparkles size={15} className="loader" /> Thinking...</div>
              )}
              <div ref={messagesEndRef} />
            </div>
          </div>

          {rememberMsg && (
            <RememberDialog
              initialText={memoryDraft(rememberMsg.plain ?? rememberMsg.text)}
              initialKind={guessKind(rememberMsg.plain ?? rememberMsg.text, rememberMsg.type)}
              source={{ conversationId, messageId: rememberMsg.serverId }}
              onClose={() => setRememberMsg(null)}
            />
          )}

          <div className="composer">
            <div className="chat-column">
              <SuggestionBar
                suggestions={conversationId ? suggestions.filter((m) => m.source_conversation_id === conversationId) : []}
                onDone={suggestionDone}
              />
              <form onSubmit={handleSend} className="composer-box">
                <MediaInput authFetch={authFetch} disabled={isTyping}
                  onText={(text) => setInputVal((v) => (v.trim() ? `${v.trim()} ${text}` : text))} />
                <input
                  type="text" value={inputVal} onChange={(e) => setInputVal(e.target.value)}
                  placeholder={QUESTION_PLACEHOLDER} autoFocus aria-label="Your question"
                  style={{ fontSize: isPhone ? '16px' : '15px' }}
                />
                <button type="submit" className="send-btn" disabled={isTyping || !inputVal.trim()} aria-label="Send">
                  <Send size={16} />
                </button>
              </form>
            </div>
          </div>
        </main>
      )}

      {view === 'chat' && sourcesOpen && (
        <SourcesPanel
          message={selectedMsg} activeFocus={activeFocus} setActiveFocus={setActiveFocus}
          onClose={() => { setSourcesOpen(false); setActiveFocus(null); }}
          onOpenChat={(id) => { setSourcesOpen(false); openChat(id); }} busy={isTyping}
        />
      )}
    </div>
  );
}
