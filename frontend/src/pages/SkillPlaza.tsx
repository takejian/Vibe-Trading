import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BadgeCheck,
  FlaskConical,
  Loader2,
  PackageOpen,
  Pencil,
  PlayCircle,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import {
  api,
  type SkillCapabilities,
  type SkillCatalogEntry,
  type SkillProfile,
  type SkillSyncResult,
  type SwarmRunSummary,
} from "@/lib/api";
import { RunView } from "@/components/swarm/RunView";
import { HistoryList, type HistoryFilters } from "@/components/swarm/HistoryList";

type TopTab = "plaza" | "evaluations";
type View = "list" | "detail" | "run";
type DetailTab = "profile" | "run" | "history";

const NAME_MAX = 80;
const PURPOSE_MAX = 200;
const METHODOLOGY_MAX = 20000;
const IO_MAX = 4000;

// Mirrors SKILL_CATEGORY_ORDER in src/swarm/skill_catalog.py — built-in
// skills are laid out in the same financial-research taxonomy as teams in
// the Role Square, with one extra "data_toolkit" bucket for data adapters
// and general research tooling.
const CATEGORY_ORDER = [
  "technical",
  "fundamental",
  "macro",
  "quant",
  "sentiment",
  "event_driven",
  "allocation",
  "fixed_income_derivatives",
  "alternatives",
  "risk",
  "data_toolkit",
  "other",
] as const;
const ALL_CATEGORIES = "all";

function categoryRank(id: string): number {
  const index = CATEGORY_ORDER.indexOf(id as (typeof CATEGORY_ORDER)[number]);
  return index === -1 ? CATEGORY_ORDER.length : index;
}

// ---------------------------------------------------------------------------
// Skill create/edit form (the five business elements)
// ---------------------------------------------------------------------------

interface SkillFormState {
  name: string;
  purpose: string;
  methodology: string;
  inputs: string;
  outputs: string;
}

function blankForm(): SkillFormState {
  return { name: "", purpose: "", methodology: "", inputs: "", outputs: "" };
}

function formFromProfile(profile: SkillProfile): SkillFormState {
  return {
    name: profile.name,
    purpose: profile.purpose,
    methodology: profile.methodology,
    inputs: profile.inputs,
    outputs: profile.outputs,
  };
}

interface SkillFormProps {
  form: SkillFormState;
  saving: boolean;
  error: string;
  isCreating: boolean;
  templates: SkillCatalogEntry[];
  templateRef: string;
  applyingTemplate: boolean;
  onSelectTemplate: (ref: string) => void;
  onChange: (next: SkillFormState) => void;
  onSubmit: () => void;
  onCancel: () => void;
}

