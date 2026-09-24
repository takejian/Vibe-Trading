import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { api, ApiError, type MacroJudgment, type MacroReadiness } from "@/lib/api";
import { MacroJudgmentDetail } from "./MacroJudgmentDetail";

type Status = "idle" | "loading" | "insufficient" | "done" | "error" | "timeout";

interface Props {
  /** Compact variant is used on the welcome screen tab panel. */
  embedded?: boolean;
}

const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

export function MacroAnalysisPanel({ embedded = false }: Props) {
  const { t } = useTranslation();
  const [economies, setEconomies] = useState<string[]>([]);
  const [economy, setEconomy] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [judgment, setJudgment] = useState<MacroJudgment | null>(null);
  const [cached, setCached] = useState(false);
  const [readiness, setReadiness] = useState<MacroReadiness | null>(null);
  const [supplement, setSupplement] = useState("");
  const [monthInput, setMonthInput] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .listMacroEconomies()
      .then((res) => {
        if (cancelled) return;
        setEconomies(res.economies);
        setEconomy((prev) => prev || res.economies[0] || "");
      })
      .catch(() => {
        if (!cancelled) setErrorMessage(t("macro.panel.dbUnavailable"));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const run = useCallback(
    async (override?: { supplement?: string; statistics_date?: string }) => {
      if (!economy) return;
      setStatus("loading");
      setErrorMessage("");
      try {
        const res = await api.runMacroCycleJudgment({
          economy,
          supplement: override?.supplement?.trim() || undefined,
          statistics_date: override?.statistics_date?.trim() || undefined,
        });
        setJudgment(res.judgment);
        setCached(res.cached);
        setStatus("done");
        setReadiness(null);
        setSupplement("");
        setMonthInput("");
      } catch (error) {
        if (error instanceof ApiError) {
          if (error.status === 422 && error.payload?.readiness) {
            setReadiness(error.payload.readiness);
            setStatus("insufficient");
            return;
          }
          if (error.status === 409) {
            setErrorMessage(t("macro.panel.inProgress"));
          } else if (error.status === 504) {
            setStatus("timeout");
            setErrorMessage(t("macro.panel.timeout"));
            return;
          } else if (error.status === 503) {
            setErrorMessage(t("macro.panel.dbUnavailable"));
          } else {
            setErrorMessage(error.message || t("macro.panel.failed"));
          }
        } else {
          setErrorMessage(t("macro.panel.failed"));
        }
        setStatus("error");
      }
    },
    [economy, t],
  );

  const monthInvalid = monthInput.trim().length > 0 && !MONTH_RE.test(monthInput.trim());
  const forcedDisabled =
    monthInvalid || (!supplement.trim() && !monthInput.trim());
  const displayedMonth = judgment?.statistics_date
    || readiness?.latest_month
    || "";

  return (
    <div
      data-testid="macro-analysis-panel"
      className={embedded ? "w-full" : "rounded-xl border border-border/60 bg-card p-4"}
    >
      {!embedded && (
        <h3 className="text-sm font-semibold text-foreground">{t("macro.panel.title")}</h3>
      )}
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
        {t("macro.panel.intro")}
      </p>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          {t("macro.panel.economy")}
          <select
            data-testid="macro-economy-select"
            value={economy}
            disabled={status === "loading"}
            onChange={(event) => {
              setEconomy(event.target.value);
              setStatus("idle");
              setJudgment(null);
              setReadiness(null);
            }}
            className="min-w-40 rounded-lg border border-border/60 bg-background px-3 py-1.5 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40 disabled:opacity-50"
          >
            {economies.length === 0 && <option value="">{t("macro.panel.economyPlaceholder")}</option>}
            {economies.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          data-testid="macro-run-button"
          disabled={!economy || status === "loading"}
          onClick={() => run()}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {status === "loading" && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          {status === "loading" ? t("macro.panel.running") : t("macro.panel.run")}
        </button>
        {displayedMonth && (
          <span className="pb-1.5 text-xs text-muted-foreground">
            {t("macro.panel.latestMonth", { month: displayedMonth })}
          </span>
        )}
      </div>

      {status === "insufficient" && readiness && (
        <div
          data-testid="macro-insufficient"
          className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-start"
        >
          <p className="text-sm font-medium text-foreground">{t("macro.panel.insufficientTitle")}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {t("macro.panel.insufficientDesc", { month: readiness.latest_month })}
          </p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              {t("macro.panel.supplement")}
              <textarea
                data-testid="macro-supplement-input"
                value={supplement}
                onChange={(event) => setSupplement(event.target.value)}
                rows={2}
                placeholder={t("macro.panel.supplementPlaceholder")}
                className="rounded-lg border border-border/60 bg-background px-3 py-1.5 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              {t("macro.panel.statisticsMonth")}
              <input
                data-testid="macro-month-input"
                value={monthInput}
                onChange={(event) => setMonthInput(event.target.value)}
                placeholder="YYYY-MM"
                className={`rounded-lg border bg-background px-3 py-1.5 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40 ${
                  monthInvalid ? "border-destructive/60" : "border-border/60"
                }`}
              />
            </label>
          </div>
          <div className="mt-2 flex justify-end">
            <button
              type="button"
              data-testid="macro-force-run-button"
              disabled={forcedDisabled}
              onClick={() =>
                run({
                  supplement: supplement.trim() || undefined,
                  statistics_date: monthInput.trim() || undefined,
                })
              }
              className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {t("macro.panel.submitForced")}
            </button>
          </div>
        </div>
      )}

      {(status === "error" || status === "timeout") && errorMessage && (
        <div
          data-testid="macro-error"
          className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-start"
        >
          <p className="text-xs text-foreground">{errorMessage}</p>
          <button
            type="button"
            onClick={() => run()}
            className="rounded-lg border border-border/60 px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted"
          >
            {t("macro.panel.retry")}
          </button>
        </div>
      )}

      {status === "done" && judgment && (
        <div className="mt-3">
          {cached && (
            <p data-testid="macro-cached-note" className="mb-2 text-xs text-muted-foreground">
              {t("macro.panel.cachedNote", { month: judgment.statistics_date })}
            </p>
          )}
          <MacroJudgmentDetail judgment={judgment} cached={cached} />
        </div>
      )}
    </div>
  );
}
