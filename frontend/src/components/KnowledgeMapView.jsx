import React, { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { X, Search, Map as MapIcon, ArrowRight, Loader2, BookOpen, ChevronLeft } from 'lucide-react';
import { useAuth } from '../context/useAuth';
import { API } from '../api';
import { bookColorAt, shortBook } from './bookColors';

const CATEGORIES = ['CONCEPT', 'METHOD', 'TECHNOLOGY', 'PERSON', 'ORGANIZATION', 'EVENT', 'LOCATION', 'OTHER'];
const MODES = [
  { id: 'backbone', label: 'Backbone', hint: 'Links backed by 2+ passages' },
  { id: 'full', label: 'Everything', hint: 'All links, most central concepts' },
  { id: 'communities', label: 'Topics', hint: 'One bubble per topic' },
];
const LABEL_TOP_N = 30; // most central concepts keep their label at any zoom, for orientation
const LABEL_TOP_TOPICS = 15;

// Minimal collision force (keeps topic bubbles from overlapping). O(n^2), so only used for the ~25 topics.
const collideForce = (radiusOf, padding = 6) => {
  let nodes = [];
  const force = () => {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        const dx = b.x - a.x || 0.01, dy = b.y - a.y || 0.01;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const min = radiusOf(a) + radiusOf(b) + padding;
        if (dist < min) {
          const push = (min - dist) / dist / 2;
          a.x -= dx * push; a.y -= dy * push;
          b.x += dx * push; b.y += dy * push;
        }
      }
    }
  };
  force.initialize = (n) => { nodes = n; };
  return force;
};

// Weak pull towards the centre so disconnected clusters (and unlinked topics) do not drift off-screen.
const gravityForce = (strength) => {
  let nodes = [];
  const force = (alpha) => {
    for (const n of nodes) {
      n.vx -= n.x * strength * alpha;
      n.vy -= n.y * strength * alpha;
    }
  };
  force.initialize = (n) => { nodes = n; };
  return force;
};

const chip = (active, color) => ({
  fontSize: '11px', padding: '4px 10px', borderRadius: '12px', cursor: 'pointer', whiteSpace: 'nowrap',
  border: `1px solid ${active ? (color || 'var(--accent-blue)') : 'rgba(255,255,255,0.12)'}`,
  background: active ? `${color || '#3b82f6'}22` : 'transparent',
  color: active ? 'var(--text-primary)' : 'var(--text-muted)',
});

function BookTag({ book, index }) {
  const color = bookColorAt(index);
  return (
    <span title={book.filename} style={{ fontSize: '10px', padding: '1px 6px', borderRadius: '8px', color, border: `1px solid ${color}` }}>
      {shortBook(book.filename)}
    </span>
  );
}

