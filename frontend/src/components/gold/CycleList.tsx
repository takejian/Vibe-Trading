import { useState } from "react";
import { ChevronRight, ChevronDown, Loader2, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { api, type GoldPolicyCycle, type GoldMonthlyRow, type GoldSignalItem } from "@/lib/api";

interface Props {
  cycles: GoldPolicyCycle[];
  onCycleApproved?: () => void;
}

const INDICATOR_LABELS: Record<string, string> = {
  ffr_drivers: "增长与就业(FFR)",
  bei_drivers: "通胀预期(BEI)",
  usd_fx: "美元与汇率",
  tail_risk: "尾部风险溢价",
  physical_flow: "实物与资金流",
};

function fmtNum(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(decimals);
}

function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  return v >= 0 ? "text-red-500" : "text-green-600";
}

function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `$${v.toLocaleString()}`;
}

function cycleTypeLabel(t: string): string {
  return { hiking: "加息周期", cutting: "降息周期", plateau: "利率平台" }[t] ?? t;
}

function judgmentLabel(j: string): string {
  if (j === "bullish") return "利多";
  if (j === "bearish") return "利空";
  return "中性";
}

function judgmentClass(j: string): string {
  if (j === "bullish") return "text-green-600 bg-green-500/10 border-green-500/30";
  if (j === "bearish") return "text-red-500 bg-red-500/10 border-red-500/30";
  return "text-muted-foreground bg-muted border-border";
}

function judgmentIcon(j: string) {
  if (j === "bullish") return <TrendingUp className="h-3 w-3" />;
  if (j === "bearish") return <TrendingDown className="h-3 w-3" />;
  return <Minus className="h-3 w-3" />;
}

function fmtConfidence(c: number | null | undefined): string {
  if (c === null || c === undefined) return "—";
  return `${Math.round(c * 100)}%`;
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace("T", " ").slice(0, 16);
}

