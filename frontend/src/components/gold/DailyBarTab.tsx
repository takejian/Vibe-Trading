import { useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, Loader2, TrendingUp, TrendingDown, AlertTriangle } from "lucide-react";
import type { GoldDailyBar } from "@/lib/api";
import { echarts } from "@/lib/echarts";
import { getChartTheme } from "@/lib/chart-theme";
import { useThemeDark } from "@/lib/theme-store";

type RangeKey = "1M" | "3M" | "1Y" | "3Y" | "ALL";
const RANGE_DAYS: Record<RangeKey, number> = { "1M": 30, "3M": 90, "1Y": 365, "3Y": 1095, ALL: Infinity };

interface Props {
  bars: GoldDailyBar[];
  latest: GoldDailyBar | null;
  latestSummary: GoldDailyBar | null;
  loading: boolean;
  onRefresh: () => Promise<void>;
  refreshing: boolean;
}

// --- 简单 MA 计算 (前端本地计算, 不依赖后端字段) ---
function calcMA(values: (number | null)[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      out.push(null);
      continue;
    }
    const slice = values.slice(i - period + 1, i + 1).filter((v): v is number => v !== null);
    if (slice.length !== period) {
      out.push(null);
    } else {
      out.push(slice.reduce((a, b) => a + b, 0) / period);
    }
  }
  return out;
}

