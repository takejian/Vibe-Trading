import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BadgeCheck,
  Loader2,
  Pencil,
  PlayCircle,
  Plus,
  Trash2,
} from "lucide-react";
import {
  api,
  type RoleGroup,
  type RoleGroupItem,
  type RoleProfile,
  type SkillCatalogEntry,
  type SwarmRunSummary,
} from "@/lib/api";
import { RunView } from "@/components/swarm/RunView";
import { HistoryList, type HistoryFilters } from "@/components/swarm/HistoryList";
import { MacroEvalHistory } from "@/components/macro/MacroEvalHistory";
import { useMacroEvalData } from "@/components/macro/macroEvalRecords";

type View = "list" | "detail" | "run" | "myEvals";
type DetailTab = "profile" | "run" | "history";

const NAME_MAX = 80;
const PURPOSE_MAX = 200;
const PROMPT_MAX = 12000;

// ---------------------------------------------------------------------------
// Role create/edit form
// ---------------------------------------------------------------------------

interface RoleFormState {
  name: string;
  purpose: string;
  systemPrompt: string;
  tools: string[];
  skills: string[];
  maxIterations: number;
  timeoutSeconds: number;
}

function blankForm(): RoleFormState {
  return {
    name: "",
    purpose: "",
    systemPrompt: "",
    tools: [],
    skills: [],
    maxIterations: 25,
    timeoutSeconds: 300,
  };
}

function formFromProfile(profile: RoleProfile): RoleFormState {
  return {
    name: profile.name,
    purpose: profile.purpose,
    systemPrompt: profile.system_prompt,
    tools: [...profile.tools],
    skills: [...profile.skills],
    maxIterations: profile.max_iterations,
    timeoutSeconds: profile.timeout_seconds,
  };
}

interface RoleFormProps {
  form: RoleFormState;
  toolCatalog: string[];
  skillCatalog: SkillCatalogEntry[];
  saving: boolean;
  error: string;
  isCreating: boolean;
  templates: RoleGroupItem[];
  templateRef: string;
  applyingTemplate: boolean;
  onSelectTemplate: (ref: string) => void;
  onChange: (next: RoleFormState) => void;
  onSubmit: () => void;
  onCancel: () => void;
}

