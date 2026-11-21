import React, { useCallback, useEffect, useState } from 'react';
import { Archive, Download, FolderOpen, FileText, History, Import, ClipboardCopy, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { API } from '../../api';
import { formatBytes } from '../../lib/models';

const KIND_LABEL = {
  manual: 'Manual', 'before-update': 'Before update', 'before-restore': 'Before restore', 'before-import': 'Before import',
};

function errorText(err) {
  return (err && err.message ? err.message : String(err)).replace(/^Error invoking remote method '[^']+': (Error: )?/, '');
}

/** Desktop-only Settings section: data folder, backups, import from an older PKOS, diagnostics. */
export default function DesktopDataSection({ desktop }) {
  const { authFetch } = useAuth();
  const [list, setList] = useState([]);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState(null); // { ok, text }

  const refresh = useCallback(async () => {
    try {
      setList(await desktop.backups.list());
    } catch (e) {
      setMessage({ ok: false, text: errorText(e) });
    }
  }, [desktop]);

  useEffect(() => { refresh(); }, [refresh]);

  const act = async (label, fn) => {
    setBusy(label);
    setMessage(null);
    try {
      const text = await fn();
      if (text) setMessage({ ok: true, text });
    } catch (e) {
      setMessage({ ok: false, text: errorText(e) });
    } finally {
      setBusy('');
      refresh();
    }
  };

  const backupNow = () => act('backup', async () => {
    const b = await desktop.backups.create();
    return `Backup saved: ${b.name} (${formatBytes(b.size)}).`;
  });

  const restore = (name) => act('restore', async () => {
    const r = await desktop.backups.restore(name);
    if (r.canceled) return '';
    return `Restored ${r.restored}. Your previous data was saved as ${r.safetyBackup}. Reloading…`;
  });

  const copyDiagnostics = () => act('diag', async () => {
    await desktop.copyDiagnostics();
    return 'Diagnostics copied to the clipboard. API keys, tokens, passwords and email addresses are masked; file names may appear.';
  });

  // ---- import
  const [showImport, setShowImport] = useState(false);
  const [src, setSrc] = useState({ host: 'localhost', port: '5433', database: 'pkos_v2', user: 'postgres', password: '' });
  const [preview, setPreview] = useState(null);
  const [imported, setImported] = useState(null);

  const runImport = async (dryRun) => {
    const res = await authFetch(`${API}/import/pkos`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...src, port: Number(src.port), dry_run: dryRun }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'The import failed.');
    return body;
  };

  const check = () => act('check', async () => {
    setImported(null);
    setPreview(await runImport(true));
    return '';
  });

  const doImport = () => act('import', async () => {
    const b = await desktop.backups.create('before-import');
    const result = await runImport(false);
    setImported(result);
    setPreview(null);
    return `Import finished. A backup from before the import was saved as ${b.name}.`;
  });

  const field = (key, label, props = {}) => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: props.flex || 1 }}>
      <span className="ai-muted">{label}</span>
      <input className="ai-input" value={src[key]} onChange={(e) => { setPreview(null); setSrc({ ...src, [key]: e.target.value }); }}
        aria-label={label} {...props.input} />
    </label>
  );

  const summary = (r) => (
    <div className="ai-muted" style={{ lineHeight: 1.7 }}>
      {r.imported_users.length
        ? <>Accounts: <strong>{r.imported_users.join(', ')}</strong>. {r.rows.documents || 0} documents, {r.rows.document_chunks || 0} passages,
          {' '}{r.rows.entities || 0} concepts, {r.rows.relationships || 0} relationships.</>
        : 'No new accounts to import.'}
      {r.skipped_users.length > 0 && (
        <div>Skipped: {r.skipped_users.map((s) => `${s.username} (${s.reason})`).join('; ')}.</div>
      )}
      <div>{r.note}</div>
    </div>
  );

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <div className="ai-section-title"><FolderOpen size={14} /> This computer</div>
      <p className="ai-muted">Your vault is stored in {desktop.dataDir}. PKOS {desktop.version}.</p>
      <div className="ai-row" style={{ flexWrap: 'wrap' }}>
        <button type="button" className="ai-btn" onClick={() => desktop.openDataFolder()}><FolderOpen size={14} /> Open data folder</button>
        <button type="button" className="ai-btn" onClick={() => desktop.openLogs()}><FileText size={14} /> Open logs</button>
        <button type="button" className="ai-btn" onClick={copyDiagnostics} disabled={!!busy}><ClipboardCopy size={14} /> Copy diagnostics</button>
      </div>

      <div className="ai-section-title" style={{ marginTop: 8 }}><Archive size={14} /> Backups</div>
      <p className="ai-muted">
        A backup contains every account and document on this computer. PKOS also backs up automatically before an
        update, a restore and an import (the last 5 of each are kept).
      </p>
      <div className="ai-row" style={{ flexWrap: 'wrap' }}>
        <button type="button" className="ai-btn ai-btn-primary" onClick={backupNow} disabled={!!busy}>
          <Download size={14} className={busy === 'backup' ? 'loader' : undefined} /> {busy === 'backup' ? 'Backing up…' : 'Back up now'}
        </button>
        <button type="button" className="ai-btn" onClick={() => restore(null)} disabled={!!busy}><History size={14} /> Restore from file…</button>
        <button type="button" className="ai-btn" onClick={() => desktop.backups.openFolder()}><FolderOpen size={14} /> Backups folder</button>
      </div>
      {list.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {list.slice(0, 5).map((b) => (
            <div key={b.name} className="ai-model" style={{ padding: '8px 12px' }}>
              <div className="ai-model-name" style={{ fontSize: 13 }}>{new Date(b.created).toLocaleString()}</div>
              <div className="ai-model-meta">{KIND_LABEL[b.kind] || b.kind} · {formatBytes(b.size)}</div>
              <div className="ai-model-actions">
                <button type="button" className="ai-btn" onClick={() => restore(b.name)} disabled={!!busy}>Restore</button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="ai-section-title" style={{ marginTop: 8 }}><Import size={14} /> Import from an older PKOS</div>
      {!showImport ? (
        <div>
          <p className="ai-muted" style={{ marginBottom: 8 }}>
            Copy the accounts and documents from a PKOS database you used before (for example the Docker setup on port 5433).
            The old database is only read, never changed.
          </p>
          <button type="button" className="ai-btn" onClick={() => setShowImport(true)}><Import size={14} /> Import…</button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div className="ai-row">
            {field('host', 'Host')}
            {field('port', 'Port', { flex: 0.5, input: { inputMode: 'numeric' } })}
            {field('database', 'Database')}
          </div>
          <div className="ai-row">
            {field('user', 'User')}
            {field('password', 'Password', { input: { type: 'password', autoComplete: 'off' } })}
          </div>
          <div className="ai-row">
            <button type="button" className="ai-btn" onClick={check} disabled={!!busy}>{busy === 'check' ? 'Checking…' : 'Check'}</button>
            <button type="button" className="ai-btn ai-btn-primary" onClick={doImport} disabled={!!busy || !preview || !preview.imported_users.length}>
              {busy === 'import' ? 'Importing…' : 'Import'}
            </button>
          </div>
          {preview && <div className="ai-alert ai-alert-warn" style={{ display: 'block' }}><strong>Will import</strong> {summary(preview)}</div>}
          {imported && (
            <div className="ai-alert ai-alert-ok" style={{ display: 'block' }}>
              <strong>Imported</strong> {summary(imported)}
              <div>Each person signs in with their old username and password.</div>
            </div>
          )}
        </div>
      )}

      {message && (
        <div className={`ai-alert ${message.ok ? 'ai-alert-ok' : 'ai-alert-error'}`} role="status">
          {message.ok ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />} {message.text}
        </div>
      )}
    </section>
  );
}
