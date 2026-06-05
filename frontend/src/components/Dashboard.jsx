import React, { useState, useRef, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import VaultView from './VaultView';
import { Send, Terminal, KeySquare, ChevronRight, Activity, Bot, User, Sparkles } from 'lucide-react';

export default function Dashboard() {
  const { authFetch } = useAuth();
  const [messages, setMessages] = useState([
    {
      id: "sys_init",
      type: "system",
      text: "Secured encrypted channel established. Waiting for input...",
      sources: []
    }
  ]);
  const [inputVal, setInputVal] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [selectedMsgId, setSelectedMsgId] = useState("sys_init");
  const messagesEndRef = useRef(null);

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
    setMessages(prev => [...prev, { id: userMsgId, type: "user", text: query, sources: [] }]);
    
    setIsTyping(true);

    try {
      const res = await authFetch('http://localhost:8000/api/v1/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
      });

      if (!res.ok) throw new Error("Query Failed");
      
      const data = await res.json();
      
      const aiMsgId = (Date.now() + 1).toString();
      setMessages(prev => [...prev, {
        id: aiMsgId,
        type: "ai",
        text: data.response,
        sources: data.sources || []
      }]);
      // Auto focus the X-Ray on the newest AI response
      setSelectedMsgId(aiMsgId);
    } catch (err) {
      console.error(err);
      setMessages(prev => [...prev, {
        id: Date.now().toString(),
        type: "system",
        text: "[ERROR] Downstream inference engine connection failed.",
        sources: []
      }]);
    } finally {
      setIsTyping(false);
    }
  };

  const selectedMsg = messages.find(m => m.id === selectedMsgId);

  return (
    <div className="os-shell">
      {/* 1. Left: Vault / Documents */}
      <VaultView />

      {/* 2. Center: Terminal Chat */}
      <div className="pane-center">
        {/* Top Header */}
        <div style={{ height: '60px', borderBottom: 'var(--pane-border)', display: 'flex', alignItems: 'center', padding: '0 24px', background: 'rgba(0,0,0,0.1)' }}>
          <Terminal size={18} color="var(--accent-blue)" style={{ marginRight: '12px' }} />
          <span style={{ fontWeight: '500', fontSize: '14px', letterSpacing: '0.5px' }}>Generative Inference Core</span>
        </div>

        {/* Message Stream */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '32px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {messages.map((msg) => (
            <div 
              key={msg.id}
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
                  <div style={{ whiteSpace: 'pre-wrap', fontFamily: msg.type === 'system' ? 'monospace' : 'inherit' }}>
                    {msg.text}
                  </div>
                ) : (
                  msg.text
                )}
              </div>
            </div>
          ))}
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
              display: 'flex', background: 'rgba(255,255,255,0.03)', border: 'var(--pane-border)',
              borderRadius: 'var(--radius-lg)', padding: '8px 16px', alignItems: 'center',
              boxShadow: '0 4px 24px rgba(0,0,0,0.2)'
            }}
          >
            <ChevronRight size={20} color="var(--text-muted)" />
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

      {/* 3. Right Sidebar: RAG X-Ray */}
      <div className="pane-right">
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

              {/* Source Render blocks */}
              <div>
                <h4 style={{ fontSize: '12px', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '16px', color: 'var(--text-secondary)' }}>
                  Extracted Vectors ({selectedMsg.sources?.length || 0})
                </h4>
                
                {selectedMsg.sources && selectedMsg.sources.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    {selectedMsg.sources.map((src, idx) => (
                      <div key={idx} style={{
                        background: 'rgba(255,255,255,0.02)', border: 'var(--pane-border)',
                        borderRadius: 'var(--radius-md)', overflow: 'hidden'
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', background: 'rgba(0,0,0,0.3)', padding: '10px 14px', borderBottom: 'var(--pane-border)' }}>
                          <span style={{ fontSize: '12px', fontWeight: '500', color: 'var(--text-primary)' }}>{src.filename}</span>
                          <span style={{ fontSize: '11px', color: 'var(--accent-blue)' }}>PG {src.page}</span>
                        </div>
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
