import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Graph, { graphLayout } from '../Graph';
import type { StageNode } from '../types';

// React Flow, its controlled-node store, its resize handling and d3 viewport all run for real.
// JSDOM has no layout engine, so only the browser geometry/ResizeObserver APIs are supplied here.
let visible = false;
let canvasWidth = 979;
const canvasHeight = 560;
class LayoutObserver {
  static all = new Set<LayoutObserver>();
  targets = new Set<Element>();
  constructor(private callback: ResizeObserverCallback) {
    LayoutObserver.all.add(this);
  }
  observe(target: Element) {
    this.targets.add(target);
  }
  unobserve(target: Element) {
    this.targets.delete(target);
  }
  disconnect() {
    this.targets.clear();
    LayoutObserver.all.delete(this);
  }
  flush() {
    const entries = [...this.targets].map((target) => ({
      target,
      contentRect: target.getBoundingClientRect(),
    }));
    if (entries.length)
      this.callback(entries as ResizeObserverEntry[], this as unknown as ResizeObserver);
  }
}
function size(element: HTMLElement) {
  if (!visible) return { width: 0, height: 0 };
  if (element.classList.contains('react-flow__handle')) return { width: 4, height: 4 };
  if (element.classList.contains('react-flow__node')) return { width: 215, height: 128 };
  return { width: canvasWidth, height: canvasHeight };
}
beforeEach(() => {
  visible = false;
  canvasWidth = 979;
  LayoutObserver.all.clear();
  vi.stubGlobal('ResizeObserver', LayoutObserver);
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }));
  vi.stubGlobal(
    'DOMMatrixReadOnly',
    class {
      m22 = 1;
      constructor(transform: string) {
        this.m22 = Number(/scale\(([^)]+)\)/.exec(transform)?.[1] ?? 1);
      }
    },
  );
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(function (
    this: HTMLElement,
  ) {
    return size(this).width;
  });
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (
    this: HTMLElement,
  ) {
    return size(this).height;
  });
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    return DOMRect.fromRect({ x: 0, y: 0, ...size(this) });
  });
  Object.defineProperty(HTMLElement.prototype, 'checkVisibility', {
    configurable: true,
    value: () => visible,
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  delete (HTMLElement.prototype as unknown as { checkVisibility?: unknown }).checkVisibility;
});

async function measure() {
  // DOM measurement and controlled dimensions updates can require a second observer cycle.
  for (let index = 0; index < 3; index += 1) {
    await act(async () => {
      for (const observer of [...LayoutObserver.all]) observer.flush();
      await new Promise((resolve) => setTimeout(resolve, 25));
    });
  }
}
function viewport(container: HTMLElement) {
  const transform = (container.querySelector('.react-flow__viewport') as HTMLElement).style
    .transform;
  const match = /translate\(([-\d.e]+)px,([-\d.e]+)px\) scale\(([-\d.e]+)\)/.exec(transform);
  if (!match) throw new Error(`Unexpected viewport transform: ${transform}`);
  return { x: Number(match[1]), y: Number(match[2]), zoom: Number(match[3]), transform };
}
const stages: StageNode[] = [
  { id: 'brief', label: '简报', stage: 'brief', status: 'completed' },
  { id: 'supervisor', label: '研究统筹', stage: 'supervisor', status: 'running' },
  { id: 'r1', parent_id: 'supervisor', label: '路线一', stage: 'research', status: 'running' },
  { id: 'r2', parent_id: 'supervisor', label: '路线二', stage: 'research', status: 'running' },
  { id: 'revise', parent_id: 'r1', label: '草稿修订', stage: 'refine', status: 'running' },
  { id: 'review', parent_id: 'revise', label: '质疑', stage: 'red_team', status: 'running' },
];
describe('real React Flow measurement lifecycle', () => {
  it('retains measured controlled-node sizes and fits after a hidden mobile canvas becomes visible', async () => {
    const { container } = render(
      <Graph stages={stages} edges={[]} sources={[]} onSelect={() => {}} />,
    );
    await measure();
    expect(viewport(container).transform).toBe('translate(0px,0px) scale(1)');
    visible = true;
    await measure();
    await waitFor(() => expect(screen.getByText('正在跟随进展')).toBeInTheDocument());
    const actual = viewport(container);
    expect(actual.zoom).toBeLessThan(1);
    const layout = graphLayout(stages, [], []);
    for (const node of layout.nodes) {
      expect(actual.x + node.position.x * actual.zoom).toBeGreaterThanOrEqual(0);
      expect(actual.x + (node.position.x + 215) * actual.zoom).toBeLessThanOrEqual(canvasWidth);
      expect(actual.y + (node.position.y + 128) * actual.zoom).toBeLessThanOrEqual(canvasHeight);
    }
    canvasWidth = 600;
    await measure();
    await waitFor(() => expect(viewport(container).transform).not.toBe(actual.transform));
    const narrower = viewport(container);
    for (const node of layout.nodes)
      expect(narrower.x + (node.position.x + 215) * narrower.zoom).toBeLessThanOrEqual(canvasWidth);
  });
  it('keeps the user-selected view across size changes until following is restored', async () => {
    visible = true;
    const { container } = render(
      <Graph stages={stages} edges={[]} sources={[]} onSelect={() => {}} />,
    );
    await measure();
    await screen.findByText('正在跟随进展');
    fireEvent.click(screen.getByText('路线一'));
    const manual = viewport(container).transform;
    canvasWidth = 600;
    await measure();
    expect(viewport(container).transform).toBe(manual);
    fireEvent.click(screen.getByRole('button', { name: '跟随进展 ↗' }));
    await measure();
    await waitFor(() => expect(viewport(container).transform).not.toBe(manual));
  });
});
