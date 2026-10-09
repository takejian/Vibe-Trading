import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Circle,
  Loader2,
  Minus,
} from "lucide-react";
import {
  api,
  ApiError,
  type SynthesisCoverage,
  type SynthesisReport,
  type SynthesisReportSummary,
} from "@/lib/api";

interface Props {
  economy: string;
}

type RunState = "idle" | "loading" | "done" | "error";
type PeriodType = "month" | "quarter";

const CYCLE_ORDER = ["recovery", "overheat", "stagflation", "recession"] as const;
const DIM_ORDER = ["growth", "inflation", "money", "external", "synthesis"] as const;
const ASSET_ORDER = ["equity", "bond", "commodity", "cash"] as const;

const CYCLE_BAR: Record<string, string> = {
  recovery: "bg-emerald-400",
  overheat: "bg-orange-400",
  stagflation: "bg-amber-500",
  recession: "bg-blue-400",
};

function signalClass(signal: number): string {
  if (signal >= 1)
    return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
  if (signal <= -1) return "bg-red-500/10 text-red-600 dark:text-red-400";
  return "bg-muted text-muted-foreground";
}

function TrendIcon({ trend }: { trend: string }) {
  if (trend === "up")
    return <ArrowUp className="h-3 w-3 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />;
  if (trend === "down")
    return <ArrowDown className="h-3 w-3 text-red-600 dark:text-red-400" aria-hidden="true" />;
  return <Minus className="h-3 w-3 text-muted-foreground" aria-hidden="true" />;
}

/**
 * 宏观量化汇总面板：团队结论覆盖检查 -> AI 汇总 -> 量化总体结果。
 * 月/季切换；部分覆盖甚至零覆盖均可发起汇总。
 */
