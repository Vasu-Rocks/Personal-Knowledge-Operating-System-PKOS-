import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Smartphone, ClipboardCopy, AlertTriangle, Wifi, ShieldCheck, QrCode, Trash2, CheckCircle2 } from 'lucide-react';
import { shortDate } from '../../lib/chatView';
import { qrDataUrl } from '../../lib/qr';

function errorText(err) {
  return (err && err.message ? err.message : String(err)).replace(/^Error invoking remote method '[^']+': (Error: )?/, '');
}

const adapterLabel = (a) => (a.address === '192.168.137.1' ? 'Mobile hotspot' : a.name);

/** "4:59" until the pairing code runs out. */
function useCountdown(expiresAt) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!expiresAt) return undefined;
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0); // a new code: start from the current time, not from when the page opened
    const timer = setInterval(tick, 1000);
    return () => { clearTimeout(first); clearInterval(timer); };
  }, [expiresAt]);
  if (!expiresAt) return null;
  const left = Math.max(0, Math.round((Date.parse(expiresAt) - now) / 1000));
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
}

/**
 * Desktop-only Settings section (docs/08_PHONE_ACCESS_PLAN.md): lets paired phones on the same network (this laptop's
 * Mobile Hotspot, or the same Wi-Fi) open PKOS in their browser. Everything stays on this laptop. Off by default.
 */
