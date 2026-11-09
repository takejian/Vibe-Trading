import { useEffect, useState } from "react";
import { FinancePanel } from "./super-rebound/FinancePanel";
import { IndicatorPanel } from "./super-rebound/IndicatorPanel";
import { DailyStatusPanel } from "./super-rebound/DailyStatusPanel";

type TabKey = "finance" | "indicator" | "daily-status";

const TABS: { key: TabKey; label: string; desc: string }[] = [
  { key: "finance", label: "资金面", desc: "两融维持担保比例 + 国家队ETF监测" },
  { key: "indicator", label: "超跌指标", desc: "五维度加权超跌评分" },
  { key: "daily-status", label: "每日超跌状态", desc: "近30交易日自动跟踪" },
];

export function SuperRebound() {
  const [tab, setTab] = useState<TabKey>("finance");

  useEffect(() => {
    // 静默确保 schema 已初始化（幂等）
    fetch("/api/super-rebound/schema/ensure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }).catch(() => {});
  }, []);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-white">超跌反弹</h1>
        <p className="mt-0.5 text-sm text-gray-400">
          交易监控已隐藏，保留数据与业务逻辑。此处专注于超跌反弹信号跟踪。
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-2">
        {TABS.map((t) => {
          const active = t.key === tab;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`rounded-lg border px-4 py-2 text-sm transition-colors ${
                active
                  ? "border-blue-500 bg-blue-500/10 text-white"
                  : "border-white/10 bg-white/5 text-gray-300 hover:bg-white/10"
              }`}
            >
              <div className="font-medium">{t.label}</div>
              <div className="text-xs text-gray-400">{t.desc}</div>
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div>
        {tab === "finance" && <FinancePanel />}
        {tab === "indicator" && <IndicatorPanel />}
        {tab === "daily-status" && <DailyStatusPanel />}
      </div>
    </div>
  );
}