export function MacroSynthesisPanel({ economy }: Props) {
  const { t } = useTranslation();
  const [periodType, setPeriodType] = useState<PeriodType>("month");
  const [coverage, setCoverage] = useState<SynthesisCoverage | null>(null);
  const [report, setReport] = useState<SynthesisReport | null>(null);
  const [runState, setRunState] = useState<RunState>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [history, setHistory] = useState<SynthesisReportSummary[]>([]);

  const loadCoverage = useCallback(async () => {
    if (!economy) {
      setCoverage(null);
      return;
    }
    try {
      const data = await api.getSynthesisCoverage({ economy, period_type: periodType });
      setCoverage(data);
    } catch {
      setCoverage(null);
    }
  }, [economy, periodType]);

  const loadHistory = useCallback(async () => {
    if (!economy) {
      setHistory([]);
      return;
    }
    try {
      const res = await api.listSynthesisReports(economy);
      setHistory(res.reports);
    } catch {
      setHistory([]);
    }
  }, [economy]);

  useEffect(() => {
    void loadCoverage();
  }, [loadCoverage]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const switchPeriod = (next: PeriodType) => {
    if (next === periodType) return;
    setPeriodType(next);
    setReport(null);
    setRunState("idle");
    setErrorMsg("");
  };

  const runSynthesis = useCallback(async () => {
    if (!economy) return;
    setRunState("loading");
    setErrorMsg("");
    try {
      const res = await api.createSynthesisReport({
        economy,
        period_type: periodType,
      });
      setReport(res.report);
      setRunState("done");
      void loadHistory();
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 409) setErrorMsg(t("macro.board.syn.inProgress"));
        else if (error.status === 504) setErrorMsg(t("macro.board.syn.timeout"));
        else setErrorMsg(error.message || t("macro.board.syn.failed"));
      } else {
        setErrorMsg(t("macro.board.syn.failed"));
      }
      setRunState("error");
    }
  }, [economy, periodType, t, loadHistory]);

  const viewReport = useCallback(
    async (id: number) => {
      setRunState("loading");
      setErrorMsg("");
      try {
        const res = await api.getSynthesisReport(id);
        setReport(res.report);
        setRunState("done");
      } catch {
        setErrorMsg(t("macro.board.syn.failed"));
        setRunState("error");
      }
    },
    [t],
  );

  const coveredCount = coverage ? coverage.teams.filter((item) => item.present).length : 0;

  const coverageMessage = () => {
    if (!coverage) return "";
    if (coveredCount === 4) return t("macro.board.syn.allCovered");
    if (coveredCount === 0) return t("macro.board.syn.noneCovered");
    return t("macro.board.syn.partialCovered", { n: coveredCount });
  };

  const mcsTone =
    report && report.mcs >= 60
      ? "text-emerald-600 dark:text-emerald-400"
      : report && report.mcs <= 40
        ? "text-red-600 dark:text-red-400"
        : "text-foreground";

  const deltaText = report
    ? report.mcs_delta === null
      ? t("macro.board.syn.deltaFlat")
      : report.mcs_delta > 0
        ? t("macro.board.syn.deltaUp", { n: Math.abs(report.mcs_delta) })
        : report.mcs_delta < 0
          ? t("macro.board.syn.deltaDown", { n: report.mcs_delta })
          : t("macro.board.syn.deltaFlat")
    : "";

  return (
    <section
      data-testid="macro-syn-panel"
      className="rounded-xl border border-border/60 bg-card p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">
          {t("macro.board.syn.title")}
        </h3>
        <div className="inline-flex rounded-lg border border-border/60 p-0.5">
          {(["month", "quarter"] as const).map((item) => (
            <button
              key={item}
              type="button"
              aria-pressed={periodType === item}
              data-testid={`macro-syn-period-${item}`}
              onClick={() => switchPeriod(item)}
              className={
                periodType === item
                  ? "rounded-md bg-foreground px-2.5 py-1 text-xs text-background"
                  : "rounded-md px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
              }
            >
              {t(item === "month" ? "macro.board.syn.month" : "macro.board.syn.quarter")}
            </button>
          ))}
        </div>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
        {t("macro.board.syn.intro")}
      </p>

      {/* 覆盖检查 */}
      <div className="mt-3 rounded-lg border border-border/50 bg-background/50 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-medium text-foreground">
            {t("macro.board.syn.coverageTitle")}
            {" · "}
            {coverage?.period_label}
          </span>
          <button
            type="button"
            data-testid="macro-syn-run"
            disabled={!economy || runState === "loading"}
            onClick={() => void runSynthesis()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {runState === "loading" && (
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
            )}
            {runState === "loading"
              ? t("macro.board.syn.running")
              : t("macro.board.syn.run")}
          </button>
        </div>

        <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {coverage?.teams.map((team) => (
            <div
              key={team.team}
              data-testid={`macro-syn-team-${team.team}`}
              className={
                team.present
                  ? "rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-2"
                  : "rounded-lg border border-dashed border-border/60 bg-muted/40 p-2"
              }
            >
              <div className="flex items-center gap-1.5">
                {team.present ? (
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" aria-hidden="true" />
                ) : (
                  <Circle className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50" aria-hidden="true" />
                )}
                <span className="truncate text-xs font-medium text-foreground">
                  {team.title}
                </span>
              </div>
              <p className="mt-1 text-[10px] leading-snug text-muted-foreground">
                {team.present
                  ? `${t("macro.board.syn.covered")} · ${team.date || ""}`
                  : t("macro.board.syn.missing")}
              </p>
              {!team.present && (
                <p className="mt-0.5 text-[10px] leading-snug text-muted-foreground">
                  {t("macro.board.syn.missingHint", {
                    title: team.title,
                    period: coverage.period_label,
                  })}
                </p>
              )}
            </div>
          ))}
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
          {coverageMessage()}
        </p>
        {errorMsg && (
          <p
            data-testid="macro-syn-error"
            className="mt-1 text-[11px] text-destructive"
          >
            {errorMsg}
          </p>
        )}
      </div>

      {/* 总体结果 */}
      {runState === "done" && report && (
        <div data-testid="macro-syn-result" className="mt-3 space-y-3">
          {report.cached && (
            <p className="text-[11px] text-muted-foreground">
              {t("macro.board.syn.cached")}
            </p>
          )}

          <div className="grid gap-3 lg:grid-cols-3">
            {/* MCS */}
            <div className="rounded-lg border border-border/50 bg-background/50 p-3">
              <p className="text-[11px] text-muted-foreground">
                {t("macro.board.syn.mcsTitle")}
              </p>
              <p data-testid="macro-syn-mcs" className={`mt-1 text-3xl font-semibold tabular-nums ${mcsTone}`}>
                {report.mcs.toFixed(1)}
              </p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">{deltaText}</p>
              <p className="mt-1 text-[10px] leading-snug text-muted-foreground">
                {t("macro.board.syn.mcsHint")}
              </p>
            </div>

            {/* 周期概率 */}
            <div className="rounded-lg border border-border/50 bg-background/50 p-3 lg:col-span-2">
              <p className="text-[11px] text-muted-foreground">
                {t("macro.board.syn.cycleTitle")}
              </p>
              <div className="mt-2 flex h-6 w-full overflow-hidden rounded-md">
                {CYCLE_ORDER.map((key) => {
                  const value = report.cycle_probs[key] ?? 0;
                  return (
                    <div
                      key={key}
                      className={CYCLE_BAR[key]}
                      style={{ width: `${Math.max(value * 100, 2)}%` }}
                      title={`${t(`macro.board.syn.cycle.${key}` as never)} ${(value * 100).toFixed(0)}%`}
                    />
                  );
                })}
              </div>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                {CYCLE_ORDER.map((key) => (
                  <span key={key} className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                    <span className={`h-2 w-2 rounded-sm ${CYCLE_BAR[key]}`} />
                    {t(`macro.board.syn.cycle.${key}` as never)}
                    {" "}
                    {((report.cycle_probs[key] ?? 0) * 100).toFixed(0)}%
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* 五维信号 */}
          <div className="rounded-lg border border-border/50 bg-background/50 p-3">
            <p className="text-[11px] text-muted-foreground">
              {t("macro.board.syn.dimensionTitle")}
            </p>
            <div className="mt-2 space-y-2">
              {DIM_ORDER.map((key) => {
                const dim = report.dimensions.find((d) => d.dimension === key);
                if (!dim) return null;
                return (
                  <div key={key} className="flex flex-wrap items-center gap-2">
                    <span className="w-20 shrink-0 text-xs font-medium text-foreground">
                      {t(`macro.board.syn.dimension.${key}` as never)}
                    </span>
                    <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium ${signalClass(dim.signal)}`}>
                      {t(`macro.board.syn.signal.${dim.signal}` as never)}
                    </span>
                    <TrendIcon trend={dim.trend} />
                    <span className="text-[10px] text-muted-foreground">
                      {t("macro.board.syn.confidence")} {(dim.confidence * 100).toFixed(0)}%
                    </span>
                    <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-primary" style={{ width: `${dim.confidence * 100}%` }} />
                    </div>
                    <span className="min-w-[8rem] flex-1 text-[10px] leading-snug text-muted-foreground">
                      {dim.rationale}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 资产建议 */}
          <div className="rounded-lg border border-border/50 bg-background/50 p-3">
            <p className="text-[11px] text-muted-foreground">
              {t("macro.board.syn.allocationTitle")}
            </p>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {ASSET_ORDER.map((key) => {
                const value = report.allocation[key] ?? 0;
                return (
                  <div key={key} className={`rounded-lg p-2 text-center ${signalClass(value)}`}>
                    <p className="text-xs font-medium">
                      {t(`macro.board.syn.asset.${key}` as never)}
                    </p>
                    <p className="mt-0.5 text-[10px]">
                      {t(`macro.board.syn.alloc.${value}` as never)}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 结论 / 建议 / 风险 */}
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-border/50 bg-background/50 p-3">
              <p className="text-[11px] font-medium text-foreground">
                {t("macro.board.syn.summaryTitle")}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-foreground">{report.summary}</p>
            </div>
            <div className="rounded-lg border border-border/50 bg-background/50 p-3">
              <p className="text-[11px] font-medium text-foreground">
                {t("macro.board.syn.adviceTitle")}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-foreground">{report.action_advice}</p>
            </div>
          </div>

          <div className="rounded-lg border border-border/50 bg-background/50 p-3">
            <p className="text-[11px] font-medium text-foreground">
              {t("macro.board.syn.riskTitle")}
            </p>
            <ul className="mt-1 list-disc space-y-1 pl-4">
              {report.risk_triggers.map((trigger, index) => (
                <li key={index} className="text-xs leading-relaxed text-muted-foreground">
                  {trigger}
                </li>
              ))}
            </ul>
          </div>

          {/* Claims */}
          <div data-testid="macro-syn-claims" className="rounded-lg border border-border/50 bg-background/50 p-3">
            <p className="text-[11px] font-medium text-foreground">
              {t("macro.board.syn.claimsTitle", { n: report.claims.length })}
            </p>
            <p className="mt-0.5 text-[10px] text-muted-foreground">
              {t("macro.board.syn.claimsHint")}
            </p>
            <div className="mt-2 space-y-2">
              {report.claims.map((claim) => (
                <div key={claim.id ?? `${claim.metric}-${claim.text}`} className="rounded-lg border border-border/40 bg-card p-2">
                  <div className="flex items-start gap-2">
                    <TrendIcon trend={claim.direction} />
                    <p className="flex-1 text-xs leading-relaxed text-foreground">{claim.text}</p>
                    <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {t(`macro.board.syn.claimStatus.${claim.status}` as never)}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 pl-5 text-[10px] text-muted-foreground">
                    <span>{t("macro.board.syn.metric")}: {claim.metric} · {claim.predicted_value}</span>
                    <span>{t("macro.board.syn.probability")}: {(claim.probability * 100).toFixed(0)}%</span>
                    <span>
                      {t("macro.board.syn.window")}: {claim.window_start} ~ {claim.window_end}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 历史 */}
      <div className="mt-3">
        <p className="text-[11px] font-medium text-foreground">
          {t("macro.board.syn.historyTitle")}
        </p>
        {history.length === 0 ? (
          <p className="mt-1 text-[11px] text-muted-foreground">
            {t("macro.board.syn.historyEmpty")}
          </p>
        ) : (
          <ol className="mt-1.5 flex flex-wrap gap-2">
            {history.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  aria-pressed={report?.id === item.id}
                  data-testid={`macro-syn-history-${item.id}`}
                  onClick={() => void viewReport(item.id)}
                  className={
                    report?.id === item.id
                      ? "rounded-full border border-primary/40 bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary"
                      : "rounded-full border border-border/60 bg-card px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/30 hover:text-foreground"
                  }
                >
                  {item.period_label} · MCS {item.mcs.toFixed(0)}
                </button>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
