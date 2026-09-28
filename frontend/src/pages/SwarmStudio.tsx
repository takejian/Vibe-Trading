import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { History, Plus, Users } from "lucide-react";
import { api, type SwarmPreset, type SwarmRunSummary } from "@/lib/api";
import {
  computeLayers,
  draftFromPresetDetail,
  isLaunchable,
  nextNodeId,
  toCustomPayload,
  validateGraph,
  type FlowEdge,
  type FlowNodeDraft,
  type SwarmPresetDetail,
} from "@/lib/swarmGraph";
import { PresetGallery } from "@/components/swarm/PresetGallery";
import { FlowCanvas } from "@/components/swarm/FlowCanvas";
import { NodeEditorPanel } from "@/components/swarm/NodeEditorPanel";
import { LaunchBar } from "@/components/swarm/LaunchBar";
import { RunView } from "@/components/swarm/RunView";
import { HistoryList } from "@/components/swarm/HistoryList";

type Tab = "studio" | "history";
type View = "gallery" | "edit" | "run";

export function SwarmStudio() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("studio");
  const [view, setView] = useState<View>("gallery");

  const [presets, setPresets] = useState<SwarmPreset[]>([]);
  const [galleryLoading, setGalleryLoading] = useState(true);
  const [galleryError, setGalleryError] = useState("");

  const [presetName, setPresetName] = useState("");
  const [detail, setDetail] = useState<SwarmPresetDetail | null>(null);
  const [nodes, setNodes] = useState<FlowNodeDraft[]>([]);
  const [edges, setEdges] = useState<FlowEdge[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [target, setTarget] = useState("");
  const [question, setQuestion] = useState("");
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState("");
  const [activeRunId, setActiveRunId] = useState("");

  const [historyRuns, setHistoryRuns] = useState<SwarmRunSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [historyRunId, setHistoryRunId] = useState("");

  useEffect(() => {
    let cancelled = false;
    setGalleryLoading(true);
    api
      .listSwarmPresets()
      .then((res) => {
        if (!cancelled) setPresets(res);
      })
      .catch(() => {
        if (!cancelled) setGalleryError(t("swarmStudio.gallery.loadError"));
      })
      .finally(() => {
        if (!cancelled) setGalleryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const loadPreset = useCallback(
    async (name: string) => {
      const presetDetail = await api.getSwarmPresetDetail(name);
      setDetail(presetDetail);
      setPresetName(name);
      const draft = draftFromPresetDetail(presetDetail);
      setNodes(draft.nodes);
      setEdges(draft.edges);
      setSelectedId(draft.nodes[0]?.id ?? null);
      setTarget("");
      setQuestion("");
      setLaunchError("");
      setView("edit");
    },
    [],
  );

  const loadHistory = useCallback(() => {
    setTab("history");
    setHistoryLoading(true);
    setHistoryError("");
    api
      .listSwarmRuns()
      .then(setHistoryRuns)
      .catch(() => setHistoryError(t("swarmStudio.history.loadError")))
      .finally(() => setHistoryLoading(false));
  }, [t]);

  const issues = useMemo(() => validateGraph(nodes, edges), [nodes, edges]);
  const graphValid = isLaunchable(issues);
  const finalLayerIds = useMemo(() => {
    if (nodes.length === 0) return new Set<string>();
    const { layers, cycleNodes } = computeLayers(nodes, edges);
    if (cycleNodes.length > 0) return new Set<string>();
    const last = layers[layers.length - 1] ?? [];
    return last.length === 1 ? new Set(last) : new Set<string>();
  }, [nodes, edges]);

  const updateNode = (id: string, patch: Partial<FlowNodeDraft>) => {
    setNodes((prev) => prev.map((n) => (n.id === id ? { ...n, ...patch } : n)));
  };

  const deleteNode = (id: string) => {
    setNodes((prev) => prev.filter((n) => n.id !== id));
    setEdges((prev) => prev.filter((e) => e.upstream !== id && e.downstream !== id));
    setSelectedId((prev) => (prev === id ? null : prev));
  };

  const addNode = () => {
    const id = nextNodeId(nodes);
    const node: FlowNodeDraft = {
      id,
      role: "",
      duty: "",
      tools: [],
      timeoutSeconds: 300,
      sourceTaskId: null,
      isNew: true,
    };
    setNodes((prev) => [...prev, node]);
    setSelectedId(id);
  };

  const deleteEdge = (edge: FlowEdge) => {
    setEdges((prev) =>
      prev.filter((e) => !(e.upstream === edge.upstream && e.downstream === edge.downstream)),
    );
  };

  const addEdge = (edge: FlowEdge) => {
    setEdges((prev) =>
      prev.some((e) => e.upstream === edge.upstream && e.downstream === edge.downstream)
        ? prev
        : [...prev, edge],
    );
  };

  const resetPreset = async () => {
    await loadPreset(presetName);
  };

  const handleLaunch = async () => {
    if (!presetName || !detail) return;
    if (!graphValid || !target.trim() || !question.trim()) return;
    setLaunching(true);
    setLaunchError("");
    try {
      const payload = toCustomPayload(nodes, edges, target, question);
      const run = await api.createSwarmRun(presetName, { target: payload.target }, payload);
      setActiveRunId(run.id);
      setView("run");
    } catch (err) {
      setLaunchError(
        err instanceof Error ? err.message : t("swarmStudio.launch.failed"),
      );
    } finally {
      setLaunching(false);
    }
  };

  const canvasNodes = nodes.map((n) => ({
    id: n.id,
    role: n.role || n.id,
    meta: t("swarmStudio.canvas.nodeMeta", {
      tools: n.tools.length,
      minutes: Math.round(n.timeoutSeconds / 60),
    }),
    isFinal: finalLayerIds.has(n.id),
  }));

  if (view === "run" && activeRunId) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-8" data-testid="swarm-studio-page">
        <RunView
          runId={activeRunId}
          onBack={() => {
            setView("gallery");
            setActiveRunId("");
          }}
        />
      </div>
    );
  }

  if (tab === "history") {
    if (historyRunId) {
      return (
        <div className="mx-auto w-full max-w-7xl px-4 py-8" data-testid="swarm-studio-page">
          <RunView
            runId={historyRunId}
            readOnly
            onBack={() => setHistoryRunId("")}
          />
        </div>
      );
    }
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-8" data-testid="swarm-studio-page">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="font-serif text-2xl text-foreground">
              {t("swarmStudio.title")}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("swarmStudio.subtitle")}
            </p>
          </div>
        </header>
        <nav className="mt-4 flex gap-2 text-sm">
          <button
            type="button"
            onClick={() => setTab("studio")}
            className="inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 hover:bg-accent"
          >
            <Users className="h-4 w-4" />
            {t("swarmStudio.tabs.studio")}
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded bg-foreground px-3 py-1.5 text-background"
            aria-current="page"
          >
            <History className="h-4 w-4" />
            {t("swarmStudio.tabs.history")}
          </button>
        </nav>
        <HistoryList
          runs={historyRuns}
          loading={historyLoading}
          error={historyError}
          onOpen={setHistoryRunId}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8" data-testid="swarm-studio-page">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-serif text-2xl text-foreground">{t("swarmStudio.title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("swarmStudio.subtitle")}</p>
        </div>
        <nav className="flex gap-2 text-sm">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded bg-foreground px-3 py-1.5 text-background"
            aria-current="page"
          >
            <Users className="h-4 w-4" />
            {t("swarmStudio.tabs.studio")}
          </button>
          <button
            type="button"
            onClick={loadHistory}
            className="inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 hover:bg-accent"
            data-testid="history-tab-btn"
          >
            <History className="h-4 w-4" />
            {t("swarmStudio.tabs.history")}
          </button>
        </nav>
      </header>

      {view === "gallery" && (
        <section>
          <h2 className="mt-6 text-sm font-semibold text-foreground">
            {t("swarmStudio.gallery.sectionTitle")}
          </h2>
          <PresetGallery
            presets={presets}
            loading={galleryLoading}
            error={galleryError}
            onSelect={(name) => {
              void loadPreset(name);
            }}
          />
        </section>
      )}

      {view === "edit" && detail && (
        <section className="mt-6 space-y-4" data-testid="swarm-edit-view">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-foreground">
                {detail.title || presetName}
              </h2>
              <p className="text-xs text-muted-foreground">{detail.description}</p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setView("gallery")}
                className="rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
                data-testid="back-to-gallery-btn"
              >
                {t("swarmStudio.editor.backToGallery")}
              </button>
              <button
                type="button"
                onClick={addNode}
                className="inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
                data-testid="add-node-btn"
              >
                <Plus className="h-3.5 w-3.5" />
                {t("swarmStudio.editor.addNode")}
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-4 lg:flex-row">
            <div className="min-w-0 flex-1 rounded-lg border border-border bg-card p-3">
              <FlowCanvas
                nodes={canvasNodes}
                edges={edges}
                issues={issues}
                selectedId={selectedId}
                onSelectNode={setSelectedId}
              />
            </div>
            <NodeEditorPanel
              node={nodes.find((n) => n.id === selectedId) ?? null}
              nodes={nodes}
              edges={edges}
              toolCatalog={detail.tool_catalog}
              onUpdateNode={updateNode}
              onDeleteNode={deleteNode}
              onDeleteEdge={deleteEdge}
              onAddEdge={addEdge}
            />
          </div>

          <LaunchBar
            target={target}
            question={question}
            issues={issues}
            launching={launching}
            onTargetChange={setTarget}
            onQuestionChange={setQuestion}
            onReset={() => void resetPreset()}
            onLaunch={() => void handleLaunch()}
          />
          {launchError && (
            <p className="text-sm text-destructive" data-testid="launch-error">
              {launchError}
            </p>
          )}
        </section>
      )}
    </div>
  );
}