export default function PhoneAccessSection({ desktop }) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState('');
  const [via, setVia] = useState(null);         // the address the QR code points at
  const [justPaired, setJustPaired] = useState(null);
  const lastStatus = useRef(null);

  const pairingActive = Boolean(status && status.pairing);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await desktop.phone.status();
        if (cancelled) return;
        const prev = lastStatus.current;
        // The code was used: name the phone that just paired.
        if (prev && prev.pairing && !s.pairing && s.devices.length > prev.devices.length) {
          setJustPaired(s.devices[s.devices.length - 1].name);
        }
        lastStatus.current = s;
        setStatus(s);
      } catch (e) {
        if (!cancelled) setError(errorText(e));
      }
    };
    load();
    // Faster while a code waits to be used; otherwise the laptop may join a network while this is open.
    const timer = setInterval(load, pairingActive ? 2000 : 5000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [desktop, pairingActive]);

  const run = async (fn) => {
    setBusy(true);
    setError('');
    try {
      const s = await fn();
      lastStatus.current = s;
      setStatus(s);
    } catch (e) {
      setError(errorText(e));
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

  const running = Boolean(status && status.enabled && status.running);
  const addresses = (status && status.addresses) || [];
  const target = addresses.find((a) => a.address === via) || addresses[0];
  const countdown = useCountdown(status && status.pairing ? status.pairing.expiresAt : null);
  const qr = useMemo(() => (target && target.pairUrl ? qrDataUrl(target.pairUrl) : null), [target]);
  const shortPrint = status && status.fingerprint ? status.fingerprint.split(':').slice(0, 4).join(':') : null;
  const code = status && status.pairing ? status.pairing.code : '';

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 12 }} aria-labelledby="phone-title">
      <div className="ai-section-title" id="phone-title"><Smartphone size={14} /> Phone access</div>
      <p className="ai-muted">
        Use PKOS from your phone's browser, with nothing to install. Your documents, chats and the AI stay on this
        laptop; the phone only shows the screens. Each phone is paired once with a code from here.
      </p>
      <label htmlFor="phone-enabled" style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer' }}>
        <input id="phone-enabled" type="checkbox" checked={Boolean(status && status.enabled)} disabled={!status || busy}
          onChange={(e) => run(() => desktop.phone.setEnabled(e.target.checked))} style={{ marginTop: 3 }} />
        <span>
          <span style={{ fontSize: 13, color: 'var(--text-primary)' }}>Let paired phones on this network use PKOS</span>
          <span className="ai-muted" style={{ display: 'block' }}>
            Off until you switch it on. Switching it off, or closing PKOS, disconnects phones at once.
          </span>
        </span>
      </label>

      {(error || (status && status.error)) && (
        <div className="ai-alert ai-alert-error" role="alert"><AlertTriangle size={16} /> {error || status.error}</div>
      )}

      {running && addresses.length === 0 && (
        <div className="ai-alert ai-alert-warn" role="status">
          <Wifi size={16} /> This laptop is not on a network. Turn on Mobile hotspot (Windows Settings &gt; Network &amp;
          internet &gt; Mobile hotspot) or join a Wi-Fi, then connect your phone to it.
        </div>
      )}

      {running && addresses.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }} data-testid="phone-addresses">
          {justPaired && (
            <div className="ai-alert ai-alert-ok" role="status"><CheckCircle2 size={16} /> Paired: {justPaired}. Log in on the phone.</div>
          )}

          {pairingActive ? (
            <div className="phone-pairing" data-testid="phone-pairing">
              {qr && <img src={qr} alt={`QR code to pair a phone through ${adapterLabel(target)}`} width={168} height={168} />}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
                <span className="ai-muted">1. Connect the phone to {adapterLabel(target)}.</span>
                <span className="ai-muted">2. Scan this code with the phone's camera, or open the address below and type:</span>
                <span className="phone-code" aria-label="Pairing code">{code.slice(0, 3)} {code.slice(3)}</span>
                <span className="ai-muted">3. Accept the "not private" warning (it is PKOS's own certificate), then log in.</span>
                <span className="ai-muted">Valid for one phone, {countdown} left.</span>
                <div className="ai-row">
                  {addresses.length > 1 && (
                    <select aria-label="Network the phone uses" className="ai-input" value={target.address}
                      onChange={(e) => setVia(e.target.value)} style={{ width: 'auto', flex: 'none' }}>
                      {addresses.map((a) => <option key={a.address} value={a.address}>{adapterLabel(a)}</option>)}
                    </select>
                  )}
                  <button type="button" className="ai-btn" disabled={busy} onClick={() => run(() => desktop.phone.cancelPair())}>Cancel</button>
                </div>
              </div>
            </div>
          ) : (
            <button type="button" className="ai-btn ai-btn-primary" style={{ alignSelf: 'flex-start' }} disabled={busy}
              onClick={() => { setJustPaired(null); run(() => desktop.phone.pair()); }}>
              <QrCode size={14} /> Pair a phone
            </button>
          )}

          <span className="ai-muted">Address to open on a paired phone:</span>
          {addresses.map((a) => (
            <div key={a.address} className="ai-row" style={{ justifyContent: 'space-between' }}>
              <span>
                <code style={{ fontSize: 14, color: 'var(--text-primary)' }}>{a.url}</code>
                <span className="ai-muted"> · {adapterLabel(a)}</span>
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
      )}

      {status && status.devices && status.devices.length > 0 && (
        <div>
          <div className="ai-label" style={{ marginBottom: 6 }}>Paired phones ({status.devices.length})</div>
          <ul aria-label="Paired phones" style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {status.devices.map((d) => (
              <li key={d.id} className="memory-row" style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>
                  <span style={{ fontSize: 13, color: 'var(--text-primary)' }}>{d.name}</span>
                  <span className="ai-muted"> · paired {shortDate(d.pairedAt)}, last used {shortDate(d.lastSeenAt)}</span>
                </span>
                <button type="button" className="ai-btn ai-btn-danger" aria-label={`Remove ${d.name}`} disabled={busy}
                  onClick={() => run(() => desktop.phone.remove(d.id))}>
                  <Trash2 size={13} /> Remove
                </button>
              </li>
            ))}
          </ul>
          <p className="ai-muted" style={{ marginTop: 6 }}>A removed phone is disconnected at once and has to pair again.</p>
        </div>
      )}
    </section>
  );
}
