import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useAuth } from '../context/useAuth';
import VaultView from './VaultView';
import { API } from '../api';
import { readSSE } from '../lib/sse';
import { migrateLegacySettings } from '../lib/llmApi';
import useAiStatus from './ai/useAiStatus';
import StatusBadge from './ai/StatusBadge';
import SetupWizard from './ai/SetupWizard';
import MediaInput from './MediaInput';
import ChatList from './chats/ChatList';
import useChats from './chats/useChats';
import { getConversation } from '../lib/conversationsApi';
import { EMPTY_GRAPH, prepareGraph, toUiMessages } from '../lib/chatView';
import { guessKind, memoryDraft } from '../lib/memoriesApi';
import RememberDialog from './memory/RememberDialog';
import { Send, Terminal, KeySquare, Activity, Bot, Sparkles, Bookmark, Brain, MessagesSquare } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ForceGraph2D from 'react-force-graph-2d';

const SETUP_SKIPPED = 'pkos_ai_setup_skipped'; // sessionStorage: skipping lasts until the app restarts
const SYS_ID = 'sys_init';
const LAST_CHAT_KEY = 'pkos_last_chat'; // a convenience only: the server decides whose chat it is (404 otherwise)
const initialMessages = () => [
  { id: SYS_ID, type: 'system', text: 'Secured encrypted channel established. Waiting for input...', sources: [] },
];
function remember(id) {
  try { if (id) localStorage.setItem(LAST_CHAT_KEY, id); else localStorage.removeItem(LAST_CHAT_KEY); } catch { /* ignore */ }
}

function rememberedChat() {
  try { return localStorage.getItem(LAST_CHAT_KEY); } catch { return null; }
}

