import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api, type GoldCurrentStatus, type GoldPolicyCycle, type GoldCycleTrend, type GoldSignalsResponse, type GoldFomcResponse, type GoldDailyBar } from "@/lib/api";
import { StatusCards } from "@/components/gold/StatusCards";
import { CycleList } from "@/components/gold/CycleList";
import { ReviewDialog } from "@/components/gold/ReviewDialog";
import { SignalSection } from "@/components/gold/SignalSection";
import { DailyBarTab } from "@/components/gold/DailyBarTab";

type Tab = "current" | "history" | "daily";

export function GoldMonitor() {
  const [tab, setTab] = useState<Tab>("current");
  const [status, setStatus] = useState<GoldCurrentStatus | null>(null);
  const [cycles, setCycles] = useState<GoldPolicyCycle[]>([]);
  const [trend, setTrend] = useState<GoldCycleTrend | null>(null);
  const [signals, setSignals] = useState<GoldSignalsResponse | null>(null);
  const [fomc, setFomc] = useState<GoldFomcResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshNeeded, setRefreshNeeded] = useState<string | null>(null);

  // Daily bar state
  const [dailyBars, setDailyBars] = useState<GoldDailyBar[]>([]);
  const [dailyLatest, setDailyLatest] = useState<GoldDailyBar | null>(null);
  const [dailySummary, setDailySummary] = useState<GoldDailyBar | null>(null);
  const [dailyLoading, setDailyLoading] = useState(false);
  const [dailyRefreshing, setDailyRefreshing] = useState(false);

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
      const [s, c, rn, t, sig, f] = await Promise.all([
        api.goldCurrent(),
        api.goldCycles(),
        api.goldRefreshNeeded(),
        api.goldCycleTrend().catch(() => null),
        api.goldSignals().catch(() => null),
        api.goldFomc().catch(() => null),
      ]);
      setStatus(s);
      setCycles(c.items);
      setTrend(t);
      setSignals(sig);
      setFomc(f);
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

  const loadDailyBars = async () => {
    setDailyLoading(true);
    try {
      const resp = await api.goldDailyBar(0);
      setDailyBars(resp.items);
      setDailyLatest(resp.latest);
      setDailySummary(resp.latest_summary);
    } catch {
      // 数据可能还没初始化 (404) — 忽略, 让组件显示空状态
      setDailyBars([]);
      setDailyLatest(null);
      setDailySummary(null);
    } finally {
      setDailyLoading(false);
    }
  };

  const handleDailyRefresh = async () => {
    setDailyRefreshing(true);
    try {
      const result = await api.goldDailyRefresh("manual", "AU0", false);
      if (result.status === "failed") {
        setError("日线刷新失败：" + (result.error_msg ?? "未知错误"));
      } else if (result.status === "ok_already_latest") {
        // 已是最新 — 不报错, 静默刷新一下页面数据 (可能有盘中更新)
      } else {
        // ok — 顺便显示一下 (可以后面加个 toast)
      }
      await loadDailyBars();
    } catch (e: any) {
      // HTTP 层的异常 (429 限流 / 502 akshare 挂了)
      const msg = e?.response?.data?.detail ?? e?.message ?? String(e);
      setError("日线刷新失败：" + msg);
    } finally {
      setDailyRefreshing(false);
    }
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
        <button
          type="button"
          className={`-mb-px border-b-2 px-3 py-2 text-sm ${
            tab === "daily"
              ? "border-primary font-medium text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
          onClick={() => {
            setTab("daily");
            if (dailyBars.length === 0) loadDailyBars();
          }}
        >
          日线行情
        </button>
      </div>

      {tab === "current" && status && (
        <>
          <StatusCards
            status={status}
            trend={trend}
            fomc={fomc}
            onRefresh={handleRefresh}
            refreshNeeded={refreshNeeded}
            onRefreshFomc={() => api.goldFomcRefresh().then(() => loadStatus())}
          />
          <SignalSection signals={signals} onChanged={loadStatus} />
        </>
      )}

      {tab === "history" && (
        <CycleList cycles={cycles} onCycleApproved={() => loadStatus()} />
      )}

      {tab === "daily" && (
        <DailyBarTab
          bars={dailyBars}
          latest={dailyLatest}
          latestSummary={dailySummary}
          loading={dailyLoading}
          refreshing={dailyRefreshing}
          onRefresh={handleDailyRefresh}
        />
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
