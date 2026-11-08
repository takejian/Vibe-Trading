import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw, AlertTriangle, TrendingDown, Activity, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChartLifecycle } from "@/hooks/useChartLifecycle";
import {
  superReboundApi,
  type MarginRatioData,
  type EtfMonitorDetail,
  type EtfMonitorSummary,
} from "@/lib/superRebound";

export function FinancePanel() {
  const { t } = useTranslation();

  const [margin, setMargin] = useState<MarginRatioData | null>(null);
  const [etfSummary, setEtfSummary] = useState<EtfMonitorSummary | null>(null);
  const [etfDetail, setEtfDetail] = useState<EtfMonitorDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);

  // Date filter state
  const defaultStart = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - 40);
    return d.toISOString().slice(0, 10);
  }, []);
  const defaultEnd = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const [startDate, setStartDate] = useState(defaultStart);
  const [endDate, setEndDate] = useState(defaultEnd);
  const [appliedRange, setAppliedRange] = useState<{ start: string; end: string } | null>(null);

  const loadData = useCallback(async (s?: string, e?: string) => {
    setLoading(true);
    setError(null);
    try {
      const [m, sum, d] = await Promise.all([
        superReboundApi.marginRatio().catch(() => null),
        superReboundApi.etfMonitor(s, e).catch(() => null),
        superReboundApi.etfMonitorDetail(s, e).catch(() => null),
      ]);
      setMargin(m);
      setEtfSummary(sum);
      setEtfDetail(d);
    } catch (err: any) {
      setError(err?.message || "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = async () => {
    setRefreshing(true);
    setRefreshMessage(null);
    setError(null);
    try {
      const result = await superReboundApi.refresh();
      if (result.success) {
        setRefreshMessage(`${t("superRebound.refreshSuccess")}（两融 ${result.margin_rows} 行，ETF ${result.etf_rows} 行）`);
        await loadData(appliedRange?.start, appliedRange?.end);
      } else {
        setRefreshMessage(`${t("superRebound.refreshFailed")}: ${result.message}`);
      }
    } catch (err: any) {
      setError(err?.message || "刷新请求失败");
    } finally {
      setRefreshing(false);
      setTimeout(() => setRefreshMessage(null), 5000);
    }
  };

  const handleApplyFilter = async () => {
    setAppliedRange({ start: startDate, end: endDate });
    await loadData(startDate, endDate);
  };

  const handleResetFilter = async () => {
    setStartDate(defaultStart);
    setEndDate(defaultEnd);
    setAppliedRange(null);
    await loadData();
  };

  return (
    <div className="space-y-8">
      {/* Header bar with refresh */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <FileText className="h-4 w-4" />
          {margin?.updated_at && <span>{t("superRebound.updatedAt")}: {margin.updated_at}</span>}
          {!margin && etfDetail?.latest_date && <span>{t("superRebound.updatedAt")}: {etfDetail.latest_date}</span>}
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-background px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
          {t("superRebound.refresh")}
        </button>
      </div>

      {/* Error / message banner */}
      {error && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-4 py-2 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}
      {refreshMessage && (
        <div className="flex items-center gap-2 rounded-md border border-emerald-400/40 bg-emerald-400/10 px-4 py-2 text-sm text-emerald-600">
          {refreshMessage}
        </div>
      )}

      {/* No data placeholder */}
      {!loading && !margin && !etfDetail && !error && (
        <div className="rounded-lg border border-dashed border-border/60 bg-muted/30 px-6 py-12 text-center">
          <p className="text-lg font-medium">{t("superRebound.noData")}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t("superRebound.noDataHint")}</p>
        </div>
      )}

      {/* 1. Margin Ratio Section */}
      {margin && <MarginRatioSection data={margin} loading={loading} />}

      {/* 2. ETF Monitor Section */}
      {etfDetail && (
        <EtfMonitorSection
          summary={etfSummary}
          detail={etfDetail}
          loading={loading}
          startDate={startDate}
          endDate={endDate}
          onStartChange={setStartDate}
          onEndChange={setEndDate}
          onApply={handleApplyFilter}
          onReset={handleResetFilter}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Margin Ratio sub-component
// ---------------------------------------------------------------------------

function MarginRatioSection({ data, loading }: { data: MarginRatioData; loading: boolean }) {
  const { t } = useTranslation();

  const chartRef = useRef<HTMLDivElement>(null);

  // 7 张指标卡 —— 严格对齐截图布局
  const cards: Array<{ label: string; value: string; sub?: string; emphasis?: boolean; warn?: boolean }> = [
    // 1. 最新担保比例 + 日期（最大卡）
    { label: "维持担保比例", value: data.margin_ratio_pct, sub: `截至 ${data.trade_date}`, emphasis: true },
    // 2. 近 6 年分位
    { label: "近6年分位", value: data.six_year_percentile_display },
    // 3. 近 10 年分位
    { label: "近10年分位", value: data.ten_year_percentile_display },
    // 4. 较区间高点
    {
      label: "较区间高点",
      value: data.vs_range_high_display ?? "—",
      warn: data.vs_range_high_pct !== null && data.vs_range_high_pct < -10,
    },
    // 5. 区间高点 + 日期
    {
      label: `区间高${data.range_high_date ? `（${data.range_high_date}）` : ""}`,
      value: data.range_high_display ?? "—",
    },
    // 6. 区间低点 + 日期
    {
      label: `区间低${data.range_low_date ? `（${data.range_low_date}）` : ""}`,
      value: data.range_low_display ?? "—",
    },
    // 7. 样本数
    { label: "样本（交易日）", value: String(data.sample_count) },
  ];

  // Color vs warning line
  const isWarning = data.margin_ratio < data.warning_line;

  // ECharts option
  const history = data.history_series ?? [];
  const dates = useMemo(() => history.map((h) => h.date), [history]);
  const values = useMemo(() => history.map((h) => Number(h.ratio.toFixed(2))), [history]);

  useChartLifecycle(
    chartRef,
    () => ({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(15,23,42,0.92)",
        borderColor: "rgba(148,163,184,0.3)",
        textStyle: { color: "#e2e8f0" },
        formatter: (params: any) => {
          const p = Array.isArray(params) ? params[0] : params;
          if (!p) return "";
          return `<div style="font-weight:600;margin-bottom:4px">${p.axisValue}</div>
                  <div>担保比例: <b>${Number(p.value).toFixed(2)}%</b></div>`;
        },
      },
      grid: { left: 56, right: 24, top: 32, bottom: 72 },
      xAxis: {
        type: "category",
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: "rgba(148,163,184,0.4)" } },
        axisLabel: { color: "#94a3b8", fontSize: 11 },
      },
      yAxis: {
        type: "value",
        name: "担保比例 (%)",
        nameTextStyle: { color: "#94a3b8", fontSize: 11 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: "rgba(148,163,184,0.15)", type: "dashed" } },
        axisLabel: { color: "#94a3b8", fontSize: 11, formatter: "{value}%" },
        scale: true,
      },
      dataZoom: [
        {
          type: "inside",
          start: 0,
          end: 100,
        },
        {
          type: "slider",
          start: 0,
          end: 100,
          height: 22,
          bottom: 16,
          borderColor: "rgba(148,163,184,0.3)",
          fillerColor: "rgba(59,130,246,0.18)",
          handleStyle: { color: "#3b82f6" },
          textStyle: { color: "#94a3b8", fontSize: 10 },
        },
      ],
      series: [
        {
          type: "line",
          data: values,
          smooth: true,
          symbol: "none",
          lineStyle: { color: "#3b82f6", width: 1.8 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(59,130,246,0.28)" },
                { offset: 1, color: "rgba(59,130,246,0.02)" },
              ],
            },
          },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: "#f97316", width: 1.5, type: "dashed" },
            data: [
              {
                yAxis: data.warning_line,
                label: {
                  formatter: `警戒 ${data.warning_line}%`,
                  position: "insideEndTop",
                  color: "#f97316",
                  fontSize: 11,
                },
              },
            ],
          },
        },
      ],
    }),
    [dates, values, data.warning_line],
  );

  return (
    <section className="space-y-4">
      <header className="flex items-center gap-2">
        <Activity className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-semibold">{t("superRebound.marginTitle")}</h2>
        <span className="text-sm text-muted-foreground">· {t("superRebound.marginSubtitle")}</span>
      </header>

      {/* 7 张指标卡 —— 截图布局 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
        {cards.map((c) => (
          <StatCard
            key={c.label}
            label={c.label}
            value={c.value}
            sub={c.sub}
            emphasis={c.emphasis}
            warn={c.warn}
            loading={loading}
          />
        ))}
      </div>

      {/* 折线图 */}
      {history.length > 0 && (
        <div className="rounded-lg border border-border/60 bg-card p-3">
          <div ref={chartRef} className="h-[380px] w-full" />
        </div>
      )}

      {/* 警戒提示 */}
      {isWarning && (
        <div className="flex items-center gap-2 rounded-md border border-amber-400/40 bg-amber-400/10 px-4 py-2 text-sm text-amber-700">
          <AlertTriangle className="h-4 w-4" />
          {`维持担保比例 ${data.margin_ratio_pct} 低于警戒参考线 ${data.warning_line}%`}
        </div>
      )}

      {/* 底部说明 */}
      <p className="text-xs leading-relaxed text-muted-foreground">
        维持担保比例 = 担保物总价值 ÷ 融资融券债务 · 数据区间 {data.data_range_start} ~ {data.data_range_end} · 共 {data.sample_count} 个交易日。
        240% 为两融常用警戒参考线（橙色虚线）。T 日数据预计 T+1 日 22:00 前后更新。
      </p>
    </section>
  );
}