export function DailyBarTab({ bars, latest, latestSummary, loading, onRefresh, refreshing }: Props) {
  const [range, setRange] = useState<RangeKey>("1Y");
  const [showMA5, setShowMA5] = useState(true);
  const [showMA20, setShowMA20] = useState(true);
  const [showMA60, setShowMA60] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstRef = useRef<ReturnType<typeof echarts.init> | null>(null);
  const dark = useThemeDark();

  // 根据 range 过滤 bars (bars 已按日期升序)
  const visible = useMemo(() => {
    if (!Number.isFinite(RANGE_DAYS[range]) || bars.length === 0) return bars;
    const cutoff = Date.now() - RANGE_DAYS[range] * 86400000;
    return bars.filter(b => new Date(b.trade_date).getTime() >= cutoff);
  }, [bars, range]);

  // MA 计算
  const closes = useMemo(() => visible.map(b => b.close), [visible]);
  const ma5 = useMemo(() => calcMA(closes, 5), [closes]);
  const ma20 = useMemo(() => calcMA(closes, 20), [closes]);
  const ma60 = useMemo(() => calcMA(closes, 60), [closes]);

  // --- 图表渲染 ---
  useEffect(() => {
    if (!chartRef.current || visible.length === 0) return;
    const t = getChartTheme();
    const chart = chartInstRef.current ?? echarts.init(chartRef.current);
    chartInstRef.current = chart;

    const dates = visible.map(b => b.trade_date);
    const closeSeries = closes.map((c, i) => [dates[i], c]);

    const series: any[] = [
      {
        name: "收盘价",
        type: "line",
        data: closeSeries,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: t.upColor },
        areaStyle: {
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(59, 130, 246, 0.25)" },
              { offset: 1, color: "rgba(59, 130, 246, 0.0)" },
            ],
          },
        },
      },
    ];

    const overlays: { show: boolean; ma: (number | null)[]; color: string; name: string }[] = [
      { show: showMA5, ma: ma5, color: "#f59e0b", name: "MA5" },
      { show: showMA20, ma: ma20, color: "#8b5cf6", name: "MA20" },
      { show: showMA60, ma: ma60, color: "#3b82f6", name: "MA60" },
    ];
    for (const ov of overlays) {
      if (!ov.show) continue;
      series.push({
        name: ov.name,
        type: "line",
        data: ov.ma.map((v, i) => (v === null ? null : [dates[i], v])),
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, color: ov.color },
      });
    }

    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 50, right: 20, top: 20, bottom: 40 },
      tooltip: {
        trigger: "axis",
        backgroundColor: dark ? "#1e293b" : "#ffffff",
        borderColor: t.axisColor,
        textStyle: { color: t.textColor },
        formatter: (params: any[]) => {
          const date = params[0]?.value?.[0] ?? "";
          let html = `<div class="font-medium mb-1">${date}</div>`;
          for (const p of params) {
            const v = p.value?.[1];
            if (v === null || v === undefined) continue;
            html += `<div>${p.marker} ${p.seriesName}: <b>${v.toFixed(2)}</b></div>`;
          }
          return html;
        },
      },
      legend: { show: false },
      xAxis: {
        type: "category",
        data: dates,
        axisLine: { lineStyle: { color: t.axisColor } },
        axisLabel: { color: t.textColor },
        boundaryGap: false,
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        axisLabel: { color: t.textColor, formatter: (v: number) => v.toFixed(0) },
        splitLine: { lineStyle: { color: t.gridColor, type: "dashed" } },
        scale: true,
      },
      series,
    });
    const handleResize = () => chart.resize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [visible, closes, ma5, ma20, ma60, showMA5, showMA20, showMA60, dark]);

  useEffect(() => () => chartInstRef.current?.dispose(), []);

  // --- 渲染 ---
  if (loading) {
    return (
      <div className="flex h-40 items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载日线行情...
      </div>
    );
  }

  if (!bars || bars.length === 0) {
    return (
      <div className="flex h-60 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border text-muted-foreground">
        <AlertTriangle className="h-8 w-8" />
        <div className="text-sm">暂无日线数据，点击下方按钮初始化</div>
        <button
          type="button"
          disabled={refreshing}
          onClick={onRefresh}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {refreshing ? <Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> : null}
          {refreshing ? "拉取中..." : "🔄 加载日线历史"}
        </button>
      </div>
    );
  }

  const summary = latestSummary ?? latest;
  const changePct = summary?.change_pct ?? 0;
  const changeAmt = summary?.change_amt ?? 0;
  const isUp = changePct >= 0;
  const colorClass = isUp ? "text-red-500" : "text-emerald-500";
  const Icon = isUp ? TrendingUp : TrendingDown;

  return (
    <div className="space-y-6">
      {/* --- 最新价卡片 --- */}
      <div className="rounded-md border border-border bg-card p-4">
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">当日最新价</div>
            <div className="flex items-baseline gap-3">
              <div className="text-3xl font-semibold tabular-nums">
                <span className="mr-1 text-base text-muted-foreground">￥</span>
                {summary?.close?.toFixed(2)}
                <span className="ml-1 text-sm text-muted-foreground">/克</span>
              </div>
              {summary?.price_usd_per_oz != null && (
                <div className="text-sm text-muted-foreground">
                  ≈ <span className="text-base font-medium text-foreground">${summary.price_usd_per_oz.toFixed(2)}</span>
                  <span className="ml-1 text-xs">/盎司</span>
                  <span className="ml-1 text-xs">（换算参考）</span>
                </div>
              )}
            </div>
            {summary && (
              <div className={`flex items-center gap-1 text-sm font-medium ${colorClass}`}>
                <Icon className="h-4 w-4" />
                <span>{isUp ? "+" : ""}{changeAmt.toFixed(2)}</span>
                <span>({isUp ? "+" : ""}{changePct.toFixed(2)}%)</span>
              </div>
            )}
          </div>

          <div className="flex flex-col items-end gap-2 text-right text-xs text-muted-foreground">
            {summary?.is_interday && (
              <div className="rounded bg-amber-500/10 px-2 py-0.5 text-amber-600 dark:text-amber-400">
                ⚠️ 盘中实时
              </div>
            )}
            <div>数据源：{summary?.source ?? "akshare / SHFE AU0"}</div>
            <div>交易日：{summary?.trade_date}</div>
            {summary?.fetched_at && (
              <div>最后更新：{summary.fetched_at.replace("T", " ")}</div>
            )}
            <button
              type="button"
              onClick={onRefresh}
              disabled={refreshing}
              className="mt-1 inline-flex items-center gap-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
            >
              {refreshing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {refreshing ? "刷新中..." : "手动刷新"}
            </button>
          </div>
        </div>
      </div>

      {/* --- 日线图 --- */}
      <div className="rounded-md border border-border bg-card p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-1">
            {(["1M", "3M", "1Y", "3Y", "ALL"] as RangeKey[]).map(rk => (
              <button
                key={rk}
                type="button"
                onClick={() => setRange(rk)}
                className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                  range === rk
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:text-foreground"
                }`}
              >
                {rk === "ALL" ? "全部" : rk}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">均线：</span>
            {([
              { k: "MA5", v: showMA5, set: setShowMA5, color: "#f59e0b" },
              { k: "MA20", v: showMA20, set: setShowMA20, color: "#8b5cf6" },
              { k: "MA60", v: showMA60, set: setShowMA60, color: "#3b82f6" },
            ] as const).map(m => (
              <button
                key={m.k}
                type="button"
                onClick={() => m.set(!m.v)}
                className={`flex items-center gap-1 rounded px-2 py-0.5 transition-colors ${
                  m.v ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: m.color }} />
                {m.k}
              </button>
            ))}
          </div>
        </div>
        <div ref={chartRef} className="h-[380px] w-full" />
        <div className="mt-2 text-center text-xs text-muted-foreground">
          纵轴：收盘价 人民币/克 · 共 {visible.length} 根日线
        </div>
      </div>

      {/* --- 近 5 日明细 --- */}
      <div className="rounded-md border border-border bg-card p-4">
        <h3 className="mb-3 text-sm font-medium">近 5 个交易日明细</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="py-2 pr-3">日期</th>
                <th className="py-2 pr-3 text-right">开盘</th>
                <th className="py-2 pr-3 text-right">最高</th>
                <th className="py-2 pr-3 text-right">最低</th>
                <th className="py-2 pr-3 text-right">收盘</th>
                <th className="py-2 pr-3 text-right">涨跌</th>
                <th className="py-2 pr-3 text-right">USD/oz</th>
              </tr>
            </thead>
            <tbody>
              {bars.slice(-5).map(b => {
                const chgPct = b.change_pct ?? 0;
                const chgAmt = b.change_amt ?? 0;
                const up = chgPct >= 0;
                return (
                  <tr key={b.trade_date} className="border-b border-border/50 last:border-0">
                    <td className="py-2 pr-3">{b.trade_date}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{b.open?.toFixed(2)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums text-red-500">{b.high?.toFixed(2)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums text-emerald-500">{b.low?.toFixed(2)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums font-medium">{b.close?.toFixed(2)}</td>
                    <td className={`py-2 pr-3 text-right tabular-nums ${up ? "text-red-500" : "text-emerald-500"}`}>
                      {up ? "+" : ""}{chgAmt.toFixed(2)}
                      <span className="ml-1 text-xs opacity-80">({up ? "+" : ""}{chgPct.toFixed(2)}%)</span>
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">
                      {b.price_usd_per_oz?.toFixed(2) ?? "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
