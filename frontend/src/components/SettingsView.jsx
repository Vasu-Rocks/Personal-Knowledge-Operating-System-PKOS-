import React, { useState, useEffect } from 'react';
import { X, Server, Cloud, Lock, Save, CheckCircle2, Network, RefreshCw } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function SettingsView({ onClose }) {
  const [provider, setProvider] = useState('ollama');
  const [ollamaModel, setOllamaModel] = useState('llama3.2');
  const [openaiKey, setOpenaiKey] = useState('');
  const [anthropicKey, setAnthropicKey] = useState('');
  const [saved, setSaved] = useState(false);
  const { authFetch } = useAuth();
  const [graphStatus, setGraphStatus] = useState(null);
  const [rebuilding, setRebuilding] = useState(false);

  const loadGraphStatus = async () => {
    try {
      const res = await authFetch('http://localhost:8000/api/v1/graph/status');
      if (res.ok) setGraphStatus(await res.json());
    } catch (err) {
      console.error('Failed to load graph status', err);
    }
  };

  useEffect(() => {
    loadGraphStatus();
    const timer = setInterval(loadGraphStatus, 5000);
    return () => clearInterval(timer);
  }, []);

  const handleRebuild = async () => {
    setRebuilding(true);
    try {
      await authFetch('http://localhost:8000/api/v1/graph/rebuild', { method: 'POST' });
      await loadGraphStatus();
    } catch (err) {
      console.error('Rebuild request failed', err);
    } finally {
      setRebuilding(false);
    }
  };

  const mapBusy = graphStatus && (graphStatus.rebuild_queued || graphStatus.pending_summaries > 0 || graphStatus.active_jobs > 0);

  useEffect(() => {
    // Load existing settings
    setProvider(localStorage.getItem('llm_provider') || 'ollama');
    setOllamaModel(localStorage.getItem('ollama_model') || 'llama3.2');
    setOpenaiKey(localStorage.getItem('openai_api_key') || '');
    setAnthropicKey(localStorage.getItem('anthropic_api_key') || '');
  }, []);

  const handleSave = () => {
    localStorage.setItem('llm_provider', provider);
    localStorage.setItem('ollama_model', ollamaModel);
    localStorage.setItem('openai_api_key', openaiKey);
    localStorage.setItem('anthropic_api_key', anthropicKey);
    
    setSaved(true);
    setTimeout(() => {
      setSaved(false);
      onClose();
    }, 1000);
  };

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0, 0, 0, 0.6)', backdropFilter: 'blur(8px)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center'
    }}>
      <div className="glass-panel" style={{
        width: '450px', borderRadius: 'var(--radius-lg)', overflow: 'hidden',
        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '20px 24px', borderBottom: 'var(--pane-border)', background: 'rgba(255,255,255,0.02)' }}>
          <h2 style={{ fontSize: '16px', fontWeight: '600' }}>Inference Settings</h2>
          <button onClick={onClose} style={{ color: 'var(--text-muted)' }}>
            <X size={20} />
          </button>
        </div>

        <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          {/* Provider Toggle */}
          <div>
            <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '10px' }}>Active Provider</label>
            <div style={{ display: 'flex', background: 'rgba(0,0,0,0.3)', borderRadius: 'var(--radius-md)', padding: '4px' }}>
              <button
                onClick={() => setProvider('ollama')}
                style={{
                  flex: 1, padding: '10px', borderRadius: 'var(--radius-sm)',
                  background: provider === 'ollama' ? 'var(--accent-blue)' : 'transparent',
                  color: provider === 'ollama' ? '#fff' : 'var(--text-muted)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', fontSize: '13px', fontWeight: '500', border: 'none'
                }}
              >
                <Server size={16} /> Local Ollama
              </button>
              <button
                onClick={() => setProvider('openai')}
                style={{
                  flex: 1, padding: '10px', borderRadius: 'var(--radius-sm)',
                  background: provider === 'openai' ? 'var(--accent-blue)' : 'transparent',
                  color: provider === 'openai' ? '#fff' : 'var(--text-muted)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', fontSize: '13px', fontWeight: '500', border: 'none'
                }}
              >
                <Cloud size={16} /> Cloud LLM
              </button>
            </div>
          </div>

          {/* Dynamic Settings */}
          {provider === 'ollama' && (
            <div>
               <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '8px' }}>Ollama Model Name</label>
               <input 
                 type="text" 
                 value={ollamaModel}
                 onChange={(e) => setOllamaModel(e.target.value)}
                 placeholder="e.g. llama3.2"
                 style={{ 
                   width: '100%', padding: '12px 16px', borderRadius: 'var(--radius-md)', 
                   background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text-primary)', fontSize: '14px', outline: 'none'
                 }}
               />
            </div>
          )}

          {provider === 'openai' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
               <div>
                 <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                   <Lock size={12} /> OpenAI API Key
                 </label>
                 <input 
                   type="password" 
                   value={openaiKey}
                   onChange={(e) => setOpenaiKey(e.target.value)}
                   placeholder="sk-..."
                   autoComplete="new-password"
                   style={{ 
                     width: '100%', padding: '12px 16px', borderRadius: 'var(--radius-md)', 
                     background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text-primary)', fontSize: '14px', outline: 'none'
                   }}
                 />
                 <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '8px', lineHeight: 1.4 }}>
                   Stored exclusively on your device via HTML5 LocalStorage. Never saved to our database.
                 </p>
               </div>
            </div>
          )}
        </div>

        {/* Knowledge map */}
        <div style={{ padding: '0 24px 24px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: 'var(--text-secondary)' }}>
            <Network size={14} /> Knowledge map
          </label>
          {graphStatus && (
            <p style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
              {graphStatus.entities} concepts, {graphStatus.relationships} relationships, {graphStatus.communities} topic groups
              {graphStatus.pending_summaries > 0 ? ` (${graphStatus.pending_summaries} still being summarised)` : ''}
              {graphStatus.active_jobs > 0 ? ' - documents are still being processed' : ''}
              {graphStatus.rebuild_queued && graphStatus.active_jobs === 0 ? ' - rebuild queued' : ''}
            </p>
          )}
          <button
            onClick={handleRebuild}
            disabled={rebuilding || (graphStatus && graphStatus.rebuild_queued)}
            style={{
              alignSelf: 'flex-start', display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 14px',
              borderRadius: 'var(--radius-sm)', fontSize: '12px', background: 'rgba(255,255,255,0.05)',
              color: 'var(--text-secondary)', border: '1px solid rgba(255,255,255,0.1)', cursor: 'pointer'
            }}
          >
            <RefreshCw size={14} className={mapBusy ? 'loader' : undefined} /> Rebuild knowledge map
          </button>
          <p style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.4 }}>
            Topic groups answer broad questions such as "give me an overview". They rebuild automatically after a document finishes processing.
          </p>
        </div>

        {/* Footer */}
        <div style={{ padding: '16px 24px', borderTop: 'var(--pane-border)', background: 'rgba(0,0,0,0.2)', display: 'flex', justifyContent: 'flex-end' }}>
          <button 
            onClick={handleSave}
            style={{
              display: 'flex', alignItems: 'center', gap: '8px', background: 'var(--accent-blue)', 
              color: '#fff', padding: '10px 20px', borderRadius: 'var(--radius-sm)', fontSize: '13px', fontWeight: '500', border: 'none', cursor: 'pointer'
            }}
          >
            {saved ? <><CheckCircle2 size={16} /> Saved</> : <><Save size={16} /> Save Config</>}
          </button>
        </div>
      </div>
    </div>
  );
}
