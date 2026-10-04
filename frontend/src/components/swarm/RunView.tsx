import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowLeft, ChevronDown, ChevronRight, Loader2, XCircle } from "lucide-react";
import { api, type SwarmRunDetail } from "@/lib/api";
import {
  computeLayers,
  edgesFromRunTasks,
  type FlowEdge,
} from "@/lib/swarmGraph";
import { MarkdownContent } from "@/components/common/MarkdownContent";
import { FlowCanvas, type NodeVisualStatus } from "./FlowCanvas";

interface RunViewProps {
  runId: string;
  /** Snapshot mode: history record, no SSE subscription and no cancel. */
  readOnly?: boolean;
  onBack?: () => void;
}

const ACTIVE_STATUSES = new Set(["pending", "running"]);
const TASK_STATUS_MAP: Record<string, NodeVisualStatus> = {
  pending: "waiting",
  blocked: "blocked",
  in_progress: "running",
  completed: "completed",
  failed: "failed",
  cancelled: "cancelled",
};

type NodeStatusTKey =
  | "swarmStudio.run.nodeStatus.waiting"
  | "swarmStudio.run.nodeStatus.blocked"
  | "swarmStudio.run.nodeStatus.running"
  | "swarmStudio.run.nodeStatus.completed"
  | "swarmStudio.run.nodeStatus.failed"
  | "swarmStudio.run.nodeStatus.cancelled";

const NODE_STATUS_TKEY: Record<NodeVisualStatus, NodeStatusTKey> = {
  idle: "swarmStudio.run.nodeStatus.waiting",
  waiting: "swarmStudio.run.nodeStatus.waiting",
  blocked: "swarmStudio.run.nodeStatus.blocked",
  running: "swarmStudio.run.nodeStatus.running",
  completed: "swarmStudio.run.nodeStatus.completed",
  failed: "swarmStudio.run.nodeStatus.failed",
  cancelled: "swarmStudio.run.nodeStatus.cancelled",
};

interface ProgressNote {
  agentId: string;
  text: string;
}

