import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import {
  ArrowLeftRight,
  CheckSquare,
  Loader2,
  Search,
  Square,
  X,
} from "lucide-react";
import { api, type RoleGroupItem } from "@/lib/api";
import { RunView } from "@/components/swarm/RunView";
import {
  MACRO_BOARD_CATEGORIES,
  splitRoleRef,
  type MacroBoardIndicator,
} from "./macroCatalog";
import {
  RUN_LEVEL_AGENT,
  useMacroEvalData,
  type MacroEvalRecord,
} from "./macroEvalRecords";

const MAX_COMPARE = 5;
const COLLAPSED_RUNS = 2;

const testIdSafe = (ref: string) => ref.replace(/[^A-Za-z0-9_-]/g, "-");

export function MacroBoardTab() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { records, groups, loading, error } = useMacroEvalData();
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState("");
  const [activeRunId, setActiveRunId] = useState("");
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keyword, setKeyword] = useState("");

  const roleMap = useMemo(() => {
    const map: Record<string, RoleGroupItem> = {};
    for (const group of groups) {
      for (const role of group.roles) map[role.ref] = role;
    }
    return map;
  }, [groups]);

  const teamTitles = useMemo(() => {
    const map: Record<string, string> = {};
    for (const group of groups) map[group.ref] = group.title;
    return map;
  }, [groups]);

  /** Completed records attributable to a role ref. */
  const recordsByRole = useMemo(() => {
    const map: Record<string, MacroEvalRecord[]> = {};
    for (const record of records) {
      if (record.status !== "completed") continue;
      if (!record.roleRef || record.agentId === RUN_LEVEL_AGENT) continue;
      (map[record.roleRef] ||= []).push(record);
    }
    return map;
  }, [records]);

  /** Role refs with a running standalone run. */
  const runningRoles = useMemo(() => {
    const set = new Set<string>();
    for (const record of records) {
      if (
        record.kind === "role_run" &&
        ["running", "pending"].includes(record.status)
      ) {
        set.add(record.roleRef);
      }
    }
    return set;
  }, [records]);

  /** Presets with a running/pending team run (affects all its roles). */
  const runningPresets = useMemo(() => {
    const set = new Set<string>();
    for (const record of records) {
      if (
        record.kind === "team" &&
        record.agentId === RUN_LEVEL_AGENT &&
        ["running", "pending"].includes(record.status)
      ) {
        set.add(record.presetName);
      }
    }
    return set;
  }, [records]);

  const roleToIndicator = useMemo(() => {
    const map: Record<string, MacroBoardIndicator> = {};
    for (const category of MACRO_BOARD_CATEGORIES) {
      for (const indicator of category.indicators) {
        map[indicator.roleRef] = indicator;
      }
    }
    return map;
  }, []);

  // Records in board display order — used to resolve picked records sorted.
  const orderedRecords = useMemo(() => {
    const ordered: MacroEvalRecord[] = [];
    for (const category of MACRO_BOARD_CATEGORIES) {
      for (const indicator of category.indicators) {
        ordered.push(...(recordsByRole[indicator.roleRef] || []));
      }
    }
    return ordered;
  }, [recordsByRole]);

  const toggleSelect = useCallback((recordKey: string) => {
    setCompareError("");
    setSelectedKeys((prev) => {
      if (prev.includes(recordKey)) return prev.filter((k) => k !== recordKey);
      if (prev.length >= MAX_COMPARE) return prev;
      return [...prev, recordKey];
    });
  }, []);

  const toggleExpanded = useCallback((roleRef: string) => {
    setExpanded((prev) =>
      prev.includes(roleRef)
        ? prev.filter((ref) => ref !== roleRef)
        : [...prev, roleRef],
    );
  }, []);

  const recordMatches = useCallback(
    (record: MacroEvalRecord, kw: string) =>
      [
        record.roleName,
        record.target,
        record.date,
        record.excerpt,
        record.presetName,
      ]
        .join(" ")
        .toLowerCase()
        .includes(kw.toLowerCase()),
    [],
  );

  const buildComparePrompt = useCallback(
    (picked: MacroEvalRecord[]) => {
      const parts: string[] = [
        t("macro.board.promptIntro", { n: picked.length }),
        "",
      ];
      picked.forEach((record, i) => {
        const indicator = roleToIndicator[record.roleRef];
        const { presetName } = splitRoleRef(record.roleRef);
        parts.push(
          t("macro.board.promptItem", {
            index: i + 1,
            indicator: indicator
              ? t(indicator.nameKey as never)
              : record.roleName,
            role: roleMap[record.roleRef]?.name || record.roleName,
            team: teamTitles[presetName] || presetName,
            target: record.target || "-",
            date: record.date,
            conclusion: record.excerpt,
          }),
        );
      });
      parts.push("", t("macro.board.promptTasks"));
      return parts.join("\n");
    },
    [roleMap, roleToIndicator, t, teamTitles],
  );

  const runCompare = useCallback(async () => {
    const picked = orderedRecords.filter((record) =>
      selectedKeys.includes(record.key),
    );
    if (picked.length < 2) {
      setCompareError(t("macro.board.needTwo"));
      return;
    }
    setComparing(true);
    setCompareError("");
    try {
      const session = await api.createSession(
        t("macro.board.compareSessionTitle"),
      );
      await api.sendMessage(session.session_id, buildComparePrompt(picked));
      navigate(`/agent?session=${encodeURIComponent(session.session_id)}`);
    } catch {
      setCompareError(t("macro.board.compareFailed"));
      setComparing(false);
    }
  }, [buildComparePrompt, navigate, orderedRecords, selectedKeys, t]);

  if (activeRunId) {
    return <RunView runId={activeRunId} onBack={() => setActiveRunId("")} />;
  }

  const searching = keyword.trim().length > 0;
  let matchCount = 0;

  return (
    <div data-testid="macro-board-tab">
      <p className="text-xs leading-relaxed text-muted-foreground">
        {t("macro.board.intro")}
      </p>

      {loading && (
        <div className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        </div>
      )}
      {error && (
        <p
          data-testid="macro-board-load-error"
          className="mt-6 text-sm text-destructive"
        >
          {t("macro.board.loadFailed")}
        </p>
      )}

      {!loading && !error && (
        <>
          {/* Evaluation-record search (synced team + role records) */}
          <form
            className="mt-4 flex flex-wrap items-end gap-2"
            data-testid="macro-board-search"
            onSubmit={(e) => {
              e.preventDefault();
              setKeyword(keywordDraft);
            }}
          >
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              {t("macro.evalHistory.keyword")}
              <input
                value={keywordDraft}
                onChange={(e) => setKeywordDraft(e.target.value)}
                data-testid="macro-board-search-input"
                placeholder={t("macro.evalHistory.keywordPlaceholder")}
                className="w-72 rounded-lg border border-border/60 bg-background px-2.5 py-1.5 text-xs text-foreground outline-none focus:ring-2 focus:ring-primary/40"
              />
            </label>
            <button
              type="submit"
              data-testid="macro-board-search-submit"
              className="inline-flex items-center gap-1 rounded-lg bg-foreground px-3 py-1.5 text-xs text-background"
            >
              <Search className="h-3.5 w-3.5" />
              {t("macro.evalHistory.search")}
            </button>
            {searching && (
              <button
                type="button"
                data-testid="macro-board-search-clear"
                onClick={() => {
                  setKeywordDraft("");
                  setKeyword("");
                }}
                className="inline-flex items-center gap-1 rounded-lg border border-border/60 px-3 py-1.5 text-xs text-foreground transition-colors hover:bg-muted"
              >
                <X className="h-3.5 w-3.5" />
                {t("macro.evalHistory.clear")}
              </button>
            )}
          </form>

          {MACRO_BOARD_CATEGORIES.map((category) => {
            const visibleIndicators = category.indicators.filter((indicator) => {
              if (!searching) return true;
              const name = t(indicator.nameKey as never) as string;
              const hint = t(indicator.hintKey as never) as string;
              if (
                name.toLowerCase().includes(keyword.toLowerCase()) ||
                hint.toLowerCase().includes(keyword.toLowerCase())
              ) {
                return true;
              }
              return (recordsByRole[indicator.roleRef] || []).some((r) =>
                recordMatches(r, keyword.trim()),
              );
            });
            if (visibleIndicators.length === 0) return null;

            return (
              <section key={category.nameKey} className="mt-6">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t(category.nameKey as never)}
                </h2>
                <div className="mt-2 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {visibleIndicators.map((indicator) => {
                    const roleRef = indicator.roleRef;
                    const allCompleted = recordsByRole[roleRef] || [];
                    const isRunning =
                      runningRoles.has(roleRef) ||
                      runningPresets.has(splitRoleRef(roleRef).presetName);
                    const isExpanded =
                      searching || expanded.includes(roleRef);
                    let visibleRecords = isExpanded
                      ? allCompleted
                      : allCompleted.slice(0, COLLAPSED_RUNS);
                    if (searching) {
                      visibleRecords = allCompleted.filter((r) =>
                        recordMatches(r, keyword.trim()),
                      );
                      matchCount += visibleRecords.length;
                    }
                    const roleName =
                      roleMap[roleRef]?.name || splitRoleRef(roleRef).agentId;
                    const teamName =
                      teamTitles[splitRoleRef(roleRef).presetName] ||
                      splitRoleRef(roleRef).presetName;
                    return (
                      <div
                        key={roleRef}
                        data-testid={`macro-board-indicator-${testIdSafe(roleRef)}`}
                        className="flex flex-col rounded-xl border border-border/60 bg-card p-3.5"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <h3 className="text-sm font-semibold text-foreground">
                            {t(indicator.nameKey as never)}
                          </h3>
                          {isRunning && (
                            <span
                              data-testid={`macro-board-running-${testIdSafe(roleRef)}`}
                              className="inline-flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[9px] text-primary"
                            >
                              <Loader2
                                className="h-2.5 w-2.5 animate-spin"
                                aria-hidden="true"
                              />
                              {t("macro.board.running")}
                            </span>
                          )}
                        </div>
                        <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
                          {t(indicator.hintKey as never)}
                        </p>
                        <p className="mt-1.5 text-[10px] text-muted-foreground">
                          <span className="text-foreground">{roleName}</span>
                          {" · "}
                          {teamName}
                        </p>

                        <div className="mt-2 flex-1 space-y-2">
                          {visibleRecords.map((record) => {
                            const checked = selectedKeys.includes(record.key);
                            const selectionFull =
                              selectedKeys.length >= MAX_COMPARE && !checked;
                            return (
                              <div
                                key={record.key}
                                data-testid={`macro-board-run-${record.key}`}
                                className={
                                  checked
                                    ? "rounded-lg border border-primary/60 bg-primary/5 p-2"
                                    : "rounded-lg border border-border/50 bg-background/60 p-2"
                                }
                              >
                                <div className="flex items-start gap-1.5">
                                  <button
                                    type="button"
                                    role="checkbox"
                                    aria-checked={checked}
                                    disabled={selectionFull}
                                    data-testid={`macro-board-run-checkbox-${record.key}`}
                                    title={
                                      selectionFull
                                        ? t("macro.board.maxSelected")
                                        : ""
                                    }
                                    onClick={() => toggleSelect(record.key)}
                                    className="mt-0.5 shrink-0 text-foreground disabled:opacity-40"
                                  >
                                    {checked ? (
                                      <CheckSquare
                                        className="h-3.5 w-3.5 text-primary"
                                        aria-hidden="true"
                                      />
                                    ) : (
                                      <Square
                                        className="h-3.5 w-3.5"
                                        aria-hidden="true"
                                      />
                                    )}
                                  </button>
                                  <p className="line-clamp-3 text-[11px] leading-snug text-foreground">
                                    {record.excerpt}
                                  </p>
                                </div>
                                <div className="mt-1.5 flex items-center justify-between gap-2 pl-5 text-[9px] text-muted-foreground">
                                  <span className="truncate">
                                    {record.target || "-"} · {record.date}
                                  </span>
                                  <button
                                    type="button"
                                    data-testid={`macro-board-view-${record.key}`}
                                    onClick={() => setActiveRunId(record.runId)}
                                    className="shrink-0 text-primary hover:underline"
                                  >
                                    {t("macro.board.viewFull")}
                                  </button>
                                </div>
                              </div>
                            );
                          })}
                          {visibleRecords.length === 0 && !isRunning && (
                            <p className="rounded-lg bg-muted/50 p-2 text-[10px] leading-relaxed text-muted-foreground">
                              {searching
                                ? t("macro.evalHistory.noMatch")
                                : t("macro.board.empty")}
                            </p>
                          )}
                        </div>

                        {!searching &&
                          allCompleted.length > COLLAPSED_RUNS && (
                            <button
                              type="button"
                              data-testid={`macro-board-expand-${testIdSafe(roleRef)}`}
                              onClick={() => toggleExpanded(roleRef)}
                              className="mt-2 text-[10px] text-primary hover:underline"
                            >
                              {isExpanded
                                ? t("macro.board.hideMore")
                                : t("macro.board.showAll", {
                                    n: allCompleted.length,
                                  })}
                            </button>
                          )}
                      </div>
                    );
                  })}
                </div>
              </section>
            );
          })}

          {searching && (
            <p
              data-testid="macro-board-search-count"
              className="mt-3 text-[11px] text-muted-foreground"
            >
              {t("macro.evalHistory.matchCount", { n: matchCount })}
            </p>
          )}

          <div className="sticky bottom-4 mt-6">
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border/60 bg-card/95 px-4 py-2.5 shadow-lg backdrop-blur">
              <span
                data-testid="macro-board-selected-count"
                className="text-xs font-medium text-foreground"
              >
                {t("macro.board.selectedCount", { n: selectedKeys.length })}
              </span>
              <div className="ml-auto flex items-center gap-2">
                {compareError && (
                  <span
                    data-testid="macro-board-compare-error"
                    className="text-[11px] text-destructive"
                  >
                    {compareError}
                  </span>
                )}
                <button
                  type="button"
                  data-testid="macro-board-clear"
                  disabled={selectedKeys.length === 0 || comparing}
                  onClick={() => setSelectedKeys([])}
                  className="rounded-lg border border-border/60 px-3 py-1.5 text-xs text-foreground transition-colors hover:bg-muted disabled:opacity-40"
                >
                  {t("macro.board.clear")}
                </button>
                <button
                  type="button"
                  data-testid="macro-board-compare"
                  disabled={selectedKeys.length < 2 || comparing}
                  onClick={() => void runCompare()}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  {comparing ? (
                    <Loader2
                      className="h-3.5 w-3.5 animate-spin"
                      aria-hidden="true"
                    />
                  ) : (
                    <ArrowLeftRight
                      className="h-3.5 w-3.5"
                      aria-hidden="true"
                    />
                  )}
                  {t("macro.board.compare")}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
