import React, { useCallback, useEffect, useState } from 'react';
import { X, Cpu, Cloud, CheckCircle2, ArrowLeft, AlertTriangle } from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { getLlmSettings, getOllamaModels, saveLlmSettings, settingsBody } from '../../lib/llmApi';
import { CLOUD_PROVIDERS } from '../../lib/models';
import OllamaModelPicker from './OllamaModelPicker';
import CloudKeyForm from './CloudKeyForm';
import './ai.css';

const STEPS = ['choose', 'configure', 'done'];

/**
 * First-run AI setup: local model (download with progress) or a cloud API key. Can be skipped and reopened
 * from the status badge or Settings. onClose(done) is called when it closes.
 */
export default function SetupWizard({ status, onClose }) {
  const { authFetch } = useAuth();
  const [step, setStep] = useState('choose');
  const [mode, setMode] = useState(null); // 'local' | 'cloud'
  const [saved, setSaved] = useState(null);
  const [models, setModels] = useState(null); // null = Ollama not reachable
  const [cloud, setCloud] = useState('openai');
  const [draft, setDraft] = useState({ key: '', model: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState('');

  const loadModels = useCallback(async () => {
    try {
      setModels(await getOllamaModels(authFetch));
    } catch {
      setModels(null);
    }
  }, [authFetch]);

  useEffect(() => {
    getLlmSettings(authFetch).then(setSaved).catch((e) => setError(e.message));
    loadModels();
  }, [authFetch, loadModels]);

  const ollamaReachable = models !== null;

  const finish = async (changes, text) => {
    setBusy(true);
    setError('');
    try {
      setSaved(await saveLlmSettings(authFetch, settingsBody(saved, changes)));
      setSummary(text);
      setStep('done');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const chooseLocal = (name) => finish({ provider: 'ollama', ollama_model: name }, `PKOS will answer with ${name}, running privately on this computer.`);

  const chooseCloud = () => {
    const changes = { provider: cloud, [`${cloud}_model`]: draft.model || null };
    if (draft.key) changes[`${cloud}_key`] = draft.key;
    const model = draft.model || CLOUD_PROVIDERS[cloud].defaultModel;
    finish(changes, `PKOS will answer with ${model} from ${CLOUD_PROVIDERS[cloud].label}.`);
  };

  const cloudReady = Boolean(draft.key || (saved && saved[`${cloud}_key_set`]));
  const stepIndex = STEPS.indexOf(step);

  return (
    <div className="ai-backdrop" role="dialog" aria-modal="true" aria-labelledby="setup-title">
      <div className="ai-card glass-panel">
        <div className="ai-card-header">
          <h2 id="setup-title">Set up your AI</h2>
          <button type="button" onClick={() => onClose(step === 'done')} aria-label="Close" style={{ color: 'var(--text-muted)' }}>
            <X size={20} />
          </button>
        </div>

        <div className="ai-card-body">
          <div className="ai-steps" aria-hidden="true">
            {STEPS.map((s, i) => <span key={s} className={i <= stepIndex ? 'on' : ''} />)}
          </div>
          {error && <div className="ai-alert ai-alert-error"><AlertTriangle size={16} /> {error}</div>}

          {step === 'choose' && (
            <>
              <p className="ai-lead">
                PKOS needs an AI model to answer questions and build your knowledge map. Choose where it runs.
                You can change this any time in Settings.
              </p>
              {status && !status.ready && <p className="ai-muted">Current status: {status.message}</p>}
              <div className="ai-choices">
                <button type="button" className={`ai-choice${mode === 'local' ? ' selected' : ''}`} disabled={!ollamaReachable}
                  onClick={() => { setMode('local'); setStep('configure'); }}>
                  <span className="ai-choice-title"><Cpu size={18} /> On this computer</span>
                  <p>Private and offline: nothing leaves your PC. Downloads a model once (about 2 GB). Free.</p>
                  {!ollamaReachable && <p style={{ color: '#fca5a5' }}>The local AI engine (Ollama) is not running.</p>}
                </button>
                <button type="button" className={`ai-choice${mode === 'cloud' ? ' selected' : ''}`}
                  onClick={() => { setMode('cloud'); setStep('configure'); }}>
                  <span className="ai-choice-title"><Cloud size={18} /> Cloud API</span>
                  <p>Use your OpenAI or Anthropic API key. Faster on PCs without a GPU; your text is sent to the provider.</p>
                </button>
              </div>
            </>
          )}

          {step === 'configure' && mode === 'local' && (
            <>
              <p className="ai-lead">Pick a model. Models already on this computer can be used straight away.</p>
              {ollamaReachable ? (
                <OllamaModelPicker
                  installed={models}
                  selected={null}
                  onSelect={chooseLocal}
                  onDownloaded={async (name) => { await loadModels(); chooseLocal(name); }}
                />
              ) : (
                <div className="ai-alert ai-alert-error">The local AI engine is not running. Go back and choose Cloud API, or restart PKOS.</div>
              )}
            </>
          )}

          {step === 'configure' && mode === 'cloud' && (
            <>
              <div className="ai-tabs" role="tablist">
                {Object.entries(CLOUD_PROVIDERS).map(([id, p]) => (
                  <button key={id} type="button" role="tab" aria-selected={cloud === id} className={`ai-tab${cloud === id ? ' active' : ''}`}
                    onClick={() => { setCloud(id); setDraft({ key: '', model: '' }); }}>
                    {p.label}
                  </button>
                ))}
              </div>
              <CloudKeyForm key={cloud} provider={cloud} saved={saved} draft={draft} onChange={setDraft} />
            </>
          )}

          {step === 'done' && (
            <div style={{ textAlign: 'center', padding: '12px 0', display: 'flex', flexDirection: 'column', gap: 12, alignItems: 'center' }}>
              <CheckCircle2 size={40} color="#4ade80" />
              <h3 style={{ fontSize: 18 }}>You're all set</h3>
              <p className="ai-lead">{summary}</p>
              <p className="ai-muted">Upload a document on the left, then ask a question about it.</p>
            </div>
          )}
        </div>

        <div className="ai-card-footer">
          {step === 'configure' ? (
            <button type="button" className="ai-btn" onClick={() => { setStep('choose'); setError(''); }}>
              <ArrowLeft size={14} /> Back
            </button>
          ) : (
            <span />
          )}
          {step === 'choose' && <button type="button" className="ai-btn-link ai-btn" onClick={() => onClose(false)}>Skip for now</button>}
          {step === 'configure' && mode === 'cloud' && (
            <button type="button" className="ai-btn ai-btn-primary" disabled={!cloudReady || busy} onClick={chooseCloud}>
              {busy ? 'Saving…' : 'Save and continue'}
            </button>
          )}
          {step === 'done' && <button type="button" className="ai-btn ai-btn-primary" onClick={() => onClose(true)}>Start using PKOS</button>}
        </div>
      </div>
    </div>
  );
}
