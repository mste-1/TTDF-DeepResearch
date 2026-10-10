import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, api, errorText } from './api';
import { isTerminal } from './format';
import type { ResearchRun, RunEvent } from './types';

export type Connection = 'connecting' | 'live' | 'reconnecting' | 'closed';
export function eventSequence(event: MessageEvent) {
  const id = Number(event.lastEventId);
  if (event.lastEventId && Number.isSafeInteger(id) && id >= 0) return id;
  try {
    const seq = JSON.parse(event.data).seq;
    return Number.isSafeInteger(seq) && seq >= 0 ? (seq as number) : null;
  } catch {
    return null;
  }
}

function mergeEvents(previous: RunEvent[], incoming: RunEvent[]) {
  const unique = new Map(previous.map((event) => [event.seq, event]));
  for (const event of incoming) unique.set(event.seq, event);
  return [...unique.values()].sort((a, b) => a.seq - b.seq);
}

export function useRun(id: string) {
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [error, setError] = useState('');
  const [connection, setConnection] = useState<Connection>('connecting');
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [historyError, setHistoryError] = useState('');
  const [historyLoading, setHistoryLoading] = useState(false);
  const [hasEarlier, setHasEarlier] = useState(false);
  const refreshRef = useRef<() => void>(() => {});
  const historyRef = useRef<() => void>(() => {});
  const refresh = useCallback(() => refreshRef.current(), []);
  const loadEarlier = useCallback(() => historyRef.current(), []);
  useEffect(() => {
    let disposed = false;
    let source: EventSource | null = null;
    let controller: AbortController | null = null;
    let lastSeq = 0;
    let terminal = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let busy = false;
    let pending = false;
    let historyStarted = false;
    let historyReady = false;
    let historyBusy = false;
    let historyAvailable = false;
    let earliestAfter = 0;
    setRun(null);
    setError('');
    setEvents([]);
    setHistoryError('');
    setHistoryLoading(false);
    setHasEarlier(false);
    setConnection('connecting');
    const historyController = new AbortController();

    async function historyPage(after: number) {
      if (disposed || historyBusy || !historyAvailable) return;
      historyBusy = true;
      setHistoryLoading(true);
      setHistoryError('');
      try {
        const result = await api.history(id, after, historyController.signal);
        if (disposed) return;
        setEvents((previous) => mergeEvents(previous, result.items));
        earliestAfter = after;
        historyReady = true;
        setHasEarlier(after > 0);
      } catch (error) {
        if (disposed || historyController.signal.aborted) return;
        if (error instanceof ApiError && error.status === 410) {
          historyAvailable = false;
          setHasEarlier(false);
          setRun((previous) => (previous ? { ...previous, history_available: false } : previous));
        } else setHistoryError(errorText(error));
      } finally {
        historyBusy = false;
        if (!disposed) setHistoryLoading(false);
      }
    }
    historyRef.current = () => {
      // The API reads forward after a sequence; request the preceding 100-sequence window.
      // Its overlap with the visible recent page is merged by seq, so no backend change is needed.
      void historyPage(historyReady ? Math.max(0, earliestAfter - 100) : earliestAfter);
    };

    async function load() {
      if (disposed) return;
      if (busy) {
        pending = true;
        return;
      }
      busy = true;
      controller = new AbortController();
      try {
        const data = await api.run(id, controller.signal);
        if (disposed) return;
        setRun(data);
        setError('');
        historyAvailable = data.history_available;
        if (!historyAvailable) setHasEarlier(false);
        if (!historyStarted && historyAvailable) {
          historyStarted = true;
          earliestAfter = Math.max(0, (data.last_event_seq ?? 0) - 100);
          void historyPage(earliestAfter);
        }
        terminal = isTerminal(data.status);
        if (terminal) {
          source?.close();
          source = null;
          setConnection('closed');
        } else if (!source) subscribe(data.last_event_seq ?? 0);
      } catch (error) {
        if (!disposed && !(error instanceof DOMException && error.name === 'AbortError')) {
          setError(errorText(error));
          setConnection('reconnecting');
        }
      } finally {
        busy = false;
        if (pending && !disposed) {
          pending = false;
          void load();
        }
      }
    }
    function subscribe(after: number) {
      if (typeof EventSource === 'undefined') {
        setConnection('reconnecting');
        return;
      }
      lastSeq = Math.max(lastSeq, after);
      source = new EventSource(
        `/api/v1/research-runs/${encodeURIComponent(id)}/events?after=${lastSeq}`,
        { withCredentials: true },
      );
      source.onopen = () => {
        if (!disposed) setConnection('live');
      };
      source.onerror = () => {
        if (!disposed) setConnection('reconnecting');
      };
      source.onmessage = (event) => {
        const seq = eventSequence(event);
        if (seq === null || seq <= lastSeq || disposed) return;
        lastSeq = seq;
        try {
          const data = JSON.parse(event.data) as RunEvent;
          setEvents((previous) => mergeEvents(previous, [{ ...data, seq }]));
        } catch {
          return;
        }
        // Native EventSource keeps Last-Event-ID on reconnect. Refresh only the durable snapshot.
        if (!timer)
          timer = setTimeout(() => {
            timer = undefined;
            void load();
          }, 250);
      };
      source.addEventListener('history_truncated', () => {
        source?.close();
        source = null;
        void load();
      });
      source.addEventListener('stream_error', () => {
        source?.close();
        source = null;
        setConnection('reconnecting');
        void load();
      });
    }
    refreshRef.current = () => {
      void load();
    };
    void load();
    // A read-only fallback also covers dropped terminal notifications and suspended tabs.
    const poll = setInterval(() => {
      if (!terminal) void load();
    }, 5000);
    const visible = () => {
      if (document.visibilityState === 'visible' && !terminal) void load();
    };
    document.addEventListener('visibilitychange', visible);
    return () => {
      disposed = true;
      source?.close();
      controller?.abort();
      historyController.abort();
      clearTimeout(timer);
      clearInterval(poll);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [id]);
  return {
    run,
    error,
    connection,
    events,
    historyError,
    historyLoading,
    hasEarlier,
    loadEarlier,
    refresh,
  };
}
