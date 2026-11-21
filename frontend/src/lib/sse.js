// Server-Sent Events over fetch (EventSource cannot send an Authorization header or a POST body).

/**
 * Splits a growing text buffer into complete SSE frames. Returns [payloads, rest]: the `data:` payloads of
 * every complete frame, and the unfinished tail to keep for the next chunk.
 */
export function splitFrames(buffer) {
  const parts = buffer.split('\n\n');
  const rest = parts.pop();
  const payloads = [];
  for (const part of parts) {
    for (const line of part.split('\n')) {
      if (line.startsWith('data: ')) payloads.push(line.slice(6).trim());
    }
  }
  return [payloads, rest];
}

/**
 * Reads an SSE response to the end, calling onData(payloadString) for each `data:` line.
 * Stops at a `[DONE]` payload. A final frame without the trailing blank line is still delivered.
 */
export async function readSSE(response, onData) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const [payloads, rest] = splitFrames(buffer);
    buffer = rest;
    for (const payload of payloads) {
      if (payload === '[DONE]') {
        reader.cancel().catch(() => {});
        return;
      }
      onData(payload);
    }
  }
  const [payloads] = splitFrames(`${buffer}\n\n`);
  for (const payload of payloads) if (payload !== '[DONE]') onData(payload);
}
