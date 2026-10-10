import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  useNodes,
  useNodesInitialized,
  useReactFlow,
  type NodeProps,
  type Node,
  type Edge,
  type NodeChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { nodeStatus, stageName } from './format';
import type { Source, StageEdge, StageNode } from './types';

type ResearchNode = Node<{ stage: StageNode; sources: number }, 'research'>;
function StageCard({ data, selected }: NodeProps<ResearchNode>) {
  const { stage } = data;
  return (
    <div className={`graph-node node-${stage.status} ${selected ? 'is-selected' : ''}`}>
      <Handle id="top-in" type="target" position={Position.Top} />
      <Handle id="dispatch-in" type="target" position={Position.Left} style={{ top: '30%' }} />
      <Handle id="dispatch-out" type="source" position={Position.Right} style={{ top: '30%' }} />
      <Handle id="return-out" type="source" position={Position.Left} style={{ top: '70%' }} />
      <Handle id="return-in" type="target" position={Position.Right} style={{ top: '70%' }} />
      <div className="node-eyebrow">
        <span>{stageName(stage.stage)}</span>
        <span className="node-dot" />
      </div>
      <strong>{stage.label}</strong>
      <div className="node-meta">
        <span>{nodeStatus(stage.status)}</span>
        {data.sources > 0 && <span>{data.sources} 个来源</span>}
      </div>
      <Handle id="bottom-out" type="source" position={Position.Bottom} />
    </div>
  );
}
const nodeTypes = { research: StageCard };

export function FollowViewport({
  enabled,
  signature,
  nodeIds,
  size,
  onReadyChange,
}: {
  enabled: boolean;
  signature: string;
  nodeIds: string;
  size: { width: number; height: number };
  onReadyChange: (ready: boolean) => void;
}) {
  const initialized = useNodesInitialized();
  const renderedIds = JSON.stringify(useNodes().map((node) => node.id));
  const { fitView, viewportInitialized } = useReactFlow();
  const lastFit = useRef<string | null>(null);
  const fitKey = `${signature}:${size.width}x${size.height}`;
  useEffect(() => {
    if (!enabled) {
      lastFit.current = null;
      onReadyChange(false);
      return;
    }
    // Hidden mobile canvases have no usable dimensions even if the pan/zoom instance exists.
    if (
      !viewportInitialized ||
      !initialized ||
      renderedIds !== nodeIds ||
      !size.width ||
      !size.height
    ) {
      lastFit.current = null;
      onReadyChange(false);
      return;
    }
    if (lastFit.current === fitKey) return;
    let disposed = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    onReadyChange(false);
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    async function fit() {
      attempts += 1;
      try {
        const success = await fitView({
          padding: 0.2,
          maxZoom: 1,
          duration: reducedMotion ? 0 : 300,
        });
        if (disposed) return;
        if (success) {
          lastFit.current = fitKey;
          onReadyChange(true);
          return;
        }
      } catch {
        /* Measurements can disappear while a responsive canvas is being hidden. */
      }
      if (!disposed && attempts < 3) retryTimer = setTimeout(() => void fit(), 100 * attempts);
    }
    void fit();
    return () => {
      disposed = true;
      clearTimeout(retryTimer);
    };
  }, [
    enabled,
    fitKey,
    nodeIds,
    renderedIds,
    initialized,
    viewportInitialized,
    fitView,
    size.width,
    size.height,
    onReadyChange,
  ]);
  return null;
}

