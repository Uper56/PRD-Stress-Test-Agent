/** SSE hook — fetch + ReadableStream parser with reconnect support.

   Emits parsed events ({id, event, data}). On connection loss it waits
   `reconnectMs` and reconnects, sending Last-Event-ID so the server
   replays anything missed while the pipe was down.
*/

import { useEffect, useRef } from 'react';

export interface SSEEvent {
  id: number;
  event: string;
  data: Record<string, unknown>;
}

export interface UseSSEOptions {
  onEvent: (ev: SSEEvent) => void;
  onError?: (err: Error) => void;
  onClose?: () => void;
  reconnectMs?: number | null; // null = never reconnect
}

export interface SSEHandle {
  close: () => void;
}

/** Parse one SSE block ("id:/event:/data: lines, no trailing blank line). */
export function parseSSEBlock(block: string): SSEEvent | null {
  let id = 0;
  let event = '';
  const dataLines: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('id:')) id = Number(line.slice(3).trim()) || 0;
    else if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (!event) return null;
  let data: Record<string, unknown> = {};
  if (dataLines.length) {
    try {
      data = JSON.parse(dataLines.join('\n'));
    } catch {
      data = { raw: dataLines.join('\n') };
    }
  }
  return { id, event, data };
}

export function useSSE(
  url: string | null,
  { onEvent, onError, onClose, reconnectMs = 3000 }: UseSSEOptions,
): SSEHandle {
  const abortRef = useRef<AbortController | null>(null);
  const callbacksRef = useRef({ onEvent, onError, onClose, reconnectMs });
  callbacksRef.current = { onEvent, onError, onClose, reconnectMs };

  useEffect(() => {
    if (!url) return;
    const cbs = () => callbacksRef.current;
    let stopped = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = async (lastId: number) => {
      if (stopped) return;
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const headers: Record<string, string> = { Accept: 'text/event-stream' };
        if (lastId > 0) headers['Last-Event-ID'] = String(lastId);
        const resp = await fetch(url, { headers, signal: controller.signal });
        if (!resp.ok || !resp.body) {
          throw new Error(`SSE ${resp.status}`);
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let maxId = lastId;
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let sep: number;
          while ((sep = buffer.indexOf('\n\n')) !== -1) {
            const block = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            const ev = parseSSEBlock(block);
            if (ev) {
              maxId = Math.max(maxId, ev.id);
              cbs().onEvent(ev);
            }
          }
        }
        if (!stopped) cbs().onClose?.();
        scheduleReconnect(maxId);
      } catch (err) {
        if (stopped) return;
        if (err instanceof Error && err.name !== 'AbortError') cbs().onError?.(err);
        scheduleReconnect(lastId);
      }
    };

    const scheduleReconnect = (lastId: number) => {
      const ms = cbs().reconnectMs;
      if (stopped || ms === null || ms === undefined) return;
      retryTimer = setTimeout(() => void connect(lastId), ms);
    };

    void connect(0);

    return () => {
      stopped = true;
      abortRef.current?.abort();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [url]);

  return { close: () => abortRef.current?.abort() };
}
