import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle } from "lucide-react";
import {
  computeLayers,
  type FlowEdge,
  type GraphIssue,
} from "@/lib/swarmGraph";

export type NodeVisualStatus =
  | "idle"
  | "waiting"
  | "blocked"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface CanvasNode {
  id: string;
  role: string;
  meta?: string;
  isFinal?: boolean;
}

interface FlowCanvasProps {
  nodes: CanvasNode[];
  edges: FlowEdge[];
  statusById?: Record<string, NodeVisualStatus>;
  issues?: GraphIssue[];
  selectedId?: string | null;
  onSelectNode?: (id: string) => void;
}

const NODE_W = 190;
const NODE_H = 92;
const GAP_X = 48;
const LAYER_H = 158;
const TOP_PAD = 30;

const STATUS_RING: Record<NodeVisualStatus, string> = {
  idle: "border-border bg-card",
  waiting: "border-border bg-card",
  blocked: "border-amber-400 bg-amber-50 dark:bg-amber-950/30",
  running: "border-blue-500 bg-blue-50 shadow-[0_0_0_3px_rgba(59,130,246,0.15)] dark:bg-blue-950/30",
  completed: "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30",
  failed: "border-red-500 bg-red-50 dark:bg-red-950/30",
  cancelled: "border-zinc-400 bg-zinc-100 dark:bg-zinc-800/40",
};

const STATUS_DOT: Record<NodeVisualStatus, string> = {
  idle: "bg-zinc-300",
  waiting: "bg-zinc-300",
  blocked: "bg-amber-400",
  running: "bg-blue-500 animate-pulse",
  completed: "bg-emerald-500",
  failed: "bg-red-500",
  cancelled: "bg-zinc-400",
};