function SkillForm({
  form,
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
}: SkillFormProps) {
  const { t } = useTranslation();
  const nameValid = form.name.trim().length > 0 && form.name.length <= NAME_MAX;
  const methodologyValid =
    form.methodology.trim().length > 0 &&
    form.methodology.length <= METHODOLOGY_MAX;
  const canSubmit = nameValid && methodologyValid && !saving;

  return (
    <div className="space-y-4" data-testid="skill-form">
      {isCreating && (
        <div data-testid="skill-template-picker">
          <label className="block">
            <span className="text-xs font-medium text-foreground">
              {t("skillPlaza.form.template")}
            </span>
            <select
              value={templateRef}
              disabled={applyingTemplate}
              onChange={(e) => onSelectTemplate(e.target.value)}
              data-testid="skill-form-template"
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
            >
              <option value="">{t("skillPlaza.form.templateNone")}</option>
              {templates.map((item) => (
                <option key={item.ref} value={item.ref}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {applyingTemplate
              ? t("skillPlaza.form.templateApplying")
              : t("skillPlaza.form.templateHint")}
          </p>
        </div>
      )}

      <label className="block">
        <span className="text-xs font-medium text-foreground">
          {t("skillPlaza.form.name")}
        </span>
        <input
          value={form.name}
          onChange={(e) => onChange({ ...form, name: e.target.value })}
          maxLength={NAME_MAX}
          data-testid="skill-form-name"
          className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
        />
        {!nameValid && (
          <span className="mt-1 block text-xs text-red-600">
            {t("skillPlaza.form.nameInvalid", { number: NAME_MAX })}
          </span>
        )}
      </label>

      <label className="block">
        <span className="text-xs font-medium text-foreground">
          {t("skillPlaza.form.purpose")}
        </span>
        <input
          value={form.purpose}
          onChange={(e) => onChange({ ...form, purpose: e.target.value })}
          maxLength={PURPOSE_MAX}
          data-testid="skill-form-purpose"
          className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
        />
      </label>

      <label className="block">
        <span className="text-xs font-medium text-foreground">
          {t("skillPlaza.form.methodology")}
        </span>
        <textarea
          value={form.methodology}
          onChange={(e) => onChange({ ...form, methodology: e.target.value })}
          rows={10}
          maxLength={METHODOLOGY_MAX}
          data-testid="skill-form-methodology"
          className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm font-mono"
        />
        {!methodologyValid && (
          <span className="mt-1 block text-xs text-red-600">
            {t("skillPlaza.form.methodologyInvalid", {
              number: METHODOLOGY_MAX,
            })}
          </span>
        )}
      </label>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <label className="block">
          <span className="text-xs font-medium text-foreground">
            {t("skillPlaza.form.inputs")}
          </span>
          <textarea
            value={form.inputs}
            onChange={(e) => onChange({ ...form, inputs: e.target.value })}
            rows={5}
            maxLength={IO_MAX}
            data-testid="skill-form-inputs"
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs font-medium text-foreground">
            {t("skillPlaza.form.outputs")}
          </span>
          <textarea
            value={form.outputs}
            onChange={(e) => onChange({ ...form, outputs: e.target.value })}
            rows={5}
            maxLength={IO_MAX}
            data-testid="skill-form-outputs"
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
          />
        </label>
      </div>

      {error && (
        <p className="text-xs text-destructive" data-testid="skill-form-error">
          {error}
        </p>
      )}

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
          data-testid="skill-form-cancel"
        >
          {t("skillPlaza.form.cancel")}
        </button>
        <button
          type="button"
          disabled={!canSubmit}
          onClick={onSubmit}
          data-testid="skill-form-submit"
          className="rounded bg-foreground px-3 py-1.5 text-xs text-background disabled:opacity-40"
        >
          {saving
            ? t("skillPlaza.form.saving")
            : isCreating
              ? t("skillPlaza.form.saveAs")
              : t("skillPlaza.form.save")}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill card + sections
// ---------------------------------------------------------------------------

function SkillCard({
  entry,
  onOpen,
}: {
  entry: SkillCatalogEntry;
  onOpen: (ref: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(entry.ref)}
        data-testid={`skill-card-${entry.name}`}
        className="flex w-full flex-col rounded border border-border bg-background px-3 py-2 text-left hover:bg-accent"
      >
        <span className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium text-foreground">
            {entry.name}
          </span>
          {entry.approved ? (
            <BadgeCheck
              className="h-3.5 w-3.5 shrink-0 text-emerald-600"
              aria-label={t("skillPlaza.list.approved")}
            />
          ) : entry.kind === "custom" ? (
            <span
              className="rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-700 dark:text-amber-400"
              data-testid={`unapproved-badge-${entry.name}`}
            >
              {t("skillPlaza.list.unapprovedMine")}
            </span>
          ) : null}
        </span>
        <span className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">
          {entry.description || "—"}
        </span>
        {entry.kind === "custom" && entry.approved && (
          <span className="mt-1 text-[10px] text-muted-foreground">
            {t("skillPlaza.list.approvedMine")}
          </span>
        )}
      </button>
    </li>
  );
}

const CARD_GRID_CLASS =
  "grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3";

// Built-in skills: one shared name search, category filter chips, and the
// cards grouped by financial research category.
function BuiltinSkillsSection({
  entries,
  onOpen,
}: {
  entries: SkillCatalogEntry[];
  onOpen: (ref: string) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>(ALL_CATEGORIES);

  const needle = query.trim().toLowerCase();
  const searched = entries.filter(
    (entry) => !needle || entry.name.toLowerCase().includes(needle),
  );

  const byCategory = useMemo(() => {
    const buckets = new Map<string, SkillCatalogEntry[]>();
    for (const entry of searched) {
      const category = entry.finance_category || "other";
      const list = buckets.get(category);
      if (list) {
        list.push(entry);
      } else {
        buckets.set(category, [entry]);
      }
    }
    return [...buckets.entries()].sort(
      ([a], [b]) => categoryRank(a) - categoryRank(b),
    );
  }, [searched]);

  const visibleCategories = byCategory.filter(
    ([category]) =>
      activeCategory === ALL_CATEGORIES || category === activeCategory,
  );

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            {t("skillPlaza.groups.builtin")}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {t("skillPlaza.groups.builtinHint")}
          </p>
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label={t("skillPlaza.list.groupSearch")}
          placeholder={t("skillPlaza.list.groupSearch")}
          data-testid="group-search-builtin"
          className="rounded border border-border bg-background px-2 py-1 text-xs"
        />
      </div>

      {byCategory.length > 1 && (
        <div
          className="mt-3 flex flex-wrap gap-2"
          role="group"
          aria-label={t("swarmStudio.gallery.categoryFilterLabel")}
          data-testid="skill-category-filter"
        >
          <button
            key={ALL_CATEGORIES}
            type="button"
            onClick={() => setActiveCategory(ALL_CATEGORIES)}
            aria-pressed={activeCategory === ALL_CATEGORIES}
            data-testid="skill-filter-all"
            className={`rounded-full border px-3 py-1 text-xs transition-colors ${
              activeCategory === ALL_CATEGORIES
                ? "border-foreground bg-foreground text-background"
                : "border-border bg-card text-muted-foreground hover:border-foreground/50"
            }`}
          >
            {t("swarmStudio.gallery.allCategories")}
          </button>
          {byCategory.map(([category, categoryEntries]) => (
            <button
              key={category}
              type="button"
              onClick={() => setActiveCategory(category)}
              aria-pressed={activeCategory === category}
              data-testid={`skill-filter-${category}`}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                activeCategory === category
                  ? "border-foreground bg-foreground text-background"
                  : "border-border bg-card text-muted-foreground hover:border-foreground/50"
              }`}
            >
              {t(`swarmStudio.category.${category}`, { defaultValue: category })}
              <span className="ml-1 opacity-70">{categoryEntries.length}</span>
            </button>
          ))}
        </div>
      )}

      <div className="mt-3 space-y-4" data-testid="skill-group-builtin">
        {visibleCategories.map(([category, categoryEntries]) => (
          <div key={category} data-testid={`skill-category-${category}`}>
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {t(`swarmStudio.category.${category}`, { defaultValue: category })}
            </h4>
            <ul className={CARD_GRID_CLASS}>
              {categoryEntries.map((entry) => (
                <SkillCard key={entry.ref} entry={entry} onOpen={onOpen} />
              ))}
            </ul>
          </div>
        ))}
      </div>
      {byCategory.length === 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          {needle
            ? t("skillPlaza.list.noMatchInGroup")
            : t("skillPlaza.list.emptyGroup")}
        </p>
      )}
    </section>
  );
}

// Custom skills keep a single standalone group with its own name search.
function SkillGroupSection({
  title,
  hint,
  entries,
  onOpen,
}: {
  title: string;
  hint: string;
  entries: SkillCatalogEntry[];
  onOpen: (ref: string) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");

  const needle = query.trim().toLowerCase();
  const visible = entries.filter(
    (entry) => !needle || entry.name.toLowerCase().includes(needle),
  );

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label={t("skillPlaza.list.groupSearch")}
          placeholder={t("skillPlaza.list.groupSearch")}
          data-testid="group-search-custom"
          className="rounded border border-border bg-background px-2 py-1 text-xs"
        />
      </div>
      <ul className={`mt-3 ${CARD_GRID_CLASS}`} data-testid="skill-group-custom">
        {visible.map((entry) => (
          <SkillCard key={entry.ref} entry={entry} onOpen={onOpen} />
        ))}
      </ul>
      {visible.length === 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          {query
            ? t("skillPlaza.list.noMatchInGroup")
            : t("skillPlaza.list.emptyGroup")}
        </p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function SkillPlaza() {
  const { t } = useTranslation();

  const [topTab, setTopTab] = useState<TopTab>("plaza");
  const [view, setView] = useState<View>("list");

  const [catalog, setCatalog] = useState<SkillCatalogEntry[]>([]);
  const [capabilities, setCapabilities] = useState<SkillCapabilities | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [profile, setProfile] = useState<SkillProfile | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("profile");
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<SkillFormState>(blankForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [templateRef, setTemplateRef] = useState("");
  const [applyingTemplate, setApplyingTemplate] = useState(false);
  const [hasQualifiedTrial, setHasQualifiedTrial] = useState(false);

  const [runTarget, setRunTarget] = useState("");
  const [runQuestion, setRunQuestion] = useState("");
  const [launching, setLaunching] = useState(false);
  const [runError, setRunError] = useState("");

  const [history, setHistory] = useState<SwarmRunSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [historyScopeAll, setHistoryScopeAll] = useState(false);

  const [activeRunId, setActiveRunId] = useState("");
  // Where the RunView back button lands: the skill detail, or the
  // "My evaluations" list when the run was opened from there.
  const [runReturn, setRunReturn] = useState<"list" | "detail">("detail");

  // Personal zip import.
  const [personalImporting, setPersonalImporting] = useState(false);
  const [personalMessage, setPersonalMessage] = useState("");
  const [personalError, setPersonalError] = useState("");

  // Admin zone (migrated from the old orchestration-page SkillSquare).
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [adminMessage, setAdminMessage] = useState("");
  const [adminError, setAdminError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<SkillSyncResult | null>(null);

  // "My evaluations" tab state.
  const [evaluations, setEvaluations] = useState<SwarmRunSummary[]>([]);
  const [evaluationsLoading, setEvaluationsLoading] = useState(false);
  const [evaluationsError, setEvaluationsError] = useState("");
  const [evalSkill, setEvalSkill] = useState("");
  const [evalTarget, setEvalTarget] = useState("");
  const [evalFrom, setEvalFrom] = useState("");
  const [evalTo, setEvalTo] = useState("");

  const adminEnabled = capabilities?.admin_enabled ?? false;

  const loadList = useCallback(async () => {
    setListLoading(true);
    setListError("");
    try {
      const [catalogRes, caps] = await Promise.all([
        api.getSkillCatalog(),
        api.getSkillCapabilities().catch(() => ({
          admin_enabled: false,
          sync_source_configured: false,
        })),
      ]);
      setCatalog(catalogRes.skills);
      setCapabilities(caps);
    } catch (err) {
      setListError(err instanceof Error ? err.message : t("skillPlaza.list.loadError"));
    } finally {
      setListLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const builtinEntries = useMemo(
    () => catalog.filter((entry) => entry.kind !== "custom"),
    [catalog],
  );
  const customEntries = useMemo(
    () => catalog.filter((entry) => entry.kind === "custom"),
    [catalog],
  );

  // Only currently approved skills may serve as a "save as new" template.
  const templates = useMemo<SkillCatalogEntry[]>(
    () =>
      catalog
        .filter((entry) => entry.approved)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [catalog],
  );

  const openDetail = useCallback(
    async (ref: string) => {
      try {
        const detail = await api.getSkillDetail(ref);
        setProfile(detail);
        setForm(formFromProfile(detail));
        setDetailTab("profile");
        setEditing(false);
        setCreating(false);
        setFormError("");
        setTemplateRef("");
        setApplyingTemplate(false);
        setHasQualifiedTrial(false);
        setRunTarget("");
        setRunQuestion("");
        setRunError("");
        setHistory([]);
        setHistoryScopeAll(false);
        setView("detail");

        // Operator gating needs to know whether a qualified trial exists.
        if (detail.kind === "custom") {
          try {
            const rows = await api.listSkillTrials({
              skillName: detail.name,
              limit: 100,
            });
            setHasQualifiedTrial(
              rows.some(
                (row) =>
                  row.status === "completed" &&
                  (row.qualified === true ||
                    Boolean((row.final_report_excerpt ?? "").trim())),
              ),
            );
          } catch {
            /* approve button stays conservative; the 409 response is the
               authoritative gate and its message surfaces on click. */
          }
        }
      } catch (err) {
        setListError(err instanceof Error ? err.message : t("skillPlaza.list.loadError"));
      }
    },
    [t],
  );

  const loadHistory = useCallback(
    async (skillName: string, filters?: HistoryFilters, scopeAll = false) => {
      setHistoryLoading(true);
      setHistoryError("");
      try {
        const rows = await api.listSkillTrials({
          skillName,
          target: filters?.target || undefined,
          from: filters?.from || undefined,
          to: filters?.to || undefined,
          scope: scopeAll ? "all" : "mine",
          limit: 100,
        });
        setHistory(rows);
      } catch {
        setHistoryError(t("skillPlaza.history.loadError"));
      } finally {
        setHistoryLoading(false);
      }
    },
    [t],
  );

  const switchTab = (tab: DetailTab) => {
    setDetailTab(tab);
    if (tab === "history" && profile) {
      void loadHistory(profile.name, undefined, historyScopeAll);
    }
  };

  const toggleHistoryScope = (all: boolean) => {
    setHistoryScopeAll(all);
    if (profile && detailTab === "history") {
      void loadHistory(profile.name, undefined, all);
    }
  };

  const loadEvaluations = useCallback(async () => {
    setEvaluationsLoading(true);
    setEvaluationsError("");
    try {
      const rows = await api.listSkillTrials({ limit: 100, scope: "mine" });
      setEvaluations(rows);
    } catch {
      setEvaluationsError(t("skillPlaza.evaluations.loadError"));
    } finally {
      setEvaluationsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (topTab === "evaluations" && view === "list") void loadEvaluations();
  }, [topTab, view, loadEvaluations]);

  const filteredEvaluations = useMemo(() => {
    const skillNeedle = evalSkill.trim().toLowerCase();
    const targetNeedle = evalTarget.trim().toLowerCase();
    return evaluations.filter((row) => {
      if (
        skillNeedle &&
        !(row.trial_skill ?? row.preset_name).toLowerCase().includes(skillNeedle)
      )
        return false;
      if (targetNeedle && !(row.research_target ?? "").toLowerCase().includes(targetNeedle))
        return false;
      if (evalFrom || evalTo) {
        const createdDay = row.created_at.slice(0, 10);
        if (evalFrom && createdDay < evalFrom) return false;
        if (evalTo && createdDay > evalTo) return false;
      }
      return true;
    });
  }, [evaluations, evalSkill, evalTarget, evalFrom, evalTo]);

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

  const startDerive = () => {
    if (!profile) return;
    setForm({ ...formFromProfile(profile), name: "" });
    setTemplateRef(profile.ref);
    setFormError("");
    setCreating(true);
    setEditing(true);
    setProfile(null);
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
        const detail = await api.getSkillDetail(ref);
        // The name is intentionally never copied: a derived skill needs a
        // new, globally unique name.
        setForm((current) => ({
          ...current,
          purpose: detail.purpose,
          methodology: detail.methodology,
          inputs: detail.inputs,
          outputs: detail.outputs,
        }));
      } catch (err) {
        setFormError(
          err instanceof Error
            ? err.message
            : t("skillPlaza.form.templateLoadFailed"),
        );
      } finally {
        setApplyingTemplate(false);
      }
    },
    [t],
  );

  const submitForm = async () => {
    setSaving(true);
    setFormError("");
    const body = {
      name: form.name.trim(),
      purpose: form.purpose.trim(),
      methodology: form.methodology.trim(),
      inputs: form.inputs.trim(),
      outputs: form.outputs.trim(),
      ...(creating && templateRef ? { template_ref: templateRef } : {}),
    };
    try {
      if (creating) {
        const created = await api.createCustomSkill(body);
        await loadList();
        await openDetail(created.id);
      } else if (profile) {
        const updated = await api.updateCustomSkill(profile.ref, body);
        await loadList();
        await openDetail(updated.id);
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : t("skillPlaza.form.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const deleteSkill = async () => {
    if (!profile) return;
    const confirmed = window.confirm(t("skillPlaza.detail.deleteConfirm"));
    if (!confirmed) return;
    try {
      await api.deleteCustomSkill(profile.ref);
      await loadList();
      setView("list");
    } catch (err) {
      setFormError(err instanceof Error ? err.message : t("skillPlaza.detail.deleteFailed"));
    }
  };

  const approve = async () => {
    if (!profile) return;
    setFormError("");
    try {
      await api.approveCustomSkill(profile.ref);
      await loadList();
      await openDetail(profile.ref);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : t("skillPlaza.detail.approveFailed"));
    }
  };

  const unapprove = async () => {
    if (!profile) return;
    setFormError("");
    try {
      await api.unapproveCustomSkill(profile.ref);
      await loadList();
      await openDetail(profile.ref);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : t("skillPlaza.detail.approveFailed"));
    }
  };

  const launchTrial = async () => {
    if (!profile) return;
    if (!runTarget.trim() || !runQuestion.trim()) return;
    setLaunching(true);
    setRunError("");
    try {
      const run = await api.createSkillTrial({
        skill_name: profile.name,
        target: runTarget.trim(),
        question: runQuestion.trim(),
      });
      setActiveRunId(run.id);
      setRunReturn("detail");
      setView("run");
    } catch (err) {
      setRunError(err instanceof Error ? err.message : t("skillPlaza.run.launchFailed"));
    } finally {
      setLaunching(false);
    }
  };

  const doPersonalImport = async (file: File) => {
    setPersonalImporting(true);
    setPersonalError("");
    setPersonalMessage("");
    try {
      const result = await api.importPersonalSkillPackage(file);
      setPersonalMessage(
        t("skillPlaza.personal.importDone", { number: result.installed.length }),
      );
      await loadList();
    } catch (err) {
      setPersonalError(err instanceof Error ? err.message : t("skillPlaza.personal.importFailed"));
    } finally {
      setPersonalImporting(false);
    }
  };

  const doAdminImport = async () => {
    if (!importFile) return;
    setImporting(true);
    setAdminError("");
    setAdminMessage("");
    try {
      const result = await api.importSkillPackage(importFile);
      setAdminMessage(
        t("skillPlaza.admin.importDone", { number: result.installed.length }),
      );
      setImportFile(null);
      await loadList();
    } catch (err) {
      setAdminError(err instanceof Error ? err.message : t("skillPlaza.admin.importFailed"));
    } finally {
      setImporting(false);
    }
  };

  const doSync = async () => {
    setSyncing(true);
    setAdminError("");
    setAdminMessage("");
    setSyncResult(null);
    try {
      const result = await api.syncSkills();
      setSyncResult(result);
      await loadList();
    } catch (err) {
      setAdminError(err instanceof Error ? err.message : t("skillPlaza.admin.syncFailed"));
    } finally {
      setSyncing(false);
    }
  };

  // -----------------------------------------------------------------
  // Run view
  // -----------------------------------------------------------------

  if (view === "run" && activeRunId) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-8" data-testid="skill-plaza-page">
        <RunView
          runId={activeRunId}
          onBack={() => {
            setActiveRunId("");
            setView(runReturn);
            if (runReturn === "list") {
              void loadEvaluations();
            } else if (profile) {
              void loadHistory(profile.name, undefined, historyScopeAll);
            }
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
      <div className="mx-auto w-full max-w-5xl px-4 py-8" data-testid="skill-plaza-page">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <button
              type="button"
              onClick={() => {
                setView("list");
                void loadList();
              }}
              data-testid="back-to-skill-list"
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              ← {t("skillPlaza.detail.backToList")}
            </button>
            <h1 className="mt-1 flex flex-wrap items-center gap-2 font-serif text-2xl text-foreground">
              <span className="truncate">
                {creating ? t("skillPlaza.detail.createTitle") : profile?.name}
              </span>
              {profile?.approved && (
                <span
                  className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-700 dark:text-emerald-400"
                  data-testid="skill-approved-badge"
                >
                  <BadgeCheck className="h-3 w-3" />
                  {isCustom
                    ? t("skillPlaza.list.approvedMine")
                    : t("skillPlaza.list.approved")}
                </span>
              )}
              {isCustom && !profile?.approved && (
                <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-700 dark:text-amber-400">
                  {t("skillPlaza.list.unapprovedMine")}
                </span>
              )}
            </h1>
          </div>

          {!creating && profile && (
            <div className="flex flex-wrap gap-2">
              {profile.approved && (
                <button
                  type="button"
                  onClick={startDerive}
                  data-testid="skill-derive-btn"
                  className="inline-flex items-center gap-1 rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
                >
                  <Plus className="h-3.5 w-3.5" />
                  {t("skillPlaza.detail.derive")}
                </button>
              )}
              {isCustom && !editing && (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      setForm(profile ? formFromProfile(profile) : blankForm());
                      setEditing(true);
                    }}
                    data-testid="skill-edit-btn"
                    className="inline-flex items-center gap-1 rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                    {t("skillPlaza.detail.edit")}
                  </button>
                  <button
                    type="button"
                    onClick={() => void deleteSkill()}
                    data-testid="skill-delete-btn"
                    className="inline-flex items-center gap-1 rounded border border-red-300 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 dark:border-red-900 dark:hover:bg-red-950/40"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {t("skillPlaza.detail.delete")}
                  </button>
                </>
              )}
              {adminEnabled && isCustom && (
                profile.approved ? (
                  <button
                    type="button"
                    onClick={() => void unapprove()}
                    data-testid="skill-unapprove-btn"
                    className="rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
                  >
                    {t("skillPlaza.detail.unapprove")}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => void approve()}
                    disabled={!hasQualifiedTrial}
                    data-testid="skill-approve-btn"
                    title={
                      hasQualifiedTrial
                        ? undefined
                        : t("skillPlaza.detail.approvePrerequisite")
                    }
                    className="rounded bg-foreground px-3 py-1.5 text-xs text-background disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {t("skillPlaza.detail.approve")}
                  </button>
                )
              )}
            </div>
          )}
        </header>

        {!creating && profile && !profile.approved && isCustom && adminEnabled && (
          <p
            className="mt-2 text-[11px] text-muted-foreground"
            data-testid="skill-approve-hint"
          >
            {t("skillPlaza.detail.approvePrerequisite")}
          </p>
        )}

        {!creating && (
          <nav className="mt-4 flex gap-2 text-sm" data-testid="skill-detail-tabs">
            {(
              [
                ["profile", t("skillPlaza.tabs.profile")],
                ["run", t("skillPlaza.tabs.run")],
                ["history", t("skillPlaza.tabs.history")],
              ] as Array<[DetailTab, string]>
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => switchTab(key)}
                data-testid={`skill-tab-${key}`}
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
            <SkillForm
              form={form}
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
              <dl className="space-y-4 text-sm" data-testid="skill-profile-view">
                <div>
                  <dt className="text-xs font-medium text-muted-foreground">
                    {t("skillPlaza.form.purpose")}
                  </dt>
                  <dd className="mt-1 text-foreground">{profile.purpose || "—"}</dd>
                </div>
                {profile.derived_from && (
                  <div data-testid="skill-derived-from">
                    <dt className="text-xs font-medium text-muted-foreground">
                      {t("skillPlaza.detail.derivedFrom")}
                    </dt>
                    <dd className="mt-1 text-foreground">
                      <code className="rounded bg-foreground/10 px-1.5 py-0.5 text-[11px]">
                        {profile.derived_from}
                      </code>
                    </dd>
                  </div>
                )}
                <div data-testid="skill-used-by">
                  <dt className="text-xs font-medium text-muted-foreground">
                    {t("skillPlaza.detail.usedBy")}
                  </dt>
                  <dd className="mt-1 text-foreground">
                    {profile.used_by && profile.used_by.length > 0 ? (
                      <ul className="flex flex-wrap gap-1.5" data-testid="skill-used-by-list">
                        {profile.used_by.map((item) => (
                          <li
                            key={item.ref}
                            className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 text-[11px]"
                          >
                            <span className="font-medium">{item.name}</span>
                            <span className="text-muted-foreground">
                              · {item.source}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        {t("skillPlaza.detail.usedByNone")}
                      </span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-muted-foreground">
                    {t("skillPlaza.form.methodology")}
                  </dt>
                  <dd className="mt-1 whitespace-pre-wrap rounded border border-border bg-background p-3 font-mono text-xs">
                    {profile.methodology}
                  </dd>
                </div>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">
                      {t("skillPlaza.form.inputs")}
                    </dt>
                    <dd className="mt-1 whitespace-pre-wrap text-foreground">
                      {profile.inputs || "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-muted-foreground">
                      {t("skillPlaza.form.outputs")}
                    </dt>
                    <dd className="mt-1 whitespace-pre-wrap text-foreground">
                      {profile.outputs || "—"}
                    </dd>
                  </div>
                </div>
                {profile.kind === "assembled" && (
                  <p className="text-[11px] text-muted-foreground">
                    {t("skillPlaza.detail.assembledReadonly")}
                  </p>
                )}
              </dl>
            ) : detailTab === "run" ? (
              <div
                className="space-y-3 rounded-lg border border-border bg-card p-4"
                data-testid="skill-run-panel"
              >
                <p className="text-xs text-muted-foreground">
                  {t("skillPlaza.run.hint")}
                </p>
                <input
                  value={runTarget}
                  onChange={(e) => setRunTarget(e.target.value)}
                  data-testid="skill-run-target"
                  placeholder={t("skillPlaza.run.targetPlaceholder")}
                  className="w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
                />
                <textarea
                  value={runQuestion}
                  onChange={(e) => setRunQuestion(e.target.value)}
                  rows={3}
                  data-testid="skill-run-question"
                  placeholder={t("skillPlaza.run.questionPlaceholder")}
                  className="w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
                />
                <button
                  type="button"
                  disabled={launching || !runTarget.trim() || !runQuestion.trim()}
                  onClick={() => void launchTrial()}
                  data-testid="skill-run-launch"
                  className="inline-flex items-center gap-1.5 rounded bg-foreground px-3 py-1.5 text-sm text-background disabled:opacity-40"
                >
                  {launching ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <FlaskConical className="h-4 w-4" />
                  )}
                  {t("skillPlaza.run.launch")}
                </button>
                {runError && (
                  <p className="text-xs text-destructive" data-testid="skill-run-error">
                    {runError}
                  </p>
                )}
              </div>
            ) : (
              <div data-testid="skill-history-panel">
                {adminEnabled && isCustom && (
                  <label className="mb-2 inline-flex items-center gap-2 text-xs text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={historyScopeAll}
                      onChange={(e) => toggleHistoryScope(e.target.checked)}
                      data-testid="skill-history-scope-all"
                    />
                    {t("skillPlaza.history.scopeAll")}
                  </label>
                )}
                <HistoryList
                  runs={history}
                  loading={historyLoading}
                  error={historyError}
                  trialMode
                  onSearch={(filters) =>
                    profile &&
                    void loadHistory(profile.name, filters, historyScopeAll)
                  }
                  onOpen={(runId) => {
                    setActiveRunId(runId);
                    setRunReturn("detail");
                    setView("run");
                  }}
                />
              </div>
            ))
          )}
        </div>
      </div>
    );
  }

  // -----------------------------------------------------------------
  // List view — top tabs: plaza / my evaluations
  // -----------------------------------------------------------------

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8" data-testid="skill-plaza-page">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-serif text-2xl text-foreground">
            {t("skillPlaza.title")}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("skillPlaza.subtitle")}
          </p>
        </div>
        {topTab === "plaza" && (
          <div className="flex flex-wrap gap-2">
            <label
              className="inline-flex cursor-pointer items-center gap-1.5 rounded border border-border px-3 py-1.5 text-sm hover:bg-accent"
              data-testid="personal-import-label"
            >
              {personalImporting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4" />
              )}
              {t("skillPlaza.personal.button")}
              <input
                type="file"
                accept=".zip,application/zip"
                className="hidden"
                data-testid="personal-import-file"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void doPersonalImport(file);
                  e.target.value = "";
                }}
              />
            </label>
            <button
              type="button"
              onClick={startCreate}
              data-testid="create-skill-btn"
              className="inline-flex items-center gap-1.5 rounded bg-foreground px-3 py-1.5 text-sm text-background"
            >
              <Plus className="h-4 w-4" />
              {t("skillPlaza.list.create")}
            </button>
          </div>
        )}
      </header>

      <nav className="mt-4 flex gap-2 text-sm" data-testid="skill-plaza-tabs">
        {(
          [
            ["plaza", t("skillPlaza.tabs.plaza")],
            ["evaluations", t("skillPlaza.tabs.evaluations")],
          ] as Array<[TopTab, string]>
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTopTab(key)}
            data-testid={`plaza-tab-${key}`}
            className={
              topTab === key
                ? "rounded bg-foreground px-3 py-1.5 text-background"
                : "rounded border border-border px-3 py-1.5 hover:bg-accent"
            }
          >
            {label}
          </button>
        ))}
      </nav>

      {topTab === "plaza" ? (
        listLoading ? (
          <p className="mt-8 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("skillPlaza.list.loading")}
          </p>
        ) : (
          <div className="mt-6 space-y-4" data-testid="skill-groups">
            {listError && (
              <div className="flex items-center gap-3 text-sm text-destructive">
                <p>{listError}</p>
                <button
                  type="button"
                  data-testid="skill-list-retry-btn"
                  className="rounded border border-border px-2 py-1 text-xs text-foreground hover:bg-accent"
                  onClick={() => void loadList()}
                >
                  {t("skillPlaza.list.retry")}
                </button>
              </div>
            )}
            {(personalMessage || personalError) && (
              <div
                className="rounded border border-border bg-card p-3 text-xs"
                data-testid="personal-import-result"
              >
                {personalError ? (
                  <span className="text-destructive">{personalError}</span>
                ) : (
                  <span className="text-emerald-700 dark:text-emerald-400">
                    {personalMessage}
                  </span>
                )}
              </div>
            )}
            <BuiltinSkillsSection
              entries={builtinEntries}
              onOpen={(ref) => void openDetail(ref)}
            />
            <SkillGroupSection
              title={t("skillPlaza.groups.custom")}
              hint={t("skillPlaza.groups.customHint")}
              entries={customEntries}
              onOpen={(ref) => void openDetail(ref)}
            />

            {adminEnabled && (
              <section
                className="rounded-lg border border-border bg-card p-4"
                data-testid="skill-admin-zone"
              >
                <h2 className="text-sm font-semibold text-foreground">
                  {t("skillPlaza.admin.title")}
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("skillPlaza.admin.hint")}
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <label className="inline-flex items-center gap-2 rounded border border-border px-2 py-1.5 text-xs">
                    <PackageOpen className="h-3.5 w-3.5" />
                    <input
                      type="file"
                      accept=".zip,application/zip"
                      data-testid="skill-import-file"
                      onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={!importFile || importing}
                    onClick={() => void doAdminImport()}
                    data-testid="skill-import-btn"
                    className="inline-flex items-center gap-1 rounded bg-foreground px-3 py-1.5 text-xs text-background disabled:opacity-40"
                  >
                    <Upload className="h-3.5 w-3.5" />
                    {importing
                      ? t("skillPlaza.admin.importing")
                      : t("skillPlaza.admin.import")}
                  </button>
                  <button
                    type="button"
                    disabled={syncing}
                    onClick={() => void doSync()}
                    data-testid="skill-sync-btn"
                    className="inline-flex items-center gap-1 rounded border border-border px-3 py-1.5 text-xs hover:bg-accent disabled:opacity-40"
                  >
                    {syncing ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5" />
                    )}
                    {t("skillPlaza.admin.sync")}
                  </button>
                  {!capabilities?.sync_source_configured && (
                    <span className="text-[11px] text-muted-foreground">
                      {t("skillPlaza.admin.syncNotConfigured")}
                    </span>
                  )}
                </div>
                {adminMessage && (
                  <p
                    className="mt-2 text-xs text-emerald-700 dark:text-emerald-400"
                    data-testid="skill-admin-message"
                  >
                    {adminMessage}
                  </p>
                )}
                {adminError && (
                  <p className="mt-2 text-xs text-destructive" data-testid="skill-admin-error">
                    {adminError}
                  </p>
                )}
                {syncResult && (
                  <dl className="mt-3 grid grid-cols-2 gap-1 text-[11px] text-muted-foreground md:grid-cols-4">
                    <dt>{t("skillPlaza.admin.syncAdded", { number: syncResult.added.length })}</dt>
                    <dt>{t("skillPlaza.admin.syncUpdated", { number: syncResult.updated.length })}</dt>
                    <dt>{t("skillPlaza.admin.syncRemoved", { number: syncResult.removed.length })}</dt>
                    <dt>{t("skillPlaza.admin.syncRejected", { number: syncResult.rejected.length })}</dt>
                  </dl>
                )}
              </section>
            )}
          </div>
        )
      ) : (
        <section className="mt-6" data-testid="my-evaluations">
          <form
            className="flex flex-wrap items-end gap-2"
            data-testid="eval-filters"
            onSubmit={(e) => {
              e.preventDefault();
              void loadEvaluations();
            }}
          >
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              {t("skillPlaza.evaluations.filterSkill")}
              <input
                value={evalSkill}
                onChange={(e) => setEvalSkill(e.target.value)}
                data-testid="eval-filter-skill"
                placeholder={t("skillPlaza.evaluations.filterSkillPlaceholder")}
                className="w-40 rounded border border-border bg-background px-2 py-1.5 text-xs text-foreground"
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              {t("skillPlaza.evaluations.filterTarget")}
              <input
                value={evalTarget}
                onChange={(e) => setEvalTarget(e.target.value)}
                data-testid="eval-filter-target"
                placeholder={t("skillPlaza.evaluations.filterTargetPlaceholder")}
                className="w-44 rounded border border-border bg-background px-2 py-1.5 text-xs text-foreground"
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              {t("skillPlaza.evaluations.filterFrom")}
              <input
                type="date"
                value={evalFrom}
                onChange={(e) => setEvalFrom(e.target.value)}
                data-testid="eval-filter-from"
                className="rounded border border-border bg-background px-2 py-1.5 text-xs text-foreground"
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              {t("skillPlaza.evaluations.filterTo")}
              <input
                type="date"
                value={evalTo}
                onChange={(e) => setEvalTo(e.target.value)}
                data-testid="eval-filter-to"
                className="rounded border border-border bg-background px-2 py-1.5 text-xs text-foreground"
              />
            </label>
            <button
              type="submit"
              data-testid="eval-search"
              className="inline-flex items-center gap-1 rounded bg-foreground px-3 py-1.5 text-xs text-background"
            >
              {t("skillPlaza.evaluations.search")}
            </button>
            <button
              type="button"
              data-testid="eval-clear"
              onClick={() => {
                setEvalSkill("");
                setEvalTarget("");
                setEvalFrom("");
                setEvalTo("");
              }}
              className="inline-flex items-center gap-1 rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
            >
              {t("skillPlaza.evaluations.clear")}
            </button>
          </form>

          {evaluationsLoading ? (
            <p className="mt-8 flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("skillPlaza.evaluations.loading")}
            </p>
          ) : evaluationsError ? (
            <p className="mt-4 text-sm text-destructive">{evaluationsError}</p>
          ) : (
            <div className="mt-4 overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[820px] text-left text-xs">
                <thead className="bg-accent/40 text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">
                      {t("skillPlaza.evaluations.columnSkill")}
                    </th>
                    <th className="px-3 py-2 font-medium">
                      {t("swarmStudio.history.createdAt")}
                    </th>
                    <th className="px-3 py-2 font-medium">
                      {t("swarmStudio.history.target")}
                    </th>
                    <th className="px-3 py-2 font-medium">
                      {t("swarmStudio.history.question")}
                    </th>
                    <th className="px-3 py-2 font-medium">
                      {t("swarmStudio.history.statusLabel")}
                    </th>
                    <th className="px-3 py-2 font-medium">
                      {t("swarmStudio.history.excerpt")}
                    </th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {filteredEvaluations.map((row) => (
                    <tr key={row.id} className="border-t border-border align-top">
                      <td className="px-3 py-2 font-mono">
                        {row.trial_skill ?? row.preset_name}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {new Date(row.created_at).toLocaleString()}
                      </td>
                      <td className="px-3 py-2">{row.research_target || "—"}</td>
                      <td
                        className="max-w-[14rem] truncate px-3 py-2"
                        title={row.research_question ?? ""}
                      >
                        {row.research_question || "—"}
                      </td>
                      <td className="px-3 py-2">
                        {t(`swarmStudio.history.status.${row.status}`, {
                          defaultValue: row.status,
                        })}
                      </td>
                      <td
                        className="max-w-[18rem] truncate px-3 py-2 text-muted-foreground"
                        title={row.final_report_excerpt ?? ""}
                      >
                        {row.final_report_excerpt || "—"}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          type="button"
                          onClick={() => {
                            setActiveRunId(row.id);
                            setRunReturn("list");
                            setView("run");
                          }}
                          data-testid={`open-eval-${row.id}`}
                          className="rounded border border-border px-2 py-1 hover:bg-accent"
                        >
                          {t("swarmStudio.history.viewSnapshot")}
                        </button>
                      </td>
                    </tr>
                  ))}
                  {filteredEvaluations.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">
                        {t("skillPlaza.evaluations.empty")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
