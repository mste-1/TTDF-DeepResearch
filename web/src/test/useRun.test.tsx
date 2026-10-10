import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from '../api';
import type { ResearchRun, RunEvent } from '../types';
import { useRun } from '../useRun';
import { Inspector } from '../Workbench';

class FakeStream {
  static all: FakeStream[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  addEventListener = vi.fn();
  constructor(public url: string) {
    FakeStream.all.push(this);
  }
  emit(seq: number) {
    this.onmessage?.({
      lastEventId: String(seq),
      data: JSON.stringify({ seq, type: 'stage.started' }),
    } as MessageEvent);
  }
}
const run: ResearchRun = {
  id: 'one',
  user_id: 'u',
  topic: '研究主题',
  instructions: '',
  status: 'running',
  created_at: '2026-10-10T00:00:00Z',
  has_warnings: false,
  history_available: true,
  last_event_seq: 4,
  snapshot: { nodes: [], edges: [] },
  sources: [],
  artifacts: [],
};
function page(after: number, last = 350) {
  return {
    items: Array.from({ length: Math.min(100, last - after) }, (_, index) => ({
      seq: after + index + 1,
      type: 'stage.completed',
      agent_instance_id: after + index + 1 === 1 ? 'brief' : 'later',
      payload: { label: after + index + 1 === 1 ? '已生成研究简报' : '其他阶段' },
    })),
    history_available: true,
  };
}
beforeEach(() => {
  vi.useFakeTimers();
  FakeStream.all = [];
  vi.stubGlobal('EventSource', FakeStream);
  vi.spyOn(api, 'history').mockResolvedValue({ items: [], history_available: true });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
describe('durable event subscription', () => {
  it('loads only the recent page initially, pages backward without duplicates, and retains older rows on SSE', async () => {
    vi.spyOn(api, 'run').mockResolvedValue({ ...run, last_event_seq: 350 });
    const history = vi
      .mocked(api.history)
      .mockImplementation(async (_id, after = 0) => page(after));
    const { result, unmount } = renderHook(() => useRun('one'));
    await act(async () => {});
    expect(result.current.events).toHaveLength(100);
    expect(history).toHaveBeenCalledTimes(1);
    expect(result.current.hasEarlier).toBe(true);
    await act(async () => result.current.loadEarlier());
    await act(async () => result.current.loadEarlier());
    await act(async () => result.current.loadEarlier());
    expect(history.mock.calls.map((call) => call[1])).toEqual([250, 150, 50, 0]);
    expect(result.current.events).toHaveLength(350);
    expect(new Set(result.current.events.map((event) => event.seq)).size).toBe(350);
    expect(result.current.hasEarlier).toBe(false);
    act(() => FakeStream.all[0].emit(351));
    expect(result.current.events).toHaveLength(351);
    expect(result.current.events[0].seq).toBe(1);
    unmount();
  });
  it('reveals an old selected node activity through the earlier-history button', async () => {
    vi.spyOn(api, 'run').mockResolvedValue({ ...run, last_event_seq: 159 });
    vi.mocked(api.history).mockImplementation(async (_id, after = 0) => page(after, 159));
    function NodeDetails() {
      const state = useRun('one');
      return state.run ? (
        <Inspector
          run={state.run}
          node={{ id: 'brief', label: '研究简报', stage: 'brief', status: 'completed' }}
          events={state.events}
          historyError={state.historyError}
          historyLoading={state.historyLoading}
          hasEarlier={state.hasEarlier}
          loadEarlier={state.loadEarlier}
          onOpen={() => {}}
        />
      ) : null;
    }
    const { unmount } = render(<NodeDetails />);
    await act(async () => {});
    fireEvent.click(screen.getByRole('tab', { name: '活动' }));
    expect(screen.getByText('此节点暂无已载入活动')).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: '加载更早活动' })));
    expect(screen.getByText('完成：已生成研究简报')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '加载更早活动' })).toBeNull();
    unmount();
  });
  it('keeps failed earlier pages retryable and handles expired history explicitly', async () => {
    vi.spyOn(api, 'run').mockResolvedValue({ ...run, last_event_seq: 159 });
    const history = vi
      .mocked(api.history)
      .mockResolvedValueOnce(page(59, 159))
      .mockRejectedValueOnce(new Error('读取历史失败'))
      .mockResolvedValueOnce(page(0, 159));
    const { result, unmount } = renderHook(() => useRun('one'));
    await act(async () => {});
    await act(async () => result.current.loadEarlier());
    expect(result.current.historyError).toBe('读取历史失败');
    expect(result.current.events).toHaveLength(100);
    await act(async () => result.current.loadEarlier());
    expect(result.current.historyError).toBe('');
    expect(result.current.events).toHaveLength(159);
    expect(history.mock.calls.map((call) => call[1])).toEqual([59, 0, 0]);
    history.mockRejectedValueOnce(new ApiError(410, 'HISTORY_EXPIRED', '已过期'));
    await act(async () => result.current.loadEarlier());
    expect(result.current.run?.history_available).toBe(false);
    expect(result.current.hasEarlier).toBe(false);
    unmount();
  });
  it('aborts an earlier-history request when changing tasks and ignores its late response', async () => {
    vi.spyOn(api, 'run').mockImplementation(async (id) => ({
      ...run,
      id,
      last_event_seq: id === 'one' ? 159 : 4,
    }));
    let resolveOld: (value: { items: RunEvent[]; history_available: boolean }) => void = () => {};
    const history = vi
      .mocked(api.history)
      .mockResolvedValueOnce(page(59, 159))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveOld = resolve;
          }),
      )
      .mockResolvedValue({ items: [], history_available: true });
    const { result, rerender, unmount } = renderHook(({ id }) => useRun(id), {
      initialProps: { id: 'one' },
    });
    await act(async () => {});
    act(() => result.current.loadEarlier());
    const oldSignal = history.mock.calls[1][2]!;
    rerender({ id: 'two' });
    await act(async () => {});
    expect(oldSignal.aborted).toBe(true);
    await act(async () => resolveOld(page(0, 159)));
    expect(result.current.run?.id).toBe('two');
    expect(result.current.events).toEqual([]);
    unmount();
  });
  it('subscribes after the snapshot cursor, deduplicates events, and closes on terminal state', async () => {
    const load = vi.spyOn(api, 'run').mockResolvedValue(run);
    const { result, unmount } = renderHook(() => useRun('one'));
    await act(async () => {});
    const stream = FakeStream.all[0];
    expect(stream.url).toBe('/api/v1/research-runs/one/events?after=4');
    act(() => {
      stream.onopen?.();
      stream.emit(4);
      stream.emit(5);
      stream.emit(5);
    });
    expect(result.current.events.map((event) => event.seq)).toEqual([5]);
    load.mockResolvedValue({ ...run, status: 'completed', last_event_seq: 5 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(load).toHaveBeenCalledTimes(2);
    expect(stream.close).toHaveBeenCalled();
    expect(result.current.connection).toBe('closed');
    unmount();
  });
  it('keeps the last snapshot while disconnected and polls without creating or cancelling work', async () => {
    const load = vi.spyOn(api, 'run').mockResolvedValue(run);
    const create = vi.spyOn(api, 'create');
    const cancel = vi.spyOn(api, 'cancel');
    const { result, unmount } = renderHook(() => useRun('one'));
    await act(async () => {});
    act(() => FakeStream.all[0].onerror?.());
    expect(result.current.connection).toBe('reconnecting');
    expect(result.current.run?.topic).toBe('研究主题');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(load).toHaveBeenCalledTimes(2);
    expect(create).not.toHaveBeenCalled();
    expect(cancel).not.toHaveBeenCalled();
    unmount();
  });
  it('closes the old subscription and clears old artifacts when switching runs', async () => {
    vi.spyOn(api, 'run').mockImplementation(async (id) => ({ ...run, id, topic: id }));
    const { result, rerender, unmount } = renderHook(({ id }) => useRun(id), {
      initialProps: { id: 'one' },
    });
    await act(async () => {});
    const old = FakeStream.all[0];
    act(() => old.emit(5));
    rerender({ id: 'two' });
    await act(async () => {});
    expect(old.close).toHaveBeenCalled();
    expect(result.current.run?.id).toBe('two');
    expect(result.current.events).toEqual([]);
    expect(FakeStream.all[1].url).toContain('/two/');
    unmount();
  });
});