export function FlowCanvas({
  nodes,
  edges,
  statusById = {},
  issues = [],
  selectedId = null,
  onSelectNode,
}: FlowCanvasProps) {
  const { t } = useTranslation();

  const geometry = useMemo(() => {
    const { layers, cycleNodes } = computeLayers(nodes, edges);
    const ordered = layers.map((layer) =>
      layer
        .map((id) => nodes.find((n) => n.id === id))
        .filter((n): n is CanvasNode => Boolean(n)),
    );
    if (cycleNodes.length > 0) {
      const bucket = cycleNodes
        .map((id) => nodes.find((n) => n.id === id))
        .filter((n): n is CanvasNode => Boolean(n));
      if (bucket.length > 0) ordered.push(bucket);
    }
    const maxCols = Math.max(1, ...ordered.map((l) => l.length));
    const width = maxCols * NODE_W + (maxCols - 1) * GAP_X;
    const height = TOP_PAD + ordered.length * LAYER_H - (LAYER_H - NODE_H);
    return { layers: ordered, width, height, hasCycle: cycleNodes.length > 0 };
  }, [nodes, edges]);

  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number; layer: number }>();
    geometry.layers.forEach((layer, layerIdx) => {
      const layerWidth = layer.length * NODE_W + (layer.length - 1) * GAP_X;
      const offsetX = (geometry.width - layerWidth) / 2;
      layer.forEach((node, colIdx) => {
        map.set(node.id, {
          x: offsetX + colIdx * (NODE_W + GAP_X),
          y: TOP_PAD + layerIdx * LAYER_H,
          layer: layerIdx,
        });
      });
    });
    return map;
  }, [geometry]);

  const issueNodeIds = useMemo(() => {
    const s = new Set<string>();
    for (const issue of issues) issue.nodeIds.forEach((id) => s.add(id));
    return s;
  }, [issues]);

  const issueEdgeKeys = useMemo(() => {
    const s = new Set<string>();
    for (const issue of issues) {
      if (issue.edge) s.add(`${issue.edge.upstream} ${issue.edge.downstream}`);
    }
    return s;
  }, [issues]);

  return (
    <div
      className="relative w-full overflow-x-auto"
      data-testid="swarm-flow-canvas"
    >
      <div
        className="relative mx-auto"
        style={{ width: geometry.width, height: geometry.height, minWidth: "100%" }}
      >
        {geometry.layers.map((_, layerIdx) => (
          <div
            key={`layer-label-${layerIdx}`}
            className="absolute text-[11px] uppercase tracking-wide text-muted-foreground"
            style={{ left: 0, top: TOP_PAD + layerIdx * LAYER_H - 22 }}
          >
            {t("swarmStudio.canvas.layer", { index: layerIdx + 1 })}
          </div>
        ))}

        <svg
          width={geometry.width}
          height={geometry.height}
          className="absolute inset-0 pointer-events-none"
        >
          <defs>
            <marker
              id="swarm-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" className="text-muted-foreground" />
            </marker>
            <marker
              id="swarm-arrow-error"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" className="text-red-500" />
            </marker>
          </defs>
          {edges.map((edge) => {
            const from = positions.get(edge.upstream);
            const to = positions.get(edge.downstream);
            if (!from || !to) return null;
            const x1 = from.x + NODE_W / 2;
            const y1 = from.y + NODE_H;
            const x2 = to.x + NODE_W / 2;
            const y2 = to.y;
            const midY = (y1 + y2) / 2;
            const bad = issueEdgeKeys.has(`${edge.upstream} ${edge.downstream}`);
            const failed =
              statusById[edge.upstream] === "failed" ||
              statusById[edge.upstream] === "cancelled";
            const stroke = bad
              ? "#ef4444"
              : failed
                ? "#f59e0b"
                : statusById[edge.downstream] === "running" ||
                    statusById[edge.upstream] === "completed"
                  ? "#10b981"
                  : undefined;
            return (
              <path
                key={`${edge.upstream}->${edge.downstream}`}
                d={`M ${x1} ${y1} V ${midY} H ${x2} V ${y2 - 4}`}
                fill="none"
                stroke={stroke}
                strokeWidth={bad ? 2.4 : 1.6}
                className={stroke ? "" : "text-muted-foreground"}
                color={stroke ?? undefined}
                markerEnd={`url(#${bad ? "swarm-arrow-error" : "swarm-arrow"})`}
                data-testid={`edge-${edge.upstream}-${edge.downstream}`}
              />
            );
          })}
        </svg>

        {nodes.map((node) => {
          const pos = positions.get(node.id);
          if (!pos) return null;
          const status = statusById[node.id] ?? "idle";
          const hasIssue = issueNodeIds.has(node.id);
          const selected = selectedId === node.id;
          return (
            <button
              type="button"
              key={node.id}
              onClick={() => onSelectNode?.(node.id)}
              data-testid={`canvas-node-${node.id}`}
              aria-label={node.role}
              className={`absolute flex flex-col rounded-lg border px-3 py-2 text-left transition-colors ${STATUS_RING[status]} ${
                selected ? "ring-2 ring-foreground/60" : ""
              } ${hasIssue ? "ring-2 ring-red-400" : ""} ${
                onSelectNode ? "cursor-pointer hover:border-foreground/50" : "cursor-default"
              }`}
              style={{ left: pos.x, top: pos.y, width: NODE_W, height: NODE_H }}
            >
              <span className="flex items-center gap-1.5">
                <span className={`h-2 w-2 shrink-0 rounded-full ${STATUS_DOT[status]}`} />
                <span className="truncate text-xs font-semibold text-foreground" title={node.role}>
                  {node.role}
                </span>
              </span>
              {node.meta && (
                <span className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">
                  {node.meta}
                </span>
              )}
              <span className="mt-auto flex items-center gap-1">
                {node.isFinal && (
                  <span className="rounded bg-foreground/10 px-1.5 py-0.5 text-[10px] font-medium text-foreground">
                    {t("swarmStudio.canvas.finalRole")}
                  </span>
                )}
                {hasIssue && (
                  <AlertTriangle className="ml-auto h-3.5 w-3.5 text-red-500" aria-label="issue" />
                )}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
