import { act, fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Graph from '../Graph';
import type { StageNode } from '../types';

const mocks = vi.hoisted(() => ({
  fitView: vi.fn().mockResolvedValue(true),
  nodes: [] as { id: string }[],
  viewportReady: true,
}));
vi.mock('@xyflow/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@xyflow/react')>();
  return {
    ...actual,
    useNodes: () => mocks.nodes,
    useNodesInitialized: () => true,
    useReactFlow: () => ({ fitView: mocks.fitView, viewportInitialized: mocks.viewportReady }),
    ReactFlow: ({
      children,
      nodes,
      onMoveStart,
      onNodeClick,
    }: {
      children: ReactNode;
      nodes: { id: string }[];
      onMoveStart: (event: MouseEvent | null) => void;
      onNodeClick: (event: MouseEvent, node: { id: string }) => void;
    }) => {
      mocks.nodes = nodes;
      return (
        <div>
          {children}
          <button onClick={() => onMoveStart(new MouseEvent('mousedown'))}>拖动画布</button>
          <button onClick={() => onMoveStart(null)}>程序视野变化</button>
          <button onClick={() => onNodeClick(new MouseEvent('click'), nodes[0])}>选中节点</button>
        </div>
      );
    },
    Background: () => null,
    Controls: ({ onZoomIn }: { onZoomIn: () => void }) => (
      <button onClick={onZoomIn}>手动缩放</button>
    ),
  };
});
const one: StageNode = {
  id: 'one',
  label: '研究统筹',
  stage: 'supervisor',
  status: 'running',
  iteration: 1,
};
const two: StageNode = {
  id: 'two',
  label: '技术路线',
  stage: 'research',
  status: 'running',
  parent_id: 'one',
  iteration: 1,
};
const props = { edges: [], sources: [], onSelect: vi.fn() };
beforeEach(() => {
  mocks.fitView.mockClear();
  mocks.viewportReady = true;
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }));
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    width: 979,
    height: 560,
  } as DOMRect);
});
afterEach(() => vi.unstubAllGlobals());
describe('following actual research progress', () => {
  it('waits for viewport initialization and records only a successful fit', async () => {
    vi.useFakeTimers();
    mocks.viewportReady = false;
    mocks.fitView.mockResolvedValueOnce(false).mockResolvedValue(true);
    const { rerender } = render(<Graph {...props} stages={[one]} />);
    expect(mocks.fitView).not.toHaveBeenCalled();
    mocks.viewportReady = true;
    rerender(<Graph {...props} stages={[one]} />);
    await act(async () => {});
    expect(screen.getByText('跟随进展 · 等待画布就绪')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(mocks.fitView).toHaveBeenCalledTimes(2);
    expect(screen.getByText('正在跟随进展')).toBeInTheDocument();
    vi.useRealTimers();
  });
  it('fits initial/new-node/round changes but leaves ordinary snapshot updates still', () => {
    const { rerender } = render(<Graph {...props} stages={[one]} />);
    expect(mocks.fitView).toHaveBeenCalledTimes(1);
    rerender(<Graph {...props} stages={[{ ...one, status: 'completed' }]} />);
    expect(mocks.fitView).toHaveBeenCalledTimes(1);
    rerender(<Graph {...props} stages={[one, two]} />);
    expect(mocks.fitView).toHaveBeenCalledTimes(2);
    rerender(<Graph {...props} stages={[{ ...one, iteration: 2 }, two]} />);
    expect(mocks.fitView).toHaveBeenCalledTimes(3);
    expect(mocks.fitView).toHaveBeenLastCalledWith(expect.objectContaining({ duration: 300 }));
  });
  it.each(['拖动画布', '手动缩放', '选中节点'])(
    'pauses after %s and resumes only when asked',
    async (action) => {
      const { rerender } = render(<Graph {...props} stages={[one]} />);
      fireEvent.click(screen.getByRole('button', { name: action }));
      rerender(<Graph {...props} stages={[one, two]} />);
      expect(mocks.fitView).toHaveBeenCalledTimes(1);
      fireEvent.click(screen.getByRole('button', { name: '跟随进展 ↗' }));
      expect(mocks.fitView).toHaveBeenCalledTimes(2);
      await act(async () => {});
      expect(screen.getByText('正在跟随进展')).toBeInTheDocument();
    },
  );
  it('does not mistake programmatic fitting for user movement and respects reduced motion', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }));
    render(<Graph {...props} stages={[one]} />);
    act(() => fireEvent.click(screen.getByRole('button', { name: '程序视野变化' })));
    await act(async () => {});
    expect(screen.getByText('正在跟随进展')).toBeInTheDocument();
    expect(mocks.fitView).toHaveBeenCalledWith(expect.objectContaining({ duration: 0 }));
  });
});
