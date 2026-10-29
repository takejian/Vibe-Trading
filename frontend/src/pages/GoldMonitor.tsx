import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api, type GoldCurrentStatus, type GoldPolicyCycle } from "@/lib/api";
import { StatusCards } from "@/components/gold/StatusCards";
import { CycleList } from "@/components/gold/CycleList";
import { ReviewDialog } from "@/components/gold/ReviewDialog";

type Tab = "current" | "history";

export function GoldMonitor() {
  const [tab, setTab] = useState<Tab>("current");
  const [status, setStatus] = useState<GoldCurrentStatus | null>(null);
  const [cycles, setCycles] = useState<GoldPolicyCycle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshNeeded, setRefreshNeeded] = useState<string | null>(null);

  // Review dialog state
  const [reviewDialog, setReviewDialog] = useState<{
    kind: "cycle" | "diff";
    cycleId?: number;
    cycleName?: string;
    diff?: any;
    newValues?: any;
    targetMonth?: string;
  } | null>(null);

  const loadStatus = async () => {
    setError(null);
    try {
      const [s, c, rn] = await Promise.all([
        api.goldCurrent(),
        api.goldCycles(),
        api.goldRefreshNeeded(),
      ]);
      setStatus(s);
      setCycles(c.items);
      if (rn.needed) {
        setRefreshNeeded(rn.target ?? "上月");
      }
    } catch {
      setError("加载黄金数据失败，请确认后端服务正常并已导入历史数据");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handleRefresh = async () => {
    try {
      const result = await api.goldRefresh();
      if (result.status === "pending_diff" && result.diff) {
        setReviewDialog({
          kind: "diff",
          diff: result.diff,
          newValues: result.new_values,
          targetMonth: result.target_month,
        });
      } else if (result.auto_cycle) {
        setReviewDialog({
          kind: "cycle",
          cycleId: result.auto_cycle.cycle_id,
          cycleName: result.auto_cycle.cycle_name,
        });
      }
      await loadStatus();
    } catch (e) {
      setError("刷新失败：" + (e as Error).message);
    }
  };

  const handleDiffConfirm = async (accept: boolean) => {
    if (!reviewDialog?.targetMonth) return;
    if (accept) {
      await api.goldConfirm(reviewDialog.targetMonth);
    }
    setReviewDialog(null);
    await loadStatus();
  };

  const handleCycleApprove = async (approve: boolean) => {
    if (!approve || !reviewDialog?.cycleId) {
      setReviewDialog(null);
      return;
    }
    await api.goldApproveCycle(reviewDialog.cycleId);
    setReviewDialog(null);
    await loadStatus();
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-6">
        <div className="flex h-40 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载中...
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <h1 className="mb-4 text-xl font-semibold">黄金政策周期监测</h1>

      {error && (
        <div role="alert" className="mb-4 rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-500">
          {error}
        </div>
      )}

      {/* Tab switcher */}
      <div className="mb-4 flex gap-1 border-b border-border">
        <button
          type="button"
          className={`-mb-px border-b-2 px-3 py-2 text-sm ${
            tab === "current"
              ? "border-primary font-medium text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => setTab("current")}
        >
          当前状态
        </button>
        <button
          type="button"
          className={`-mb-px border-b-2 px-3 py-2 text-sm ${
            tab === "history"
              ? "border-primary font-medium text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => setTab("history")}
        >
          历史周期
        </button>
      </div>

      {tab === "current" && status && (
        <StatusCards
          status={status}
          onRefresh={handleRefresh}
          refreshNeeded={refreshNeeded}
        />
      )}

      {tab === "history" && (
        <CycleList cycles={cycles} onCycleApproved={() => loadStatus()} />
      )}

      {reviewDialog && reviewDialog.kind === "diff" && (
        <ReviewDialog
          kind="diff"
          title={`数据差异确认 — ${reviewDialog.targetMonth}`}
          diff={reviewDialog.diff}
          newValues={reviewDialog.newValues}
          onConfirm={() => handleDiffConfirm(true)}
          onCancel={() => handleDiffConfirm(false)}
        />
      )}
      {reviewDialog && reviewDialog.kind === "cycle" && (
        <ReviewDialog
          kind="cycle"
          title="政策周期审核"
          cycleName={reviewDialog.cycleName}
          onConfirm={() => handleCycleApprove(true)}
          onCancel={() => handleCycleApprove(false)}
        />
      )}
    </div>
  );
}
