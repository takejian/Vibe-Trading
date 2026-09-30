import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Bookmark, History, Plus, Save, Trash2, Users } from "lucide-react";
import {
  api,
  type CustomTeamSummary,
  type RoleGroup,
  type SkillCatalogEntry,
  type SwarmPreset,
  type SwarmRunSummary,
} from "@/lib/api";
import {
  computeLayers,
  draftFromCustomTeam,
  draftFromPresetDetail,
  isLaunchable,
  nextNodeId,
  nodeDraftFromRole,
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
import { HistoryList, type HistoryFilters } from "@/components/swarm/HistoryList";
import { SaveTeamDialog } from "@/components/swarm/SaveTeamDialog";
import { SkillSquare } from "@/components/swarm/SkillSquare";
import { RolePickerDialog } from "@/components/swarm/RolePickerDialog";

type Tab = "studio" | "history" | "skills";
type View = "gallery" | "edit" | "run";
type RunOrigin = "studio" | "skills" | "history";

export function SwarmStudio() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("studio");
  const [view, setView] = useState<View>("gallery");

  const [presets, setPresets] = useState<SwarmPreset[]>([]);
  const [galleryLoading, setGalleryLoading] = useState(true);
  const [galleryError, setGalleryError] = useState("");

  const [teams, setTeams] = useState<CustomTeamSummary[]>([]);
  const [teamsLoading, setTeamsLoading] = useState(false);
  const [teamsError, setTeamsError] = useState("");
  const [editingTeamId, setEditingTeamId] = useState<string | null>(null);

  const [skillCatalogEntries, setSkillCatalogEntries] = useState<SkillCatalogEntry[]>([]);
  const [roleGroups, setRoleGroups] = useState<RoleGroup[]>([]);

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
  const [runOrigin, setRunOrigin] = useState<RunOrigin>("studio");

  const [teamDialogOpen, setTeamDialogOpen] = useState(false);
  const [teamDialogMode, setTeamDialogMode] = useState<"create" | "update">("create");
  const [teamSaving, setTeamSaving] = useState(false);
  const [teamSaveError, setTeamSaveError] = useState("");

  const [historyRuns, setHistoryRuns] = useState<SwarmRunSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [historyRunId, setHistoryRunId] = useState("");

  const loadTeams = useCallback(() => {
    setTeamsLoading(true);
    setTeamsError("");
    api
      .listCustomTeams()
      .then(setTeams)
      .catch(() => setTeamsError(t("swarmStudio.teams.loadError")))
      .finally(() => setTeamsLoading(false));
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    setGalleryLoading(true);
    Promise.all([
      api.listSwarmPresets(),
      api.getSkillCatalog().catch(() => ({ skills: [] as SkillCatalogEntry[] })),
      api.listRoleGroups().catch(() => ({ groups: [] as RoleGroup[] })),
    ])
      .then(([presetRes, catalogRes, rolesRes]) => {
        if (cancelled) return;
        setPresets(presetRes);
        setSkillCatalogEntries(catalogRes.skills);
        setRoleGroups(rolesRes.groups);
      })
      .catch(() => {
        if (!cancelled) setGalleryError(t("swarmStudio.gallery.loadError"));
      })
      .finally(() => {
        if (!cancelled) setGalleryLoading(false);
      });
    loadTeams();
    return () => {
      cancelled = true;
    };
  }, [t, loadTeams]);

  const applyPreset = useCallback((presetDetail: SwarmPresetDetail) => {
    setDetail(presetDetail);
    setPresetName(presetDetail.name);
    const draft = draftFromPresetDetail(presetDetail);
    setNodes(draft.nodes);
    setEdges(draft.edges);
    setSelectedId(draft.nodes[0]?.id ?? null);
  }, []);

  const loadPreset = useCallback(
    async (name: string) => {
      const presetDetail = await api.getSwarmPresetDetail(name);
      applyPreset(presetDetail);
      setEditingTeamId(null);
      setTarget("");
      setQuestion("");
      setLaunchError("");
      setView("edit");
    },
    [applyPreset],
  );

  const loadCustomTeam = useCallback(
    async (teamId: string) => {
      const team = await api.getCustomTeam(teamId);
      const presetDetail = await api.getSwarmPresetDetail(team.source_preset);
      applyPreset(presetDetail);
      const draft = draftFromCustomTeam(team);
      setNodes(draft.nodes);
      setEdges(draft.edges);
      setSelectedId(draft.nodes[0]?.id ?? null);
      setEditingTeamId(team.id);
      setTarget("");
      setQuestion("");
      setLaunchError("");
      setView("edit");
    },
    [applyPreset],
  );

  const loadHistory = useCallback(
    (filters?: HistoryFilters) => {
      setTab("history");
      setHistoryLoading(true);
      setHistoryError("");
      api
        .listSwarmRuns({
          kind: "team",
          target: filters?.target || undefined,
          from: filters?.from || undefined,
          to: filters?.to || undefined,
          limit: 100,
        })
        .then(setHistoryRuns)
        .catch(() => setHistoryError(t("swarmStudio.history.loadError")))
        .finally(() => setHistoryLoading(false));
    },
    [t],
  );

  const availableSkills = useMemo(() => {
    const approved = skillCatalogEntries
      .filter((entry) => entry.approved)
      .map((entry) => entry.name);
    return new Set([...(detail?.skill_catalog ?? []), ...approved]);
  }, [detail, skillCatalogEntries]);

  const issues = useMemo(
    () => validateGraph(nodes, edges, availableSkills),
    [nodes, edges, availableSkills],
  );
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

  const [rolePickerOpen, setRolePickerOpen] = useState(false);

  const addRoleFromPicker = async (roleRef: string) => {
    setRolePickerOpen(false);
    try {
      const profile = await api.getRoleDetail(roleRef);
      const id = nextNodeId(nodes);
      const draft = nodeDraftFromRole(profile, id);
      setNodes((prev) => [...prev, draft]);
      setSelectedId(id);
    } catch (err) {
      setLaunchError(
        err instanceof Error ? err.message : t("swarmStudio.launch.failed"),
      );
    }
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
      setRunOrigin("studio");
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

  const buildTeamRequestBody = (name: string, description: string) => {
    const payload = toCustomPayload(nodes, edges, target || "_", question || "_");
    return {
      name,
      description,
      source_preset: presetName,
      nodes: payload.nodes,
      edges: payload.edges,
    };
  };

  const handleSaveTeam = async (name: string, description: string) => {
    if (!presetName) return;
    setTeamSaving(true);
    setTeamSaveError("");
    const body = buildTeamRequestBody(name, description);
    try {
      if (teamDialogMode === "update" && editingTeamId) {
        const updated = await api.updateCustomTeam(editingTeamId, body);
        setEditingTeamId(updated.id);
      } else {
        const created = await api.createCustomTeam(body);
        setEditingTeamId(created.id);
      }
      setTeamDialogOpen(false);
      loadTeams();
    } catch (err) {
      setTeamSaveError(
        err instanceof Error ? err.message : t("swarmStudio.teams.saveFailed"),
      );
    } finally {
      setTeamSaving(false);
    }
  };

  const handleDeleteTeam = async () => {
    if (!editingTeamId) return;
    const confirmed = window.confirm(t("swarmStudio.teams.deleteConfirm"));
    if (!confirmed) return;
    try {
      await api.deleteCustomTeam(editingTeamId);
      setEditingTeamId(null);
      loadTeams();
      setView("gallery");
    } catch (err) {
      setLaunchError(err instanceof Error ? err.message : t("swarmStudio.teams.deleteFailed"));
    }
  };

  const editingTeam = useMemo(
    () => teams.find((team) => team.id === editingTeamId) ?? null,
    [teams, editingTeamId],
  );

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
            const origin = runOrigin;
            setView("gallery");
            setTab(origin);
            setActiveRunId("");
            if (origin === "skills") loadTeams();
          }}
        />
      </div>
    );
  }

  const tabNav = (active: Tab) => (
    <nav className="flex gap-2 text-sm">
      <button
        type="button"
        onClick={() => setTab("studio")}
        data-testid="tab-studio"
        className={
          active === "studio"
            ? "inline-flex items-center gap-1.5 rounded bg-foreground px-3 py-1.5 text-background"
            : "inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 hover:bg-accent"
        }
      >
        <Users className="h-4 w-4" />
        {t("swarmStudio.tabs.studio")}
      </button>
      <button
        type="button"
        onClick={() => loadHistory()}
        data-testid="tab-history"
        className={
          active === "history"
            ? "inline-flex items-center gap-1.5 rounded bg-foreground px-3 py-1.5 text-background"
            : "inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 hover:bg-accent"
        }
      >
        <History className="h-4 w-4" />
        {t("swarmStudio.tabs.history")}
      </button>
      <button
        type="button"
        onClick={() => setTab("skills")}
        data-testid="tab-skills"
        className={
          active === "skills"
            ? "inline-flex items-center gap-1.5 rounded bg-foreground px-3 py-1.5 text-background"
            : "inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 hover:bg-accent"
        }
      >
        <Bookmark className="h-4 w-4" />
        {t("swarmStudio.tabs.skills")}
      </button>
    </nav>
  );

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
          {tabNav("history")}
        </header>
        <HistoryList
          runs={historyRuns}
          loading={historyLoading}
          error={historyError}
          onSearch={loadHistory}
          onOpen={setHistoryRunId}
        />
      </div>
    );
  }

  if (tab === "skills") {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-8" data-testid="swarm-studio-page">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="font-serif text-2xl text-foreground">
              {t("swarmStudio.title")}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("swarmStudio.skills.pageHint")}
            </p>
          </div>
          {tabNav("skills")}
        </header>
        <SkillSquare
          onOpenRun={(runId) => {
            setRunOrigin("skills");
            setActiveRunId(runId);
            setView("run");
          }}
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
        {tabNav("studio")}
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
            teams={teams}
            teamsLoading={teamsLoading}
            teamsError={teamsError}
            onSelect={(name) => {
              void loadPreset(name);
            }}
            onSelectTeam={(teamId) => {
              void loadCustomTeam(teamId);
            }}
          />
        </section>
      )}

      {view === "edit" && detail && (
        <section className="mt-6 space-y-4" data-testid="swarm-edit-view">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-foreground">
                {editingTeam?.name || detail.title || presetName}
              </h2>
              <p className="text-xs text-muted-foreground">
                {editingTeam?.description || detail.description}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
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
                onClick={() => setRolePickerOpen(true)}
                className="inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
                data-testid="add-node-btn"
              >
                <Plus className="h-3.5 w-3.5" />
                {t("swarmStudio.editor.addNode")}
              </button>
              {editingTeamId ? (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      setTeamDialogMode("update");
                      setTeamSaveError("");
                      setTeamDialogOpen(true);
                    }}
                    className="inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
                    data-testid="update-team-btn"
                  >
                    <Save className="h-3.5 w-3.5" />
                    {t("swarmStudio.teams.updateShort")}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDeleteTeam()}
                    className="inline-flex items-center gap-1.5 rounded border border-red-300 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 dark:border-red-900 dark:hover:bg-red-950/40"
                    data-testid="delete-team-btn"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {t("swarmStudio.teams.delete")}
                  </button>
                </>
              ) : null}
              <button
                type="button"
                onClick={() => {
                  setTeamDialogMode("create");
                  setTeamSaveError("");
                  setTeamDialogOpen(true);
                }}
                className="inline-flex items-center gap-1.5 rounded bg-foreground px-3 py-1.5 text-xs text-background"
                data-testid="save-team-btn"
              >
                <Bookmark className="h-3.5 w-3.5" />
                {t("swarmStudio.teams.saveAs")}
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
              skillCatalog={detail.skill_catalog}
              approvedSkills={skillCatalogEntries.filter((entry) => entry.approved)}
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

      <RolePickerDialog
        open={rolePickerOpen}
        groups={roleGroups}
        onPick={(roleRef) => void addRoleFromPicker(roleRef)}
        onClose={() => setRolePickerOpen(false)}
      />

      <SaveTeamDialog
        open={teamDialogOpen}
        mode={teamDialogMode}
        initialName={teamDialogMode === "update" ? editingTeam?.name ?? "" : ""}
        initialDescription={
          teamDialogMode === "update" ? editingTeam?.description ?? "" : ""
        }
        saving={teamSaving}
        error={teamSaveError}
        onSave={(name, description) => void handleSaveTeam(name, description)}
        onClose={() => setTeamDialogOpen(false)}
      />
    </div>
  );
}
