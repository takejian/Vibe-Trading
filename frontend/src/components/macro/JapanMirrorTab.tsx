import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Compass,
  Landmark,
  Scale,
  Sparkles,
  XCircle,
} from "lucide-react";
import { echarts } from "@/lib/echarts";
import { useThemeDark } from "@/lib/theme-store";
import {
  CHINA_METRICS,
  JAPAN_METRICS,
  JAPAN_MIRROR_DISCLAIMER,
  JAPAN_MIRROR_FRAMEWORK,
  JAPAN_MIRROR_INTRO,
  MIRROR_LESSONS,
  MIRROR_PHASES,
} from "./japanMirrorData";

/** 日本 1985-2005 ↔ 中国 2015-2025 双指标图（x 轴按 1991/2021 对齐）。 */
function MirrorCharts({ dark }: { dark: boolean }) {
  const jpRef = useRef<HTMLDivElement>(null);
  const cnRef = useRef<HTMLDivElement>(null);

  const pairedLabels = useMemo(
    () => JAPAN_METRICS.map((p, i) => `${p.year} / ${CHINA_METRICS[i]?.year ?? ""}`),
    [],
  );

  useEffect(() => {
    const charts: ReturnType<typeof echarts.init>[] = [];

    const baseGrid = { left: 48, right: 48, top: 34, bottom: 28 };
    const axisLabel = { color: dark ? "#a1a1aa" : "#71717a", fontSize: 10 };
    const splitLine = { lineStyle: { color: dark ? "#27272a" : "#f4f4f5" } };

    if (jpRef.current) {
      const chart = echarts.init(jpRef.current);
      chart.setOption({
        backgroundColor: "transparent",
        title: {
          text: "日本 1985–2005：日经 / 地价指数 / 政策利率",
          left: 8,
          top: 4,
          textStyle: { fontSize: 11, color: dark ? "#e4e4e7" : "#18181b" },
        },
        tooltip: { trigger: "axis" },
        legend: {
          right: 8,
          top: 4,
          itemWidth: 12,
          itemHeight: 8,
          textStyle: { fontSize: 10, color: dark ? "#d4d4d8" : "#3f3f46" },
        },
        grid: baseGrid,
        xAxis: {
          type: "category",
          data: pairedLabels,
          axisLabel: { ...axisLabel, rotate: 45 },
        },
        yAxis: [
          {
            type: "value",
            name: "点/指数",
            nameTextStyle: { fontSize: 9, color: axisLabel.color },
            axisLabel,
            splitLine,
            scale: true,
          },
          {
            type: "value",
            name: "利率%",
            nameTextStyle: { fontSize: 9, color: axisLabel.color },
            axisLabel,
            splitLine: { show: false },
            min: -1,
            max: 7,
          },
        ],
        series: [
          {
            name: "日经平均(年末)",
            type: "line",
            data: JAPAN_METRICS.map((p) => p.nikkei),
            smooth: true,
            symbol: "circle",
            symbolSize: 4,
            lineStyle: { color: "#dc2626", width: 2 },
            itemStyle: { color: "#dc2626" },
            markLine: {
              symbol: "none",
              data: [{ xAxis: pairedLabels[6] }],
              lineStyle: { color: "#f59e0b", type: "dashed" },
              label: { formatter: "1991 地价见顶", fontSize: 9, color: "#f59e0b" },
            },
          },
          {
            name: "六大城市地价(1990=100)",
            type: "line",
            data: JAPAN_METRICS.map((p) => p.land),
            smooth: true,
            symbol: "none",
            lineStyle: { color: "#f97316", width: 1.5, type: "dashed" },
            itemStyle: { color: "#f97316" },
          },
          {
            name: "政策利率%(右轴)",
            type: "line",
            yAxisIndex: 1,
            data: JAPAN_METRICS.map((p) => p.rate),
            smooth: false,
            symbol: "none",
            lineStyle: { color: "#2563eb", width: 1.5 },
            itemStyle: { color: "#2563eb" },
          },
        ],
      });
      charts.push(chart);
    }

    if (cnRef.current) {
      const chart = echarts.init(cnRef.current);
      chart.setOption({
        backgroundColor: "transparent",
        title: {
          text: "中国 2015–2025：上证 / LPR（对齐日本后移 30 年）",
          left: 8,
          top: 4,
          textStyle: { fontSize: 11, color: dark ? "#e4e4e7" : "#18181b" },
        },
        tooltip: { trigger: "axis" },
        legend: {
          right: 8,
          top: 4,
          itemWidth: 12,
          itemHeight: 8,
          textStyle: { fontSize: 10, color: dark ? "#d4d4d8" : "#3f3f46" },
        },
        grid: baseGrid,
        xAxis: {
          type: "category",
          data: pairedLabels,
          axisLabel: { ...axisLabel, rotate: 45 },
        },
        yAxis: [
          {
            type: "value",
            name: "点",
            nameTextStyle: { fontSize: 9, color: axisLabel.color },
            axisLabel,
            splitLine,
            scale: true,
          },
          {
            type: "value",
            name: "LPR%",
            nameTextStyle: { fontSize: 9, color: axisLabel.color },
            axisLabel,
            splitLine: { show: false },
            min: 2,
            max: 5,
          },
        ],
        series: [
          {
            name: "上证综指(年末)",
            type: "line",
            data: CHINA_METRICS.map((p) => p.sse),
            smooth: true,
            symbol: "circle",
            symbolSize: 4,
            lineStyle: { color: "#dc2626", width: 2 },
            itemStyle: { color: "#dc2626" },
            markLine: {
              symbol: "none",
              data: [{ xAxis: pairedLabels[6] }],
              lineStyle: { color: "#f59e0b", type: "dashed" },
              label: { formatter: "2021 地产见顶", fontSize: 9, color: "#f59e0b" },
            },
          },
          {
            name: "1Y LPR%(右轴)",
            type: "line",
            yAxisIndex: 1,
            data: CHINA_METRICS.map((p) => p.lpr),
            smooth: false,
            symbol: "none",
            lineStyle: { color: "#2563eb", width: 1.5 },
            itemStyle: { color: "#2563eb" },
          },
        ],
      });
      charts.push(chart);
    }

    let frame = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => charts.forEach((c) => c.resize()));
    });
    if (jpRef.current) ro.observe(jpRef.current);
    if (cnRef.current) ro.observe(cnRef.current);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(frame);
      charts.forEach((c) => c.dispose());
    };
  }, [dark, pairedLabels]);

  return (
    <div data-testid="japan-mirror-charts" className="grid gap-3 lg:grid-cols-2">
      <div className="rounded-lg border border-border/50 bg-card p-2">
        <div ref={jpRef} style={{ height: 280 }} />
      </div>
      <div className="rounded-lg border border-border/50 bg-card p-2">
        <div ref={cnRef} style={{ height: 280 }} />
      </div>
    </div>
  );
}