export function graphLayout(
  stages: StageNode[],
  edges: StageEdge[],
  sources: Source[],
  selected?: string,
) {
  const nodes: ResearchNode[] = [];
  // Append-only positions: a growing run never moves an existing stage. Child research lives beside its supervisor.
  const placed = new Map<string, { x: number; y: number }>();
  const siblings = new Map<string, number>();
  let row = 0;
  for (const stage of stages) {
    const parent = stage.parent_id ? placed.get(stage.parent_id) : undefined;
    const sibling = stage.parent_id ? (siblings.get(stage.parent_id) ?? 0) : 0;
    const position = parent
      ? { x: parent.x + 320, y: parent.y + sibling * 156 }
      : { x: 0, y: row * 156 };
    if (stage.parent_id) siblings.set(stage.parent_id, sibling + 1);
    row = Math.max(row + (parent ? 0 : 1), Math.ceil(position.y / 156) + 1);
    placed.set(stage.id, position);
    nodes.push({
      id: stage.id,
      type: 'research',
      data: {
        stage,
        sources:
          sources.filter((source) => source.agent_instance_id === stage.id).length ||
          stage.source_count ||
          0,
      },
      position,
      selected: selected === stage.id,
    });
  }
  const ids = new Set(stages.map((stage) => stage.id));
  const flowEdges: Edge[] = edges
    .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
    .map((edge) => {
      const feedback = /反馈|质疑/.test(edge.label ?? '') || edge.kind === 'feedback';
      const result = /返回|成果|证据/.test(edge.label ?? '') || edge.kind === 'result';
      const active = stages.find((node) => node.id === edge.target)?.status === 'running';
      const sourcePosition = placed.get(edge.source)!;
      const targetPosition = placed.get(edge.target)!;
      // Reciprocal relations need separate ports: sharing the default smoothstep center
      // places their labels on exactly the same point, regardless of their line styles.
      const handles =
        targetPosition.x > sourcePosition.x
          ? { sourceHandle: 'dispatch-out', targetHandle: 'dispatch-in' }
          : targetPosition.x < sourcePosition.x
            ? { sourceHandle: 'return-out', targetHandle: 'return-in' }
            : { sourceHandle: 'bottom-out', targetHandle: 'top-in' };
      return {
        ...edge,
        ...handles,
        type: 'smoothstep',
        animated: active,
        markerEnd: { type: MarkerType.ArrowClosed, color: feedback ? '#a23e32' : '#99978d' },
        style: {
          stroke: feedback ? '#a23e32' : '#aaa79d',
          strokeDasharray: feedback ? '3 5' : result ? '8 4' : undefined,
        },
        labelStyle: { fill: '#68675f', fontSize: 11 },
        labelBgStyle: { fill: '#f7f4ed' },
      };
    });
  return { nodes, edges: flowEdges };
}
export default function Graph({
  stages,
  edges,
  sources,
  selected,
  onSelect,
}: {
  stages: StageNode[];
  edges: StageEdge[];
  sources: Source[];
  selected?: string;
  onSelect: (id: string) => void;
}) {
  const [following, setFollowing] = useState(true);
  const [followReady, setFollowReady] = useState(false);
  const canvas = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [measurements, setMeasurements] = useState(
    new Map<string, { width: number; height: number }>(),
  );
  useEffect(() => {
    const element = canvas.current!;
    const update = () => {
      const rect = element.getBoundingClientRect();
      const next = { width: Math.round(rect.width), height: Math.round(rect.height) };
      setSize((previous) =>
        previous.width === next.width && previous.height === next.height ? previous : next,
      );
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const onNodesChange = useCallback((changes: NodeChange<ResearchNode>[]) => {
    // This is a read-only graph, but controlled nodes must retain React Flow's measured sizes.
    // Ignoring dimensions changes leaves useNodesInitialized false and prevents fitView forever.
    const dimensions = changes.filter(
      (change) => change.type === 'dimensions' && change.dimensions,
    );
    if (!dimensions.length) return;
    setMeasurements((previous) => {
      let next = previous;
      for (const change of dimensions) {
        if (change.type !== 'dimensions' || !change.dimensions) continue;
        const current = previous.get(change.id);
        if (
          current?.width === change.dimensions.width &&
          current?.height === change.dimensions.height
        )
          continue;
        if (next === previous) next = new Map(previous);
        next.set(change.id, change.dimensions);
      }
      return next;
    });
  }, []);
  const signature = JSON.stringify(stages.map((stage) => [stage.id, stage.iteration ?? null]));
  const nodeIds = JSON.stringify(stages.map((stage) => stage.id));
  const flow = useMemo(() => {
    const layout = graphLayout(stages, edges, sources, selected);
    return {
      ...layout,
      nodes: layout.nodes.map((node) => ({ ...node, measured: measurements.get(node.id) })),
    };
  }, [stages, edges, sources, selected, measurements]);
  return (
    <div ref={canvas} className="graph-canvas" role="region" aria-label="研究协作关系图">
      <ReactFlow
        nodes={flow.nodes}
        edges={flow.edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        nodesDraggable={false}
        nodesConnectable={false}
        edgesFocusable={false}
        onNodeClick={(_, node) => {
          setFollowing(false);
          onSelect(node.id);
        }}
        onMoveStart={(event) => {
          // Programmatic fitView emits a null event and must not disable following itself.
          if (event) setFollowing(false);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            const id = (event.target as HTMLElement).closest<HTMLElement>('.react-flow__node')
              ?.dataset.id;
            if (id) {
              setFollowing(false);
              onSelect(id);
            }
          }
        }}
        minZoom={0.25}
        maxZoom={1.5}
        deleteKeyCode={null}
      >
        <Background gap={24} size={0.6} color="#d6d1c6" />
        <FollowViewport
          enabled={following}
          signature={signature}
          nodeIds={nodeIds}
          size={size}
          onReadyChange={setFollowReady}
        />
        <Controls
          position="bottom-right"
          showInteractive={false}
          onZoomIn={() => setFollowing(false)}
          onZoomOut={() => setFollowing(false)}
          onFitView={() => setFollowing(false)}
        />
      </ReactFlow>
      <div className="graph-follow">
        {following ? (
          <span>{followReady ? '正在跟随进展' : '跟随进展 · 等待画布就绪'}</span>
        ) : (
          <button className="text-button" onClick={() => setFollowing(true)}>
            跟随进展 ↗
          </button>
        )}
      </div>
      <div className="graph-legend">
        <span>实线 · 分发</span>
        <span>虚线 · 成果返回</span>
        <span>朱砂 · 质疑反馈</span>
      </div>
    </div>
  );
}
