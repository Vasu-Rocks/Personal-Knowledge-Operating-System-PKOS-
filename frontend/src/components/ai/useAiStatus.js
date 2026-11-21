import { useCallback, useEffect, useState } from 'react';
import { getLlmStatus, getSystemStatus } from '../../lib/llmApi';

const POLL_MS = 15000;

/** AI readiness (/llm/status) and system status (/system/status), refreshed every 15 s and on demand. */
export default function useAiStatus(authFetch) {
  const [llm, setLlm] = useState(null);
  const [system, setSystem] = useState(null);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [l, s] = await Promise.all([getLlmStatus(authFetch), getSystemStatus(authFetch)]);
      setLlm(l);
      setSystem(s);
      setError('');
      return l;
    } catch (e) {
      setError(e.message || 'PKOS engine is not reachable.');
      return null;
    }
  }, [authFetch]);

  useEffect(() => {
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  return { llm, system, error, refresh };
}