export function RunView({ runId, readOnly = false, onBack }: RunViewProps) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<SwarmRunDetail | null>(null);
  const [loadError, setLoadError] = useState("");
  const [liveStatus, setLiveStatus] = useState<Record<string, NodeVisualStatus>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const [notes, setNotes] = useState<ProgressNote[]>([]);
  const [cancelling, setCancelling] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);
  const panelBodyId = useId();

  const refresh = useCallback(async () => {
    const run = await api.getSwarmRun(runId);
    setDetail(run);
    return run;
  }, [runId]);

  useEffect(() => {
    let disposed = false;
    refresh()
      .then((run) => {
        if (disposed || readOnly) return;
        if (!ACTIVE_STATUSES.has(run.status)) return;
        api.swarmSseUrl(runId).then((url) => {
          if (disposed) return;
          const source = new EventSource(url);
          sourceRef.current = source;

          const mark = (agentId: string | undefined, status: NodeVisualStatus) => {
            if (!agentId) return;
            setLiveStatus((prev) => ({ ...prev, [agentId]: status }));
          };
          const addNote = (agentId: string | undefined, text: string) => {
            if (!agentId) return;
            setNotes((prev) =>
              prev.some((n) => n.agentId === agentId && n.text === text)
                ? prev
                : [...prev, { agentId, text }],
            );
          };

          source.addEventListener("task_started", (ev) => {
            const d = JSON.parse((ev as MessageEvent).data);
            mark(d.agent_id, "running");
          });
          source.addEventListener("worker_started", (ev) => {
            const d = JSON.parse((ev as MessageEvent).data);
            mark(d.agent_id, "running");
          });
          source.addEventListener("task_blocked", (ev) => {
            const d = JSON.parse((ev as MessageEvent).data);
            mark(d.agent_id, "blocked");
            addNote(d.agent_id, t("swarmStudio.run.blockedHint"));
          });
          source.addEventListener("task_completed", (ev) => {
            const d = JSON.parse((ev as MessageEvent).data);
            mark(d.agent_id, "completed");
          });
          source.addEventListener("task_failed", (ev) => {
            const d = JSON.parse((ev as MessageEvent).data);
            mark(d.agent_id, "failed");
          });
          source.addEventListener("task_cancelled", (ev) => {
            const d = JSON.parse((ev as MessageEvent).data);
            mark(d.agent_id, "cancelled");
          });
          source.addEventListener("worker_failed", (ev) => {
            const d = JSON.parse((ev as MessageEvent).data);
            mark(d.agent_id, "failed");
            addNote(d.agent_id, d.data?.error || t("swarmStudio.run.failedHint"));
          });
          source.addEventListener("worker_timeout", (ev) => {
            const d = JSON.parse((ev as MessageEvent).data);
            addNote(d.agent_id, t("swarmStudio.run.timeoutHint"));
          });
          source.addEventListener("done", () => {
            source.close();
            sourceRef.current = null;
            void refresh();
          });
          source.onerror = () => {
            // EventSource auto-reconnects; a terminal "done" closes cleanly.
          };
        });
      })
      .catch(() => {
        if (!disposed) setLoadError(t("swarmStudio.run.loadError"));
      });
    return () => {
      disposed = true;
      sourceRef.current?.close();
      sourceRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, readOnly]);

  const graph = useMemo(() => {
    if (!detail) return { nodes: [], edges: [] as FlowEdge[], finalAgentId: null as string | null };
    const edges = edgesFromRunTasks(detail.tasks);
    const { layers, cycleNodes } = computeLayers(
      detail.agents.map((a) => ({ id: a.id })),
      edges,
    );
    const finalLayer = layers[layers.length - 1] ?? [];
    const finalAgentId =
      cycleNodes.length === 0 && finalLayer.length === 1 ? finalLayer[0] : null;
    const nodes = detail.agents.map((a) => ({
      id: a.id,
      role: a.role,
      meta: t("swarmStudio.canvas.nodeMeta", {
        tools: a.tools.length,
        minutes: Math.round(a.timeout_seconds / 60),
      }),
      isFinal: a.id === finalAgentId,
    }));
    return { nodes, edges, finalAgentId };
  }, [detail, t]);

  const statusById = useMemo(() => {
    if (!detail) return {};
    const map: Record<string, NodeVisualStatus> = {};
    for (const task of detail.tasks) {
      map[task.agent_id] = TASK_STATUS_MAP[task.status] ?? "waiting";
    }
    // live SSE overrides the hydrate snapshot while the run is active
    return readOnly ? map : { ...map, ...liveStatus };
  }, [detail, liveStatus, readOnly]);

  const selectedTask = useMemo(() => {
    if (!detail || !selectedId) return null;
    return detail.tasks.find((task) => task.agent_id === selectedId) ?? null;
  }, [detail, selectedId]);
  const selectedAgent = useMemo(
    () => detail?.agents.find((a) => a.id === selectedId) ?? null,
    [detail, selectedId],
  );

  const active = detail ? ACTIVE_STATUSES.has(detail.status) : false;
  const terminal = detail && !active;
  const finalReport = detail?.final_report;
  // Collect concrete failure reasons from every failed task so a failed
  // run surfaces the real causes (provider/model/timeout, etc.) on the
  // web UI instead of a bare no-final-report line.
  const failedTaskErrors = useMemo(() => {
    if (!detail || detail.status !== "failed") return [] as { agent: string; error: string }[];
    const items: { agent: string; error: string }[] = [];
    for (const task of detail.tasks) {
      if (task.status === "failed" && task.error) {
        const agent = detail.agents.find((a) => a.id === task.agent_id);
        items.push({ agent: agent?.role || task.agent_id, error: task.error });
      }
    }
    return items;
  }, [detail]);


  // Selecting a node is the intent to read its conclusion, so it always
  // reveals the panel; afterwards the user may collapse manually until
  // another node is picked.
  const handleSelectNode = useCallback((id: string | null) => {
    setSelectedId(id);
    if (id) setPanelCollapsed(false);
  }, []);

  const handleCancel = async () => {
    if (!detail) return;
    setCancelling(true);
    try {
      await api.cancelSwarmRun(detail.id);
      await refresh();
    } finally {
      setCancelling(false);
    }
  };

  if (loadError) {
    return (
      <div className="p-8 text-sm text-destructive" data-testid="run-view-error">
        {loadError}
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("swarmStudio.run.loading")}
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="run-view">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          {onBack && (
            <button
              type="button"
              onClick={onBack}
              className="rounded p-1 text-muted-foreground hover:bg-accent"
              aria-label={t("swarmStudio.run.back")}
              data-testid="run-back-btn"
            >
              <ArrowLeft className="h-4 w-4" />
            </button>
          )}
          <div>
            <h2 className="text-base font-semibold text-foreground">
              {t("swarmStudio.run.title", { id: detail.id })}
            </h2>
            <p className="text-xs text-muted-foreground">
              {detail.preset_name} · {detail.research_target || detail.user_vars?.target} ·{" "}
              {t(`swarmStudio.history.status.${detail.status}`, {
                defaultValue: detail.status,
              })}
            </p>
          </div>
        </div>
        {!readOnly && active && (
          <button
            type="button"
            onClick={handleCancel}
            disabled={cancelling}
            data-testid="cancel-run-btn"
            className="inline-flex items-center gap-1.5 rounded border border-red-300 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 disabled:opacity-40 dark:border-red-800 dark:hover:bg-red-950/40"
          >
            <XCircle className="h-3.5 w-3.5" />
            {t("swarmStudio.run.cancel")}
          </button>
        )}
      </div>

      {detail.research_question && (
        <p className="rounded-lg bg-accent/50 px-3 py-2 text-xs text-foreground">
          <span className="font-semibold">{t("swarmStudio.launch.question")}：</span>
          {detail.research_question}
        </p>
      )}

      <div className="rounded-lg border border-border bg-card p-3">
        <FlowCanvas
          nodes={graph.nodes}
          edges={graph.edges}
          statusById={statusById}
          selectedId={selectedId}
          onSelectNode={handleSelectNode}
        />
        <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
          {(["waiting", "running", "completed", "failed"] as NodeVisualStatus[]).map(
            (s) => (
              <span key={s} className="inline-flex items-center gap-1">
                <span
                  className={`h-2 w-2 rounded-full ${
                    s === "waiting"
                      ? "bg-zinc-300"
                      : s === "running"
                        ? "bg-blue-500"
                        : s === "completed"
                          ? "bg-emerald-500"
                          : "bg-red-500"
                  }`}
                />
                {t(NODE_STATUS_TKEY[s])}
              </span>
            ),
          )}
        </div>
      </div>

      <section
        data-testid="node-detail-panel"
        className="overflow-hidden rounded-lg border border-border bg-card"
      >
        <div className="flex items-center justify-between gap-2 border-b border-border/60 px-4 py-2.5">
          <h3 className="min-w-0 text-sm font-semibold text-foreground">
            <span className="block truncate">
              {selectedAgent
                ? selectedAgent.role
                : t("swarmStudio.run.analysisTitle")}
            </span>
            {selectedAgent && (
              <span className="mt-0.5 block text-[11px] font-normal text-muted-foreground">
                {t(NODE_STATUS_TKEY[statusById[selectedAgent.id] ?? "waiting"])}
              </span>
            )}
          </h3>
          <button
            type="button"
            onClick={() => setPanelCollapsed((prev) => !prev)}
            aria-expanded={!panelCollapsed}
            aria-label={
              panelCollapsed
                ? t("swarmStudio.run.expand")
                : t("swarmStudio.run.collapse")
            }
            data-testid="node-panel-toggle"
            aria-controls={panelBodyId}
            className="inline-flex shrink-0 items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            {panelCollapsed ? t("swarmStudio.run.expand") : t("swarmStudio.run.collapse")}
            {panelCollapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
        </div>

        {!panelCollapsed && (
          <div className="p-4" id={panelBodyId} data-testid="node-panel-body">
            {selectedAgent ? (
              <>
                {selectedTask?.summary && (
                  <div className="max-h-[40vh] overflow-y-auto rounded bg-background p-2 text-xs text-foreground">
                    <MarkdownContent content={selectedTask.summary} />
                  </div>
                )}
                {selectedTask?.error && (
                  <p className="mt-2 rounded bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950/40 dark:text-red-300">
                    {selectedTask.error}
                  </p>
                )}
                {notes
                  .filter((n) => n.agentId === selectedAgent.id)
                  .slice(-3)
                  .map((n, i) => (
                    <p key={i} className="mt-1 text-[11px] text-amber-600">
                      {n.text}
                    </p>
                  ))}
                {!selectedTask?.summary && !selectedTask?.error && (
                  <p className="text-xs text-muted-foreground">
                    {t("swarmStudio.run.noConclusionYet")}
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("swarmStudio.run.selectNode")}
              </p>
            )}
          </div>
        )}
      </section>

      <section
        data-testid="final-decision-panel"
        className={`rounded-lg border bg-card p-4 ${
          terminal && finalReport ? "border-emerald-400" : "border-border"
        }`}
      >
        <h3 className="text-sm font-semibold text-foreground">
          {t("swarmStudio.run.finalDecision")}
        </h3>
        {terminal && finalReport ? (
          <div
            className="mt-2 max-h-[50vh] overflow-y-auto text-sm text-foreground"
            data-testid="final-decision-content"
          >
            <MarkdownContent content={finalReport} />
          </div>
        ) : terminal && failedTaskErrors.length > 0 ? (
          <div
            className="mt-2 space-y-2"
            data-testid="run-failure-reasons"
          >
            {failedTaskErrors.map((item, idx) => (
              <div
                key={idx}
                className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-700 dark:text-red-300"
              >
                <span className="font-semibold">{item.agent}：</span>
                <span className="whitespace-pre-wrap break-words">{item.error}</span>
              </div>
            ))}
          </div>
        ) : active ? (
          <p className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("swarmStudio.run.finalPending")}
          </p>
        ) : (
          <p className="mt-2 text-xs text-muted-foreground">
            {t("swarmStudio.run.noFinalReport")}
          </p>
        )}
      </section>
    </div>
  );
}
