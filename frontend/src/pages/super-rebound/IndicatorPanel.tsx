import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { TrendingDown, AlertTriangle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { superReboundApi, type IndicatorScoreStub, type IndicatorDimensionsStub } from "@/lib/superRebound";

const INDEX_OPTIONS = [
  { code: "沪深300", label: "沪深300" },
  { code: "上证A500", label: "上证A500" },
  { code: "上证50", label: "上证50" },
  { code: "中证500", label: "中证500" },
  { code: "中证1000", label: "中证1000" },
  { code: "创业板", label: "创业板" },
  { code: "科创50", label: "科创50" },
];

export function IndicatorPanel() {
  const { t } = useTranslation();
  const [indexCode, setIndexCode] = useState("沪深300");
  const [score, setScore] = useState<IndicatorScoreStub | null>(null);
  const [dims, setDims] = useState<IndicatorDimensionsStub | null>(null);
  const [loading, setLoading] = useState(false);

  const loadData = useCallback(async (code: string) => {
    setLoading(true);
    try {
      const [s, d] = await Promise.all([
        superReboundApi.indicatorScore(code).catch(() => null),
        superReboundApi.indicatorDimensions(code).catch(() => null),
      ]);
      setScore(s);
      setDims(d);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(indexCode);
  }, [indexCode, loadData]);

  // Signal color
  const getSignalColor = (score: number | null) => {
    if (score === null) return { bg: "bg-muted", text: "text-muted-foreground", label: "—" };
    if (score <= 30) return { bg: "bg-emerald-500/20", text: "text-emerald-600", label: t("superRebound.safe") };
    if (score <= 70) return { bg: "bg-amber-500/20", text: "text-amber-600", label: t("superRebound.watch") };
    return { bg: "bg-red-500/20", text: "text-red-600", label: t("superRebound.reboundSignal") };
  };

  const signalStyle = getSignalColor(score?.total_score ?? null);

  return (
    <div className="space-y-6">
      {/* Index selector */}
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-muted-foreground">{t("superRebound.indexLabel")}:</label>
        <select
          value={indexCode}
          onChange={(e) => setIndexCode(e.target.value)}
          className="rounded-md border border-border/60 bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
        >
          {INDEX_OPTIONS.map((opt) => (
            <option key={opt.code} value={opt.code}>{opt.label}</option>
          ))}
        </select>
        {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
      </div>

      {/* TODO banner */}
      <div className="flex items-start gap-2 rounded-md border border-amber-400/40 bg-amber-400/10 px-4 py-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
        <div>
          <p className="text-sm font-medium text-amber-700">{t("superRebound.indicatorTodo")}</p>
          <p className="mt-0.5 text-xs text-amber-600/80">{t("superRebound.indicatorTodoHint")}</p>
        </div>
      </div>

      {/* Composite score card */}
      <div className="rounded-xl border border-border/60 bg-card p-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <TrendingDown className="h-4 w-4" />
          {t("superRebound.compositeScore")}
        </div>
        <div className="mt-3 flex items-end gap-4">
          <div className="text-4xl font-bold tabular-nums text-foreground">
            {score?.total_score !== null && score?.total_score !== undefined ? (
              score.total_score
            ) : (
              <span className="text-muted-foreground text-2xl">—</span>
            )}
            <span className="text-lg text-muted-foreground"> / 100</span>
          </div>
          <div className={cn("rounded-md px-3 py-1 text-sm font-medium", signalStyle.bg, signalStyle.text)}>
            🔴 {signalStyle.label}
          </div>
        </div>
      </div>

      {/* Dimensions table */}
      <div className="overflow-hidden rounded-xl border border-border/60">
        <table className="min-w-full text-sm">
          <thead className="bg-muted/50 text-muted-foreground">
            <tr>
              <th className="px-4 py-2 text-left font-medium">维度</th>
              <th className="px-4 py-2 text-center font-medium">权重</th>
              <th className="px-4 py-2 text-center font-medium">得分</th>
              <th className="px-4 py-2 text-left font-medium">超跌判断标准</th>
              <th className="px-4 py-2 text-left font-medium">指标值</th>
            </tr>
          </thead>
          <tbody>
            {(dims?.dimensions ?? []).map((dim) => (
              <tr key={dim.name} className="border-t border-border/40">
                <td className="px-4 py-3 font-medium">{dim.name}</td>
                <td className="px-4 py-3 text-center text-muted-foreground">{dim.weight}%</td>
                <td className="px-4 py-3 text-center">
                  <span className="text-muted-foreground">—</span>
                </td>
                <td className="px-4 py-3 text-xs text-muted-foreground">
                  {dim.indicators.map((ind, i) => (
                    <div key={i} className="mb-1 last:mb-0">
                      <span className="font-medium text-foreground">{ind.name}</span>: {ind.criterion}
                      {ind.auto_from_finance && (
                        <span className="ml-1 rounded bg-blue-500/10 px-1 text-[10px] text-blue-600">自动</span>
                      )}
                    </div>
                  ))}
                </td>
                <td className="px-4 py-3 text-xs text-muted-foreground">
                  {dim.indicators.map((ind, i) => (
                    <div key={i} className="mb-1 last:mb-0">
                      {ind.value !== null && ind.value !== undefined ? ind.value : "—"}
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* TODO list */}
      {(score?.todo ?? []).length > 0 && (
        <div className="rounded-lg border border-dashed border-border/60 bg-muted/20 p-4">
          <p className="text-sm font-medium text-muted-foreground mb-2">待实现项</p>
          <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
            {(score?.todo ?? []).map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
