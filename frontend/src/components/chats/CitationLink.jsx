import React, { useContext } from 'react';
import CitationContext from '../../lib/citationContext';

/** Markdown link renderer: citation:// links become clickable badges ([Chunk 1], [Graph Entity: X]); others stay links. */
// `node` is taken out only to keep it out of the DOM props spread below.
// eslint-disable-next-line no-unused-vars
export default function CitationLink({ node, href, children, ...props }) {
  const { activeFocus, setActiveFocus, openChunk, openEntity } = useContext(CitationContext);
  if (!href || !href.startsWith('citation://')) {
    return <a href={href} {...props} style={{ color: 'var(--accent-blue)', textDecoration: 'underline' }}>{children}</a>;
  }
  const url = new URL(href);
  const type = url.hostname;
  const id = decodeURIComponent(url.pathname.substring(1));
  const isHovered = activeFocus && activeFocus.type === type && activeFocus.id === id;
  const chunk = type === 'chunk';

  return (
    <span
      className="citation-badge"
      role="button"
      tabIndex={0}
      style={{
        display: 'inline-block', margin: '0 4px', padding: '2px 8px', borderRadius: '12px', fontSize: '0.85em',
        fontWeight: '600', cursor: 'pointer',
        background: chunk
          ? (isHovered ? 'rgba(16, 185, 129, 0.3)' : 'rgba(16, 185, 129, 0.15)')
          : (isHovered ? 'rgba(59, 130, 246, 0.3)' : 'rgba(59, 130, 246, 0.15)'),
        color: chunk ? '#10b981' : '#3b82f6',
        border: `1px solid ${chunk ? '#10b981' : '#3b82f6'}`,
        transition: 'all 0.2s ease',
        transform: isHovered ? 'scale(1.05)' : 'scale(1)',
      }}
      onMouseEnter={() => setActiveFocus({ type, id })}
      onMouseLeave={() => setActiveFocus(null)}
      onClick={() => (chunk ? openChunk(id) : openEntity(id))}
      onKeyDown={(e) => { if (e.key === 'Enter') (chunk ? openChunk(id) : openEntity(id)); }}
    >
      {children}
    </span>
  );
}