function RoleForm({
  form,
  toolCatalog,
  skillCatalog,
  saving,
  error,
  isCreating,
  templates,
  templateRef,
  applyingTemplate,
  onSelectTemplate,
  onChange,
  onSubmit,
  onCancel,
}: RoleFormProps) {
  const { t } = useTranslation();
  const nameValid = form.name.trim().length > 0 && form.name.length <= NAME_MAX;
  const promptValid =
    form.systemPrompt.trim().length > 0 && form.systemPrompt.length <= PROMPT_MAX;
  const iterationsValid =
    Number.isInteger(form.maxIterations) &&
    form.maxIterations >= 1 &&
    form.maxIterations <= 100;
  const timeoutValid =
    Number.isInteger(form.timeoutSeconds) &&
    form.timeoutSeconds >= 1 &&
    form.timeoutSeconds <= 1800;
  const canSubmit =
    nameValid && promptValid && iterationsValid && timeoutValid && !saving;

  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((item) => item !== value) : [...list, value];

  return (
    <div className="space-y-4" data-testid="role-form">
      {isCreating && (
        <div data-testid="role-template-picker">
          <label className="block">
            <span className="text-xs font-medium text-foreground">
              {t("roleSquare.form.template")}
            </span>
            <select
              value={templateRef}
              disabled={applyingTemplate}
              onChange={(e) => onSelectTemplate(e.target.value)}
              data-testid="role-form-template"
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
            >
              <option value="">{t("roleSquare.form.templateNone")}</option>
              {templates.map((item) => (
                <option key={item.ref} value={item.ref}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {applyingTemplate
              ? t("roleSquare.form.templateApplying")
              : t("roleSquare.form.templateHint")}
          </p>
        </div>
      )}

      <label className="block">
        <span className="text-xs font-medium text-foreground">
          {t("roleSquare.form.name")}
        </span>
        <input
          value={form.name}
          onChange={(e) => onChange({ ...form, name: e.target.value })}
          maxLength={NAME_MAX}
          data-testid="role-form-name"
          className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
        />
        {!nameValid && (
          <span className="mt-1 block text-xs text-red-600">
            {t("roleSquare.form.nameInvalid", { number: NAME_MAX })}
          </span>
        )}
      </label>

      <label className="block">
        <span className="text-xs font-medium text-foreground">
          {t("roleSquare.form.purpose")}
        </span>
        <input
          value={form.purpose}
          onChange={(e) => onChange({ ...form, purpose: e.target.value })}
          maxLength={PURPOSE_MAX}
          data-testid="role-form-purpose"
          className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
        />
      </label>

      <label className="block">
        <span className="text-xs font-medium text-foreground">
          {t("roleSquare.form.systemPrompt")}
        </span>
        <textarea
          value={form.systemPrompt}
          onChange={(e) => onChange({ ...form, systemPrompt: e.target.value })}
          rows={8}
          maxLength={PROMPT_MAX}
          data-testid="role-form-prompt"
          className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm font-mono"
        />
        {!promptValid && (
          <span className="mt-1 block text-xs text-red-600">
            {t("roleSquare.form.promptInvalid", { number: PROMPT_MAX })}
          </span>
        )}
      </label>

      <fieldset>
        <legend className="text-xs font-medium text-foreground">
          {t("roleSquare.form.tools")}
        </legend>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {toolCatalog.map((tool) => {
            const active = form.tools.includes(tool);
            return (
              <button
                key={tool}
                type="button"
                aria-pressed={active}
                data-testid={`role-form-tool-${tool}`}
                onClick={() =>
                  onChange({ ...form, tools: toggle(form.tools, tool) })
                }
                className={
                  active
                    ? "rounded bg-foreground px-2 py-1 text-[11px] text-background"
                    : "rounded border border-border px-2 py-1 text-[11px] hover:bg-accent"
                }
              >
                {tool}
              </button>
            );
          })}
        </div>
      </fieldset>

      <fieldset>
        <legend className="text-xs font-medium text-foreground">
          {t("roleSquare.form.skills")}
        </legend>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {skillCatalog.map((skill) => {
            const active = form.skills.includes(skill.name);
            return (
              <button
                key={skill.name}
                type="button"
                aria-pressed={active}
                data-testid={`role-form-skill-${skill.name}`}
                onClick={() =>
                  onChange({ ...form, skills: toggle(form.skills, skill.name) })
                }
                className={
                  active
                    ? "rounded bg-foreground px-2 py-1 text-[11px] text-background"
                    : "rounded border border-border px-2 py-1 text-[11px] hover:bg-accent"
                }
              >
                {skill.name}
              </button>
            );
          })}
          {skillCatalog.length === 0 && (
            <span className="text-[11px] text-muted-foreground">
              {t("roleSquare.form.skillsEmpty")}
            </span>
          )}
        </div>
      </fieldset>

      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="text-xs font-medium text-foreground">
            {t("roleSquare.form.maxIterations")}
          </span>
          <input
            type="number"
            min={1}
            max={100}
            value={form.maxIterations}
            onChange={(e) =>
              onChange({ ...form, maxIterations: Number(e.target.value) })
            }
            data-testid="role-form-iterations"
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs font-medium text-foreground">
            {t("roleSquare.form.timeoutSeconds")}
          </span>
          <input
            type="number"
            min={1}
            max={1800}
            value={form.timeoutSeconds}
            onChange={(e) =>
              onChange({ ...form, timeoutSeconds: Number(e.target.value) })
            }
            data-testid="role-form-timeout"
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
          />
        </label>
      </div>
      {(!iterationsValid || !timeoutValid) && (
        <p className="text-xs text-red-600">{t("roleSquare.form.limitsInvalid")}</p>
      )}

      {error && (
        <p className="text-xs text-destructive" data-testid="role-form-error">
          {error}
        </p>
      )}

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
          data-testid="role-form-cancel"
        >
          {t("roleSquare.form.cancel")}
        </button>
        <button
          type="button"
          disabled={!canSubmit}
          onClick={onSubmit}
          data-testid="role-form-submit"
          className="rounded bg-foreground px-3 py-1.5 text-xs text-background disabled:opacity-40"
        >
          {saving ? t("roleSquare.form.saving") : t("roleSquare.form.save")}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Group card with its own within-group search
// ---------------------------------------------------------------------------

function RoleGroupSection({
  group,
  onOpen,
}: {
  group: RoleGroup;
  onOpen: (ref: string) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");

  const needle = query.trim().toLowerCase();
  const roles = group.roles.filter(
    (role) =>
      !needle ||
      role.name.toLowerCase().includes(needle) ||
      role.purpose.toLowerCase().includes(needle),
  );

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            {group.kind === "custom" ? t("roleSquare.groups.custom") : group.title}
          </h3>
          {group.description && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {group.description}
            </p>
          )}
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label={t("roleSquare.list.groupSearch")}
          placeholder={t("roleSquare.list.groupSearch")}
          data-testid={`group-search-${group.ref}`}
          className="rounded border border-border bg-background px-2 py-1 text-xs"
        />
      </div>
      <ul className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
        {roles.map((role) => (
          <li key={role.ref}>
            <button
              type="button"
              onClick={() => onOpen(role.ref)}
              data-testid={`role-card-${role.ref}`}
              className="flex w-full flex-col rounded border border-border bg-background px-3 py-2 text-left hover:bg-accent"
            >
              <span className="flex items-center gap-1.5">
                <span className="truncate text-sm font-medium text-foreground">
                  {role.name}
                </span>
                {role.approved && (
                  <BadgeCheck
                    className="h-3.5 w-3.5 shrink-0 text-emerald-600"
                    aria-label={t("roleSquare.list.approved")}
                  />
                )}
              </span>
              <span className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">
                {role.purpose || "—"}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {roles.length === 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          {query
            ? t("roleSquare.list.noMatchInGroup")
            : t("roleSquare.list.emptyGroup")}
        </p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function RoleSquare() {
  const { t } = useTranslation();

  const [view, setView] = useState<View>("list");
  const [groups, setGroups] = useState<RoleGroup[]>([]);
  const [toolCatalog, setToolCatalog] = useState<string[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [skillCatalog, setSkillCatalog] = useState<SkillCatalogEntry[]>([]);
  const [adminEnabled, setAdminEnabled] = useState(false);

  const [profile, setProfile] = useState<RoleProfile | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("profile");
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<RoleFormState>(blankForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [templateRef, setTemplateRef] = useState("");
  const [applyingTemplate, setApplyingTemplate] = useState(false);

  const [runTarget, setRunTarget] = useState("");
  const [runQuestion, setRunQuestion] = useState("");
  const [launching, setLaunching] = useState(false);
  const [runError, setRunError] = useState("");

  const [history, setHistory] = useState<SwarmRunSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");

  const [activeRunId, setActiveRunId] = useState("");
  const [runReturnTo, setRunReturnTo] = useState<View>("detail");
  const evalData = useMacroEvalData();
  // "我的评估": standalone role runs across ALL roles (not macro-only).
  const myEvalRecords = useMemo(
    () => evalData.records.filter((record) => record.kind === "role_run"),
    [evalData.records],
  );

  const loadList = useCallback(async () => {
    setListLoading(true);
    setListError("");
    try {
      const [catalog, skills, caps] = await Promise.all([
        api.listRoleGroups(),
        api.getSkillCatalog().catch(() => ({ skills: [] as SkillCatalogEntry[] })),
        api.getSkillCapabilities().catch(() => ({
          admin_enabled: false,
          sync_source_configured: false,
        })),
      ]);
      setGroups(catalog.groups);
      setToolCatalog(catalog.tool_catalog ?? []);
      setSkillCatalog(skills.skills.filter((entry) => entry.approved));
      setAdminEnabled(caps.admin_enabled);
    } catch (err) {
      setListError(err instanceof Error ? err.message : t("roleSquare.list.loadError"));
    } finally {
      setListLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  // Flat picker list: every built-in role plus approved custom roles.
  const templates = useMemo<RoleGroupItem[]>(() => {
    const items: RoleGroupItem[] = [];
    for (const group of groups) {
      for (const role of group.roles) {
        if (group.kind === "builtin" || role.approved) items.push(role);
      }
    }
    items.sort((a, b) => a.name.localeCompare(b.name));
    return items;
  }, [groups]);

  const openDetail = useCallback(
    async (ref: string) => {
      try {
        const detail = await api.getRoleDetail(ref);
        setProfile(detail);
        setForm(formFromProfile(detail));
        setDetailTab("profile");
        setEditing(false);
        setCreating(false);
        setFormError("");
        setTemplateRef("");
        setApplyingTemplate(false);
        setRunTarget("");
        setRunQuestion("");
        setRunError("");
        setView("detail");
      } catch (err) {
        setListError(err instanceof Error ? err.message : t("roleSquare.list.loadError"));
      }
    },
    [t],
  );

  const loadHistory = useCallback(
    async (ref: string, filters?: HistoryFilters) => {
      setHistoryLoading(true);
      setHistoryError("");
      try {
        const rows = await api.listRoleRuns({
          roleRef: ref,
          target: filters?.target || undefined,
          from: filters?.from || undefined,
          to: filters?.to || undefined,
          limit: 100,
        });
        setHistory(rows);
      } catch {
        setHistoryError(t("roleSquare.history.loadError"));
      } finally {
        setHistoryLoading(false);
      }
    },
    [t],
  );

  const switchTab = (tab: DetailTab) => {
    setDetailTab(tab);
    if (tab === "history" && profile) void loadHistory(profile.ref);
  };

  const startCreate = () => {
    setForm(blankForm());
    setFormError("");
    setCreating(true);
    setEditing(true);
    setProfile(null);
    setTemplateRef("");
    setApplyingTemplate(false);
    setView("detail");
    setDetailTab("profile");
  };

  const applyTemplate = useCallback(
    async (ref: string) => {
      setTemplateRef(ref);
      if (!ref) return;
      setApplyingTemplate(true);
      setFormError("");
      try {
        const detail = await api.getRoleDetail(ref);
        // Only carry over tools/skills still available in this deployment.
        const allowedTools = new Set(toolCatalog);
        const allowedSkills = new Set(skillCatalog.map((entry) => entry.name));
        // The name is intentionally never copied: a derived role needs a
        // new, globally unique name.
        setForm((current) => ({
          ...current,
          purpose: detail.purpose,
          systemPrompt: detail.system_prompt,
          tools: detail.tools.filter((tool) => allowedTools.has(tool)),
          skills: detail.skills.filter((skill) => allowedSkills.has(skill)),
          maxIterations: detail.max_iterations,
          timeoutSeconds: detail.timeout_seconds,
        }));
      } catch (err) {
        setFormError(
          err instanceof Error
            ? err.message
            : t("roleSquare.form.templateLoadFailed"),
        );
      } finally {
        setApplyingTemplate(false);
      }
    },
    [toolCatalog, skillCatalog, t],
  );

  const submitForm = async () => {
    setSaving(true);
    setFormError("");
    const body = {
      name: form.name.trim(),
      purpose: form.purpose.trim(),
      system_prompt: form.systemPrompt.trim(),
      tools: form.tools,
      skills: form.skills,
      max_iterations: form.maxIterations,
      timeout_seconds: form.timeoutSeconds,
      ...(creating && templateRef ? { template_ref: templateRef } : {}),
    };
    try {
      if (creating) {
        const created = await api.createCustomRole(body);
        await loadList();
        await openDetail(created.id);
      } else if (profile) {
        const updated = await api.updateCustomRole(profile.ref, body);
        await loadList();
        await openDetail(updated.id);
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : t("roleSquare.form.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const deleteRole = async () => {
    if (!profile) return;
    const confirmed = window.confirm(t("roleSquare.detail.deleteConfirm"));
    if (!confirmed) return;
    try {
      await api.deleteCustomRole(profile.ref);
      await loadList();
      setView("list");
    } catch (err) {
      setFormError(err instanceof Error ? err.message : t("roleSquare.detail.deleteFailed"));
    }
  };

  const approve = async () => {
    if (!profile) return;
    setFormError("");
    try {
      await api.approveRole(profile.ref);
      await openDetail(profile.ref);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : t("roleSquare.detail.approveFailed"));
    }
  };

  const unapprove = async () => {
    if (!profile) return;
    setFormError("");
    try {
      await api.unapproveRole(profile.ref);
      await openDetail(profile.ref);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : t("roleSquare.detail.approveFailed"));
    }
  };

  const launchRoleRun = async () => {
    if (!profile) return;
    if (!runTarget.trim() || !runQuestion.trim()) return;
    setLaunching(true);
    setRunError("");
    try {
      const run = await api.createRoleRun({
        role_ref: profile.ref,
        target: runTarget.trim(),
        question: runQuestion.trim(),
      });
      setActiveRunId(run.id);
      setRunReturnTo("detail");
      setView("run");
    } catch (err) {
      setRunError(err instanceof Error ? err.message : t("roleSquare.run.launchFailed"));
    } finally {
      setLaunching(false);
    }
  };

  // -----------------------------------------------------------------
  // Run view
  // -----------------------------------------------------------------

  if (view === "run" && activeRunId) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-8" data-testid="role-square-page">
        <RunView
          runId={activeRunId}
          onBack={() => {
            const origin = runReturnTo;
            setActiveRunId("");
            setView(origin);
            if (origin === "detail" && profile) void loadHistory(profile.ref);
          }}
        />
      </div>
    );
  }

  // -----------------------------------------------------------------
  // Detail / create view
  // -----------------------------------------------------------------

  if (view === "detail") {
    const isCustom = profile?.kind === "custom";
    return (
      <div className="mx-auto w-full max-w-5xl px-4 py-8" data-testid="role-square-page">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <button
              type="button"
              onClick={() => {
                setView("list");
                void loadList();
              }}
              data-testid="back-to-role-list"
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              ← {t("roleSquare.detail.backToList")}
            </button>
            <h1 className="mt-1 flex items-center gap-2 font-serif text-2xl text-foreground">
              <span className="truncate">{creating ? t("roleSquare.detail.createTitle") : profile?.name}</span>
              {profile?.approved && (
                <span
                  className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-700 dark:text-emerald-400"
                  data-testid="role-approved-badge"
                >
                  <BadgeCheck className="h-3 w-3" />
                  {t("roleSquare.list.approved")}
                </span>
              )}
            </h1>
          </div>

          {!creating && profile && (
            <div className="flex flex-wrap gap-2">
              {isCustom && !editing && (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      setForm(formFromProfile(profile));
                      setEditing(true);
                    }}
                    data-testid="role-edit-btn"
                    className="inline-flex items-center gap-1 rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                    {t("roleSquare.detail.edit")}
                  </button>
                  <button
                    type="button"
                    onClick={() => void deleteRole()}
                    data-testid="role-delete-btn"
                    className="inline-flex items-center gap-1 rounded border border-red-300 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 dark:border-red-900 dark:hover:bg-red-950/40"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {t("roleSquare.detail.delete")}
                  </button>
                </>
              )}
              {adminEnabled && isCustom && (
                profile.approved ? (
                  <button
                    type="button"
                    onClick={() => void unapprove()}
                    data-testid="role-unapprove-btn"
                    className="rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
                  >
                    {t("roleSquare.detail.unapprove")}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => void approve()}
                    data-testid="role-approve-btn"
                    className="rounded bg-foreground px-3 py-1.5 text-xs text-background"
                  >
                    {t("roleSquare.detail.approve")}
                  </button>
                )
              )}
            </div>
          )}
        </header>

        {!creating && (
          <nav className="mt-4 flex gap-2 text-sm" data-testid="role-detail-tabs">
            {(
              [
                ["profile", t("roleSquare.tabs.profile")],
                ["run", t("roleSquare.tabs.run")],
                ["history", t("roleSquare.tabs.history")],
              ] as Array<[DetailTab, string]>
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => switchTab(key)}
                data-testid={`role-tab-${key}`}
                className={
                  detailTab === key
                    ? "inline-flex items-center gap-1.5 rounded bg-foreground px-3 py-1.5 text-background"
                    : "rounded border border-border px-3 py-1.5 hover:bg-accent"
                }
              >
                {key === "run" && <PlayCircle className="h-3.5 w-3.5" />}
                {label}
              </button>
            ))}
          </nav>
        )}

        <div className="mt-5">
          {editing ? (
            <RoleForm
              form={form}
              toolCatalog={toolCatalog}
              skillCatalog={skillCatalog}
              saving={saving}
              error={formError}
              isCreating={creating}
              templates={templates}
              templateRef={templateRef}
              applyingTemplate={applyingTemplate}
              onSelectTemplate={(ref) => void applyTemplate(ref)}
              onChange={setForm}
              onSubmit={() => void submitForm()}
              onCancel={() => {
                if (creating) {
                  setView("list");
                } else {
                  setEditing(false);
                  setForm(profile ? formFromProfile(profile) : blankForm());
                }
                setFormError("");
              }}
            />
          ) : (
            profile &&
            (detailTab === "profile" ? (
              <dl className="space-y-4 text-sm" data-testid="role-profile-view">
                <div>
                  <dt className="text-xs font-medium text-muted-foreground">
                    {t("roleSquare.form.purpose")}
                  </dt>
                  <dd className="mt-1 text-foreground">{profile.purpose || "—"}</dd>
                </div>
                {profile.derived_from && (
                  <div data-testid="role-derived-from">
                    <dt className="text-xs font-medium text-muted-foreground">
                      {t("roleSquare.form.derivedFrom")}
                    </dt>
                    <dd className="mt-1 text-foreground">
                      <code className="rounded bg-foreground/10 px-1.5 py-0.5 text-[11px]">
                        {profile.derived_from}
                      </code>
                    </dd>
                  </div>
                )}
                <div>
                  <dt className="text-xs font-medium text-muted-foreground">
                    {t("roleSquare.form.systemPrompt")}
                  </dt>
                  <dd className="mt-1 whitespace-pre-wrap rounded border border-border bg-background p-3 font-mono text-xs">
                    {profile.system_prompt}
                  </dd>
                </div>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">
                      {t("roleSquare.form.tools")}
                    </dt>
                    <dd className="mt-1 flex flex-wrap gap-1">
                      {profile.tools.length ? (
                        profile.tools.map((tool) => (
                          <code
                            key={tool}
                            className="rounded bg-foreground/10 px-1.5 py-0.5 text-[11px]"
                          >
                            {tool}
                          </code>
                        ))
                      ) : (
                        <span className="text-xs">—</span>
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">
                      {t("roleSquare.form.skills")}
                    </dt>
                    <dd className="mt-1 flex flex-wrap gap-1">
                      {profile.skills.length ? (
                        profile.skills.map((skill) => (
                          <code
                            key={skill}
                            className="rounded bg-foreground/10 px-1.5 py-0.5 text-[11px]"
                          >
                            {skill}
                          </code>
                        ))
                      ) : (
                        <span className="text-xs">—</span>
                      )}
                    </dd>
                  </div>
                </div>
                <div className="flex gap-6 text-xs text-muted-foreground">
                  <span>
                    {t("roleSquare.form.maxIterations")}: {profile.max_iterations}
                  </span>
                  <span>
                    {t("roleSquare.form.timeoutSeconds")}: {profile.timeout_seconds}
                  </span>
                </div>
                {profile.kind === "builtin" && (
                  <p className="text-[11px] text-muted-foreground">
                    {t("roleSquare.detail.builtinReadonly")}
                  </p>
                )}
              </dl>
            ) : detailTab === "run" ? (
              <div className="space-y-3 rounded-lg border border-border bg-card p-4" data-testid="role-run-panel">
                <p className="text-xs text-muted-foreground">
                  {t("roleSquare.run.hint")}
                </p>
                <input
                  value={runTarget}
                  onChange={(e) => setRunTarget(e.target.value)}
                  data-testid="role-run-target"
                  placeholder={t("roleSquare.run.targetPlaceholder")}
                  className="w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
                />
                <textarea
                  value={runQuestion}
                  onChange={(e) => setRunQuestion(e.target.value)}
                  rows={3}
                  data-testid="role-run-question"
                  placeholder={t("roleSquare.run.questionPlaceholder")}
                  className="w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
                />
                <button
                  type="button"
                  disabled={launching || !runTarget.trim() || !runQuestion.trim()}
                  onClick={() => void launchRoleRun()}
                  data-testid="role-run-launch"
                  className="inline-flex items-center gap-1.5 rounded bg-foreground px-3 py-1.5 text-sm text-background disabled:opacity-40"
                >
                  {launching ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <PlayCircle className="h-4 w-4" />
                  )}
                  {t("roleSquare.run.launch")}
                </button>
                {runError && (
                  <p className="text-xs text-destructive" data-testid="role-run-error">
                    {runError}
                  </p>
                )}
              </div>
            ) : (
              <HistoryList
                runs={history}
                loading={historyLoading}
                error={historyError}
                onSearch={(filters) => profile && void loadHistory(profile.ref, filters)}
                onOpen={(runId) => {
                  setActiveRunId(runId);
                  setView("run");
                }}
              />
            ))
          )}
        </div>
      </div>
    );
  }

  // -----------------------------------------------------------------
  // My evaluations view
  // -----------------------------------------------------------------

  if (view === "myEvals") {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-8" data-testid="role-square-page">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <button
              type="button"
              onClick={() => setView("list")}
              data-testid="my-evals-back"
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              ← {t("roleSquare.detail.backToList")}
            </button>
            <h1 className="mt-1 font-serif text-2xl text-foreground">
              {t("roleSquare.tabs.myEvaluations")}
            </h1>
          </div>
        </header>
        <MacroEvalHistory
          records={myEvalRecords}
          loading={evalData.loading}
          error={evalData.error}
          testId="my-evaluations-history"
          variant="role"
          onView={(record) => {
            setActiveRunId(record.runId);
            setRunReturnTo("myEvals");
            setView("run");
          }}
        />
      </div>
    );
  }

  // -----------------------------------------------------------------
  // List view
  // -----------------------------------------------------------------

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8" data-testid="role-square-page">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-serif text-2xl text-foreground">
            {t("roleSquare.title")}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("roleSquare.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setView("myEvals")}
            data-testid="my-evaluations-btn"
            className="inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-sm text-foreground hover:bg-accent"
          >
            {t("roleSquare.tabs.myEvaluations")}
          </button>
          <button
            type="button"
            onClick={startCreate}
            data-testid="create-role-btn"
            className="inline-flex items-center gap-1.5 rounded bg-foreground px-3 py-1.5 text-sm text-background"
          >
            <Plus className="h-4 w-4" />
            {t("roleSquare.list.create")}
          </button>
        </div>
      </header>

      {listLoading ? (
        <p className="mt-8 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("roleSquare.list.loading")}
        </p>
      ) : (
        <div className="mt-6 space-y-4" data-testid="role-groups">
          {listError && (
            <div className="flex items-center gap-3 text-sm text-destructive">
              <p>{listError}</p>
              <button
                type="button"
                data-testid="role-list-retry-btn"
                className="rounded border border-border px-2 py-1 text-xs text-foreground hover:bg-accent"
                onClick={() => void loadList()}
              >
                {t("roleSquare.list.retry")}
              </button>
            </div>
          )}
          {groups.map((group) => (
            <RoleGroupSection
              key={group.ref}
              group={group}
              onOpen={(ref) => void openDetail(ref)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
