import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BadgeCheck,
  FlaskConical,
  Loader2,
  PackageOpen,
  RefreshCw,
  Upload,
} from "lucide-react";
import {
  api,
  type SkillCapabilities,
  type SkillCatalogEntry,
  type SkillSyncResult,
  type SwarmRunSummary,
} from "@/lib/api";
import { HistoryList, type HistoryFilters } from "./HistoryList";

interface SkillSquareProps {
  onOpenRun: (runId: string) => void;
}

export function SkillSquare({ onOpenRun }: SkillSquareProps) {
  const { t } = useTranslation();

  const [catalog, setCatalog] = useState<SkillCatalogEntry[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [capabilities, setCapabilities] = useState<SkillCapabilities | null>(null);

  const [trials, setTrials] = useState<SwarmRunSummary[]>([]);
  const [trialsLoading, setTrialsLoading] = useState(false);
  const [trialsError, setTrialsError] = useState("");

  // Trial form (one shared form for the skill currently being tried).
  const [trialSkill, setTrialSkill] = useState("");
  const [target, setTarget] = useState("");
  const [question, setQuestion] = useState("");
  const [launching, setLaunching] = useState(false);
  const [trialError, setTrialError] = useState("");

  // Admin zone.
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [adminMessage, setAdminMessage] = useState("");
  const [adminError, setAdminError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<SkillSyncResult | null>(null);

  const refreshCatalog = useCallback(() => {
    setCatalogLoading(true);
    setCatalogError("");
    return Promise.all([api.getSkillCatalog(), api.getSkillCapabilities()])
      .then(([catalogRes, caps]) => {
        setCatalog(catalogRes.skills);
        setCapabilities(caps);
      })
      .catch(() => setCatalogError(t("swarmStudio.skills.loadError")))
      .finally(() => setCatalogLoading(false));
  }, [t]);

  const loadTrials = useCallback(
    (filters?: HistoryFilters) => {
      setTrialsLoading(true);
      setTrialsError("");
      api
        .listSkillTrials({
          target: filters?.target || undefined,
          from: filters?.from || undefined,
          to: filters?.to || undefined,
          limit: 100,
        })
        .then(setTrials)
        .catch(() => setTrialsError(t("swarmStudio.skills.trialsLoadError")))
        .finally(() => setTrialsLoading(false));
    },
    [t],
  );

  useEffect(() => {
    void refreshCatalog();
    loadTrials();
  }, [refreshCatalog, loadTrials]);

  const launchTrial = async () => {
    if (!trialSkill || !target.trim() || !question.trim()) return;
    setLaunching(true);
    setTrialError("");
    try {
      const run = await api.createSkillTrial({
        skill_name: trialSkill,
        target: target.trim(),
        question: question.trim(),
      });
      onOpenRun(run.id);
    } catch (err) {
      setTrialError(err instanceof Error ? err.message : t("swarmStudio.skills.trialFailed"));
    } finally {
      setLaunching(false);
    }
  };

  const doImport = async () => {
    if (!importFile) return;
    setImporting(true);
    setAdminError("");
    setAdminMessage("");
    try {
      const result = await api.importSkillPackage(importFile);
      setAdminMessage(
        t("swarmStudio.skills.importDone", {
          number: result.installed.length,
        }),
      );
      setImportFile(null);
      await refreshCatalog();
    } catch (err) {
      setAdminError(err instanceof Error ? err.message : t("swarmStudio.skills.importFailed"));
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
      await refreshCatalog();
      loadTrials();
    } catch (err) {
      setAdminError(err instanceof Error ? err.message : t("swarmStudio.skills.syncFailed"));
    } finally {
      setSyncing(false);
    }
  };

  if (catalogLoading) {
    return (
      <p className="mt-8 flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("swarmStudio.skills.loading")}
      </p>
    );
  }

  return (
    <div className="mt-6 space-y-8" data-testid="skill-square">
      {catalogError && <p className="text-sm text-destructive">{catalogError}</p>}

      <section>
        <h2 className="text-sm font-semibold text-foreground">
          {t("swarmStudio.skills.catalogTitle")}
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("swarmStudio.skills.catalogHint")}
        </p>
        <div
          className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3"
          data-testid="skill-catalog-grid"
        >
          {catalog.map((entry) => (
            <div
              key={entry.name}
              className="flex flex-col rounded-lg border border-border bg-card p-4"
              data-testid={`skill-card-${entry.name}`}
            >
              <div className="flex items-start justify-between gap-2">
                <code className="text-sm font-semibold text-foreground">{entry.name}</code>
                {entry.approved && (
                  <span
                    className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-700 dark:text-emerald-400"
                    title={t("swarmStudio.skills.approvedHint")}
                  >
                    <BadgeCheck className="h-3 w-3" />
                    {t("swarmStudio.skills.approved")}
                  </span>
                )}
              </div>
              <p className="mt-1 line-clamp-3 flex-1 text-xs text-muted-foreground">
                {entry.description || "—"}
              </p>
              <div className="mt-2 flex items-center justify-between">
                <span className="rounded-full bg-foreground/10 px-2 py-0.5 text-[10px] text-muted-foreground">
                  {entry.source === "user"
                    ? t("swarmStudio.skills.sourceUser")
                    : t("swarmStudio.skills.sourceBundled")}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    setTrialSkill(entry.name);
                    setTrialError("");
                  }}
                  data-testid={`skill-trial-set-${entry.name}`}
                  className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[11px] hover:bg-accent"
                >
                  <FlaskConical className="h-3 w-3" />
                  {t("swarmStudio.skills.trial")}
                </button>
              </div>
            </div>
          ))}
          {catalog.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("swarmStudio.skills.catalogEmpty")}</p>
          )}
        </div>
      </section>

      <section className="rounded-lg border border-border bg-card p-4">
        <h2 className="text-sm font-semibold text-foreground">
          {t("swarmStudio.skills.trialTitle")}
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">{t("swarmStudio.skills.trialHint")}</p>
        <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-[1fr_1fr_auto]">
          <input
            value={trialSkill}
            onChange={(e) => setTrialSkill(e.target.value)}
            data-testid="trial-skill-input"
            placeholder={t("swarmStudio.skills.trialSkillPlaceholder")}
            className="rounded border border-border bg-background px-2 py-1.5 text-sm"
          />
          <input
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            data-testid="trial-target-input"
            placeholder={t("swarmStudio.skills.trialTargetPlaceholder")}
            className="rounded border border-border bg-background px-2 py-1.5 text-sm"
          />
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            data-testid="trial-question-input"
            placeholder={t("swarmStudio.skills.trialQuestionPlaceholder")}
            className="rounded border border-border bg-background px-2 py-1.5 text-sm md:col-span-2"
          />
          <button
            type="button"
            disabled={launching || !trialSkill || !target.trim() || !question.trim()}
            onClick={() => void launchTrial()}
            data-testid="trial-launch-btn"
            className="inline-flex items-center justify-center gap-1.5 rounded bg-foreground px-3 py-1.5 text-sm text-background disabled:opacity-40 md:col-span-1"
          >
            {launching ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FlaskConical className="h-4 w-4" />
            )}
            {t("swarmStudio.skills.trialLaunch")}
          </button>
        </div>
        {trialError && (
          <p className="mt-2 text-xs text-destructive" data-testid="trial-error">
            {trialError}
          </p>
        )}
      </section>

      {capabilities?.admin_enabled && (
        <section
          className="rounded-lg border border-border bg-card p-4"
          data-testid="skill-admin-zone"
        >
          <h2 className="text-sm font-semibold text-foreground">
            {t("swarmStudio.skills.adminTitle")}
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("swarmStudio.skills.adminHint")}
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
              onClick={() => void doImport()}
              data-testid="skill-import-btn"
              className="inline-flex items-center gap-1 rounded bg-foreground px-3 py-1.5 text-xs text-background disabled:opacity-40"
            >
              <Upload className="h-3.5 w-3.5" />
              {importing ? t("swarmStudio.skills.importing") : t("swarmStudio.skills.import")}
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
              {t("swarmStudio.skills.sync")}
            </button>
            {!capabilities.sync_source_configured && (
              <span className="text-[11px] text-muted-foreground">
                {t("swarmStudio.skills.syncNotConfigured")}
              </span>
            )}
          </div>
          {adminMessage && (
            <p className="mt-2 text-xs text-emerald-700 dark:text-emerald-400" data-testid="skill-admin-message">
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
              <dt>{t("swarmStudio.skills.syncAdded", { number: syncResult.added.length })}</dt>
              <dt>{t("swarmStudio.skills.syncUpdated", { number: syncResult.updated.length })}</dt>
              <dt>{t("swarmStudio.skills.syncRemoved", { number: syncResult.removed.length })}</dt>
              <dt>{t("swarmStudio.skills.syncRejected", { number: syncResult.rejected.length })}</dt>
            </dl>
          )}
        </section>
      )}

      <section>
        <h2 className="text-sm font-semibold text-foreground">
          {t("swarmStudio.skills.trialsHistoryTitle")}
        </h2>
        <HistoryList
          runs={trials}
          loading={trialsLoading}
          error={trialsError}
          trialMode
          onSearch={loadTrials}
          onOpen={onOpenRun}
        />
      </section>
    </div>
  );
}