export default function KnowledgeMapView({ onClose }) {
  const { authFetch } = useAuth();
  const [mode, setMode] = useState('backbone');
  const [selectedBooks, setSelectedBooks] = useState(null); // null = all books
  const [minSupport, setMinSupport] = useState('');
  const [categories, setCategories] = useState([]);
  const [crossBook, setCrossBook] = useState(false);
  const [hideGeneric, setHideGeneric] = useState(true);
  const [community, setCommunity] = useState(null); // {id, name} when drilled into a topic
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null); // {type: 'node'|'link', item}
  const [panel, setPanel] = useState(null); // {loading, data, error}
  const [hover, setHover] = useState(null);
  const [search, setSearch] = useState('');
  const [size, setSize] = useState({ width: 800, height: 600 });
  const graphRef = useRef(null);
  const fitPending = useRef(false);
  const boxRef = useRef(null);

  // Fit the canvas to its container.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width: Math.max(200, width), height: Math.max(200, height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      if (selected) { setSelected(null); setPanel(null); } else onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selected, onClose]);

  const effectiveMode = community ? 'full' : mode;

  // Load the map whenever a filter changes; an abort drops responses for filters that are no longer current.
  useEffect(() => {
    const ctrl = new AbortController();
    const params = new URLSearchParams({ mode: effectiveMode, hide_generic: String(hideGeneric), cross_book: String(crossBook) });
    if (selectedBooks) params.set('books', selectedBooks.join(','));
    if (minSupport) params.set('min_support', minSupport);
    if (categories.length) params.set('categories', categories.join(','));
    if (community) params.set('community', community.id);
    setLoading(true);
    setError('');
    authFetch(`${API}/graph/map?${params}`, { signal: ctrl.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`Could not load the map (${res.status}).`);
        setData(await res.json());
        fitPending.current = true; // re-centre once the new layout settles
        setSelected(null);
        setPanel(null);
      })
      .catch((err) => { if (err.name !== 'AbortError') setError(err.message); })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveMode, selectedBooks, minSupport, categories, crossBook, hideGeneric, community]);

  // Fresh objects per response: the force layout mutates nodes (x, y) and replaces link ends with node objects.
  const graph = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    // Topics are ranked by size, concepts by PageRank; only the top few are labelled until you zoom in.
    const rank = data.mode === 'communities' ? (n => n.size || 0) : (n => n.pagerank || 0);
    const top = new Set([...data.nodes].sort((a, b) => rank(b) - rank(a))
      .slice(0, data.mode === 'communities' ? LABEL_TOP_TOPICS : LABEL_TOP_N).map(n => n.id));
    return {
      nodes: data.nodes.map(n => ({ ...n, isTop: top.has(n.id) })),
      links: data.links.map(l => ({ ...l })),
    };
  }, [data]);

  const neighbours = useMemo(() => {
    const m = new Map();
    for (const l of data?.links || []) {
      if (!m.has(l.source)) m.set(l.source, new Set());
      if (!m.has(l.target)) m.set(l.target, new Set());
      m.get(l.source).add(l.target);
      m.get(l.target).add(l.source);
    }
    return m;
  }, [data]);

  const books = data?.books || [];
  const focusId = selected?.type === 'node' ? selected.item.id : hover;
  const isLit = (id) => !focusId || id === focusId || neighbours.get(focusId)?.has(id);
  const endId = (end) => (typeof end === 'object' ? end.id : end);

  const radius = (n) => data?.mode === 'communities'
    ? 4 + Math.sqrt(n.size || 1) * 1.2
    : 2.5 + Math.min(10, Math.sqrt(n.mentions || 1) * 0.9);

  // Bubbles need room; dots are fine with the library defaults.
  useEffect(() => {
    const fg = graphRef.current;
    if (!fg || !data) return;
    if (data.mode === 'communities') {
      fg.d3Force('charge').strength(-300);
      fg.d3Force('link').distance(90);
      fg.d3Force('collide', collideForce(radius));
      fg.d3Force('gravity', gravityForce(0.08));
    } else {
      fg.d3Force('charge').strength(-30);
      fg.d3Force('link').distance(30);
      fg.d3Force('collide', null);
      fg.d3Force('gravity', gravityForce(0.03));
    }
    fg.d3ReheatSimulation();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const drawNode = (node, ctx, scale) => {
    const r = radius(node);
    const colors = (node.books || []).map(i => bookColorAt(i));
    const alpha = isLit(node.id) ? 1 : 0.15;
    ctx.globalAlpha = alpha;
    if (colors.length <= 1) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = colors[0] || '#94a3b8';
      ctx.fill();
    } else {
      // One slice per book the concept appears in: a multi-coloured node is a cross-book concept.
      colors.forEach((c, i) => {
        ctx.beginPath();
        ctx.moveTo(node.x, node.y);
        ctx.arc(node.x, node.y, r, (2 * Math.PI * i) / colors.length, (2 * Math.PI * (i + 1)) / colors.length);
        ctx.closePath();
        ctx.fillStyle = c;
        ctx.fill();
      });
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 1.2, 0, 2 * Math.PI);
      ctx.strokeStyle = 'rgba(255,255,255,0.85)';
      ctx.lineWidth = 0.8;
      ctx.stroke();
    }
    if (node.id === focusId) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 3, 0, 2 * Math.PI);
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    const showLabel = node.isTop || scale > 2.2 || node.id === focusId || (focusId && isLit(node.id));
    if (showLabel) {
      const fontSize = Math.max(10 / scale, 2.5);
      ctx.font = `${fontSize}px Inter, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = 'rgba(229,231,235,0.95)';
      ctx.fillText(node.name, node.x, node.y + r + 1.5);
    }
    ctx.globalAlpha = 1;
  };

  const paintArea = (node, color, ctx) => {
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius(node) + 2, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();
  };

  const linkColor = (l) => {
    const lit = !focusId || endId(l.source) === focusId || endId(l.target) === focusId;
    if (!lit) return 'rgba(148,163,184,0.06)';
    if (l.cross_book) return 'rgba(255,255,255,0.8)'; // supported by passages from several books
    const i = (l.books || [])[0];
    return i !== undefined ? `${bookColorAt(i)}99` : 'rgba(148,163,184,0.4)';
  };
  const linkWidth = (l) => (data?.mode === 'communities' ? l.width : 0.4 + Math.log2(1 + (l.support || 1)) * 0.8);

  const openNode = async (node) => {
    setSelected({ type: 'node', item: node });
    if (data.mode === 'communities') {
      setPanel({ data: node });
      return;
    }
    setPanel({ loading: true });
    try {
      const res = await authFetch(`${API}/graph/entity/${node.id}`);
      if (!res.ok) throw new Error(`Could not load this concept (${res.status}).`);
      setPanel({ data: await res.json() });
    } catch (err) {
      setPanel({ error: err.message });
    }
  };

  const openLink = async (link) => {
    setSelected({ type: 'link', item: link });
    if (data.mode === 'communities') {
      setPanel({ data: link });
      return;
    }
    setPanel({ loading: true });
    try {
      const rels = (link.relations || []).slice(0, 6);
      const evidence = await Promise.all(rels.map(r =>
        authFetch(`${API}/graph/evidence?rel=${r.rel_id}`).then(res => (res.ok ? res.json() : null))));
      setPanel({ data: { link, evidence: evidence.filter(Boolean) } });
    } catch (err) {
      setPanel({ error: err.message });
    }
  };

  const runSearch = (e) => {
    e.preventDefault();
    const q = search.trim().toLowerCase();
    if (!q) return;
    const hit = graph.nodes.find(n => n.name.toLowerCase() === q) || graph.nodes.find(n => n.name.toLowerCase().includes(q));
    if (!hit) {
      setError(`"${search}" is not on this map (try "Everything" or fewer filters).`);
      return;
    }
    setError('');
    if (graphRef.current && hit.x !== undefined) {
      graphRef.current.centerAt(hit.x, hit.y, 800);
      graphRef.current.zoom(4, 800);
    }
    openNode(hit);
  };

  const toggleBook = (docId) => {
    const all = books.map(b => b.doc_id);
    const current = selectedBooks || all;
    const next = current.includes(docId) ? current.filter(d => d !== docId) : [...current, docId];
    if (next.length === 0) return; // keep at least one book
    setSelectedBooks(next.length === all.length ? null : next);
  };
  const toggleCategory = (c) => setCategories(cs => (cs.includes(c) ? cs.filter(x => x !== c) : [...cs, c]));

  const colorOfFile = (filename) => bookColorAt(Math.max(0, books.findIndex(b => b.filename === filename)));
  const nameOf = (id) => graph.nodes.find(n => n.id === endId(id))?.name || '?';
  const caption = { fontSize: '11px', color: 'var(--text-muted)' };
  const control = {
    fontSize: '12px', padding: '6px 8px', borderRadius: 'var(--radius-sm)', background: 'rgba(0,0,0,0.3)',
    border: '1px solid rgba(255,255,255,0.12)', color: 'var(--text-primary)'
  };

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'var(--bg-base, #05070d)', display: 'flex', flexDirection: 'column' }}>
      {/* Toolbar */}
      <div style={{ padding: '12px 16px', borderBottom: 'var(--pane-border)', display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <h2 style={{ fontSize: '15px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px', marginRight: '8px' }}>
            <MapIcon size={18} /> Knowledge map
          </h2>
          <div style={{ display: 'flex', background: 'rgba(0,0,0,0.3)', borderRadius: 'var(--radius-sm)', padding: '3px' }}>
            {MODES.map(m => (
              <button key={m.id} title={m.hint} onClick={() => { setCommunity(null); setMode(m.id); }} style={{
                fontSize: '12px', padding: '5px 12px', borderRadius: 'var(--radius-sm)', border: 'none', cursor: 'pointer',
                background: !community && mode === m.id ? 'var(--accent-blue)' : 'transparent',
                color: !community && mode === m.id ? '#fff' : 'var(--text-muted)'
              }}>{m.label}</button>
            ))}
          </div>
          {community && (
            <button onClick={() => setCommunity(null)} style={{ ...chip(true), display: 'flex', alignItems: 'center', gap: '4px' }}>
              <ChevronLeft size={12} /> Topic: {community.name}
            </button>
          )}
          <label style={{ ...caption, display: 'flex', alignItems: 'center', gap: '6px' }}>
            Min. passages
            <select value={minSupport} onChange={e => setMinSupport(e.target.value)} style={control}>
              <option value="">default</option>
              {[1, 2, 3, 5].map(v => <option key={v} value={v}>{v}+</option>)}
            </select>
          </label>
          <label style={{ ...caption, display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
            <input type="checkbox" checked={crossBook} onChange={e => setCrossBook(e.target.checked)} /> Only concepts in 2+ books
          </label>
          <label style={{ ...caption, display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
            <input type="checkbox" checked={hideGeneric} onChange={e => setHideGeneric(e.target.checked)} /> Hide generic words
          </label>
          <form onSubmit={runSearch} style={{ display: 'flex', gap: '6px', marginLeft: 'auto' }}>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Find a concept on the map" style={{ ...control, width: '200px' }} />
            <button type="submit" title="Find" style={{ ...control, cursor: 'pointer' }}><Search size={14} /></button>
          </form>
          <button onClick={onClose} aria-label="Close map" style={{ color: 'var(--text-muted)' }}><X size={20} /></button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
          <span style={caption}>Books:</span>
          {books.map((b, i) => (
            <button key={b.doc_id} onClick={() => b.concepts && toggleBook(b.doc_id)} disabled={!b.concepts}
              title={b.concepts ? `${b.filename}: ${b.concepts} concepts` : `${b.filename}: graph not built yet`}
              style={{ ...chip(b.concepts > 0 && (!selectedBooks || selectedBooks.includes(b.doc_id)), bookColorAt(i)), opacity: b.concepts ? 1 : 0.45, cursor: b.concepts ? 'pointer' : 'default' }}>
              {shortBook(b.filename, 30)}{b.concepts ? '' : ' (no graph yet)'}
            </button>
          ))}
          <span style={{ ...caption, marginLeft: '10px' }}>Types:</span>
          {CATEGORIES.map(c => (
            <button key={c} onClick={() => toggleCategory(c)} style={chip(categories.includes(c))}>{c.toLowerCase()}</button>
          ))}
        </div>
        <div style={{ ...caption, display: 'flex', gap: '14px', flexWrap: 'wrap' }}>
          {data && (
            <span>
              {data.stats.shown_concepts} {data.mode === 'communities' ? 'topics' : 'concepts'}, {data.stats.shown_links} links
              {data.stats.truncated ? ` (most central of ${data.stats.matching_concepts} matching)` : ''}
            </span>
          )}
          <span>Node colour = book; several colours = in several books. White line = supported by several books. Thicker = more passages.</span>
          {loading && <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Loader2 size={12} className="loader" /> Loading</span>}
          {error && <span style={{ color: '#ef4444' }}>{error}</span>}
        </div>
      </div>

      {/* Map + side panel */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <div ref={boxRef} style={{ flex: 1, minWidth: 0, position: 'relative' }}>
          {data && data.nodes.length === 0 && !loading && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', fontSize: '13px' }}>
              No concepts match these filters.
            </div>
          )}
          <ForceGraph2D
            ref={graphRef}
            graphData={graph}
            width={size.width}
            height={size.height}
            backgroundColor="rgba(0,0,0,0)"
            nodeId="id"
            nodeLabel={n => `${n.name}${n.category ? ` (${n.category.toLowerCase()})` : ''}`}
            nodeCanvasObject={drawNode}
            nodePointerAreaPaint={paintArea}
            linkColor={linkColor}
            linkWidth={linkWidth}
            linkLabel={l => (l.predicates ? `${nameOf(l.source)} - ${l.predicates.join(', ')} - ${nameOf(l.target)} (${l.support} passage${l.support === 1 ? '' : 's'})` : `${l.pairs} links between topics`)}
            onNodeClick={openNode}
            onLinkClick={openLink}
            onNodeHover={n => setHover(n ? n.id : null)}
            onBackgroundClick={() => { setSelected(null); setPanel(null); }}
            cooldownTicks={200}
            onEngineStop={() => {
              if (fitPending.current && graphRef.current) {
                graphRef.current.zoomToFit(600, 40);
                fitPending.current = false;
              }
            }}
            d3VelocityDecay={0.3}
          />
        </div>

        {selected && (
          <aside style={{ width: '380px', maxWidth: '45vw', borderLeft: 'var(--pane-border)', overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <button onClick={() => { setSelected(null); setPanel(null); }} style={{ alignSelf: 'flex-end', color: 'var(--text-muted)' }} aria-label="Close panel"><X size={16} /></button>
            {panel?.loading && <span style={caption}>Loading...</span>}
            {panel?.error && <span style={{ fontSize: '12px', color: '#ef4444' }}>{panel.error}</span>}

            {/* Topic (communities mode) */}
            {panel?.data && data?.mode === 'communities' && selected.type === 'node' && (
              <>
                <h3 style={{ fontSize: '15px', fontWeight: 600 }}>{panel.data.name}</h3>
                <span style={caption}>{panel.data.size} concepts</span>
                <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>{(panel.data.books || []).map(i => books[i] && <BookTag key={i} book={books[i]} index={i} />)}</div>
                <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{panel.data.summary}</p>
                <span style={caption}>Main concepts: {(panel.data.top_members || []).join(', ')}</span>
                <button onClick={() => setCommunity({ id: panel.data.id, name: panel.data.name })} style={{ ...chip(true), alignSelf: 'flex-start' }}>
                  Explore this topic
                </button>
              </>
            )}
            {panel?.data && data?.mode === 'communities' && selected.type === 'link' && (
              <span style={{ fontSize: '13px' }}>{panel.data.pairs} links between "{nameOf(panel.data.source)}" and "{nameOf(panel.data.target)}".</span>
            )}

            {/* Concept */}
            {panel?.data && data?.mode !== 'communities' && selected.type === 'node' && (
              <>
                <div>
                  <h3 style={{ fontSize: '15px', fontWeight: 600 }}>{panel.data.name}</h3>
                  <span style={caption}>{panel.data.category?.toLowerCase()}{panel.data.community ? ` - topic: ${panel.data.community}` : ''}</span>
                </div>
                {panel.data.description && <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{panel.data.description}</p>}
                <span style={caption}>
                  {panel.data.stats.mentions} passages, {panel.data.stats.links} links ({panel.data.stats.strong_links} backed by 2+ passages), in {panel.data.stats.books} book{panel.data.stats.books === 1 ? '' : 's'}
                </span>
                {panel.data.same_concepts?.length > 0 && (
                  <span style={caption}>Possibly the same as: {panel.data.same_concepts.map(s => `${s.name}${s.status === 'confirmed' ? ' (confirmed)' : ''}`).join(', ')}</span>
                )}
                {panel.data.books.map(b => (
                  <div key={b.filename} style={{ padding: '10px', borderRadius: 'var(--radius-sm)', border: `1px solid ${colorOfFile(b.filename)}55`, display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <BookOpen size={12} color={colorOfFile(b.filename)} /> {b.book}
                    </span>
                    <span style={caption}>{b.mentions} passage{b.mentions === 1 ? '' : 's'}, pages {b.pages.join(', ')}</span>
                    {b.neighbors.length > 0 && (
                      <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                        Linked here to: {b.neighbors.slice(0, 8).map(n => n.name).join(', ')}
                      </span>
                    )}
                    {b.chunks.slice(0, 1).map((c, i) => (
                      <p key={i} style={{ fontSize: '11px', color: 'var(--text-secondary)', fontStyle: 'italic', lineHeight: 1.5 }}>p. {c.page}: {c.text}</p>
                    ))}
                  </div>
                ))}
              </>
            )}

            {/* Link evidence */}
            {panel?.data && data?.mode !== 'communities' && selected.type === 'link' && (
              <>
                <h3 style={{ fontSize: '14px', fontWeight: 600 }}>{nameOf(panel.data.link.source)} - {nameOf(panel.data.link.target)}</h3>
                <span style={caption}>
                  {panel.data.link.support} passage{panel.data.link.support === 1 ? '' : 's'}
                  {panel.data.link.cross_book ? ', from several books' : ''}
                </span>
                {panel.data.evidence.map(ev => (
                  <div key={ev.rel_id} style={{ display: 'flex', flexDirection: 'column', gap: '6px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                    <span style={{ fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                      <strong>{ev.source}</strong>
                      <span style={{ fontFamily: 'monospace', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '3px' }}>
                        {ev.predicate}<ArrowRight size={10} />
                      </span>
                      <strong>{ev.target}</strong>
                    </span>
                    {ev.note && <span style={caption}>{ev.note}</span>}
                    {ev.passages.slice(0, 3).map((p, i) => (
                      <p key={i} style={{ fontSize: '11px', color: 'var(--text-secondary)', fontStyle: 'italic', lineHeight: 1.5 }}>
                        <span style={{ color: colorOfFile(p.filename), fontStyle: 'normal' }}>{p.book}, p. {p.page}:</span> {p.excerpt}
                      </p>
                    ))}
                    {ev.passages.length > 3 && <span style={caption}>+{ev.passages.length - 3} more passages</span>}
                  </div>
                ))}
                {(panel.data.link.relations || []).length > 6 && <span style={caption}>Showing 6 of {panel.data.link.relations.length} relations.</span>}
              </>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
