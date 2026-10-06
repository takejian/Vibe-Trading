import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { api, type ChanlunRecord } from "@/lib/api";
import { MarkdownContent } from "@/components/common/MarkdownContent";

/** Fixed bilingual titles for the seven parsed Chanlun dimensions.
 *  Order is part of the product contract — do not reorder. */
export const CHANLUN_DIMENSIONS: {
  key: keyof ChanlunRecord;
  zh: string;
  en: string;
}[] = [
  { key: "dim1_structure_read", zh: "结构读取", en: "Structure Read" },
  { key: "dim2_active_pivots", zh: "活跃支点", en: "Active Pivots" },
  { key: "dim3_divergence", zh: "背驰", en: "Divergence" },
  { key: "dim4_buy_sell_points", zh: "买卖点", en: "Buy/Sell Points" },
  { key: "dim5_multi_level_plan", zh: "多级别计划", en: "Multi-level Plan" },
  { key: "dim6_elliott_corroboration", zh: "艾略特验证", en: "Elliott Corroboration" },
  { key: "dim7_chanlun_score", zh: "缠论打分", en: "Chanlun Score" },
];

export function formatChanlunScore(score: number | null): string {
  if (score === null || score === undefined) return "—";
  return score > 0 ? `+${score}` : String(score);
}

export function formatConfidence(confidence: number | null): string {
  if (confidence === null || confidence === undefined) return "—";
  return `${Math.round(confidence * 100)}%`;
}

export function ChanlunHistory({ symbol }: { symbol: string }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ChanlunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(
    async (from?: string, to?: string) => {
      setLoading(true);
      setFailed(false);
      try {
        const resp = await api.listChanlun(symbol, {
          from: from || undefined,
          to: to || undefined,
          limit: 50,
        });
        setRows(resp.items);
      } catch {
        setFailed(true);
      } finally {
        setLoading(false);
      }
    },
    [symbol],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const scoreClass = (score: number | null) => {
    if (score === null || score === undefined || score === 0) return "";
    return score > 0 ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400";
  };

  return (
    <section className="mt-6" data-testid="chanlun-history">
      <h3 className="mb-2 text-sm font-semibold">{t("watch.ch.title")}</h3>

      <div className="mb-3 flex flex-wrap items-end gap-3 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">{t("watch.ch.from")}</span>
          <input
            type="date"
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => setDateFrom(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1"
            data-testid="chanlun-from"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">{t("watch.ch.to")}</span>
          <input
            type="date"
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => setDateTo(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1"
            data-testid="chanlun-to"
          />
        </label>
        <button
          type="button"
          onClick={() => void load(dateFrom, dateTo)}
          className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-muted/60"
        >
          {t("watch.ch.filter")}
        </button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        </div>
      ) : failed ? (
        <p className="py-4 text-sm text-red-500">{t("watch.error.dataFailed")}</p>
      ) : rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground" data-testid="chanlun-empty">
          {t("watch.ch.recordEmpty")}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                <th className="w-8 px-2 py-2" />
                <th className="px-3 py-2">{t("watch.ch.analyzedAt")}</th>
                <th className="px-3 py-2">{t("watch.ch.score")}</th>
                <th className="px-3 py-2">{t("watch.ch.confidence")}</th>
                <th className="px-3 py-2">ID</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const open = expanded.has(row.id);
                return (
                  <FragmentRow
                    key={row.id}
                    row={row}
                    open={open}
                    onToggle={() => toggle(row.id)}
                    scoreClass={scoreClass(row.score)}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function FragmentRow({
  row,
  open,
  onToggle,
  scoreClass,
}: {
  row: ChanlunRecord;
  open: boolean;
  onToggle: () => void;
  scoreClass: string;
}) {
  const { t } = useTranslation();
  return (
    <>
      <tr className="border-t border-border/60 hover:bg-muted/30">
        <td className="px-2 py-2">
          <button
            type="button"
            onClick={onToggle}
            aria-label={open ? t("watch.an.collapse") : t("watch.an.expand")}
            aria-expanded={open}
          >
            {open ? (
              <ChevronDown className="h-4 w-4" aria-hidden="true" />
            ) : (
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            )}
          </button>
        </td>
        <td className="whitespace-nowrap px-3 py-2">{row.analyzed_at}</td>
        <td className={`px-3 py-2 font-semibold ${scoreClass}`} data-testid="chanlun-score">
          {formatChanlunScore(row.score)}
        </td>
        <td className="px-3 py-2">{formatConfidence(row.confidence)}</td>
        <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
          {row.run_id}
        </td>
      </tr>
      {open && (
        <tr className="border-t border-border/40 bg-muted/20">
          <td />
          <td colSpan={4} className="px-3 py-3">
            {row.structured ? (
              <dl className="grid gap-4">
                {CHANLUN_DIMENSIONS.map((dim) => {
                  const content = String(row[dim.key] ?? "");
                  return (
                    <div key={dim.key}>
                      <dt className="mb-1 text-xs font-semibold text-muted-foreground">
                        {dim.zh} <span className="opacity-70">/ {dim.en}</span>
                      </dt>
                      <dd className="mt-0.5 text-sm">
                        {content ? (
                          <MarkdownContent content={content} />
                        ) : (
                          <span className="text-muted-foreground">{t("watch.noData")}</span>
                        )}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            ) : (
              <div>
                <p className="mb-2 text-xs text-amber-600 dark:text-amber-400">
                  {t("watch.ch.unstructured")}
                </p>
                {row.raw_report ? (
                  <MarkdownContent content={row.raw_report} />
                ) : (
                  <span className="text-muted-foreground">{t("watch.noData")}</span>
                )}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
