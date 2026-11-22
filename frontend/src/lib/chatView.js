// Helpers for the chat view and the chat list (kept out of component files for fast refresh).

export const EMPTY_GRAPH = { nodes: [], links: [] };

/** Adds neighbour sets and seed styling the force graph needs (mutates and returns the graph). */
export function prepareGraph(gData) {
  const graph = gData || EMPTY_GRAPH;
  const neighborMap = new Map();
  graph.links.forEach((l) => {
    const src = typeof l.source === 'object' ? l.source.id : l.source;
    const tgt = typeof l.target === 'object' ? l.target.id : l.target;
    if (!neighborMap.has(src)) neighborMap.set(src, new Set());
    if (!neighborMap.has(tgt)) neighborMap.set(tgt, new Set());
    neighborMap.get(src).add(tgt);
    neighborMap.get(tgt).add(src);
  });
  graph.nodes.forEach((n) => {
    n.neighbors = neighborMap.get(n.id) || new Set();
    if (n.isPrimarySeed) {
      n.fx = 0;
      n.fy = 0;
      if (!String(n.name).startsWith('⭐ ')) n.name = `⭐ ${n.name}`;
      n.val = 5; // Make it significantly larger than surrounding nodes
    } else {
      n.val = 1;
    }
  });
  return graph;
}

/** Stored chat messages -> the message list the chat view renders. */
export function toUiMessages(messages) {
  return messages.map((m) => (m.role === 'user'
    ? {
      id: m.message_id, type: 'user', text: m.content, sources: [],
      searched: m.needs_search !== false && m.standalone_query && m.standalone_query !== m.content ? m.standalone_query : null,
      reused: m.needs_search === false,
    }
    : {
      id: m.message_id, type: 'ai', sources: m.sources || [],
      text: m.content + (m.status === 'partial' ? '\n\n*(This answer was interrupted.)*' : ''),
    }));
}

/** "14:05" today, "Yesterday", "12 Mar", "12 Mar 2025". */
export function shortDate(iso, now = new Date()) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86400000);
  if (diff === 0) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  if (diff === 1) return 'Yesterday';
  return d.toLocaleDateString([], d.getFullYear() === now.getFullYear()
    ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' });
}
