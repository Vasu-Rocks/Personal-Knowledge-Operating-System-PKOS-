import React, { useMemo, useState } from 'react';
import { X, FileText, MessagesSquare, Brain, Share2, Layers } from 'lucide-react';
import ForceGraph2D from 'react-force-graph-2d';
import { matchPercent, prepareGraph } from '../../lib/chatView';

function where(src) {
  if (src.via === 'community') return 'Topic summary';
  return src.page ? `${src.filename} · page ${src.page}` : src.filename;
}

/**
 * What an answer was based on: the passages (with file, page and how well they match), an earlier chat if one was
 * used, the saved memories given to the model, and - only when asked for - the concept connections.
 */
export default function SourcesPanel({ message, activeFocus, setActiveFocus, onClose, onOpenChat, busy, width = 380 }) {
  const [showGraph, setShowGraph] = useState(false);
  const sources = (message && message.sources) || [];
  const memories = (message && message.memories) || [];
  const graph = useMemo(
    () => (message && message.graph && message.graph.links && message.graph.links.length
      ? prepareGraph(JSON.parse(JSON.stringify(message.graph))) : null),
    [message],
  );
  const focused = (n) => activeFocus && activeFocus.type === 'chunk' && activeFocus.id === String(n);

  return (
    <aside className="app-drawer" aria-label="Sources">
      <div className="drawer-header">
        <span style={{ fontWeight: 600, fontSize: '15px' }}>Sources</span>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close sources"><X size={18} /></button>
      </div>

      <div className="drawer-body">
        {!message ? (
          <p className="muted-text">Click "Sources" under an answer to see what it was based on.</p>
        ) : (
          <>
            {sources.length === 0 && memories.length === 0 && (
              <p className="muted-text">No passages were used for this answer.</p>
            )}

            {sources.length > 0 && (
              <section>
                <h4 className="drawer-section">Passages ({sources.length})</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {sources.map((src, idx) => {
                    const n = idx + 1;
                    const match = matchPercent(src.distance);
                    if (src.via === 'chat') {
                      return (
                        <div key={idx} id={`source-card-${n}`} className={`source-card${focused(n) ? ' focused' : ''}`} data-testid="past-chat-source">
                          <div className="source-head">
                            <MessagesSquare size={14} color="#c4b5fd" style={{ flexShrink: 0 }} />
                            <span className="source-name" title={src.filename}>Earlier chat: {src.filename}</span>
                            <span className="muted-text">{src.page}</span>
                          </div>
                          <div className="source-text">{src.text}</div>
                          <button type="button" className="link-btn" disabled={busy}
                            onClick={() => onOpenChat(src.conversation_id)} aria-label={`Open the chat ${src.filename}`}>
                            Open chat
                          </button>
                        </div>
                      );
                    }
                    return (
                      <div key={idx} id={`source-card-${n}`} className={`source-card${focused(n) ? ' focused' : ''}`}
                        data-testid="source-card">
                        <div className="source-head">
                          <span className="source-num">{n}</span>
                          {src.via === 'community' ? <Layers size={14} style={{ flexShrink: 0 }} /> : <FileText size={14} style={{ flexShrink: 0 }} />}
                          <span className="source-name" title={where(src)}>{where(src)}</span>
                          {match !== null && <span className="source-match">Match {match}%</span>}
                        </div>
                        <div className="source-text">{src.text}</div>
                        {src.via === 'graph' && <div className="muted-text" style={{ fontSize: '11px' }}>Found through connected concepts</div>}
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {memories.length > 0 && (
              <section data-testid="memories-used">
                <h4 className="drawer-section">Memories used ({memories.length})</h4>
                <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {memories.map((m) => (
                    <li key={m.memory_id} className="memory-used">
                      <Brain size={13} color="#c4b5fd" style={{ flexShrink: 0, marginTop: '3px' }} />
                      <span style={{ flex: 1 }}>{m.text}</span>
                      <span className="memory-kind">{m.kind === 'preference' ? 'how to answer' : m.kind}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {graph && (
              <section>
                <button type="button" className="link-btn" onClick={() => setShowGraph((s) => !s)} aria-expanded={showGraph}>
                  <Share2 size={14} /> {showGraph ? 'Hide connections' : `Show connections (${graph.nodes.length} concepts)`}
                </button>
                {showGraph && (
                  <div className="graph-box" data-testid="answer-graph">
                    <ForceGraph2D
                      graphData={graph}
                      width={Math.max(220, Math.min(width, window.innerWidth) - 40)}
                      height={280}
                      nodeLabel="name"
                      nodeAutoColorBy="category"
                      nodeColor={(node) => {
                        if (!activeFocus || activeFocus.type !== 'entity') return undefined;
                        const name = node.name.replace('⭐ ', '');
                        if (name === activeFocus.id) return '#3b82f6';
                        const focus = graph.nodes.find((x) => x.name.replace('⭐ ', '') === activeFocus.id);
                        return focus && node.neighbors && node.neighbors.has(focus.id) ? '#93c5fd' : 'rgba(255,255,255,0.08)';
                      }}
                      onNodeHover={(node) => setActiveFocus(node ? { type: 'entity', id: node.name.replace('⭐ ', '') } : null)}
                      linkColor={() => 'rgba(255,255,255,0.25)'}
                      linkDirectionalArrowLength={3.5}
                      linkDirectionalArrowRelPos={1}
                      linkCurvature={0.2}
                      linkLabel={(link) => `${link.predicate}: ${link.description}`}
                      backgroundColor="transparent"
                    />
                  </div>
                )}
              </section>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
