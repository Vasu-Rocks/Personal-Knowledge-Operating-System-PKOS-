import React, { useState } from 'react';
import { X, Search, Network, ArrowRight, ArrowLeft, AlertTriangle, BookOpen } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { bookColor, shortBook } from './bookColors';

const API = 'http://localhost:8000/api/v1';

function BookBadge({ name }) {
  const color = bookColor(name);
  return (
    <span title={name} style={{
      fontSize: '10px', padding: '1px 6px', borderRadius: '8px', color, border: `1px solid ${color}`,
      whiteSpace: 'nowrap'
    }}>
      {shortBook(name)}
    </span>
  );
}

const MATCH_LABEL = {
  exact: 'same word', variant: 'close spelling', contains: 'part of a longer name', similar: 'similar meaning'
};

function Chain({ path }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
      {path.steps.map((step, i) => {
        const link = path.links[i];
        return (
          <React.Fragment key={i}>
            <div style={{
              padding: '8px 12px', borderRadius: 'var(--radius-sm)', background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.08)', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px'
            }}>
              <span style={{ fontSize: '13px', fontWeight: 600 }}>{step.name}</span>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{step.category}</span>
              {step.books.map(b => <BookBadge key={b} name={b} />)}
            </div>
            {link && (
              <div style={{
                marginLeft: '18px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px',
                fontSize: '11px', color: 'var(--text-secondary)'
              }}>
                {link.forward ? <ArrowRight size={12} /> : <ArrowLeft size={12} />}
                <span style={{ fontFamily: 'monospace' }}>{link.predicate}</span>
                <span style={{ color: 'var(--text-muted)' }}>
                  {link.weight > 1 ? `${link.weight} passages` : '1 passage'}
                </span>
                {link.books.map(b => <BookBadge key={b} name={b} />)}
              </div>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// When a typed word resolved to a differently spelled concept, say so instead of silently showing another name.
const sameName = (a, b) => a.toLowerCase().replace(/[^a-z0-9+#]/g, '') === b.toLowerCase().replace(/[^a-z0-9+#]/g, '');
const matchedNote = (c) => {
  const notes = [];
  if (!sameName(c.a, c.steps[0].name)) notes.push(`"${c.a}" matched "${c.steps[0].name}"`);
  const last = c.steps[c.steps.length - 1].name;
  if (!sameName(c.b, last)) notes.push(`"${c.b}" matched "${last}"`);
  return notes.length ? ` ${notes.join('; ')}.` : '';
};

export default function ConnectionsView({ onClose }) {
  const { authFetch } = useAuth();
  const [termA, setTermA] = useState('');
  const [termB, setTermB] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [lookup, setLookup] = useState(null);
  const [connection, setConnection] = useState(null);

  const search = async (e) => {
    e.preventDefault();
    const a = termA.trim();
    const b = termB.trim();
    if (!a) return;
    setLoading(true);
    setError('');
    setLookup(null);
    setConnection(null);
    try {
      const url = b
        ? `${API}/graph/connection?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`
        : `${API}/graph/lookup?term=${encodeURIComponent(a)}`;
      const res = await authFetch(url);
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      const data = await res.json();
      if (b) setConnection(data); else setLookup(data);
    } catch (err) {
      setError(err.message || 'Something went wrong.');
    } finally {
      setLoading(false);
    }
  };

  const inputStyle = {
    flex: 1, minWidth: 0, padding: '10px 14px', borderRadius: 'var(--radius-md)', background: 'rgba(0,0,0,0.2)',
    border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text-primary)', fontSize: '14px', outline: 'none'
  };
  const caption = { fontSize: '11px', color: 'var(--text-muted)' };

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.6)',
      backdropFilter: 'blur(8px)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center'
    }}>
      <div className="glass-panel" style={{
        width: '720px', maxWidth: '94vw', maxHeight: '88vh', display: 'flex', flexDirection: 'column',
        borderRadius: 'var(--radius-lg)', overflow: 'hidden', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)'
      }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '18px 24px',
          borderBottom: 'var(--pane-border)', background: 'rgba(255,255,255,0.02)'
        }}>
          <h2 style={{ fontSize: '16px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Network size={18} /> Connections
          </h2>
          <button onClick={onClose} style={{ color: 'var(--text-muted)' }} aria-label="Close"><X size={20} /></button>
        </div>

        <form onSubmit={search} style={{ padding: '16px 24px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            <input style={inputStyle} value={termA} onChange={(e) => setTermA(e.target.value)}
              placeholder="A word, e.g. Gaussian" maxLength={100} autoFocus />
            <input style={inputStyle} value={termB} onChange={(e) => setTermB(e.target.value)}
              placeholder="Connect to (optional), e.g. k-means" maxLength={100} />
            <button type="submit" disabled={loading || !termA.trim()} style={{
              display: 'flex', alignItems: 'center', gap: '6px', padding: '10px 18px', borderRadius: 'var(--radius-sm)',
              background: 'var(--accent-blue)', color: '#fff', border: 'none', fontSize: '13px', fontWeight: 500,
              cursor: 'pointer', opacity: loading || !termA.trim() ? 0.6 : 1
            }}>
              <Search size={14} /> {termB.trim() ? 'Connect' : 'Look up'}
            </button>
          </div>
          <span style={caption}>
            One word shows where it appears in each book. Two words show the chain of ideas that links them.
          </span>
        </form>

        <div style={{ padding: '0 24px 24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {loading && <span style={caption}>Searching...</span>}
          {error && <span style={{ fontSize: '13px', color: '#ef4444' }}>{error}</span>}

          {lookup && lookup.matches.length === 0 && (
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              Nothing in your documents matches "{lookup.term}".
            </span>
          )}

          {lookup && lookup.matches.length > 0 && (
            <>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {lookup.matches.map((m, i) => (
                  <span key={i} title={m.description || ''} style={{
                    fontSize: '12px', padding: '3px 10px', borderRadius: '10px', background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.1)'
                  }}>
                    {m.name} <span style={caption}>{MATCH_LABEL[m.match]}</span>
                  </span>
                ))}
              </div>
              {lookup.books.map((b) => (
                <div key={b.filename} style={{
                  padding: '12px 14px', borderRadius: 'var(--radius-md)', background: 'rgba(255,255,255,0.03)',
                  border: `1px solid ${bookColor(b.filename)}55`, display: 'flex', flexDirection: 'column', gap: '8px'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    <BookOpen size={14} color={bookColor(b.filename)} />
                    <span style={{ fontSize: '13px', fontWeight: 600 }}>{b.book}</span>
                    <span style={caption}>
                      {b.mentions} passage{b.mentions === 1 ? '' : 's'}, pages {b.pages.join(', ')}{b.mentions > b.pages.length ? '...' : ''}
                    </span>
                  </div>
                  {b.neighbors.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                      {b.neighbors.map((n, i) => (
                        <span key={i} style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '8px', background: 'rgba(0,0,0,0.25)' }}>
                          <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                            {n.direction === 'out' ? '' : '<- '}{n.predicate}{n.direction === 'out' ? ' ->' : ''}
                          </span>{' '}{n.name}
                        </span>
                      ))}
                    </div>
                  )}
                  {b.chunks.map((c, i) => (
                    <p key={i} style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5, fontStyle: 'italic' }}>
                      p. {c.page}: {c.text}
                    </p>
                  ))}
                </div>
              ))}
            </>
          )}

          {connection && !connection.found && (
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{connection.reason}</span>
          )}

          {connection && connection.found && (
            <>
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
                <strong>{connection.hops} link{connection.hops === 1 ? '' : 's'}</strong>
                {connection.crosses_books
                  ? <span>across {connection.books_on_path.length} books</span>
                  : <span style={caption}>within one book</span>}
                {connection.books_on_path.map(b => <BookBadge key={b} name={b} />)}
              </div>
              <span style={caption}>
                Evidence: {connection.strong_links} of {connection.hops} link{connection.hops === 1 ? '' : 's'} appear in more than one passage.
                {matchedNote(connection)}
              </span>
              {connection.weak && (
                <div style={{
                  display: 'flex', gap: '8px', alignItems: 'flex-start', padding: '8px 12px', fontSize: '12px',
                  borderRadius: 'var(--radius-sm)', background: 'rgba(245,158,11,0.1)', color: '#f59e0b'
                }}>
                  <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: '2px' }} />
                  <span>Weak connection: most links rest on a single passage, so this chain may be a coincidence of extraction rather than a real relationship.</span>
                </div>
              )}
              <Chain path={connection} />
              {connection.alternatives.length > 0 && (
                <details>
                  <summary style={{ fontSize: '12px', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                    {connection.alternatives.length} other route{connection.alternatives.length === 1 ? '' : 's'}
                  </summary>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '10px' }}>
                    {connection.alternatives.map((alt, i) => <Chain key={i} path={alt} />)}
                  </div>
                </details>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
