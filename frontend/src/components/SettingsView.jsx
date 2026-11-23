import React, { useState, useEffect, useCallback } from 'react';
import { X, Server, Cloud, Save, CheckCircle2, Network, RefreshCw, Sparkles, AlertTriangle } from 'lucide-react';
import DesktopDataSection from './ai/DesktopDataSection';
import { useAuth } from '../context/useAuth';
import { API } from '../api';
import { deleteOllamaModel, getLlmSettings, getOllamaModels, saveLlmSettings, settingsBody } from '../lib/llmApi';
import { CLOUD_PROVIDERS } from '../lib/models';
import OllamaModelPicker from './ai/OllamaModelPicker';
import CloudKeyForm from './ai/CloudKeyForm';
import MemoryPage from './memory/MemoryPage';
import PhoneAccessSection from './phone/PhoneAccessSection';
import './ai/ai.css';

const PROVIDERS = [
  { id: 'ollama', label: 'On this PC', icon: Server },
  { id: 'openai', label: 'OpenAI', icon: Cloud },
  { id: 'anthropic', label: 'Anthropic', icon: Cloud },
];

export default function SettingsView({ onClose, onOpenSetup, onSaved }) {
  const { authFetch } = useAuth();
  const desktop = typeof window !== 'undefined' ? window.pkos : null;

  // ---- AI provider
  const [saved, setSaved] = useState(null);
  const [provider, setProvider] = useState('ollama');
  const [ollamaModel, setOllamaModel] = useState('');
  const [drafts, setDrafts] = useState({ openai: { key: '', model: '' }, anthropic: { key: '', model: '' } });
  const [models, setModels] = useState(null);
  const [modelsError, setModelsError] = useState('');
  const [error, setError] = useState('');
  const [justSaved, setJustSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadModels = useCallback(async () => {
    try {
      setModels(await getOllamaModels(authFetch));
      setModelsError('');
    } catch (e) {
      setModels(null);
      setModelsError(e.message);
    }
  }, [authFetch]);

  useEffect(() => {
    (async () => {
      try {
        const s = await getLlmSettings(authFetch);
        setSaved(s);
        setProvider(s.provider);
        setOllamaModel(s.ollama_model || (s.provider === 'ollama' ? s.effective_model : ''));
        setDrafts({
          openai: { key: '', model: s.openai_model || '' },
          anthropic: { key: '', model: s.anthropic_model || '' },
        });
      } catch (e) {
        setError(e.message);
      }
    })();
    loadModels();
  }, [authFetch, loadModels]);

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const changes = {
        provider,
        ollama_model: ollamaModel || null,
        openai_model: drafts.openai.model || null,
        anthropic_model: drafts.anthropic.model || null,
      };
      if (drafts.openai.key) changes.openai_key = drafts.openai.key;
      if (drafts.anthropic.key) changes.anthropic_key = drafts.anthropic.key;
      const s = await saveLlmSettings(authFetch, settingsBody(saved, changes));
      setSaved(s);
      setDrafts((d) => ({ openai: { ...d.openai, key: '' }, anthropic: { ...d.anthropic, key: '' } }));
      setJustSaved(true);
      if (onSaved) onSaved();
      setTimeout(() => setJustSaved(false), 1500);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const removeKey = async (p) => {
    setError('');
    try {
      setSaved(await saveLlmSettings(authFetch, settingsBody(saved, { [`${p}_key`]: '' })));
      if (onSaved) onSaved();
    } catch (e) {
      setError(e.message);
    }
  };

  const removeModel = async (name) => {
    if (!window.confirm(`Remove ${name} from this computer? You can download it again later.`)) return;
    try {
      await deleteOllamaModel(authFetch, name);
      await loadModels();
      if (onSaved) onSaved();
    } catch (e) {
      setModelsError(e.message);
    }
  };

  // ---- Knowledge map
  const [graphStatus, setGraphStatus] = useState(null);
  const [rebuilding, setRebuilding] = useState(false);

  const loadGraphStatus = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/graph/status`);
      if (res.ok) setGraphStatus(await res.json());
    } catch (err) {
      console.error('Failed to load graph status', err);
    }
  }, [authFetch]);

  useEffect(() => {
    loadGraphStatus();
    const timer = setInterval(loadGraphStatus, 5000);
    return () => clearInterval(timer);
  }, [loadGraphStatus]);

  const handleRebuild = async () => {
    setRebuilding(true);
    try {
      await authFetch(`${API}/graph/rebuild`, { method: 'POST' });
      await loadGraphStatus();
    } catch (err) {
      console.error('Rebuild request failed', err);
    } finally {
      setRebuilding(false);
    }
  };

  const mapBusy = graphStatus && (graphStatus.rebuild_queued || graphStatus.pending_summaries > 0 || graphStatus.active_jobs > 0);
  const savedProviderChanged = saved && saved.provider !== provider;

  return (
    <div className="ai-backdrop" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <div className="ai-card glass-panel">
        <div className="ai-card-header">
          <h2 id="settings-title">Settings</h2>
          <button type="button" onClick={onClose} aria-label="Close" style={{ color: 'var(--text-muted)' }}>
            <X size={20} />
          </button>
        </div>

        <div className="ai-card-body">
          {/* AI provider */}
          <section>
            <div className="ai-section-title" style={{ justifyContent: 'space-between' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><Sparkles size={14} /> AI model</span>
              {onOpenSetup && (
                <button type="button" className="ai-btn-link ai-btn" onClick={onOpenSetup}>Run setup again</button>
              )}
            </div>
            {error && <div className="ai-alert ai-alert-error" style={{ marginBottom: 12 }}><AlertTriangle size={16} /> {error}</div>}
            <div className="ai-tabs" role="tablist" aria-label="AI provider" style={{ marginBottom: 16 }}>
              {PROVIDERS.map(({ id, label, icon }) => (
                <button key={id} type="button" role="tab" aria-selected={provider === id}
                  className={`ai-tab${provider === id ? ' active' : ''}`} onClick={() => setProvider(id)}>
                  {React.createElement(icon, { size: 15 })} {label}
                </button>
              ))}
            </div>

            {provider === 'ollama' && (
              models ? (
                <OllamaModelPicker
                  installed={models}
                  selected={ollamaModel}
                  onSelect={setOllamaModel}
                  onDownloaded={async (name) => { await loadModels(); setOllamaModel(name); }}
                  onDelete={removeModel}
                  selectLabel="Select"
                />
              ) : (
                <div className="ai-alert ai-alert-error">{modelsError || 'Loading models…'}</div>
              )
            )}

            {provider !== 'ollama' && (
              <>
                <CloudKeyForm
                  key={provider}
                  provider={provider}
                  saved={saved}
                  draft={drafts[provider]}
                  onChange={(d) => setDrafts((all) => ({ ...all, [provider]: d }))}
                />
                {saved && saved[`${provider}_key_set`] && (
                  <button type="button" className="ai-btn ai-btn-danger" style={{ marginTop: 12 }} onClick={() => removeKey(provider)}>
                    Remove saved {CLOUD_PROVIDERS[provider].label} key
                  </button>
                )}
              </>
            )}
            {savedProviderChanged && (
              <p className="ai-muted" style={{ marginTop: 10 }}>Save to switch PKOS to this provider.</p>
            )}
          </section>

          {/* Knowledge map */}
          <section style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div className="ai-section-title"><Network size={14} /> Knowledge map</div>
            {graphStatus && (
              <p className="ai-muted">
                {graphStatus.entities} concepts, {graphStatus.relationships} relationships, {graphStatus.communities} topic groups
                {graphStatus.pending_summaries > 0 ? ` (${graphStatus.pending_summaries} still being summarised)` : ''}
                {graphStatus.active_jobs > 0 ? ' - documents are still being processed' : ''}
                {graphStatus.rebuild_queued && graphStatus.active_jobs === 0 ? ' - rebuild queued' : ''}
              </p>
            )}
            <button type="button" className="ai-btn" style={{ alignSelf: 'flex-start' }} onClick={handleRebuild}
              disabled={rebuilding || (graphStatus && graphStatus.rebuild_queued)}>
              <RefreshCw size={14} className={mapBusy ? 'loader' : undefined} /> Rebuild knowledge map
            </button>
            <p className="ai-muted">
              Topic groups answer broad questions such as "give me an overview". They rebuild automatically after a document finishes processing.
            </p>
          </section>

          {/* Memory */}
          <MemoryPage />

          {/* Phone access (desktop app only) */}
          {desktop && desktop.isDesktop && desktop.phone && <PhoneAccessSection desktop={desktop} />}

          {/* Desktop app */}
          {desktop && desktop.isDesktop && desktop.backups && <DesktopDataSection desktop={desktop} />}
        </div>

        <div className="ai-card-footer">
          <span className="ai-muted">{justSaved ? '' : 'API keys are stored encrypted and never shown again.'}</span>
          <button type="button" className="ai-btn ai-btn-primary" onClick={handleSave} disabled={saving || !saved}>
            {justSaved ? <><CheckCircle2 size={16} /> Saved</> : <><Save size={16} /> {saving ? 'Saving…' : 'Save'}</>}
          </button>
        </div>
      </div>
    </div>
  );
}
