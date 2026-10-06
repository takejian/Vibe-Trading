import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, Loader2, PlayCircle, Users } from "lucide-react";
import {
  api,
  ApiError,
  type SwarmPreset,
} from "@/lib/api";
import type { SwarmPresetDetail } from "@/lib/swarmGraph";
import { RunView } from "@/components/swarm/RunView";
import { MACRO_TEAM_THEMES } from "./macroCatalog";
import { MacroEvalHistory } from "./MacroEvalHistory";
import {
  RUN_LEVEL_AGENT,
  useMacroEvalData,
} from "./macroEvalRecords";
import { MacroEvalHistory } from "./MacroEvalHistory";
import { useMacroEvalData } from "./macroEvalRecords";

export function MacroTeamTab() {
  const { t } = useTranslation();
  const [summaries, setSummaries] = useState<Record<string, SwarmPreset>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, SwarmPresetDetail>>({});
  const [detailLoading, setDetailLoading] = useState<string | null>(null);
  const [varValues, setVarValues] = useState<Record<string, Record<string, string>>>({});
  const [launching, setLaunching] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [activeRunId, setActiveRunId] = useState("");
  const [activeAgent, setActiveAgent] = useState<{
    ref: string;
    name: string;
  } | null>(null);
  const evalData = useMacroEvalData();
  const macroTeamPresets = useMemo(
    () => new Set(MACRO_TEAM_THEMES.map((theme) => theme.presetName)),
    [],
  );
  // One row per team run (mirrors orchestration history), macro teams only.
  const teamEvalRecords = useMemo(
    () =>
      evalData.records.filter(
        (record) =>
          record.kind === "team" &&
          record.agentId === RUN_LEVEL_AGENT &&
          macroTeamPresets.has(record.presetName),
      ),
    [evalData.records, macroTeamPresets],
  );
  // Run ids in which the clicked agent has a completed task.
  const visibleRecords = useMemo(() => {
    if (!activeAgent) return teamEvalRecords;
    const runIds = new Set(
      evalData.records
        .filter(
          (record) =>
            record.kind === "team" &&
            record.agentId !== RUN_LEVEL_AGENT &&
            record.roleRef === activeAgent.ref &&
            record.status === "completed",
        )
        .map((record) => record.runId),
    );
    return teamEvalRecords.filter((record) => runIds.has(record.runId));
  }, [activeAgent, evalData.records, teamEvalRecords]);

  useEffect(() => {
    let cancelled = false;
    api
      .listSwarmPresets()
      .then((presets) => {
        if (cancelled) return;
        setSummaries(Object.fromEntries(presets.map((p) => [p.name, p])));
      })
      .catch(() => {
        if (!cancelled) setLoadError(t("macro.teamTab.loadFailed"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const toggleTeam = useCallback(
    async (presetName: string) => {
      if (expanded === presetName) {
        setExpanded(null);
        return;
      }
      setExpanded(presetName);
      if (details[presetName]) return;
      setDetailLoading(presetName);
      setErrors((prev) => ({ ...prev, [presetName]: "" }));
      try {
        const detail = await api.getSwarmPresetDetail(presetName);
        setDetails((prev) => ({ ...prev, [presetName]: detail }));
        setVarValues((prev) =>
          prev[presetName]
            ? prev
            : {
                ...prev,
                [presetName]: Object.fromEntries(
                  detail.variables.map((v) => [v.name, ""]),
                ),
              },
        );
      } catch {
        setErrors((prev) => ({
          ...prev,
          [presetName]: t("macro.teamTab.detailFailed"),
        }));
      } finally {
        setDetailLoading(null);
      }
    },
    [details, expanded, t],
  );

  const launch = useCallback(
    async (presetName: string) => {
      const detail = details[presetName];
      const values = varValues[presetName] || {};
      if (!detail) return;
      const missing = detail.variables.some(
        (v) => v.required !== false && !(values[v.name] || "").trim(),
      );
      if (missing) {
        setErrors((prev) => ({
          ...prev,
          [presetName]: t("macro.teamTab.missingRequired"),
        }));
        return;
      }
      setLaunching(presetName);
      setErrors((prev) => ({ ...prev, [presetName]: "" }));
      try {
        const userVars = Object.fromEntries(
          Object.entries(values).map(([k, v]) => [k, v.trim()]),
        );
        const run = await api.createSwarmRun(presetName, userVars);
        setActiveRunId(run.id);
      } catch (error) {
        let message = t("macro.teamTab.launchFailed");
        if (error instanceof ApiError) {
          if (error.status === 409) message = t("macro.teamTab.inProgress");
          else if (error.message) message = error.message;
        }
        setErrors((prev) => ({ ...prev, [presetName]: message }));
      } finally {
        setLaunching(null);
      }
    },
    [details, t, varValues],
  );

  const orderedThemes = useMemo(() => MACRO_TEAM_THEMES, []);

  if (activeRunId) {
    return (
      <RunView
        runId={activeRunId}
        onBack={() => setActiveRunId("")}
      />
    );
  }

  return (
    <div data-testid="macro-team-tab">
      <p className="text-xs leading-relaxed text-muted-foreground">
        {t("macro.teamTab.intro")}
      </p>

      {loading && (
        <div className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        </div>
      )}
      {loadError && (
        <p data-testid="macro-team-load-error" className="mt-6 text-sm text-destructive">
          {loadError}
        </p>
      )}

      {!loading &&
        !loadError &&
        orderedThemes.map((theme) => {
          const presetName = theme.presetName;
          const summary = summaries[presetName];
          const detail = details[presetName];
          const isOpen = expanded === presetName;
          const values = varValues[presetName] || {};
          return (
            <section key={presetName} className="mt-5">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t(theme.themeKey as never)}
              </h2>
              <div
                data-testid={`macro-team-card-${presetName}`}
                className="mt-2 rounded-xl border border-border/60 bg-card p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <button
                      type="button"
                      data-testid={`macro-team-expand-${presetName}`}
                      onClick={() => toggleTeam(presetName)}
                      className="inline-flex items-center gap-2 text-left text-sm font-semibold text-foreground"
                    >
                      {isOpen ? (
                        <ChevronDown className="h-4 w-4 shrink-0" aria-hidden="true" />
                      ) : (
                        <ChevronRight className="h-4 w-4 shrink-0" aria-hidden="true" />
                      )}
                      {summary?.title || presetName}
                    </button>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                      {summary?.description || ""}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Users className="h-3.5 w-3.5" aria-hidden="true" />
                    {summary?.agent_count ?? detail?.agents.length ?? 0}
                  </div>
                </div>

                {isOpen && (
                  <div className="mt-4 border-t border-border/40 pt-3">
                    {detailLoading === presetName && (
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                        {t("macro.teamTab.loadingDetail")}
                      </div>
                    )}

                    {detail && (
                      <>
                        <div className="grid gap-3 md:grid-cols-2">
                          <div>
                            <h3 className="text-xs font-semibold text-foreground">
                              {t("macro.teamTab.rolesTitle")}
                            </h3>
                            <p className="mt-0.5 text-[10px] text-muted-foreground">
                              {t("macro.teamTab.agentFilterHint")}
                            </p>
                            <ul className="mt-1.5 space-y-1">
                              {detail.agents.map((agent) => {
                                const ref = `${presetName}:${agent.id}`;
                                const isAgentActive = activeAgent?.ref === ref;
                                return (
                                  <li
                                    key={agent.id}
                                    className="text-xs text-muted-foreground"
                                  >
                                    <button
                                      type="button"
                                      data-testid={`macro-team-agent-${presetName}-${agent.id}`}
                                      aria-pressed={isAgentActive}
                                      onClick={() =>
                                        setActiveAgent(
                                          isAgentActive
                                            ? null
                                            : { ref, name: agent.role },
                                        )
                                      }
                                      className={
                                        isAgentActive
                                          ? "rounded bg-primary/10 px-1.5 py-0.5 text-primary"
                                          : "rounded px-1.5 py-0.5 text-foreground hover:bg-muted"
                                      }
                                    >
                                      {agent.role}
                                    </button>
                                    {agent.skills.length > 0 && (
                                      <span className="ml-1 text-[10px]">
                                        · {agent.skills.join(" / ")}
                                      </span>
                                    )}
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                          <div>
                            <h3 className="text-xs font-semibold text-foreground">
                              {t("macro.teamTab.paramsTitle")}
                            </h3>
                            <div className="mt-1.5 grid gap-2">
                              {detail.variables.map((variable) => (
                                <label
                                  key={variable.name}
                                  className="flex flex-col gap-1 text-[11px] text-muted-foreground"
                                >
                                  {variable.name}
                                  {variable.required !== false && (
                                    <span className="text-[9px] text-primary">*</span>
                                  )}
                                  <input
                                    data-testid={`macro-team-var-${presetName}-${variable.name}`}
                                    value={values[variable.name] || ""}
                                    onChange={(event) =>
                                      setVarValues((prev) => ({
                                        ...prev,
                                        [presetName]: {
                                          ...(prev[presetName] || {}),
                                          [variable.name]: event.target.value,
                                        },
                                      }))
                                    }
                                    placeholder={variable.description || variable.name}
                                    className="rounded-lg border border-border/60 bg-background px-2.5 py-1.5 text-xs text-foreground outline-none focus:ring-2 focus:ring-primary/40"
                                  />
                                </label>
                              ))}
                            </div>
                          </div>
                        </div>

                        {errors[presetName] && (
                          <p
                            data-testid={`macro-team-error-${presetName}`}
                            className="mt-3 text-xs text-destructive"
                          >
                            {errors[presetName]}
                          </p>
                        )}

                        <div className="mt-3 flex justify-end">
                          <button
                            type="button"
                            data-testid={`macro-team-launch-${presetName}`}
                            disabled={launching === presetName}
                            onClick={() => launch(presetName)}
                            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
                          >
                            {launching === presetName ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                            ) : (
                              <PlayCircle className="h-3.5 w-3.5" aria-hidden="true" />
                            )}
                            {t("macro.teamTab.launch")}
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            </section>
          );
        })}

      <MacroEvalHistory
        records={visibleRecords}
        loading={evalData.loading}
        error={evalData.error}
        testId="macro-team-history"
        variant="team"
        filterName={activeAgent?.name}
        onClearFilter={() => setActiveAgent(null)}
        onView={(record) => setActiveRunId(record.runId)}
      />
    </div>
  );
}
