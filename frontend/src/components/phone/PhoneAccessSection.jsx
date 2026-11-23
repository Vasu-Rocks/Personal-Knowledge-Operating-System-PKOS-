import React, { useCallback, useEffect, useState } from 'react';
import { Smartphone, ClipboardCopy, AlertTriangle, Wifi, ShieldCheck } from 'lucide-react';

function errorText(err) {
  return (err && err.message ? err.message : String(err)).replace(/^Error invoking remote method '[^']+': (Error: )?/, '');
}

/**
 * Desktop-only Settings section (docs/08_PHONE_ACCESS_PLAN.md): lets phones on the same network (this laptop's Mobile
 * Hotspot, or the same Wi-Fi) open PKOS in their browser. Everything stays on this laptop. Off by default.
 */
export default function PhoneAccessSection({ desktop }) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState('');

  const refresh = useCallback(async () => {
    try {
      setStatus(await desktop.phone.status());
    } catch (e) {
      setError(errorText(e));
    }
  }, [desktop]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await desktop.phone.status();
        if (!cancelled) setStatus(s);
      } catch (e) {
        if (!cancelled) setError(errorText(e));
      }
    };
    load();
    const timer = setInterval(load, 5000); // the laptop may join a network (or the hotspot) while this is open
    return () => { cancelled = true; clearInterval(timer); };
  }, [desktop]);

  const toggle = async (enabled) => {
    setBusy(true);
    setError('');
    try {
      setStatus(await desktop.phone.setEnabled(enabled));
    } catch (e) {
      setError(errorText(e));
      refresh();
    } finally {
      setBusy(false);
    }
  };

  const copy = async (url) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(url);
      setTimeout(() => setCopied(''), 1500);
    } catch {
      setCopied('');
    }
  };

  const shortPrint = status && status.fingerprint ? status.fingerprint.split(':').slice(0, 4).join(':') : null;

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 12 }} aria-labelledby="phone-title">
      <div className="ai-section-title" id="phone-title"><Smartphone size={14} /> Phone access</div>
      <p className="ai-muted">
        Use PKOS from your phone's browser, with nothing to install. Your documents, chats and the AI stay on this
        laptop; the phone only shows the screens.
      </p>
      <label htmlFor="phone-enabled" style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer' }}>
        <input id="phone-enabled" type="checkbox" checked={Boolean(status && status.enabled)} disabled={!status || busy}
          onChange={(e) => toggle(e.target.checked)} style={{ marginTop: 3 }} />
        <span>
          <span style={{ fontSize: 13, color: 'var(--text-primary)' }}>Let phones on this network use PKOS</span>
          <span className="ai-muted" style={{ display: 'block' }}>
            Off until you switch it on. Switching it off, or closing PKOS, disconnects phones at once.
          </span>
        </span>
      </label>

      {(error || (status && status.error)) && (
        <div className="ai-alert ai-alert-error" role="alert"><AlertTriangle size={16} /> {error || status.error}</div>
      )}

      {status && status.enabled && status.running && (status.addresses.length === 0 ? (
        <div className="ai-alert ai-alert-warn" role="status">
          <Wifi size={16} /> This laptop is not on a network. Turn on Mobile hotspot (Windows Settings &gt; Network &amp;
          internet &gt; Mobile hotspot) or join a Wi-Fi, then connect your phone to it.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }} data-testid="phone-addresses">
          <span className="ai-muted">Connect your phone to the same network, then open in its browser:</span>
          {status.addresses.map((a) => (
            <div key={a.address} className="ai-row" style={{ justifyContent: 'space-between' }}>
              <span>
                <code style={{ fontSize: 14, color: 'var(--text-primary)' }}>{a.url}</code>
                <span className="ai-muted"> · {a.address === '192.168.137.1' ? 'Mobile hotspot' : a.name}</span>
              </span>
              <button type="button" className="ai-btn" onClick={() => copy(a.url)} aria-label={`Copy ${a.url}`}>
                <ClipboardCopy size={14} /> {copied === a.url ? 'Copied' : 'Copy'}
              </button>
            </div>
          ))}
          <p className="ai-muted" style={{ display: 'flex', gap: 6 }}>
            <ShieldCheck size={14} style={{ flexShrink: 0, marginTop: 2 }} />
            <span>
              The connection is encrypted with PKOS's own certificate, so the phone first warns that it is "not private".
              That is expected here: choose Advanced, then continue. The certificate's code starts with{' '}
              <code>{shortPrint || '…'}</code> if you want to compare it.
            </span>
          </p>
          <p className="ai-muted">
            If the phone cannot open the address, Windows may be blocking it: allow PKOS when Windows asks (tick
            public networks too for a hotspot).
          </p>
        </div>
      ))}
    </section>
  );
}
