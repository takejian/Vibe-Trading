import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { useChartLifecycle } from "@/hooks/useChartLifecycle";
import { getChartTheme } from "@/lib/chart-theme";
import { abbreviateNum } from "@/lib/formatters";
import type { PaperNavPoint } from "@/lib/api";

interface PaperNavChartProps {
  points: PaperNavPoint[];
  initialCapital: number;
  height?: number;
}

/** Account total-asset NAV curve with the initial-capital benchmark line. */
export function PaperNavChart({ points, initialCapital, height = 340 }: PaperNavChartProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);

  useChartLifecycle(
    ref,
    () => {
      const theme = getChartTheme();
      const times = points.map((p) =>
        p.snapped_at.replace("T", " ").slice(0, 16),
      );
      const assets = points.map((p) => Number(p.total_asset));
      const seriesName = t("paper.nav.totalAsset");
      const baselineName = t("paper.nav.baseline");
      return {
        backgroundColor: "transparent",
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "cross" },
          backgroundColor: theme.tooltipBg,
          borderColor: theme.tooltipBorder,
          textStyle: { color: theme.tooltipText, fontSize: 11 },
          valueFormatter: (v: unknown) =>
            Number(v).toLocaleString("zh-CN", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            }),
        },
        legend: {
          data: [seriesName, baselineName],
          textStyle: { color: theme.textColor, fontSize: 11 },
          right: 8,
          top: 4,
        },
        grid: { left: 8, right: 12, top: 36, bottom: 24, containLabel: true },
        xAxis: {
          type: "category",
          data: times,
          axisLine: { lineStyle: { color: theme.axisColor } },
          axisLabel: { color: theme.textColor, fontSize: 10 },
        },
        yAxis: {
          type: "value",
          scale: true,
          splitLine: { lineStyle: { color: theme.gridColor } },
          axisLabel: {
            color: theme.textColor,
            fontSize: 10,
            formatter: (v: number) => abbreviateNum(v),
          },
        },
        dataZoom: [{ type: "inside" }],
        series: [
          {
            name: seriesName,
            type: "line",
            data: assets,
            symbol: "circle",
            symbolSize: 4,
            lineStyle: { color: theme.infoColor, width: 2 },
            itemStyle: { color: theme.infoColor },
            areaStyle: {
              color: {
                type: "linear",
                x: 0, y: 0, x2: 0, y2: 1,
                colorStops: [
                  { offset: 0, color: `${theme.infoColor}40` },
                  { offset: 1, color: `${theme.infoColor}00` },
                ],
              },
            },
            markLine: {
              silent: true,
              symbol: "none",
              data: [{ yAxis: initialCapital, name: baselineName }],
              lineStyle: { color: theme.textColor, type: "dashed", width: 1 },
              label: { formatter: baselineName, fontSize: 10, color: theme.textColor },
            },
          },
          {
            name: baselineName,
            type: "line",
            data: [],
            itemStyle: { color: theme.textColor },
          },
        ],
      };
    },
    [points, initialCapital, t],
  );

  if (points.length === 0) {
    return (
      <div className="p-8 text-center text-sm text-muted-foreground">
        {t("paper.nav.empty")}
      </div>
    );
  }
  return <div ref={ref} style={{ height }} />;
}
