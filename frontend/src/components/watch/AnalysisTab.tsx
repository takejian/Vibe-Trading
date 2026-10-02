import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import {
  ApiError,
  api,
  type WatchAgent,
  type WatchAnalysisSummary,
  type WatchCategory,
  type WatchKlineLevel,
} from "@/lib/api";
import { RunView } from "@/components/swarm/RunView";
import { MarkdownContent } from "@/components/common/MarkdownContent";

const ACTIVE_STATUSES = new Set(["pending", "running"]);

export function AnalysisTab({
  category,
  symbol,
  onGotoObjective,
}: {
  category: WatchCategory;
  symbol: string;
  /** Display name kept for future question-template enrichment. */
  symbolName?: string;
  /** Technical tab: jump to the Objective-data tab from the Chanlun gate. */
  onGotoObjective?: () => void;
}) {
  const { t } = useTranslation();
  const [agents, setAgents] = useState<WatchAgent[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [history, setHistory] = useState<WatchAnalysisSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [roleRef, setRoleRef] = useState("");
  const [question, setQuestion] = useState("");
  const [starting, setStarting] = useState(false);
  const [error409, setError409] = useState(false);
  const [errorOther, setErrorOther] = useState("");
  const [activeRunId, setActiveRunId] = useState("");
  const [activeRunReadOnly, setActiveRunReadOnly] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [gateItems, setGateItems] = useState<WatchKlineLevel[] | null>(null);
  const [warn30m, setWarn30m] = useState(false);

  const loadAgents = useCallback(async () => {
    setAgentsLoading(true);
    try {
      const resp = await api.listWatchAgents(category);
      setAgents(resp.items);
    } finally {
      setAgentsLoading(false);
    }
  }, [category]);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const resp = await api.listWatchAnalyses(symbol, {
        category,
        limit: 20,
      });
      setHistory(resp.items);
    } finally {
      setHistoryLoading(false);
    }
  }, [category, symbol]);

  useEffect(() => {
    void loadAgents();
    void loadHistory();
  }, [loadAgents, loadHistory]);

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.ref === roleRef) ?? null,
    [agents, roleRef],
  );

  // Chanlun is the only role with a data prerequisite. The optional 30m
  // level never blocks — it only surfaces a non-blocking warning (BDD US-11).
  useEffect(() => {
    if (category !== "technical" || !selectedAgent?.is_chanlun) {
      setWarn30m(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const resp = await api.getWatchKlineStatus(symbol);
        const minute = resp.items.find((item) => item.interval === "30m");
        if (!cancelled) setWarn30m(minute?.status !== "ready");
      } catch {
        /* warning is advisory — ignore status-load failures */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [category, selectedAgent, symbol]);

  const grouped = useMemo(() => {
    const map = new Map<string, { name: string; items: WatchAnalysisSummary[] }>();
    for (const item of history) {
      const key = item.role_ref || item.role_name;
      const group = map.get(key) ?? { name: item.role_name, items: [] };
      group.items.push(item);
      map.set(key, group);
    }
    return [...map.entries()];
  }, [history]);

  const start = async (skipGate = false) => {
    if (!roleRef) return;
    setStarting(true);
    setError409(false);
    setErrorOther("");
    if (!skipGate) setGateItems(null);
    try {
      const run = await api.startWatchAnalysis(symbol, {
        category,
        role_ref: roleRef,
        ...(question.trim() ? { question: question.trim() } : {}),
        ...(skipGate ? { skip_kline_gate: true } : {}),
      });
      setGateItems(null);
      setActiveRunId(run.id);
      setActiveRunReadOnly(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError409(true);
        await loadHistory();
      } else if (
        err instanceof ApiError &&
        err.status === 412 &&
        err.code === "kline_not_ready"
      ) {
        setGateItems(
          Array.isArray(err.payload?.items)
            ? (err.payload!.items as WatchKlineLevel[])
            : [],
        );
      } else {
        setErrorOther(t("watch.error.dataFailed"));
      }
    } finally {
      setStarting(false);
    }
  };

  if (activeRunId) {
    return (
      <div data-testid="analysis-run-view">
        <RunView
          runId={activeRunId}
          readOnly={activeRunReadOnly}
          onBack={() => {
            setActiveRunId("");
            setActiveRunReadOnly(false);
            void loadHistory();
          }}
        />
      </div>
    );
  }

  return (
    <div className="space-y-5" data-testid={`analysis-tab-${category}`}>
      <div>
        <h3 className="mb-2 text-sm font-semibold">{t("watch.an.roleTitle")}</h3>
        {agentsLoading ? (
          <div className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          </div>
        ) : agents.length === 0 ? (
          <p className="rounded-md border border-dashed border-border px-4 py-5 text-center text-sm text-muted-foreground">
            {t("watch.an.noAgents")}
          </p>
        ) : (
          <ul
            role="radiogroup"
            aria-label={t("watch.an.roleTitle")}
            className="space-y-2"
          >
            {agents.map((agent) => {
              const checked = roleRef === agent.ref;
              return (
                <li key={agent.ref}>
                  <label
                    className={`flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2.5 ${
                      checked
                        ? "border-primary bg-primary/5"
                        : "border-border hover:bg-muted/40"
                    }`}
                  >
                    <input
                      type="radio"
                      name={`watch-agent-${category}`}
                      className="mt-1"
                      value={agent.ref}
                      checked={checked}
                      onChange={() => {
                        setRoleRef(agent.ref);
                        setError409(false);
                        setGateItems(null);
                      }}
                    />
                    <span>
                      <span className="flex items-center gap-2 text-sm font-medium">
                        {agent.name}
                        {agent.is_chanlun && (
                          <span
                            className="rounded bg-primary/15 px-1.5 py-0.5 text-[10px] text-primary"
                            data-testid="chanlun-badge"
                          >
                            {t("watch.an.chanlunBadge")}
                          </span>
                        )}
                      </span>
                      {agent.purpose && (
                        <span className="mt-0.5 block text-xs text-muted-foreground">
                          {agent.purpose}
                        </span>
                      )}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">
          {t("watch.an.questionLabel")}
        </label>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          placeholder={t("watch.an.questionPlaceholder")}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
          data-testid="analysis-question"
        />
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={!roleRef || starting}
          onClick={() => void start()}
          className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="analysis-run-btn"
        >
          {starting && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          {t("watch.an.run")}
        </button>
        {!roleRef && (
          <span className="text-xs text-muted-foreground">
            {t("watch.an.mustSelect")}
          </span>
        )}
      </div>

      {error409 && (
        <div role="alert" className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm" data-testid="analysis-409">
          {t("watch.an.inProgress")}
        </div>
      )}
      {gateItems && (
        <div
          role="alert"
          className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-3 text-sm"
          data-testid="chanlun-kline-gate"
        >
          <p className="font-medium">{t("watch.an.gateTitle")}</p>
          <p className="mt-1 text-muted-foreground">{t("watch.an.gateDesc")}</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {gateItems.map((item) => (
              <li
                key={item.interval}
                className="rounded border border-border bg-background px-2 py-0.5 text-xs"
                data-testid={`chanlun-gate-item-${item.interval}`}
              >
                {t(`watch.kline.levels.${item.interval}`)}：
                {t(`watch.kline.state.${item.status}`)}
              </li>
            ))}
          </ul>
          <div className="mt-3 flex flex-wrap gap-2">
            {onGotoObjective && (
              <button
                type="button"
                onClick={onGotoObjective}
                className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90"
                data-testid="chanlun-gate-go"
              >
                {t("watch.an.gateGo")}
              </button>
            )}
            <button
              type="button"
              disabled={starting}
              onClick={() => void start(true)}
              className="inline-flex items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-sm hover:bg-muted/40 disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="chanlun-gate-skip"
            >
              {starting && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
              {t("watch.an.gateSkip")}
            </button>
          </div>
        </div>
      )}
      {warn30m && category === "technical" && selectedAgent?.is_chanlun && (
        <div
          role="status"
          className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
          data-testid="chanlun-30m-warn"
        >
          {t("watch.an.warn30m")}
        </div>
      )}
      {errorOther && (
        <div role="alert" className="text-sm text-red-500">
          {errorOther}
        </div>
      )}

      <div>
        <h3 className="mb-2 text-sm font-semibold">{t("watch.an.historyTitle")}</h3>
        {historyLoading ? (
          <div className="flex items-center gap-2 py-3 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          </div>
        ) : history.length === 0 ? (
          <p className="rounded-md border border-dashed border-border px-4 py-5 text-center text-sm text-muted-foreground" data-testid="analysis-history-empty">
            {t("watch.an.historyEmpty")}
          </p>
        ) : (
          <div className="space-y-4">
            {grouped.map(([key, group]) => (
              <div key={key}>
                <p className="mb-1 text-xs font-semibold text-muted-foreground">
                  {group.name}
                </p>
                <ul className="space-y-1.5">
                  {group.items.map((item) => {
                    const open = expanded.has(item.id);
                    const active = ACTIVE_STATUSES.has(item.status);
                    return (
                      <li
                        key={item.id}
                        className="rounded-md border border-border"
                      >
                        <div className="flex items-center gap-2 px-3 py-2 text-sm">
                          <button
                            type="button"
                            onClick={() =>
                              setExpanded((prev) => {
                                const next = new Set(prev);
                                if (next.has(item.id)) next.delete(item.id);
                                else next.add(item.id);
                                return next;
                              })
                            }
                            aria-expanded={open}
                            className="flex flex-1 items-center gap-2 text-left"
                          >
                            {open ? (
                              <ChevronDown className="h-4 w-4" aria-hidden="true" />
                            ) : (
                              <ChevronRight className="h-4 w-4" aria-hidden="true" />
                            )}
                            <span className="text-xs text-muted-foreground">
                              {item.completed_at || item.created_at || ""}
                            </span>
                            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px]">
                              {t(`watch.status.${item.status}`, { defaultValue: item.status })}
                            </span>
                            {item.qualified && (
                              <span className="rounded bg-green-500/15 px-1.5 py-0.5 text-[10px] text-green-700 dark:text-green-400">
                                ✓
                              </span>
                            )}
                            {item.research_question && (
                              <span className="truncate text-xs">
                                {item.research_question}
                              </span>
                            )}
                          </button>
                          <button
                            type="button"
                            className="ml-auto shrink-0 rounded border border-primary/40 px-2 py-0.5 text-xs text-primary hover:underline"
                            data-testid="view-run-link"
                            aria-label={active ? t("watch.an.viewRun") : t("watch.an.viewReport")}
                            onClick={() => {
                              setActiveRunId(item.id);
                              setActiveRunReadOnly(!active);
                            }}
                          >
                            {active ? t("watch.an.viewRun") : t("watch.an.viewReport")}
                          </button>
                        </div>
                        {open && (
                          <div className="border-t border-border/60 px-3 py-2" data-testid="analysis-full-report">
                            {(item.final_report || item.final_report_excerpt) ? (
                              <MarkdownContent
                                content={item.final_report || item.final_report_excerpt || ""}
                              />
                            ) : (
                              <span className="text-sm text-muted-foreground">
                                {t("watch.noData")}
                              </span>
                            )}
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
