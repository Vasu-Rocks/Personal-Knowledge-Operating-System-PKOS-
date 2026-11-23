import { createContext } from 'react';

/**
 * What a citation badge in an answer needs from the chat view: the highlighted citation, and what to do when one is
 * hovered or tapped. Passed by context so the Markdown renderer can be one stable component: a renderer recreated on
 * every render is remounted by react-markdown, and a tap (hover + click in one go on a phone) then hits a removed badge.
 */
const CitationContext = createContext({
  activeFocus: null, setActiveFocus: () => {}, openChunk: () => {}, openEntity: () => {},
});

export default CitationContext;
