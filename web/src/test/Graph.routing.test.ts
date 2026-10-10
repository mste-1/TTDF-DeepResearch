import { getSmoothStepPath, Position } from '@xyflow/react';
import { describe, expect, it } from 'vitest';
import { graphLayout } from '../Graph';
import type { StageEdge, StageNode } from '../types';

const stages: StageNode[] = [
  { id: 'brief', label: '研究简报', stage: 'brief', status: 'completed' },
  { id: 'supervisor', label: '研究统筹', stage: 'supervisor', status: 'completed' },
  ...['a', 'b', 'c'].map((id) => ({
    id,
    label: `研究 ${id}`,
    stage: 'research',
    status: 'completed',
    parent_id: 'supervisor',
  })),
];
const edges: StageEdge[] = [
  { id: 'main', source: 'brief', target: 'supervisor', label: '传递成果' },
  ...['a', 'b', 'c'].flatMap((id) => [
    {
      id: `${id}-out`,
      source: 'supervisor',
      target: id,
      label: id === 'c' ? '发起审阅' : '分发主题',
    },
    {
      id: `${id}-back`,
      source: id,
      target: 'supervisor',
      label: id === 'c' ? '返回质疑' : '返回成果',
    },
  ]),
];

// Real smoothstep routing with the custom node's rendered 215px width / maximum 128px height.
function port(position: { x: number; y: number }, handle: string | null | undefined) {
  switch (handle) {
    case 'dispatch-out':
      return { x: position.x + 215, y: position.y + 128 * 0.3, side: Position.Right };
    case 'dispatch-in':
      return { x: position.x, y: position.y + 128 * 0.3, side: Position.Left };
    case 'return-out':
      return { x: position.x, y: position.y + 128 * 0.7, side: Position.Left };
    case 'return-in':
      return { x: position.x + 215, y: position.y + 128 * 0.7, side: Position.Right };
    case 'bottom-out':
      return { x: position.x + 215 / 2, y: position.y + 128, side: Position.Bottom };
    case 'top-in':
      return { x: position.x + 215 / 2, y: position.y, side: Position.Top };
    default:
      throw new Error(`Unconnected handle: ${handle}`);
  }
}
describe('research relationship label routing', () => {
  it('keeps complete reciprocal labels on separated paths without intersecting label backgrounds', () => {
    const layout = graphLayout(stages, edges, []);
    const rectangles = layout.edges.map((edge) => {
      const source = port(
        layout.nodes.find((node) => node.id === edge.source)!.position,
        edge.sourceHandle,
      );
      const target = port(
        layout.nodes.find((node) => node.id === edge.target)!.position,
        edge.targetHandle,
      );
      const [path, x, y] = getSmoothStepPath({
        sourceX: source.x,
        sourceY: source.y,
        sourcePosition: source.side,
        targetX: target.x,
        targetY: target.y,
        targetPosition: target.side,
      });
      expect(path).toContain(`M${source.x} ${source.y}`);
      const original = edges.find((item) => item.id === edge.id)!;
      expect(edge.label).toBe(original.label);
      // 11px CJK text plus the SVG background's horizontal padding; 24px allows vertical padding.
      return { id: edge.id, x, y, width: [...original.label!].length * 11 + 4, height: 24 };
    });
    for (let a = 0; a < rectangles.length; a += 1) {
      for (let b = a + 1; b < rectangles.length; b += 1) {
        const first = rectangles[a],
          second = rectangles[b];
        const intersects =
          Math.abs(first.x - second.x) < (first.width + second.width) / 2 &&
          Math.abs(first.y - second.y) < (first.height + second.height) / 2;
        expect(intersects, `${first.id} overlaps ${second.id}`).toBe(false);
      }
    }
    for (const child of layout.nodes.filter((node) => node.data.stage.parent_id)) {
      expect(
        child.position.x - layout.nodes.find((node) => node.id === 'supervisor')!.position.x,
      ).toBe(320);
    }
  });
  it('retains explicit top/bottom handles for the vertical main flow and preserves all edge endpoints', () => {
    const layout = graphLayout(stages, edges, []);
    expect(layout.edges).toHaveLength(edges.length);
    const main = layout.edges.find((edge) => edge.id === 'main')!;
    expect(main.sourceHandle).toBe('bottom-out');
    expect(main.targetHandle).toBe('top-in');
    for (const edge of layout.edges) {
      expect(edge.source).toBe(edges.find((item) => item.id === edge.id)!.source);
      expect(edge.target).toBe(edges.find((item) => item.id === edge.id)!.target);
    }
  });
});