export function CycleList({ cycles }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const [loadingMonths, setLoadingMonths] = useState(false);
  const [months, setMonths] = useState<GoldMonthlyRow[]>([]);
  const [tipsAvailableFrom, setTipsAvailableFrom] = useState("2003-01");
  const [cycleSignals, setCycleSignals] = useState<GoldSignalItem[] | null>(null);
  const [postHocConf, setPostHocConf] = useState<number | null>(null);
  const [savingPhc, setSavingPhc] = useState(false);

  const handleToggle = async (cycle: GoldPolicyCycle) => {
    if (expanded === cycle.cycle_id) {
      setExpanded(null);
      return;
    }
    setExpanded(cycle.cycle_id);
    setLoadingMonths(true);
    setPostHocConf(cycle.post_hoc_confidence ?? null);
    try {
      const [resp, sigResp] = await Promise.all([
        api.goldCycleMonths(cycle.cycle_id),
        api.goldCycleSignals(cycle.cycle_id).catch(() => null),
      ]);
      setMonths(resp.months);
      setTipsAvailableFrom(resp.tips_available_from);
      setCycleSignals(sigResp?.items ?? null);
    } catch {
      setMonths([]);
      setCycleSignals(null);
    } finally {
      setLoadingMonths(false);
    }
  };

  const handleSavePostHoc = async (cycleId: number) => {
    setSavingPhc(true);
    try {
      const val = postHocConf === null ? null : Number(postHocConf);
      await api.goldCyclePostHocConfidence(cycleId, val);
    } catch (e) {
      alert("保存失败：" + (e as Error).message);
    } finally {
      setSavingPhc(false);
    }
  };

  if (cycles.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        暂无政策周期数据，请先通过后端 /api/gold/import-excel 导入历史数据
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {cycles.map((cycle) => {
        const isExpanded = expanded === cycle.cycle_id;
        const monthCount = cycle.end_month
          ? _monthDiff(cycle.start_month, cycle.end_month)
          : null;
        return (
          <div key={cycle.cycle_id} className="rounded-lg border border-border bg-card">
            <button
              type="button"
              className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/40"
              onClick={() => void handleToggle(cycle)}
            >
              {isExpanded ? (
                <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              )}
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-sm truncate">{cycle.cycle_name}</span>
                  {cycle.status === "pending_review" && (
                    <span className="rounded px-1.5 py-0.5 text-[10px] bg-amber-500/10 text-amber-600">待审核</span>
                  )}
                  {cycle.status === "active" && (
                    <span className="rounded px-1.5 py-0.5 text-[10px] bg-primary/10 text-primary">已生效</span>
                  )}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {cycle.start_month} ~ {cycle.end_month ?? "至今"}
                  {monthCount !== null && <> · {monthCount}月</>}
                  {cycle.gold_start !== null && (
                    <> · 金价 {fmtMoney(cycle.gold_start)} → {fmtMoney(cycle.gold_end)}</>
                  )}
                  {cycle.gold_change_pct !== null && (
                    <> · <span className={pctClass(cycle.gold_change_pct)}>{cycle.gold_change_pct >= 0 ? "+" : ""}{cycle.gold_change_pct.toFixed(2)}%</span></>
                  )}
                  {cycle.post_hoc_confidence !== null && (
                    <span> · 事后置信度 <span className="font-medium text-foreground">{fmtConfidence(cycle.post_hoc_confidence)}</span></span>
                  )}
                </div>
              </div>
              <span className="text-xs text-muted-foreground">{cycleTypeLabel(cycle.cycle_type)}</span>
            </button>

            {isExpanded && (
              <div className="border-t border-border">
                {loadingMonths ? (
                  <div className="flex h-20 items-center justify-center text-muted-foreground text-sm">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />加载中...
                  </div>
                ) : (
                  <>
                    {/* 5-dimension state + post-hoc confidence */}
                    <CycleSignalPanel
                      signals={cycleSignals}
                      postHocConf={postHocConf}
                      onPostHocChange={setPostHocConf}
                      onSavePostHoc={() => handleSavePostHoc(cycle.cycle_id)}
                      savingPhc={savingPhc}
                    />
                    <MonthlyTable rows={months} tipsAvailableFrom={tipsAvailableFrom} />
                  </>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function CycleSignalPanel({
  signals,
  postHocConf,
  onPostHocChange,
  onSavePostHoc,
  savingPhc,
}: {
  signals: GoldSignalItem[] | null;
  postHocConf: number | null;
  onPostHocChange: (v: number | null) => void;
  onSavePostHoc: () => void;
  savingPhc: boolean;
}) {
  return (
    <div className="space-y-3 border-b border-border p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">五维指标状态</h3>
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground">事后置信度</label>
          <input
            type="number"
            step="0.05"
            min="0"
            max="1"
            value={postHocConf ?? ""}
            onChange={(e) => {
              const v = e.target.value === "" ? null : Number(e.target.value);
              onPostHocChange(v);
            }}
            placeholder="0~1"
            className="w-20 rounded border border-border bg-background px-2 py-1 text-xs"
          />
          <button
            type="button"
            onClick={onSavePostHoc}
            disabled={savingPhc}
            className="rounded bg-primary px-2.5 py-1 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {savingPhc ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
      {signals === null ? (
        <div className="text-xs text-muted-foreground">暂无该周期的指标分析记录</div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {signals.map(item => {
            const s = item.signal;
            return (
              <div key={item.indicator_key} className="rounded-md border border-border p-2.5">
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs font-medium">{INDICATOR_LABELS[item.indicator_key] ?? item.indicator_key}</span>
                  {s && (
                    <span className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${judgmentClass(s.judgment)}`}>
                      {judgmentIcon(s.judgment)}
                      {judgmentLabel(s.judgment)}
                    </span>
                  )}
                </div>
                {s ? (
                  <>
                    <div className="mb-1 text-[11px] text-muted-foreground">
                      可信度 {fmtConfidence(s.confidence)} · {fmtDate(s.created_at)}
                    </div>
                    <p className="text-[11px] leading-relaxed text-foreground/80 line-clamp-2">{s.summary ?? "（无摘要）"}</p>
                  </>
                ) : (
                  <div className="text-[11px] text-muted-foreground">无记录</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function _monthDiff(a: string, b: string): number {
  const [ay, am] = a.split("-").map(Number);
  const [by, bm] = b.split("-").map(Number);
  return (by - ay) * 12 + (bm - am) + 1;
}

function MonthlyTable({ rows, tipsAvailableFrom }: { rows: GoldMonthlyRow[]; tipsAvailableFrom: string }) {
  if (rows.length === 0) {
    return <div className="p-6 text-center text-sm text-muted-foreground">该周期暂无月度数据</div>;
  }
  const hasOldTips = rows.some(r => r.month < tipsAvailableFrom);

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-muted/40 text-left text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">月份</th>
              <th className="px-3 py-2 font-medium">金价</th>
              <th className="px-3 py-2 font-medium">FFR%</th>
              <th className="px-3 py-2 font-medium">10Y名义%</th>
              <th className="px-3 py-2 font-medium">10Y实际%</th>
              <th className="px-3 py-2 font-medium">金价环比%</th>
              <th className="px-3 py-2 font-medium">政策利率变</th>
              <th className="px-3 py-2 font-medium">实利变动</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const beforeTips = r.month < tipsAvailableFrom;
              return (
                <tr key={r.month} className="border-t border-border/60">
                  <td className="px-3 py-2 font-mono">{r.month}</td>
                  <td className="px-3 py-2">{fmtMoney(r.gold_price)}</td>
                  <td className="px-3 py-2">{fmtNum(r.ffr)}</td>
                  <td className="px-3 py-2">{fmtNum(r.yield_nominal)}</td>
                  <td className="px-3 py-2">{beforeTips && r.tips_real === null ? <span className="text-muted-foreground">N/A</span> : fmtNum(r.tips_real)}</td>
                  <td className={`px-3 py-2 ${pctClass(r.gold_change_pct)}`}>{r.gold_change_pct !== null ? `${r.gold_change_pct.toFixed(2)}%` : "—"}</td>
                  <td className={`px-3 py-2 ${pctClass(r.ffr_change)}`}>{r.ffr_change !== null ? `${r.ffr_change > 0 ? "+" : ""}${r.ffr_change.toFixed(2)}` : "—"}</td>
                  <td className={`px-3 py-2 ${pctClass(r.real_change)}`}>{beforeTips && r.real_change === null ? <span className="text-muted-foreground">N/A</span> : (r.real_change !== null ? `${r.real_change > 0 ? "+" : ""}${r.real_change.toFixed(2)}` : "—")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {hasOldTips && (
        <div className="px-3 py-2 text-[11px] text-muted-foreground border-t border-border/60">
          注：10年期TIPS实际利率数据自 {tipsAvailableFrom} 起可用，之前月份标记为 N/A
        </div>
      )}
    </div>
  );
}
