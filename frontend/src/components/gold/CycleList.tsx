import { useState } from "react";
import { ChevronRight, ChevronDown, Loader2 } from "lucide-react";
import { api, type GoldPolicyCycle, type GoldMonthlyRow } from "@/lib/api";

interface Props {
  cycles: GoldPolicyCycle[];
  onCycleApproved?: () => void;
}

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

export function CycleList({ cycles }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const [loadingMonths, setLoadingMonths] = useState(false);
  const [months, setMonths] = useState<GoldMonthlyRow[]>([]);
  const [tipsAvailableFrom, setTipsAvailableFrom] = useState("2003-01");

  const handleToggle = async (cycle: GoldPolicyCycle) => {
    if (expanded === cycle.cycle_id) {
      setExpanded(null);
      return;
    }
    setExpanded(cycle.cycle_id);
    setLoadingMonths(true);
    try {
      const resp = await api.goldCycleMonths(cycle.cycle_id);
      setMonths(resp.months);
      setTipsAvailableFrom(resp.tips_available_from);
    } catch {
      setMonths([]);
    } finally {
      setLoadingMonths(false);
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
                  <MonthlyTable rows={months} tipsAvailableFrom={tipsAvailableFrom} />
                )}
              </div>
            )}
          </div>
        );
      })}
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
