import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, PlayCircle } from "lucide-react";
import {
  api,
  ApiError,
  type RoleGroup,
  type RoleGroupItem,
  type RoleProfile,
} from "@/lib/api";
import { RunView } from "@/components/swarm/RunView";
import {
  MACRO_ROLE_REFS,
  MACRO_ROLE_THEMES,
  splitRoleRef,
} from "./macroCatalog";
import { MacroEvalHistory } from "./MacroEvalHistory";
import { useMacroEvalData } from "./macroEvalRecords";

const testIdSafe = (ref: string) => ref.replace(/[^A-Za-z0-9_-]/g, "-");

export function MacroRoleTab() {
  const { t } = useTranslation();
  const [catalog, setCatalog] = useState<Record<string, RoleGroupItem>>({});
  const [groupTitles, setGroupTitles] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [selectedRef, setSelectedRef] = useState("");
  const [profile, setProfile] = useState<RoleProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [target, setTarget] = useState("");
  const [question, setQuestion] = useState("");
  const [launching, setLaunching] = useState(false);
  const [formError, setFormError] = useState("");
  const [activeRunId, setActiveRunId] = useState("");
  const evalData = useMacroEvalData();
  const macroRoleRefs = useMemo(() => new Set(MACRO_ROLE_REFS), []);
  const roleEvalRecords = useMemo(
    () =>
      evalData.records.filter(
        (record) =>
          record.kind === "role_run" && macroRoleRefs.has(record.roleRef),
      ),
    [evalData.records, macroRoleRefs],
  );
  // Clicking a role filters the history; the chip can be dismissed while the
  // role stays selected. Switching role re-arms the filter.
  const [roleFilterDismissed, setRoleFilterDismissed] = useState(false);
  useEffect(() => {
    setRoleFilterDismissed(false);
  }, [selectedRef]);
  const roleFilterName =
    selectedRef && !roleFilterDismissed
      ? profile?.name || selectedRef
      : "";
  const visibleRecords = roleFilterName
    ? roleEvalRecords.filter((record) => record.roleRef === selectedRef)
    : roleEvalRecords;

  useEffect(() => {
    let cancelled = false;
    api
      .listRoleGroups()
      .then((res: { groups: RoleGroup[] }) => {
        if (cancelled) return;
        const itemMap: Record<string, RoleGroupItem> = {};
        const titleMap: Record<string, string> = {};
        for (const group of res.groups) {
          titleMap[group.ref] = group.title;
          for (const item of group.roles) {
            itemMap[item.ref] = item;
          }
        }
        setCatalog(itemMap);
        setGroupTitles(titleMap);
      })
      .catch(() => {
        if (!cancelled) setLoadError(t("macro.roleTab.loadFailed"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const selectRole = useCallback(
    async (ref: string) => {
      setSelectedRef(ref);
      setProfile(null);
      setTarget("");
      setQuestion("");
      setFormError("");
      setProfileLoading(true);
      try {
        const resolved = await api.getRoleDetail(ref);
        setProfile(resolved);
      } catch {
        setFormError(t("macro.roleTab.detailFailed"));
      } finally {
        setProfileLoading(false);
      }
    },
    [t],
  );

  const launch = useCallback(async () => {
    if (!selectedRef) return;
    if (!target.trim() || !question.trim()) {
      setFormError(t("macro.roleTab.missingRequired"));
      return;
    }
    setLaunching(true);
    setFormError("");
    try {
      const run = await api.createRoleRun({
        role_ref: selectedRef,
        target: target.trim(),
        question: question.trim(),
      });
      setActiveRunId(run.id);
    } catch (error) {
      let message = t("macro.roleTab.launchFailed");
      if (error instanceof ApiError) {
        if (error.status === 409) message = t("macro.roleTab.inProgress");
        else if (error.message) message = error.message;
      }
      setFormError(message);
    } finally {
      setLaunching(false);
    }
  }, [question, selectedRef, t, target]);

  const themes = useMemo(() => MACRO_ROLE_THEMES, []);

  if (activeRunId) {
    return (
      <RunView
        runId={activeRunId}
        onBack={() => setActiveRunId("")}
      />
    );
  }

  const { presetName } = selectedRef ? splitRoleRef(selectedRef) : { presetName: "" };

  return (
    <div data-testid="macro-role-tab">
      <p className="text-xs leading-relaxed text-muted-foreground">
        {t("macro.roleTab.intro")}
      </p>

      {loading && (
        <div className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        </div>
      )}
      {loadError && (
        <p data-testid="macro-role-load-error" className="mt-6 text-sm text-destructive">
          {loadError}
        </p>
      )}

      {!loading && !loadError && (
        <div className="mt-4 grid gap-5 lg:grid-cols-[1fr_340px]">
          <div>
            {themes.map((theme) => (
              <section key={theme.themeKey} className="mb-5">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t(theme.themeKey as never)}
                </h2>
                <div className="mt-2 flex flex-wrap gap-2">
                  {theme.refs.map((ref) => {
                    const item = catalog[ref];
                    const isSelected = selectedRef === ref;
                    return (
                      <button
                        key={ref}
                        type="button"
                        data-testid={`macro-role-item-${testIdSafe(ref)}`}
                        aria-pressed={isSelected}
                        title={item?.purpose || ref}
                        onClick={() => selectRole(ref)}
                        className={
                          isSelected
                            ? "inline-flex max-w-full flex-col items-start rounded-lg border border-primary bg-primary/10 px-3 py-2 text-left text-xs"
                            : "inline-flex max-w-full flex-col items-start rounded-lg border border-border/60 bg-card px-3 py-2 text-left text-xs transition-colors hover:bg-muted"
                        }
                      >
                        <span className="truncate font-medium text-foreground">
                          {item?.name || ref}
                        </span>
                        <span className="truncate text-[10px] text-muted-foreground">
                          {splitRoleRef(ref).presetName}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>

          <aside className="lg:sticky lg:top-4 lg:self-start">
            <div
              data-testid="macro-role-detail"
              className="rounded-xl border border-border/60 bg-card p-4"
            >
              {!selectedRef && (
                <p className="text-xs text-muted-foreground">
                  {t("macro.roleTab.selectPrompt")}
                </p>
              )}
              {profileLoading && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  {t("macro.roleTab.loadingProfile")}
                </div>
              )}

              {selectedRef && !profileLoading && profile && (
                <>
                  <h3 className="text-sm font-semibold text-foreground">
                    {profile.name}
                  </h3>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    {t("macro.roleTab.sourceTeam", {
                      team: groupTitles[presetName] || presetName,
                    })}
                  </p>
                  <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                    {profile.purpose}
                  </p>
                  {profile.skills.length > 0 && (
                    <p className="mt-2 text-[10px] text-muted-foreground">
                      {t("macro.roleTab.skills")}: {profile.skills.join(" / ")}
                    </p>
                  )}

                  <div className="mt-3 grid gap-2">
                    <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
                      {t("macro.roleTab.target")} *
                      <input
                        data-testid="macro-role-target"
                        value={target}
                        onChange={(event) => setTarget(event.target.value)}
                        placeholder={t("macro.roleTab.targetPlaceholder")}
                        className="rounded-lg border border-border/60 bg-background px-2.5 py-1.5 text-xs text-foreground outline-none focus:ring-2 focus:ring-primary/40"
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
                      {t("macro.roleTab.question")} *
                      <textarea
                        data-testid="macro-role-question"
                        value={question}
                        rows={3}
                        onChange={(event) => setQuestion(event.target.value)}
                        placeholder={t("macro.roleTab.questionPlaceholder")}
                        className="rounded-lg border border-border/60 bg-background px-2.5 py-1.5 text-xs text-foreground outline-none focus:ring-2 focus:ring-primary/40"
                      />
                    </label>
                  </div>

                  {formError && (
                    <p
                      data-testid="macro-role-error"
                      className="mt-2 text-xs text-destructive"
                    >
                      {formError}
                    </p>
                  )}

                  <div className="mt-3 flex justify-end">
                    <button
                      type="button"
                      data-testid="macro-role-run"
                      disabled={launching}
                      onClick={launch}
                      className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
                    >
                      {launching ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                      ) : (
                        <PlayCircle className="h-3.5 w-3.5" aria-hidden="true" />
                      )}
                      {t("macro.roleTab.run")}
                    </button>
                  </div>
                </>
              )}

              {selectedRef && !profileLoading && !profile && formError && (
                <p data-testid="macro-role-detail-error" className="text-xs text-destructive">
                  {formError}
                </p>
              )}
            </div>
          </aside>
        </div>
      )}

      <MacroEvalHistory
        records={visibleRecords}
        loading={evalData.loading}
        error={evalData.error}
        testId="macro-role-history"
        variant="role"
        filterName={roleFilterName}
        onClearFilter={() => setRoleFilterDismissed(true)}
        onView={(record) => setActiveRunId(record.runId)}
      />
    </div>
  );
}