function YearRow({
  jpYear,
  cnYear,
  jp,
  cn,
  cnProjected,
}: {
  jpYear: number;
  cnYear: number;
  jp: string[];
  cn: string[];
  cnProjected?: boolean;
}) {
  return (
    <div className="grid gap-2 border-t border-dashed border-border/60 py-2 md:grid-cols-2">
      <div data-testid={`japan-year-${jpYear}`} className="pr-2">
        <p className="mb-1 text-[11px] font-semibold text-red-600 dark:text-red-400">
          日本 {jpYear}
        </p>
        <ul className="space-y-0.5">
          {jp.map((item, i) => (
            <li key={i} className="flex gap-1.5 text-[11px] leading-snug text-muted-foreground">
              <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-red-400" />
              {item}
            </li>
          ))}
        </ul>
      </div>
      <div
        data-testid={`china-year-${cnYear}`}
        className="md:border-l md:border-dashed md:border-border/60 md:pl-3"
      >
        <p className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-blue-600 dark:text-blue-400">
          中国 {cnYear}
          {cnProjected && (
            <span className="rounded bg-amber-500/15 px-1 py-0.5 text-[9px] font-normal text-amber-600 dark:text-amber-400">
              情景推演
            </span>
          )}
        </p>
        <ul className="space-y-0.5">
          {cn.map((item, i) => (
            <li key={i} className="flex gap-1.5 text-[11px] leading-snug text-muted-foreground">
              <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-blue-400" />
              {item}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** 宏观经济分析 - 日本镜鉴 tab：野口悠纪雄框架下的 1991↔2021 双轨叙事。 */
export function JapanMirrorTab() {
  const { t } = useTranslation();
  const dark = useThemeDark();

  const scrollToPhase = (id: string) => {
    document.getElementById(`japan-phase-${id}`)?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  };

  return (
    <div data-testid="japan-mirror-tab" className="space-y-4">
      {/* 导语 */}
      <div className="rounded-lg border border-border/60 bg-gradient-to-br from-card to-background p-4">
        <div className="flex items-center gap-2">
          <Landmark className="h-4 w-4 text-primary" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-foreground">
            {t("macro.tabs.japan")}：1991 ↔ 2021 的三十年镜像
          </h2>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          {JAPAN_MIRROR_INTRO}
        </p>
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-primary/5 p-2.5">
          <BookOpen className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
          <p className="text-[11px] leading-relaxed text-foreground/90">
            {JAPAN_MIRROR_FRAMEWORK}
          </p>
        </div>
        <p className="mt-2 flex items-start gap-1.5 text-[10px] text-muted-foreground/80">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
          {JAPAN_MIRROR_DISCLAIMER}
        </p>
      </div>

      {/* 指标对照图 */}
      <MirrorCharts dark={dark} />

      {/* 阶段导航 */}
      <div className="flex flex-wrap gap-1.5">
        {MIRROR_PHASES.map((phase) => (
          <button
            key={phase.id}
            type="button"
            onClick={() => scrollToPhase(phase.id)}
            className="rounded-full border border-border/60 bg-card px-2.5 py-1 text-[10px] text-muted-foreground transition hover:border-primary/50 hover:text-primary"
          >
            {phase.title.replace(/^[一二三四五六七]、/, "")}
          </button>
        ))}
      </div>

      {/* 阶段叙事 */}
      {MIRROR_PHASES.map((phase) => (
        <section
          key={phase.id}
          id={`japan-phase-${phase.id}`}
          data-testid={`japan-phase-${phase.id}`}
          className="scroll-mt-4 rounded-lg border border-border/60 bg-card p-3.5"
        >
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="text-sm font-semibold text-foreground">{phase.title}</h3>
            <span className="rounded bg-red-500/10 px-1.5 py-0.5 text-[10px] text-red-600 dark:text-red-400">
              日本 {phase.jpRange}
            </span>
            <span className="rounded bg-blue-500/10 px-1.5 py-0.5 text-[10px] text-blue-600 dark:text-blue-400">
              中国 {phase.cnRange}
            </span>
          </div>

          <div className="mt-2 grid gap-3 md:grid-cols-2">
            <div className="rounded-lg bg-red-500/[0.03] p-2.5">
              <p className="mb-1 text-[11px] font-semibold text-red-700 dark:text-red-400">
                日本侧
              </p>
              {phase.jpNarrative.map((para, i) => (
                <p key={i} className="mb-1.5 text-[11px] leading-relaxed text-foreground/85">
                  {para}
                </p>
              ))}
            </div>
            <div className="rounded-lg bg-blue-500/[0.03] p-2.5">
              <p className="mb-1 text-[11px] font-semibold text-blue-700 dark:text-blue-400">
                中国侧{phase.cnRange.includes("20") && Number(phase.cnRange.slice(0, 4)) >= 2026 ? "（推演）" : ""}
              </p>
              {phase.cnNarrative.map((para, i) => (
                <p key={i} className="mb-1.5 text-[11px] leading-relaxed text-foreground/85">
                  {para}
                </p>
              ))}
            </div>
          </div>

          {phase.years.length > 0 && (
            <div className="mt-2">
              {phase.years.map((year) => (
                <YearRow key={year.jpYear} {...year} />
              ))}
            </div>
          )}

          <div className="mt-2 grid gap-2 md:grid-cols-2">
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/[0.04] p-2.5">
              <p className="mb-1 flex items-center gap-1 text-[11px] font-semibold text-emerald-700 dark:text-emerald-400">
                <Scale className="h-3 w-3" /> 相似之处
              </p>
              <ul className="space-y-0.5">
                {phase.similar.map((item, i) => (
                  <li key={i} className="flex gap-1.5 text-[11px] leading-snug text-muted-foreground">
                    <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-500" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-lg border border-zinc-400/20 bg-zinc-500/[0.04] p-2.5">
              <p className="mb-1 flex items-center gap-1 text-[11px] font-semibold text-zinc-600 dark:text-zinc-400">
                <XCircle className="h-3 w-3" /> 关键不同
              </p>
              <ul className="space-y-0.5">
                {phase.different.map((item, i) => (
                  <li key={i} className="flex gap-1.5 text-[11px] leading-snug text-muted-foreground">
                    <XCircle className="mt-0.5 h-3 w-3 shrink-0 text-zinc-400" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="mt-2 flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/[0.05] p-2.5">
            <Compass className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
            <div>
              <p className="text-[11px] font-semibold text-amber-700 dark:text-amber-400">
                资产配置镜鉴
              </p>
              <ul className="mt-0.5 space-y-0.5">
                {phase.allocationLessons.map((item, i) => (
                  <li key={i} className="text-[11px] leading-snug text-foreground/85">
                    {i + 1}. {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      ))}

      {/* 镜鉴清单 */}
      <section className="rounded-lg border border-border/60 bg-card p-3.5">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
          十条镜鉴：给今天的政策观察与资产配置
        </h3>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {MIRROR_LESSONS.map((lesson, i) => (
            <div
              key={i}
              data-testid={`mirror-lesson-${i}`}
              className="rounded-lg border border-border/40 bg-background/50 p-2.5"
            >
              <p className="text-[11px] font-semibold text-foreground">
                {i + 1}. {lesson.title}
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                {lesson.detail}
              </p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