function StatCard({
  label,
  value,
  sub,
  emphasis = false,
  warn = false,
  loading,
}: {
  label: string;
  value: string;
  sub?: string;
  emphasis?: boolean;
  warn?: boolean;
  loading: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border/60 bg-card transition-colors",
        emphasis ? "px-5 py-4 md:col-span-2" : "px-4 py-3",
      )}
    >
      <div className={cn("text-xs text-muted-foreground", emphasis && "text-sm")}>{label}</div>
      {loading ? (
        <div className="mt-1 h-6 w-20 animate-pulse rounded bg-muted" />
      ) : (
        <div
          className={cn(
            "mt-1 tabular-nums font-semibold",
            emphasis ? "text-3xl md:text-4xl text-primary" : "text-xl text-foreground",
            warn && "text-amber-600",
          )}
        >
          {value}
        </div>
      )}
      {sub && !loading && (
        <div className="mt-1 text-xs text-muted-foreground">{sub}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ETF Monitor sub-component
// ---------------------------------------------------------------------------

// 7 个指数组 → echarts 颜色（对齐附件截图配色）
const ETF_GROUP_COLORS: Record<string, string> = {
  中证A500: "#f97316",
  上证50: "#94a3b8",
  沪深300: "#ef4444",
  中证500: "#eab308",
  中证1000: "#3b82f6",
  创业板: "#22c55e",
  科创50: "#1e3a8a",
};

function EtfMonitorSection({
  summary,
  detail,
  loading,
  startDate,
  endDate,
  onStartChange,
  onEndChange,
  onApply,
  onReset,
}: {
  summary: EtfMonitorSummary | null;
  detail: EtfMonitorDetail;
  loading: boolean;
  startDate: string;
  endDate: string;
  onStartChange: (v: string) => void;
  onEndChange: (v: string) => void;
  onApply: () => void;
  onReset: () => void;
}) {
  const { t } = useTranslation();
  const chartRef = useRef<HTMLDivElement>(null);

  const dailyRows = Array.isArray(detail.daily_rows) ? detail.daily_rows : [];
  const cumulativeRow = detail.cumulative_row ?? null;
  const groupCodes = Array.isArray(detail.groups) && detail.groups.length > 0
    ? detail.groups
    : ["中证A500", "上证50", "沪深300", "中证500", "中证1000", "创业板", "科创50"];

  // --- 堆叠柱状图数据（净流入口径：份额变动 × 净值）---
  const chartDates = useMemo(() => dailyRows.map((r) => r.trade_date), [dailyRows]);

  const groupSeries = useMemo(() => {
    return groupCodes.map((g) => ({
      name: g,
      type: "bar",
      stack: "netflow",
      emphasis: { focus: "series" as const },
      itemStyle: {
        color: ETF_GROUP_COLORS[g] ?? "#64748b",
        borderRadius: 0,
      },
      data: dailyRows.map((r) => Number((r.values?.per_group?.[g] ?? 0).toFixed(2))),
    }));
  }, [groupCodes, dailyRows]);

  const chartDeps = useMemo(
    () => [JSON.stringify(dailyRows), JSON.stringify(groupCodes)],
    [dailyRows, groupCodes],
  );

  useChartLifecycle(
    chartRef,
    () => ({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(15,23,42,0.92)",
        borderColor: "rgba(148,163,184,0.3)",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
        axisPointer: { type: "cross" },
        formatter: (params: any) => {
          if (!Array.isArray(params) || params.length === 0) return "";
          const date = params[0].axisValue;
          let total = 0;
          let html = `<div style="font-weight:600;margin-bottom:6px">${date}</div>`;
          for (const p of params) {
            total += Number(p.value ?? 0);
            const color = p.color as string;
            html += `<div style="display:flex;justify-content:space-between;gap:18px">
              <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};margin-right:6px"></span>${p.seriesName}</span>
              <span>${Number(p.value).toFixed(2)} 亿</span>
            </div>`;
          }
          html += `<div style="margin-top:6px;padding-top:6px;border-top:1px dashed rgba(148,163,184,0.3);display:flex;justify-content:space-between;font-weight:600;color:#3b82f6">
            <span>当日合计净流入</span><span>${total.toFixed(2)} 亿</span>
          </div>`;
          return html;
        },
      },
      legend: {
        top: 4,
        left: 12,
        textStyle: { color: "#94a3b8", fontSize: 11 },
        itemWidth: 10,
        itemHeight: 10,
      },
      grid: { left: 64, right: 24, top: 60, bottom: 80 },
      xAxis: {
        type: "category",
        data: chartDates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: "rgba(148,163,184,0.4)" } },
        axisLabel: { color: "#94a3b8", fontSize: 10, rotate: chartDates.length > 20 ? 30 : 0 },
      },
      yAxis: {
        type: "value",
        name: "净流入（亿元）",
        nameTextStyle: { color: "#94a3b8", fontSize: 11 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: "rgba(148,163,184,0.15)", type: "dashed" } },
        axisLabel: { color: "#94a3b8", fontSize: 11 },
      },
      dataZoom: [
        { type: "inside", start: 0, end: 100 },
        {
          type: "slider",
          start: 0,
          end: 100,
          height: 22,
          bottom: 16,
          borderColor: "rgba(148,163,184,0.3)",
          fillerColor: "rgba(59,130,246,0.18)",
          handleStyle: { color: "#3b82f6" },
          textStyle: { color: "#94a3b8", fontSize: 10 },
        },
      ],
      series: groupSeries,
    }),
    [chartDeps],
  );

  // --- 7 张 summary 卡（净流入口径：份额变动 × 净值）---
  const latestStrongest = summary?.latest_strongest_etf ?? null;
  const avgLargest = summary?.avg_largest_etf ?? null;
  const cards: Array<{ label: string; value: string; sub?: string; emphasis?: boolean }> = [
    {
      label: "最新净流入总额",
      value: `${(summary?.latest_total_net_flow_bn ?? 0).toFixed(2)} 亿`,
      sub: `${detail.date_range_start} ~ ${detail.date_range_end}`,
      emphasis: true,
    },
    {
      label: `最新交易日（${summary?.latest_day ?? detail.latest_date ?? "—"}）`,
      value: `${(summary?.latest_day_net_flow_bn ?? 0).toFixed(2)} 亿`,
    },
    {
      label: "区间最高净流入",
      value: `${(summary?.range_high_net_flow_bn ?? 0).toFixed(2)} 亿`,
      sub: summary?.range_high_net_flow_date ? `（${summary.range_high_net_flow_date}）` : undefined,
    },
    {
      label: "当日净流入最大 ETF",
      value: latestStrongest ? latestStrongest.index_group : "—",
      sub: latestStrongest ? `${latestStrongest.etf_name} · ${latestStrongest.net_flow_bn.toFixed(2)} 亿` : undefined,
    },
    {
      label: "区间平均净流入最大 ETF",
      value: avgLargest ? avgLargest.index_group : "—",
      sub: avgLargest ? `${avgLargest.etf_name} · 日均 ${avgLargest.avg_net_flow_bn.toFixed(2)} 亿` : undefined,
    },
    {
      label: "监测天数",
      value: `${summary?.monitor_days ?? dailyRows.length}`,
      sub: "个交易日",
    },
    {
      label: "样本 ETF 数",
      value: `${summary?.sample_etf_count ?? 17}`,
      sub: "7 个指数组",
    },
  ];

  return (
    <section className="space-y-4">
      <header className="flex items-center gap-2">
        <TrendingDown className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-semibold">国家队 ETF 净流入监测</h2>
        <span className="text-sm text-muted-foreground">· 份额口径（申赎净流入）</span>
      </header>

      {/* 7 张 summary 卡 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
        {cards.map((c) => (
          <StatCard
            key={c.label}
            label={c.label}
            value={c.value}
            sub={c.sub}
            emphasis={c.emphasis}
            loading={loading}
          />
        ))}
      </div>

      {/* 堆叠柱状图 */}
      {dailyRows.length > 0 && (
        <div className="rounded-lg border border-border/60 bg-card p-3">
          <div ref={chartRef} className="h-[420px] w-full" />
        </div>
      )}

      {/* 日期筛选 + 表格 */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border/60 bg-card p-3">
        <span className="text-sm font-medium text-muted-foreground">日期筛选:</span>
        <input
          type="date"
          value={startDate}
          onChange={(e) => onStartChange(e.target.value)}
          className="rounded border border-border/60 bg-background px-2 py-1 text-sm"
        />
        <span className="text-muted-foreground">~</span>
        <input
          type="date"
          value={endDate}
          onChange={(e) => onEndChange(e.target.value)}
          className="rounded border border-border/60 bg-background px-2 py-1 text-sm"
        />
        <button
          onClick={onApply}
          disabled={loading}
          className="rounded-md bg-primary px-3 py-1 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {t("superRebound.apply")}
        </button>
        <button
          onClick={onReset}
          className="rounded-md border border-border/60 px-3 py-1 text-sm text-muted-foreground hover:text-foreground"
        >
          {t("superRebound.reset")}
        </button>
      </div>

      {/* ETF Detail Table（补充信息） */}
      <div className="overflow-x-auto rounded-lg border border-border/60">
        <table className="min-w-full text-sm">
          <thead className="bg-muted/50 text-muted-foreground">
            <tr>
              <th className="sticky left-0 z-10 px-3 py-2 text-left font-medium bg-muted/50">日期</th>
              {groupCodes.map((g) => (
                <th key={g} className="px-3 py-2 text-right font-medium whitespace-nowrap">{g}</th>
              ))}
              <th className="px-3 py-2 text-right font-medium whitespace-nowrap bg-primary/10">每日合计</th>
            </tr>
          </thead>
          <tbody>
            {dailyRows.length === 0 && (
              <tr>
                <td colSpan={groupCodes.length + 2} className="px-3 py-10 text-center text-sm text-muted-foreground">
                  {detail.note || t("superRebound.noDataHint")}
                </td>
              </tr>
            )}
            {dailyRows.map((row) => {
              const isLatest = row.is_latest;
              const perGroup = row.values?.per_group ?? {};
              return (
                <tr
                  key={row.trade_date}
                  className={cn(
                    "border-t border-border/40 transition-colors",
                    isLatest && "bg-primary/10 font-medium",
                    !isLatest && "hover:bg-muted/30",
                  )}
                >
                  <td className={cn("sticky left-0 z-10 px-3 py-2 bg-inherit whitespace-nowrap", isLatest && "bg-primary/10")}>
                    {row.trade_date}
                  </td>
                  {groupCodes.map((g) => {
                    const v = Number(perGroup[g] ?? 0);
                    return (
                      <td
                        key={g}
                        className={cn(
                          "px-3 py-2 text-right tabular-nums",
                          v < 0 && "text-red-500",
                        )}
                      >
                        {v.toFixed(2)}
                      </td>
                    );
                  })}
                  <td className={cn("px-3 py-2 text-right tabular-nums font-semibold", isLatest && "text-primary")}>
                    {(row.values?.total ?? 0).toFixed(2)}
                  </td>
                </tr>
              );
            })}
            {cumulativeRow && (
              <tr className="border-t-2 border-border bg-muted/30 font-semibold">
                <td className="sticky left-0 z-10 px-3 py-2 bg-muted/30">区间平均</td>
                {groupCodes.map((g) => {
                  const v = Number((cumulativeRow.values?.per_group ?? {})[g] ?? 0);
                  return (
                    <td
                      key={g}
                      className={cn("px-3 py-2 text-right tabular-nums", v < 0 && "text-red-500")}
                    >
                      {v.toFixed(2)}
                    </td>
                  );
                })}
                <td className="px-3 py-2 text-right tabular-nums text-primary">
                  {(cumulativeRow.values?.total ?? 0).toFixed(2)}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs leading-relaxed text-muted-foreground">
        ETF 规模 = 当日份额（万份）× 单位净值 ÷ 10000（亿元），即该 ETF 当日总 AUM；按指数组汇总反映大资金在各宽基上的持仓规模。
        数据来源：上交所 query.sse.com.cn 官方份额接口 + akshare fund_open_fund_info_em（东方财富 fundf10）净值接口。T 日份额/净值 T+1 日 22:00 前后更新。
      </p>
    </section>
  );
}
