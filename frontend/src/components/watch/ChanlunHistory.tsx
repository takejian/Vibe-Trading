import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, Loader2, X } from "lucide-react";
import {
  api,
  type ChanlunCardRecord,
  type ChanlunStats,
} from "@/lib/api";
import { MarkdownContent } from "@/components/common/MarkdownContent";
import {
  ChanlunActionCard,
  fmtPct,
  fmtPrice,
  liveStatusClass,
  outcomeClass,
  pctClass,
} from "@/components/watch/ChanlunActionCard";

/** Fixed bilingual titles for the seven parsed Chanlun dimensions.
 *  Order is part of the product contract — do not reorder. */
export const CHANLUN_DIMENSIONS: {
  key: keyof ChanlunCardRecord;
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

function StatsStrip({ stats }: { stats: ChanlunStats }) {
  const { t } = useTranslation();
  const chip = (label: string, value: string | null) => (
    <span
      className="rounded-md border border-border bg-muted/40 px-2 py-1 text-[11px]"
      data-testid="stat-chip"
    >
      <span className="text-muted-foreground">{label} </span>
      <span className="font-semibold">{value ?? "—"}</span>
    </span>
  );
  const ratings = stats.ratings;
  const ratingText =
    `${ratings.accurate ?? 0}/${ratings.partial ?? 0}/${ratings.wrong ?? 0}`;
  return (
    <div
      className="mb-3 flex flex-wrap items-center gap-1.5 rounded-lg border border-border bg-muted/20 px-3 py-2"
      data-testid="chanlun-stats"
    >
      <span className="mr-1 text-xs font-semibold">{t("watch.ch.stats.title")}</span>
      {chip(t("watch.ch.stats.cards"), String(stats.cards_total))}
      {chip(t("watch.ch.stats.sample"), String(stats.verified_decided))}
      {chip(t("watch.ch.stats.winRate"), stats.win_rate === null ? null : `${stats.win_rate}%`)}
      {chip(t("watch.ch.stats.dirAcc"), stats.direction_accuracy === null ? null : `${stats.direction_accuracy}%`)}
      {chip(t("watch.ch.stats.targetRate"), stats.target_hit_rate === null ? null : `${stats.target_hit_rate}%`)}
      {chip(t("watch.ch.stats.stopRate"), stats.stop_rate === null ? null : `${stats.stop_rate}%`)}
      {chip(t("watch.ch.stats.avgMfe"), stats.avg_mfe_pct === null ? null : fmtPct(stats.avg_mfe_pct))}
      {chip(t("watch.ch.stats.avgMae"), stats.avg_mae_pct === null ? null : fmtPct(stats.avg_mae_pct))}
      {chip(t("watch.ch.stats.pending"), String(stats.pending))}
      <span className="rounded-md border border-primary/30 bg-primary/5 px-2 py-1 text-[11px]">
        <span className="text-muted-foreground">{t("watch.ch.stats.rated")} </span>
        <span className="font-semibold">{ratingText}</span>
      </span>
    </div>
  );
}

type CompareField = {
  key: string;
  label: string;
  render: (row: ChanlunCardRecord, t: (k: string) => string) => ReactNode;
  text: (row: ChanlunCardRecord) => string;
};

const COMPARE_FIELDS: CompareField[] = [
  {
    key: "analyzed_at",
    label: "analyzedAt",
    render: (row) => row.analyzed_at,
    text: (row) => row.analyzed_at,
  },
  {
    key: "one_liner",
    label: "card.title",
    render: (row) => row.one_liner || "—",
    text: (row) => row.one_liner ?? "",
  },
  {
    key: "direction",
    label: "dir",
    render: (row, t) =>
      row.direction ? t(`watch.ch.dir.${row.direction}`) : "—",
    text: (row) => row.direction ?? "",
  },
  {
    key: "action",
    label: "action",
    render: (row, t) =>
      row.action ? t(`watch.ch.act.${row.action}`) : "—",
    text: (row) => row.action ?? "",
  },
  { key: "setup", label: "setup", render: (row) => row.setup_class || "—",
    text: (row) => row.setup_class ?? "" },
  {
    key: "confidence",
    label: "confidence",
    render: (row) => (row.card_confidence === null ? "—" : `${Math.round(row.card_confidence)}%`),
    text: (row) => String(row.card_confidence ?? ""),
  },
  { key: "trigger", label: "card.trigger", render: (row) => fmtPrice(row.trigger_price),
    text: (row) => String(row.trigger_price ?? "") },
  { key: "stop", label: "card.stop", render: (row) => fmtPrice(row.stop_price),
    text: (row) => String(row.stop_price ?? "") },
  {
    key: "targets",
    label: "card.target",
    render: (row) =>
      row.target_prices && row.target_prices.length
        ? row.target_prices.map((v) => v.toFixed(2)).join("/")
        : "—",
    text: (row) => (row.target_prices ?? []).join(","),
  },
  {
    key: "rr",
    label: "card.rr",
    render: (row) => (row.rr_at_t1 === null ? "—" : row.rr_at_t1.toFixed(2)),
    text: (row) => String(row.rr_at_t1 ?? ""),
  },
  {
    key: "horizon",
    label: "card.horizon",
    render: (row) => String(row.horizon_days ?? "—"),
    text: (row) => String(row.horizon_days ?? ""),
  },
  {
    key: "live",
    label: "statusCol",
    render: (row, t) =>
      row.live_status ? t(`watch.ch.live.${row.live_status}`) : "—",
    text: (row) => row.live_status ?? "",
  },
  {
    key: "outcome",
    label: "outcomeCol",
    render: (row, t) =>
      row.outcome_label ? t(`watch.ch.out.${row.outcome_label}`) : "—",
    text: (row) => row.outcome_label ?? "",
  },
  {
    key: "exit",
    label: "card.exitReturn",
    render: (row) => (
      <span className={pctClass(row.exit_return_pct)}>
        {fmtPct(row.exit_return_pct)}
      </span>
    ),
    text: (row) => String(row.exit_return_pct ?? ""),
  },
  {
    key: "user",
    label: "card.rating",
    render: (row, t) =>
      row.user_verdict ? t(`watch.ch.rate.${row.user_verdict}`) : "—",
    text: (row) => row.user_verdict ?? "",
  },
];

function ComparePanel({
  rows,
  onClose,
}: {
  rows: ChanlunCardRecord[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const tt = t as unknown as (k: string) => string;
  return (
    <div
      className="mb-4 rounded-lg border border-primary/30 bg-primary/[0.03] p-3"
      data-testid="chanlun-compare-panel"
    >
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-sm font-semibold">{t("watch.ch.compare.title")}</h4>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("watch.ch.compare.clear")}
          className="rounded p-1 hover:bg-muted/60"
          data-testid="compare-close"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-xs">
          <thead className="bg-muted/40 text-left text-muted-foreground">
            <tr>
              <th className="whitespace-nowrap px-2 py-2">
                {t("watch.ch.compare.field")}
              </th>
              {rows.map((row) => (
                <th key={row.run_id} className="whitespace-nowrap px-2 py-2 font-mono">
                  {row.run_id}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {COMPARE_FIELDS.map((field) => {
              const values = rows.map(field.text);
              const differs = new Set(values).size > 1;
              return (
                <tr key={field.key} className="border-t border-border/50">
                  <td className="whitespace-nowrap px-2 py-1.5 font-semibold text-muted-foreground">
                    {tt(field.label)}
                  </td>
                  {rows.map((row) => (
                    <td
                      key={row.run_id}
                      className={`px-2 py-1.5 ${
                        differs ? "bg-amber-500/10" : ""
                      }`}
                      data-testid={`compare-cell-${field.key}`}
                    >
                      {field.render(row, tt)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ChanlunHistory({ symbol }: { symbol: string }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ChanlunCardRecord[]>([]);
  const [stats, setStats] = useState<ChanlunStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [picked, setPicked] = useState<string[]>([]);
  const [compareRows, setCompareRows] = useState<ChanlunCardRecord[] | null>(
    null,
  );
  const [compareLoading, setCompareLoading] = useState(false);

  const load = useCallback(
    async (from?: string, to?: string) => {
      setLoading(true);
      setFailed(false);
      try {
        const [resp, statsResp] = await Promise.all([
          api.listChanlun(symbol, {
            from: from || undefined,
            to: to || undefined,
            limit: 50,
          }),
          api.getChanlunStats(symbol).catch(() => null),
        ]);
        setRows(resp.items);
        setStats(statsResp);
        setPicked((prev) =>
          prev.filter((id) => resp.items.some((r) => r.run_id === id)),
        );
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

  const togglePick = (runId: string) => {
    setPicked((prev) => {
      if (prev.includes(runId)) return prev.filter((id) => id !== runId);
      if (prev.length >= 4) return prev;
      return [...prev, runId];
    });
  };

  const runCompare = async () => {
    if (picked.length < 2) return;
    setCompareLoading(true);
    try {
      const resp = await api.compareChanlunCards(symbol, picked);
      setCompareRows(resp.items);
    } finally {
      setCompareLoading(false);
    }
  };

  const scoreClass = (score: number | null) => {
    if (score === null || score === undefined || score === 0) return "";
    return score > 0 ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400";
  };

  return (
    <section className="mt-6" data-testid="chanlun-history">
      <h3 className="mb-2 text-sm font-semibold">{t("watch.ch.title")}</h3>
      {stats && stats.cards_total > 0 && <StatsStrip stats={stats} />}
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
        <span className="ml-auto text-xs text-muted-foreground">
          {t("watch.ch.compare.hint")}
        </span>
        <button
          type="button"
          disabled={picked.length < 2 || compareLoading}
          onClick={() => void runCompare()}
          className="rounded-md border border-primary/50 px-3 py-1.5 text-xs text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-40"
          data-testid="compare-go"
        >
          {compareLoading && <Loader2 className="mr-1 inline h-3 w-3 animate-spin" aria-hidden="true" />}
          {t("watch.ch.compare.go")} ({picked.length})
        </button>
        {picked.length > 0 && (
          <button
            type="button"
            onClick={() => setPicked([])}
            className="rounded-md border border-border px-2 py-1.5 text-xs hover:bg-muted/60"
            data-testid="compare-clear-picks"
          >
            {t("watch.ch.compare.clear")}
          </button>
        )}
      </div>

      {compareRows && (
        <ComparePanel rows={compareRows} onClose={() => setCompareRows(null)} />
      )}

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
                <th className="px-3 py-2">{t("watch.ch.actionCol")}</th>
                <th className="px-3 py-2">{t("watch.ch.statusCol")}</th>
                <th className="px-3 py-2">{t("watch.ch.score")}</th>
                <th className="px-3 py-2">{t("watch.ch.confidence")}</th>
                <th className="px-3 py-2">{t("watch.ch.outcomeCol")}</th>
                <th className="px-3 py-2">ID</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const open = expanded.has(row.id);
                const isPicked = picked.includes(row.run_id);
                return (
                  <FragmentRow
                    key={row.id}
                    row={row}
                    open={open}
                    onToggle={() => toggle(row.id)}
                    scoreClass={scoreClass(row.score)}
                    picked={isPicked}
                    onPick={() => togglePick(row.run_id)}
                    onRated={() => void load(dateFrom, dateTo)}
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

function CardMini({ row }: { row: ChanlunCardRecord }) {
  const { t } = useTranslation();
  if (row.card_parse !== "ok" || !row.direction) {
    return (
      <span className="text-xs text-muted-foreground" data-testid="card-mini-absent">
        —
      </span>
    );
  }
  const dir = row.direction;
  const strong =
    dir === "bullish"
      ? "text-red-600 dark:text-red-400"
      : dir === "bearish"
        ? "text-green-600 dark:text-green-400"
        : "text-muted-foreground";
  return (
    <div className="max-w-[16rem]" data-testid="card-mini">
      <div className="flex flex-wrap items-center gap-1">
        <span className={`text-xs font-semibold ${strong}`}>
          {t(`watch.ch.dir.${dir}`)}
        </span>
        {row.action && (
          <span className="text-[11px] text-primary">
            {t(`watch.ch.act.${row.action}`)}
          </span>
        )}
        {row.setup_class && row.setup_class !== "none" && (
          <span className="text-[11px] text-muted-foreground">
            {row.setup_class}
          </span>
        )}
      </div>
      {row.one_liner && (
        <p className="truncate text-[11px] text-muted-foreground" title={row.one_liner}>
          {row.one_liner}
        </p>
      )}
      <p className="font-mono text-[10px] text-muted-foreground">
        {fmtPrice(row.trigger_price)} / {fmtPrice(row.stop_price)} /{" "}
        {row.target_prices && row.target_prices.length
          ? row.target_prices.map((v) => v.toFixed(2)).join("/")
          : "—"}
      </p>
    </div>
  );
}

function StatusCell({ row }: { row: ChanlunCardRecord }) {
  const { t } = useTranslation();
  if (row.card_parse === "contract_violation") {
    return (
      <span
        className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-700 dark:text-amber-400"
        title={t("watch.ch.violation")}
      >
        !
      </span>
    );
  }
  if (!row.live_status) return <span className="text-muted-foreground">—</span>;
  return (
    <span
      className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] ${liveStatusClass(
        row.live_status,
      )}`}
      data-testid="row-live-status"
    >
      {t(`watch.ch.live.${row.live_status}`)}
    </span>
  );
}

function OutcomeCell({ row }: { row: ChanlunCardRecord }) {
  const { t } = useTranslation();
  if (row.eval_status !== "verified" || !row.outcome_label) {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <div className="whitespace-nowrap" data-testid="row-outcome">
      <span
        className={`rounded border px-1.5 py-0.5 text-[10px] ${outcomeClass(
          row.outcome_label,
        )}`}
      >
        {t(`watch.ch.out.${row.outcome_label}`)}
      </span>
      {row.exit_return_pct !== null && (
        <span className={`ml-1 font-mono text-[10px] ${pctClass(row.exit_return_pct)}`}>
          {fmtPct(row.exit_return_pct)}
        </span>
      )}
    </div>
  );
}

function FragmentRow({
  row,
  open,
  onToggle,
  scoreClass,
  picked,
  onPick,
  onRated,
}: {
  row: ChanlunCardRecord;
  open: boolean;
  onToggle: () => void;
  scoreClass: string;
  picked: boolean;
  onPick: () => void;
  onRated: () => void;
}) {
  const { t } = useTranslation();
  const comparable = row.card_parse === "ok";
  return (
    <>
      <tr className="border-t border-border/60 hover:bg-muted/30">
        <td className="px-2 py-2">
          <div className="flex items-center gap-1">
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
            <input
              type="checkbox"
              checked={picked}
              disabled={!comparable}
              onChange={onPick}
              aria-label={t("watch.ch.compare.title")}
              data-testid={`compare-pick-${row.run_id}`}
              className="h-3.5 w-3.5"
            />
          </div>
        </td>
        <td className="whitespace-nowrap px-3 py-2">{row.analyzed_at}</td>
        <td className="px-3 py-2"><CardMini row={row} /></td>
        <td className="px-3 py-2"><StatusCell row={row} /></td>
        <td className={`px-3 py-2 font-semibold ${scoreClass}`} data-testid="chanlun-score">
          {formatChanlunScore(row.score)}
        </td>
        <td className="px-3 py-2">{formatConfidence(row.confidence)}</td>
        <td className="px-3 py-2"><OutcomeCell row={row} /></td>
        <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
          {row.run_id}
        </td>
      </tr>
      {open && (
        <tr className="border-t border-border/40 bg-muted/20">
          <td />
          <td colSpan={7} className="px-3 py-3">
            {comparable && (
              <div className="mb-3">
                <ChanlunActionCard record={row} symbol={row.symbol} onRated={onRated} />
              </div>
            )}
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
