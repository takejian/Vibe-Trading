import { useEffect, useState } from "react";
import { RefreshCw, Loader2 } from "lucide-react";
import { api, type CelebrityAggGroup, type CelebrityClearedItem } from "@/lib/api";

interface Props {
  onSelectInvestor?: (investorId: number) => void;
}

function fmtPrice(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function fmtRate(v: number | null): { text: string; cls: string } {
  if (v === null || v === undefined) return { text: "—", cls: "text-muted-foreground" };
  const pct = (v * 100).toFixed(2);
  const sign = v >= 0 ? "+" : "";
  return {
    text: `${sign}${pct}%`,
    cls: v >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400",
  };
}

function ActionTag({ value }: { value: string | null }) {
  if (!value || value === "不变") return null;
  const map: Record<string, string> = {
    增持: "bg-green-500/10 text-green-600 dark:text-green-400 border-green-500/30",
    减持: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/30",
    新建: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/30",
    清仓: "bg-gray-500/10 text-gray-500 border-gray-500/30",
  };
  const cls = map[value] ?? "bg-muted text-muted-foreground border-border";
  return (
    <span className={`inline-block rounded border px-1.5 py-0 text-[10px] font-medium ${cls}`}>
      {value}
    </span>
  );
}

export function PublicHoldingTab({ onSelectInvestor }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [groups, setGroups] = useState<CelebrityAggGroup[]>([]);
  const [cleared, setCleared] = useState<CelebrityClearedItem[]>([]);

  const [updating, setUpdating] = useState(false);
  const [updateMsg, setUpdateMsg] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api.celebrityAggregatedPositions()
      .then((res) => {
        setGroups(res.items ?? []);
        setCleared(res.recently_cleared ?? []);
      })
      .catch(() => setError("加载公募持仓失败"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleUpdatePrices = async () => {
    setUpdating(true);
    setUpdateMsg(null);
    try {
      const res = await api.celebrityUpdatePrices();
      setUpdateMsg(res.message ?? "价格更新完成");
      load();
    } catch {
      setUpdateMsg("价格更新失败");
    } finally {
      setUpdating(false);
      setTimeout(() => setUpdateMsg(null), 3000);
    }
  };

  const totalTargets = groups.length;
  const totalHolders = groups.reduce((s, g) => s + g.count, 0);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return <p className="py-8 text-center text-sm text-destructive">{error}</p>;
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      {/* 头部操作条 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">公募持仓 · 按标的聚合</h2>
          <p className="text-xs text-muted-foreground">
            共 {totalTargets} 个标的，{totalHolders} 笔持仓
          </p>
        </div>
        <div className="flex items-center gap-2">
          {updateMsg && (
            <span className="rounded-md border border-border bg-card px-2 py-1 text-xs">
              {updateMsg}
            </span>
          )}
          <button
            onClick={handleUpdatePrices}
            disabled={updating}
            className="flex items-center gap-1.5 rounded-md border border-primary/50 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 disabled:opacity-50"
            title="批量查询所有持仓标的的最新价格"
          >
            {updating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            更新全部价格
          </button>
        </div>
      </div>

      {/* 主表 */}
      {groups.length === 0 ? (
        <p className="rounded-md border border-dashed border-border py-12 text-center text-sm text-muted-foreground">
          暂无公募持仓数据
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">标的名称</th>
                <th className="w-16 px-3 py-2 font-medium text-center">次数</th>
                <th className="px-3 py-2 font-medium text-right">最新价</th>
                <th className="px-3 py-2 font-medium">持有机构（动作）</th>
                <th className="px-3 py-2 font-medium text-right">建仓价</th>
                <th className="px-3 py-2 font-medium text-right">收益率</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <GroupRows
                  key={g.target}
                  group={g}
                  onSelectInvestor={onSelectInvestor}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 最近清仓 */}
      <div>
        <h3 className="mb-2 text-sm font-semibold">最近清仓标的</h3>
        {cleared.length === 0 ? (
          <p className="rounded-md border border-dashed border-border py-6 text-center text-xs text-muted-foreground">
            最近无清仓记录
          </p>
        ) : (
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">标的名称</th>
                  <th className="px-3 py-2 font-medium">清仓机构</th>
                  <th className="px-3 py-2 font-medium">动作</th>
                  <th className="px-3 py-2 font-medium text-right">建仓价</th>
                  <th className="px-3 py-2 font-medium text-right">最新价</th>
                  <th className="px-3 py-2 font-medium text-right">收益率</th>
                  <th className="px-3 py-2 font-medium">清仓时间</th>
                </tr>
              </thead>
              <tbody>
                {cleared.map((c, i) => {
                  const rate = fmtRate(c.return_rate);
                  return (
                    <tr key={i} className="border-t border-border/40 hover:bg-muted/30">
                      <td className="px-3 py-2 font-medium">{c.target}</td>
                      <td className="px-3 py-2">
                        <button
                          onClick={() => onSelectInvestor?.(c.investor_id)}
                          className="text-primary hover:underline"
                        >
                          {c.investor_name}
                        </button>
                      </td>
                      <td className="px-3 py-2"><ActionTag value="清仓" /></td>
                      <td className="px-3 py-2 text-right tabular-nums">{fmtPrice(c.first_added_price)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{fmtPrice(c.latest_price)}</td>
                      <td className={`px-3 py-2 text-right tabular-nums ${rate.cls}`}>{rate.text}</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{c.snapshot_date}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/** Render one group (multi-row with rowspanned columns for 合并单元格). */
function GroupRows({
  group,
  onSelectInvestor,
}: {
  group: CelebrityAggGroup;
  onSelectInvestor?: (id: number) => void;
}) {
  const rowspan = group.rows.length;
  const displayLatest = group.latest_price !== null ? fmtPrice(group.latest_price) : "—";

  return (
    <>
      {group.rows.map((row, idx) => {
        const rowRate = fmtRate(row.return_rate);
        return (
          <tr key={idx} className="border-t border-border/40 hover:bg-muted/30 align-top">
            {/* 合并单元格：标的名称 + 次数 + 最新价 */}
            {idx === 0 && (
              <>
                <td rowSpan={rowspan} className="px-3 py-2 font-medium border-r border-border/30">
                  {group.target}
                </td>
                <td rowSpan={rowspan} className="px-3 py-2 text-center text-xs font-semibold text-primary border-r border-border/30">
                  {group.count}
                </td>
                <td rowSpan={rowspan} className="px-3 py-2 text-right tabular-nums font-medium border-r border-border/30">
                  {displayLatest}
                </td>
              </>
            )}
            {/* 逐行：持有机构（动作） */}
            <td className="px-3 py-2">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => onSelectInvestor?.(row.investor_id)}
                  className="text-primary hover:underline"
                >
                  {row.investor_name}
                </button>
                <ActionTag value={row.action} />
                {row.percentage && (
                  <span className="text-[10px] text-muted-foreground">{row.percentage}</span>
                )}
              </div>
            </td>
            {/* 逐行：建仓价 */}
            <td className="px-3 py-2 text-right tabular-nums">{fmtPrice(row.first_added_price)}</td>
            {/* 逐行：收益率（关键修复！每个投资人建仓价不同 → 收益率必不同，必须逐行） */}
            <td className={`px-3 py-2 text-right tabular-nums font-medium ${rowRate.cls}`}>{rowRate.text}</td>
          </tr>
        );
      })}
    </>
  );
}
