import { useEffect, useRef, useState } from "react";
import { RefreshCw, Loader2, AlertTriangle, AlertCircle } from "lucide-react";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useThemeDark } from "@/lib/theme-store";
import type { GoldCurrentStatus, GoldIndicator } from "@/lib/api";

interface Props {
  status: GoldCurrentStatus;
  onRefresh: () => void;
  refreshNeeded: string | null;
}

const METRIC_META: { key: string; label: string; unit: string }[] = [
  { key: "gold_price",      label: "金价",               unit: "美元/盎司" },
  { key: "ffr",             label: "联邦基金利率",       unit: "%" },
  { key: "yield_nominal",   label: "10Y名义利率",       unit: "%" },
  { key: "tips_real",       label: "10Y实际利率",       unit: "%" },
  { key: "gold_change_pct", label: "金价环比涨跌",       unit: "%" },
  { key: "ffr_change",      label: "利率月度变动",       unit: "pct" },
  { key: "real_change",     label: "实际利率月度变动",   unit: "pct" },
];

function Sparkline({ series, height = 40 }: { series: { month: string; value: number | null }[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const dark = useThemeDark();

  useEffect(() => {
    if (!ref.current || series.length < 2) return;
    const valid = series.filter(s => s.value !== null);
    if (valid.length < 2) return;
    const t = getChartTheme();
    const chart = echarts.init(ref.current);
    const values = valid.map(s => s.value!);
    const positive = values[values.length - 1] >= values[0];
    const color = positive ? t.upColor : t.downColor;
    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 0, right: 0, top: 0, bottom: 0 },
      xAxis: { type: "category", show: false, data: valid.map(s => s.month) },
      yAxis: { type: "value", show: false, scale: true },
      series: [{
        type: "line", data: values, symbol: "none", smooth: true,
        lineStyle: { color, width: 1.5 },
        areaStyle: {
          color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: color + "30" }, { offset: 1, color: color + "05" }] },
        },
      }],
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [series, dark]);

  if (!ref.current || series.length < 2) return <div style={{ height }} />;
  return <div ref={ref} style={{ height }} />;
}

function fmtNum(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(decimals);
}

function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  if (v > 0) return "text-red-500";
  if (v < 0) return "text-green-600";
  return "text-muted-foreground";
}

function pctSign(v: number | null | undefined): string {
  if (v === null || v === undefined) return "";
  return v > 0 ? "+" : "";
}

export function StatusCards({ status, onRefresh, refreshNeeded }: Props) {
  const [refreshing, setRefreshing] = useState(false);

  const handleClick = async () => {
    setRefreshing(true);
    try { await onRefresh(); } finally { setRefreshing(false); }
  };

  const cycle = status.cycle;
  const cycleLabel = cycle.name
    ?? (cycle.start_month
      ? `${cycle.start_month} ~ ${cycle.end_month ?? "至今"}  ${cycle.cycle_type === "hiking" ? "加息周期" : cycle.cycle_type === "cutting" ? "降息周期" : "利率平台"}`
      : "未归属政策周期");

  return (
    <>
      {/* Cycle header */}
      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10">
          <AlertTriangle className="h-4 w-4 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-muted-foreground">当前政策周期</div>
          <div className="text-sm font-semibold truncate">{cycleLabel}</div>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          数据月份：<span className="font-medium text-foreground">{status.latest_month}</span>
        </div>
        {refreshNeeded && (
          <div className="flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-xs text-amber-600">
            <AlertCircle className="h-3.5 w-3.5" />
            {refreshNeeded}数据尚未更新
          </div>
        )}
        <button
          type="button"
          onClick={handleClick}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60 disabled:opacity-50"
        >
          {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          手动刷新
        </button>
      </div>

      {/* 7 metric cards */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {METRIC_META.map(({ key, label, unit }) => {
          const ind = status.indicators[key] as GoldIndicator | undefined;
          const cur = ind?.current ?? null;
          const isPctOrChange = key.endsWith("_change") || key.endsWith("_pct") || key === "ffr_change" || key === "real_change";
          const decimals = key === "gold_price" ? 0 : 2;
          const isTips = key === "tips_real";
          const showNA = cur === null && (isTips && !status.tips_available);

          return (
            <div key={key} className="rounded-lg border border-border bg-card p-3">
              <div className="text-xs text-muted-foreground">{label} ({unit})</div>
              <div className={`mt-1 text-lg font-semibold ${pctClass(isPctOrChange ? cur : null)}`}>
                {showNA ? "N/A" : fmtNum(cur, decimals)}
              </div>
              {isPctOrChange && cur !== null && cur !== undefined && (
                <div className={`text-xs ${pctClass(cur)}`}>{pctSign(cur)}{cur.toFixed(2)} {cur >= 0 ? "📈" : "📉"}</div>
              )}
              <div className="mt-2">
                <Sparkline series={ind?.series ?? []} />
              </div>
              {showNA && (
                <div className="mt-1 text-[10px] text-muted-foreground">TIPS 数据自 2003 年起可用</div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
