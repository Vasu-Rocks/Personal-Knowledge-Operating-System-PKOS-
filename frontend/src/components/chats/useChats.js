import { useCallback, useState } from 'react';
import { deleteConversation, listConversations, renameConversation } from '../../lib/conversationsApi';

/** The chat list: newest activity first, paged, kept in step with the chat being used. */
export default function useChats(authFetch) {
  const [chats, setChats] = useState([]);
  const [nextBefore, setNextBefore] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listConversations(authFetch);
      setChats(data.conversations || []);
      setNextBefore(data.next_before || null);
      setError('');
    } catch (err) {
      setError(err.message || 'Could not load your chats.');
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  const loadMore = useCallback(async () => {
    if (!nextBefore) return;
    try {
      const data = await listConversations(authFetch, nextBefore);
      setChats((prev) => [...prev, ...(data.conversations || []).filter((c) => !prev.some((p) => p.conversation_id === c.conversation_id))]);
      setNextBefore(data.next_before || null);
    } catch (err) {
      setError(err.message || 'Could not load more chats.');
    }
  }, [authFetch, nextBefore]);

  /** A chat just used: moved (or added) to the top with its latest title. */
  const touch = useCallback((conversationId, title) => {
    setChats((prev) => {
      const old = prev.find((c) => c.conversation_id === conversationId);
      const chat = { ...(old || { conversation_id: conversationId, message_count: 0 }), title: title || old?.title || 'New chat',
        updated_at: new Date().toISOString() };
      return [chat, ...prev.filter((c) => c.conversation_id !== conversationId)];
    });
  }, []);

  const rename = useCallback(async (conversationId, title) => {
    const updated = await renameConversation(authFetch, conversationId, title);
    setChats((prev) => prev.map((c) => (c.conversation_id === conversationId ? { ...c, title: updated.title } : c)));
  }, [authFetch]);

  const remove = useCallback(async (conversationId) => {
    await deleteConversation(authFetch, conversationId);
    setChats((prev) => prev.filter((c) => c.conversation_id !== conversationId));
  }, [authFetch]);

  return { chats, loading, error, hasMore: Boolean(nextBefore), refresh, loadMore, touch, rename, remove };
}
