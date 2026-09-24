import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { api, type MacroJudgment } from "@/lib/api";
import { MacroJudgmentDetail } from "./MacroJudgmentDetail";

interface Props {
  economy: string;
}

/**
 * Month-descending timeline of stored judgments for one economy. History is
 * permanent by product rule, so nothing is deletable from here.
 */
export function MacroHistoryTimeline({ economy }: Props) {
  const { t } = useTranslation();
  const [items, setItems] = useState<MacroJudgment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);

  useEffect(() => {
    if (!economy) {
      setItems([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    setSelectedMonth(null);
    api
      .listMacroJudgments(economy)
      .then((res) => {
        if (cancelled) return;
        setItems(res.judgments);
      })
      .catch(() => {
        if (!cancelled) setError(t("macro.history.loadError"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [economy, t]);

  const selected = items.find((item) => item.statistics_date === selectedMonth) || null;

  return (
    <div data-testid="macro-history-timeline">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-foreground">{t("macro.history.title")}</h4>
        {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-hidden="true" />}
      </div>

      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}

      {!loading && items.length === 0 && !error && (
        <p data-testid="macro-history-empty" className="mt-2 text-xs text-muted-foreground">
          {t("macro.history.empty")}
        </p>
      )}

      {items.length > 0 && (
        <ol className="mt-3 flex flex-wrap gap-2" aria-label={t("macro.history.title")}>
          {items.map((item) => (
            <li key={item.statistics_date}>
              <button
                type="button"
                aria-pressed={item.statistics_date === selectedMonth}
                onClick={() =>
                  setSelectedMonth((prev) =>
                    prev === item.statistics_date ? null : item.statistics_date,
                  )
                }
                className={
                  item.statistics_date === selectedMonth
                    ? "rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-medium text-primary"
                    : "rounded-full border border-border/60 bg-card px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                }
              >
                {item.statistics_date}
              </button>
            </li>
          ))}
        </ol>
      )}

      {selected && (
        <div className="mt-3">
          <MacroJudgmentDetail judgment={selected} />
        </div>
      )}
    </div>
  );
}