export default function Dashboard() {
  const { authFetch } = useAuth();
  const ai = useAiStatus(authFetch);
  const [setupOpen, setSetupOpen] = useState(false);

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
      if (!cancelled && status && !status.ready && !status.configured && !sessionStorage.getItem(SETUP_SKIPPED)) {
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

  const [messages, setMessages] = useState(initialMessages);
  const [inputVal, setInputVal] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [selectedMsgId, setSelectedMsgId] = useState(SYS_ID);
  const [rememberMsg, setRememberMsg] = useState(null); // the message "Remember this" was clicked on
  const messagesEndRef = useRef(null);

  // Graph State
  const [graphData, setGraphData] = useState(EMPTY_GRAPH);
  const graphRef = useRef(null);

  // Saved chats (docs/07_MEMORY_PLAN.md): the open chat, and the list in the left panel.
  const chats = useChats(authFetch);
  const [conversationId, setConversationId] = useState(null);
  const [chatTitle, setChatTitle] = useState(null);

  const newChat = useCallback(() => {
    if (isTyping) return;
    setConversationId(null);
    setChatTitle(null);
    setMessages(initialMessages());
    setSelectedMsgId(SYS_ID);
    setGraphData(EMPTY_GRAPH);
    remember(null);
  }, [isTyping]);

  const openChat = useCallback(async (id) => {
    if (isTyping) return;
    try {
      const conv = await getConversation(authFetch, id);
      const ui = toUiMessages(conv.messages || []);
      const lastAnswer = [...(conv.messages || [])].reverse().find((m) => m.role === 'assistant');
      setConversationId(conv.conversation_id);
      setChatTitle(conv.title);
      setMessages(ui.length ? ui : initialMessages());
      setSelectedMsgId(lastAnswer ? lastAnswer.message_id : SYS_ID);
      setGraphData(lastAnswer && lastAnswer.graph ? prepareGraph(lastAnswer.graph) : EMPTY_GRAPH);
      remember(conv.conversation_id);
    } catch (err) {
      if (err.status === 404) {
        remember(null); // deleted, or another user's chat on this PC
        chats.refresh();
        return;
      }
      setMessages((prev) => [...prev, { id: `err_${Date.now()}`, type: 'system', sources: [],
        text: `[ERROR] Could not open the chat: ${err.message}` }]);
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
    const last = rememberedChat();
    if (last) openChat(last);
  }, [chats, openChat]);

  // Cross-Filtering State
  const [activeFocus, setActiveFocus] = useState(null);


  // Layout Resizing State
  const [leftWidth, setLeftWidth] = useState(250);
  const [rightWidth, setRightWidth] = useState(350);
  const isDraggingLeft = useRef(false);
  const isDraggingRight = useRef(false);

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (isDraggingLeft.current) {
        let newWidth = e.clientX;
        if (newWidth < 150) newWidth = 150;
        if (newWidth > 500) newWidth = 500;
        setLeftWidth(newWidth);
      } else if (isDraggingRight.current) {
        let newWidth = window.innerWidth - e.clientX;
        if (newWidth < 200) newWidth = 200;
        if (newWidth > 600) newWidth = 600;
        setRightWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      if (isDraggingLeft.current || isDraggingRight.current) {
        isDraggingLeft.current = false;
        isDraggingRight.current = false;
        document.body.style.cursor = 'default';
      }
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  const processCitations = (text) => {
    if (!text) return text;
    return text.replace(/\[(chunk)\s*(\d+)\]|\[(graph entity)\s*:\s*([^\]]+)\]/gi, (match, p1, chunkId, p3, entityName) => {
      if (p1) return `[Chunk ${chunkId}](citation://chunk/${chunkId})`;
      if (p3) {
        const cleanName = entityName.trim();
        return `[Graph Entity: ${cleanName}](citation://entity/${encodeURIComponent(cleanName)})`;
      }
      return match;
    });
  };

  const MarkdownComponents = {
    // `node` is destructured only to keep it out of the DOM props spread below.
    // eslint-disable-next-line no-unused-vars
    a: ({ node, href, children, ...props }) => {
      if (href && href.startsWith('citation://')) {
        const url = new URL(href);
        const type = url.hostname;
        const id = decodeURIComponent(url.pathname.substring(1));
        
        const isHovered = activeFocus && activeFocus.type === type && activeFocus.id === id;
        
        return (
          <span
            className="citation-badge"
            style={{
              display: 'inline-block',
              margin: '0 4px',
              padding: '2px 8px',
              borderRadius: '12px',
              fontSize: '0.85em',
              fontWeight: '600',
              cursor: 'pointer',
              background: type === 'chunk' 
                ? (isHovered ? 'rgba(16, 185, 129, 0.3)' : 'rgba(16, 185, 129, 0.15)') 
                : (isHovered ? 'rgba(59, 130, 246, 0.3)' : 'rgba(59, 130, 246, 0.15)'),
              color: type === 'chunk' ? '#10b981' : '#3b82f6',
              border: `1px solid ${type === 'chunk' ? '#10b981' : '#3b82f6'}`,
              transition: 'all 0.2s ease',
              transform: isHovered ? 'scale(1.05)' : 'scale(1)'
            }}
            onMouseEnter={() => setActiveFocus({ type, id })}
            onMouseLeave={() => setActiveFocus(null)}
            onClick={() => {
              if (type === 'chunk') {
                document.getElementById(`source-card-${id}`)?.scrollIntoView({ 
                  behavior: 'smooth', block: 'nearest' 
                });
              } else if (type === 'entity') {
                if (graphData.nodes) {
                  const targetNode = graphData.nodes.find(n => n.name.replace('⭐ ', '') === id || n.name === id);
                  if (targetNode && graphRef.current) {
                    graphRef.current.centerAt(targetNode.x, targetNode.y, 1000);
                    graphRef.current.zoom(8, 2000);
                  }
                }
              }
            }}
          >
            {children}
          </span>
        );
      }
      return <a href={href} {...props} style={{ color: 'var(--accent-blue)', textDecoration: 'underline' }}>{children}</a>;
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async (e) => {
    e.preventDefault();
    if (!inputVal.trim() || isTyping) return;

    const query = inputVal.trim();
    setInputVal('');
    
    const userMsgId = Date.now().toString();
    const aiMsgId = (Date.now() + 1).toString();

    setMessages(prev => [
      ...prev,
      { id: userMsgId, type: "user", text: query, sources: [] },
      { id: aiMsgId, type: "ai", text: "", sources: [] }
    ]);
    
    setSelectedMsgId(aiMsgId);
    setIsTyping(true);

    try {
      // The provider, model and API keys come from the user's saved settings on the server.
      const res = await authFetch(`${API}/query/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // A follow-up goes into the open chat; without an id the server starts a new chat and names it.
        body: JSON.stringify(conversationId ? { query, conversation_id: conversationId } : { query })
      });

      if (!res.ok) throw new Error("Query Streaming Failed");

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
            setMessages(prev => prev.map(m => (m.id === userMsgId ? {
              ...m,
              searched: parsed.needs_search && parsed.rewritten ? parsed.standalone : null,
              reused: !parsed.needs_search,
            } : m)));
          } else if (parsed.type === 'memories') {
            // Saved memories given to the model (X-Ray), and whether they were all it had to answer from.
            setMessages(prev => prev.map(m => (m.id === aiMsgId
              ? { ...m, memories: parsed.memories || [], memoriesOnly: Boolean(parsed.memories_only) } : m)));
          } else if (parsed.type === 'saved') {
            // The stored ids, so "Remember this" can link a memory to the message it came from.
            setMessages(prev => prev.map(m => {
              if (m.id === userMsgId) return { ...m, serverId: parsed.question_id };
              if (m.id === aiMsgId) return { ...m, serverId: parsed.answer_id };
              return m;
            }));
          } else if (parsed.type === 'sources') {
            setMessages(prev => prev.map(m => 
              m.id === aiMsgId ? { ...m, sources: parsed.sources || [] } : m
            ));
          } else if (parsed.type === 'graph') {
            setGraphData(prepareGraph(parsed.data || { nodes: [], links: [] }));
          } else if (parsed.type === 'token') {
            setMessages(prev => prev.map(m => 
              m.id === aiMsgId ? { ...m, text: m.text + parsed.content } : m
            ));
          }
        } catch (err) {
          console.error("[SSE Parse Warning] Could not parse SSE payload:", payloadStr, err);
        }
      });

    } catch (err) {
      console.error(err);
      setMessages(prev => [...prev, {
        id: Date.now().toString(),
        type: "system",
        text: "[ERROR] Downstream inference engine stream connection failed.",
        sources: []
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  const selectedMsg = messages.find(m => m.id === selectedMsgId);
  const streamingId = isTyping ? messages[messages.length - 1]?.id : null;
  const canRemember = (m) => (m.type === 'user' || m.type === 'ai') && !m.failed && m.id !== streamingId
    && Boolean((m.plain ?? m.text ?? '').trim()) && !String(m.text).startsWith('System Error');

  return (
    <div className="os-shell">
      {/* 1. Left: Vault / Documents */}
      <VaultView
        width={leftWidth} onOpenSetup={() => setSetupOpen(true)} onAiChanged={ai.refresh}
        chatsPanel={(
          <ChatList
            chats={chats.chats} activeId={conversationId} loading={chats.loading} error={chats.error}
            hasMore={chats.hasMore} onLoadMore={chats.loadMore} onNew={newChat} onOpen={openChat}
            onRename={async (id, title) => { await chats.rename(id, title); if (id === conversationId) setChatTitle(title); }}
            onDelete={deleteChat}
          />
        )}
      />
      {setupOpen && <SetupWizard status={ai.llm} onClose={closeSetup} />}
      
      {/* Resizer Left */}
      <div 
        className="resize-handle"
        onMouseDown={() => {
          isDraggingLeft.current = true;
          document.body.style.cursor = 'col-resize';
        }}
      />

      {/* 2. Center: Terminal Chat */}
      <div className="pane-center">
        {/* Top Header */}
        <div style={{ height: '60px', borderBottom: 'var(--pane-border)', display: 'flex', alignItems: 'center', padding: '0 24px', background: 'rgba(0,0,0,0.1)' }}>
          <Terminal size={18} color="var(--accent-blue)" style={{ marginRight: '12px' }} />
          <span style={{ fontWeight: '500', fontSize: '14px', letterSpacing: '0.5px' }}>Generative Inference Core</span>
          <span data-testid="chat-title" title={chatTitle || 'New chat'} style={{
            marginLeft: '12px', fontSize: '13px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis',
            whiteSpace: 'nowrap', maxWidth: '40%',
          }}>
            · {chatTitle || 'New chat'}
          </span>
          <StatusBadge llm={ai.llm} system={ai.system} error={ai.error} onClick={() => setSetupOpen(true)} />
        </div>

        {/* Message Stream */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '32px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {messages.map((msg) => (
            <div
              key={msg.id}
              className="msg-row"
              onClick={() => {
                if (msg.type === "ai" || msg.type === "system") setSelectedMsgId(msg.id);
              }}
              style={{
                display: 'flex', gap: '16px', maxWidth: '85%', cursor: (msg.type === 'ai' || msg.type === 'system') ? 'pointer' : 'default',
                alignSelf: msg.type === 'user' ? 'flex-end' : 'flex-start',
                opacity: selectedMsgId === msg.id && msg.type !== 'user' ? 1 : (msg.type === 'user' ? 1 : 0.7),
                transition: 'opacity var(--transition-fast)'
              }}
            >
              {msg.type !== 'user' && (
                <div style={{
                  width: '32px', height: '32px', borderRadius: 'var(--radius-sm)', flexShrink: 0,
                  background: msg.type === 'system' ? 'rgba(255,255,255,0.05)' : 'var(--accent-glow)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', border: 'var(--pane-border)'
                }}>
                  {msg.type === 'system' ? <Terminal size={16} color="var(--text-muted)" /> : <Bot size={18} color="var(--accent-blue)" />}
                </div>
              )}
              
              <div style={{
                background: msg.type === 'user' ? 'var(--accent-blue)' : 'transparent',
                padding: msg.type === 'user' ? '12px 16px' : '4px 0 0 0',
                borderRadius: 'var(--radius-md)',
                color: msg.type === 'user' ? '#fff' : 'var(--text-primary)',
                fontSize: '14px', lineHeight: 1.6,
                borderBottomRightRadius: msg.type === 'user' ? '2px' : 'var(--radius-md)'
              }}>
                {msg.type === 'ai' || msg.type === 'system' ? (
                  <div className={msg.type === 'system' ? 'system-msg-text' : 'markdown-prose'}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MarkdownComponents}>
                      {processCitations(msg.text)}
                    </ReactMarkdown>
                    {msg.memoriesOnly && (
                      <div className="memory-label" data-testid="memory-label">
                        <Brain size={12} /> Answered from your saved memories, not from your documents
                      </div>
                    )}
                  </div>
                ) : (
                  <>
                    {msg.text}
                    {msg.searched && (
                      <div className="searched-for" style={{ fontSize: '11px', opacity: 0.8, marginTop: '6px', fontStyle: 'italic' }}>
                        Searched for: {msg.searched}
                      </div>
                    )}
                    {msg.reused && (
                      <div className="searched-for" style={{ fontSize: '11px', opacity: 0.8, marginTop: '6px', fontStyle: 'italic' }}>
                        Reworking the previous answer (same sources)
                      </div>
                    )}
                  </>
                )}
                {canRemember(msg) && (
                  <div className="msg-actions" style={{ marginTop: '4px', textAlign: msg.type === 'user' ? 'right' : 'left' }}>
                    <button type="button" className="msg-action" aria-label="Remember this"
                      style={msg.type === 'user' ? { color: 'rgba(255,255,255,0.8)' } : undefined}
                      onClick={(e) => { e.stopPropagation(); setRememberMsg(msg); }}>
                      <Bookmark size={11} /> Remember this
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
          {rememberMsg && (
            <RememberDialog
              initialText={memoryDraft(rememberMsg.plain ?? rememberMsg.text)}
              initialKind={guessKind(rememberMsg.plain ?? rememberMsg.text, rememberMsg.type)}
              source={{ conversationId, messageId: rememberMsg.serverId }}
              onClose={() => setRememberMsg(null)}
            />
          )}
          {isTyping && (
            <div style={{ display: 'flex', gap: '16px', opacity: 0.7 }}>
               <div style={{
                  width: '32px', height: '32px', borderRadius: 'var(--radius-sm)', flexShrink: 0,
                  background: 'var(--accent-glow)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: 'var(--pane-border)'
                }}>
                  <Sparkles size={16} color="var(--accent-blue)" className="loader" />
                </div>
                <div style={{ fontSize: '13px', color: 'var(--text-muted)', paddingTop: '8px', fontStyle: 'italic' }}>
                  Synthesizing matrices...
                </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Dock */}
        <div style={{ padding: '24px', background: 'linear-gradient(to top, var(--bg-core) 60%, transparent)' }}>
          <form
            onSubmit={handleSend}
            style={{
              position: 'relative', display: 'flex', background: 'rgba(255,255,255,0.03)', border: 'var(--pane-border)',
              borderRadius: 'var(--radius-lg)', padding: '8px 16px', alignItems: 'center',
              boxShadow: '0 4px 24px rgba(0,0,0,0.2)'
            }}
          >
            <MediaInput authFetch={authFetch} disabled={isTyping}
              onText={(text) => setInputVal((v) => (v.trim() ? `${v.trim()} ${text}` : text))} />
            <input 
              type="text" 
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              placeholder="Query the unified database..."
              autoFocus
              style={{ flex: 1, padding: '12px 16px', fontSize: '15px' }}
            />
            <button
              type="submit" disabled={isTyping || !inputVal.trim()}
              style={{ 
                background: inputVal.trim() && !isTyping ? 'var(--accent-blue)' : 'rgba(255,255,255,0.1)',
                padding: '8px', borderRadius: 'var(--radius-sm)', display: 'flex', opacity: inputVal.trim() && !isTyping ? 1 : 0.5 
              }}
            >
              <Send size={16} color="#fff" />
            </button>
          </form>
        </div>
      </div>

      {/* Resizer Right */}
      <div 
        className="resize-handle"
        onMouseDown={() => {
          isDraggingRight.current = true;
          document.body.style.cursor = 'col-resize';
        }}
      />

      {/* 3. Right Sidebar: RAG X-Ray */}
      <div className="pane-right" style={{ width: `${rightWidth}px` }}>
        <div style={{ height: '60px', borderBottom: 'var(--pane-border)', display: 'flex', alignItems: 'center', padding: '0 20px', background: 'rgba(0,0,0,0.2)' }}>
          <Activity size={16} color="#10b981" style={{ marginRight: '10px' }} />
          <span style={{ fontWeight: '600', fontSize: '12px', textTransform: 'uppercase', letterSpacing: '1px', color: 'var(--text-secondary)' }}>
            RAG X-Ray Inspector
          </span>
        </div>

        <div style={{ padding: '20px', flex: 1, overflowY: 'auto' }}>
          {!selectedMsg ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)', fontSize: '13px' }}>
              Select a message to inspect matrix bindings.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              {/* Header Box */}
              <div style={{ background: 'rgba(0,0,0,0.2)', border: 'var(--pane-border)', padding: '16px', borderRadius: 'var(--radius-md)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}>Active Math Selection</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <KeySquare size={16} color="var(--accent-blue)" />
                  <span style={{ fontFamily: 'monospace', fontSize: '13px', color: 'var(--text-primary)' }}>MSG_{selectedMsg.id}</span>
                </div>
              </div>

              {/* Force Graph Render */}
              <div>
                <h4 style={{ fontSize: '12px', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '16px', color: 'var(--text-secondary)' }}>
                  Interactive Entity Map
                </h4>
                <div style={{ 
                  height: '300px', 
                  border: 'var(--pane-border)', 
                  borderRadius: 'var(--radius-md)', 
                  overflow: 'hidden',
                  background: 'rgba(0,0,0,0.2)',
                  position: 'relative'
                }}>
                  {graphData.links && graphData.links.length > 0 ? (
                    <ForceGraph2D
                      ref={graphRef}
                      graphData={graphData}
                      width={rightWidth - 40}
                      height={300}
                      nodeLabel="name"
                      nodeAutoColorBy="category"
                      nodeColor={node => {
                        if (!activeFocus || activeFocus.type !== 'entity') {
                          return undefined; // Use default nodeAutoColorBy
                        }
                        const cleanName = node.name.replace('⭐ ', '');
                        if (cleanName === activeFocus.id) return '#3b82f6'; // Highlight target
                        
                        // Check if it's a neighbor of the target
                        const focusNode = graphData.nodes.find(n => n.name.replace('⭐ ', '') === activeFocus.id);
                        if (focusNode && node.neighbors && node.neighbors.has(focusNode.id)) {
                          return '#93c5fd'; // Soft highlight for neighbors
                        }
                        return 'rgba(255,255,255,0.05)'; // Dim all others
                      }}
                      linkColor={link => {
                        if (!activeFocus || activeFocus.type !== 'entity') return 'rgba(255,255,255,0.2)';
                        const focusNode = graphData.nodes.find(n => n.name.replace('⭐ ', '') === activeFocus.id);
                        if (!focusNode) return 'rgba(255,255,255,0.2)';
                        
                        const src = typeof link.source === 'object' ? link.source.id : link.source;
                        const tgt = typeof link.target === 'object' ? link.target.id : link.target;
                        if (src === focusNode.id || tgt === focusNode.id) return '#3b82f6';
                        return 'rgba(255,255,255,0.05)';
                      }}
                      onNodeHover={node => {
                        if (node) {
                          const cleanName = node.name.replace('⭐ ', '');
                          setActiveFocus({ type: 'entity', id: cleanName });
                        } else {
                          setActiveFocus(null);
                        }
                      }}
                      linkDirectionalArrowLength={3.5}
                      linkDirectionalArrowRelPos={1}
                      linkCurvature={0.25}
                      linkLabel={link => `${link.predicate}: ${link.description}`}
                      backgroundColor="transparent"
                      onNodeClick={node => {
                        graphRef.current.centerAt(node.x, node.y, 1000);
                        graphRef.current.zoom(8, 2000);
                      }}
                    />
                  ) : (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)', fontSize: '12px', padding: '20px', textAlign: 'center' }}>
                      No direct graph connections found. The engine will rely strictly on semantic vector search.
                    </div>
                  )}
                </div>
              </div>

              {/* Saved memories given to the model for this answer (docs/07_MEMORY_PLAN.md 10.1 rule 4) */}
              {selectedMsg.memories && selectedMsg.memories.length > 0 && (
                <div data-testid="memories-used">
                  <h4 style={{ fontSize: '12px', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '12px', color: 'var(--text-secondary)' }}>
                    Memories used ({selectedMsg.memories.length})
                  </h4>
                  <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {selectedMsg.memories.map((m) => (
                      <li key={m.memory_id} style={{
                        display: 'flex', gap: '8px', alignItems: 'flex-start', fontSize: '13px', color: 'var(--text-secondary)',
                        lineHeight: 1.5, padding: '8px 12px', border: '1px solid rgba(167, 139, 250, 0.3)',
                        background: 'rgba(167, 139, 250, 0.06)', borderRadius: 'var(--radius-md)',
                      }}>
                        <Brain size={13} color="#c4b5fd" style={{ flexShrink: 0, marginTop: '3px' }} />
                        <span style={{ flex: 1 }}>{m.text}</span>
                        <span style={{ fontSize: '10px', textTransform: 'uppercase', color: '#c4b5fd', whiteSpace: 'nowrap' }}>
                          {m.kind === 'preference' ? 'how to answer' : m.kind}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Source Render blocks */}
              <div>
                <h4 style={{ fontSize: '12px', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '16px', color: 'var(--text-secondary)' }}>
                  Extracted Vectors ({selectedMsg.sources?.length || 0})
                </h4>
                
                {selectedMsg.sources && selectedMsg.sources.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    {selectedMsg.sources.map((src, idx) => (
                      <div key={idx} id={`source-card-${idx + 1}`} style={{
                        background: (activeFocus?.type === 'chunk' && activeFocus.id === String(idx + 1)) 
                          ? 'rgba(16, 185, 129, 0.15)' 
                          : 'rgba(255,255,255,0.02)', 
                        border: (activeFocus?.type === 'chunk' && activeFocus.id === String(idx + 1))
                          ? '1px solid #10b981'
                          : 'var(--pane-border)',
                        borderRadius: 'var(--radius-md)', 
                        overflow: 'hidden',
                        transition: 'all 0.3s ease'
                      }}>
                        {src.via === 'chat' ? (
                          // A past chat (episodic memory): its recap was given to the model; clicking opens that chat.
                          <div data-testid="past-chat-source" style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(0,0,0,0.3)', padding: '10px 14px', borderBottom: 'var(--pane-border)' }}>
                            <MessagesSquare size={13} color="#c4b5fd" style={{ flexShrink: 0 }} />
                            <span style={{ fontSize: '12px', fontWeight: '500', color: 'var(--text-primary)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                              title={src.filename}>
                              Earlier chat: {src.filename}
                            </span>
                            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{src.page}</span>
                            <button type="button" className="ai-btn-link" disabled={isTyping}
                              style={{ fontSize: '11px', color: 'var(--accent-blue)', background: 'none', border: 'none', padding: 0 }}
                              onClick={() => openChat(src.conversation_id)} aria-label={`Open the chat ${src.filename}`}>
                              Open chat
                            </button>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', justifyContent: 'space-between', background: 'rgba(0,0,0,0.3)', padding: '10px 14px', borderBottom: 'var(--pane-border)' }}>
                            <span style={{ fontSize: '12px', fontWeight: '500', color: 'var(--text-primary)' }}>{src.filename}</span>
                            <span style={{ fontSize: '11px', color: 'var(--accent-blue)' }}>PG {src.page}</span>
                          </div>
                        )}
                        <div style={{ padding: '14px', fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5, maxHeight: '200px', overflowY: 'auto' }}>
                          {src.text}
                        </div>
                        <div style={{ background: 'rgba(16, 185, 129, 0.1)', padding: '8px 14px', borderTop: 'var(--pane-border)', fontSize: '11px', color: '#10b981', display: 'flex', justifyContent: 'space-between' }}>
                          <span>HNSW Distance:</span>
                          <span style={{ fontFamily: 'monospace' }}>{src.distance?.toFixed(4)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ padding: '20px', border: '1px dashed rgba(255,255,255,0.1)', borderRadius: 'var(--radius-md)', textAlign: 'center', fontSize: '12px', color: 'var(--text-muted)' }}>
                    No relational vectors connected to this entity.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
