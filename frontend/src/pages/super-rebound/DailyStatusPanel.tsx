import { useEffect, useMemo, useState } from "react";
import { FileText, Loader2, RefreshCw, Save, X } from "lucide-react";
import { superReboundApi, type DailyStatusListResponse, type IndicatorPrompt } from "../../lib/superRebound";

const INDEX_OPTIONS = ["沪深300", "科创50", "上证A500", "上证50", "中证500", "中证1000", "创业板"];

function scoreCellCls(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-gray-500";
  if (v <= 30) return "text-green-700 font-semibold";
  if (v <= 70) return "text-yellow-700 font-semibold";
  return "text-red-700 font-semibold";
}

function Modal({ open, onClose, title, children }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-xl rounded-xl border border-gray-200 bg-white shadow-2xl"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
          <h3 className="text-base font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose} className="rounded-md p-1 text-gray-500 hover:bg-gray-100">
            <X size={18} />
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto p-5 text-gray-900">{children}</div>
      </div>
    </div>
  );
}

export function DailyStatusPanel() {
  const [indexCode, setIndexCode] = useState("沪深300");
  const [data, setData] = useState<DailyStatusListResponse | null>(null);
  const [scheduleEnabled, setScheduleEnabled] = useState(true);
  const [loading, setLoading] = useState(false);
  const [chipLoading, setChipLoading] = useState(false);
  const [trackLoading, setTrackLoading] = useState(false);

  const [promptDialogOpen, setPromptDialogOpen] = useState(false);
  const [promptEditing, setPromptEditing] = useState<IndicatorPrompt | null>(null);
  const [promptDraft, setPromptDraft] = useState("");

  async function loadData() {
    setLoading(true);
    try {
      const [list, sched] = await Promise.all([
        superReboundApi.dailyStatusList({ indexCode, days: 30 }),
        superReboundApi.schedule(),
      ]);
      setData(list);
      setScheduleEnabled(!!sched.schedule.is_enabled);
    } catch (e: any) {
      console.error("load failed:", e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadData(); /* eslint-disable-next-line */ }, [indexCode]);

  async function toggleSchedule() {
    const next = !scheduleEnabled;
    await superReboundApi.toggleSchedule("daily_status_auto", next);
    setScheduleEnabled(next);
  }

  async function refreshVolumePriceChip() {
    setChipLoading(true);
    try { await superReboundApi.refreshVolumePriceChip(indexCode); await loadData(); } finally { setChipLoading(false); }
  }

  async function refreshReboundTracking() {
    setTrackLoading(true);
    try { await superReboundApi.refreshReboundTracking(indexCode); await loadData(); } finally { setTrackLoading(false); }
  }

  function openPromptDialog(promptType: string) {
    const p = data?.prompts?.find((x) => x.prompt_type === promptType);
    setPromptEditing(p ?? ({ id: 0, prompt_type: promptType, prompt_name: "", prompt_content: "" } as IndicatorPrompt));
    setPromptDraft(p?.prompt_content ?? "");
    setPromptDialogOpen(true);
  }

  async function savePrompt() {
    if (!promptEditing) return;
    await superReboundApi.upsertPrompt({
      prompt_type: promptEditing.prompt_type,
      prompt_name: promptEditing.prompt_name,
      prompt_content: promptDraft,
    });
    setPromptDialogOpen(false);
    await loadData();
  }

  const rows = useMemo(() => data?.daily_rows || [], [data]);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-700">指数:</span>
          <select
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-blue-500"
            value={indexCode}
            onChange={(e) => setIndexCode(e.target.value)}
          >
            {INDEX_OPTIONS.map((idx) => <option key={idx} value={idx}>{idx}</option>)}
          </select>
        </div>
        <span className="text-xs text-gray-500">定时自动更新: 沪深300 + 科创50</span>

        <div className="ml-auto flex items-center gap-3 rounded-md border border-gray-300 bg-white px-3 py-1.5">
          <span className="text-xs text-gray-700">定时任务</span>
          <button
            onClick={toggleSchedule}
            className={`relative h-5 w-10 rounded-full transition-colors ${scheduleEnabled ? "bg-green-500" : "bg-gray-400"}`}
            title="每交易日 23:00 北京时间自动生成"
          >
            <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${scheduleEnabled ? "left-5" : "left-0.5"}`} />
          </button>
          <span className={`text-xs font-semibold ${scheduleEnabled ? "text-green-700" : "text-gray-500"}`}>
            {scheduleEnabled ? "开启 (23:00)" : "已关闭"}
          </span>
        </div>
      </div>

      {/* Table (white bg, black text) */}
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="overflow-x-auto">
          {loading ? (
            <div className="flex h-48 items-center justify-center text-gray-600">
              <Loader2 className="mr-2 animate-spin" /> 加载中...
            </div>
          ) : rows.length === 0 ? (
            <div className="p-8 text-center text-gray-500">暂无超跌状态数据。请等待定时任务或手动触发。</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-100 text-xs uppercase tracking-wide text-gray-700">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold">指数</th>
                  <th className="px-3 py-2 text-left font-semibold">日期</th>
                  <th className="px-2 py-2 text-right font-semibold">赔率层</th>
                  <th className="px-2 py-2 text-right font-semibold">技术超卖</th>
                  <th className="px-2 py-2 text-right font-semibold">资金承接</th>
                  <th className="px-2 py-2 text-right font-semibold">情绪广度</th>
                  <th className="px-2 py-2 text-right font-semibold">外部流动性</th>
                  <th className="px-2 py-2 text-right font-bold">综合得分</th>
                  <th className="px-2 py-2 text-center font-semibold">量价与筹码</th>
                  <th className="px-2 py-2 text-center font-semibold">反弹存续跟踪</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 text-gray-900">
                {rows.map((row) => (
                  <tr key={`${row.trade_date}-${row.index_code}`}
                      className={row.is_latest ? "bg-blue-50 font-semibold" : "hover:bg-gray-50"}>
                    <td className="px-3 py-2 text-gray-900">{row.index_code}</td>
                    <td className="px-3 py-2 text-gray-800">
                      {row.trade_date} {row.is_latest && <span className="ml-1 text-xs text-blue-600">● 最新</span>}
                    </td>
                    <td className={`px-2 py-2 text-right font-mono tabular-nums ${scoreCellCls(row.odds_score)}`}>{row.odds_score !== null ? row.odds_score.toFixed(1) : "—"}</td>
                    <td className={`px-2 py-2 text-right font-mono tabular-nums ${scoreCellCls(row.technical_score)}`}>{row.technical_score !== null ? row.technical_score.toFixed(1) : "—"}</td>
                    <td className={`px-2 py-2 text-right font-mono tabular-nums ${scoreCellCls(row.capital_score)}`}>{row.capital_score !== null ? row.capital_score.toFixed(1) : "—"}</td>
                    <td className={`px-2 py-2 text-right font-mono tabular-nums ${scoreCellCls(row.sentiment_score)}`}>{row.sentiment_score !== null ? row.sentiment_score.toFixed(1) : "—"}</td>
                    <td className={`px-2 py-2 text-right font-mono tabular-nums ${scoreCellCls(row.external_score)}`}>{row.external_score !== null ? row.external_score.toFixed(1) : "—"}</td>
                    <td className={`px-2 py-2 text-right font-bold font-mono tabular-nums ${scoreCellCls(row.total_score)}`}>{row.total_score !== null ? row.total_score.toFixed(1) : "—"}</td>
                    <td className="px-2 py-2">
                      <div className="flex flex-col items-center gap-1">
                        <span className={
                          row.volume_price_chip?.includes("真") ? "text-green-700 font-semibold" :
                          row.volume_price_chip?.includes("假") ? "text-red-700 font-semibold" :
                          row.volume_price_chip ? "text-gray-900" : "text-gray-400"
                        }>{row.volume_price_chip || "—"}</span>
                        <div className="flex gap-1">
                          <button onClick={refreshVolumePriceChip} disabled={chipLoading}
                            className="rounded p-0.5 text-gray-500 hover:bg-blue-50 hover:text-blue-600" title="手动刷新">
                            {chipLoading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                          </button>
                          <button onClick={() => openPromptDialog("volume_price_chip")}
                            className="rounded p-0.5 text-gray-500 hover:bg-blue-50 hover:text-blue-600" title="提示词">
                            <FileText size={12} />
                          </button>
                        </div>
                      </div>
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex flex-col items-center gap-1">
                        <span className={
                          row.rebound_tracking?.includes("存续") ? "text-green-700 font-semibold" :
                          row.rebound_tracking?.includes("衰退") ? "text-red-700 font-semibold" :
                          row.rebound_tracking ? "text-gray-900" : "text-gray-400"
                        }>{row.rebound_tracking || "—"}</span>
                        <div className="flex gap-1">
                          <button onClick={refreshReboundTracking} disabled={trackLoading}
                            className="rounded p-0.5 text-gray-500 hover:bg-blue-50 hover:text-blue-600" title="手动刷新">
                            {trackLoading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                          </button>
                          <button onClick={() => openPromptDialog("rebound_tracking")}
                            className="rounded p-0.5 text-gray-500 hover:bg-blue-50 hover:text-blue-600" title="提示词">
                            <FileText size={12} />
                          </button>
                        </div>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Prompt dialog */}
      <Modal open={promptDialogOpen} onClose={() => setPromptDialogOpen(false)}
        title={promptEditing ? `编辑提示词: ${promptEditing.prompt_name}` : "编辑提示词"}>
        <div className="space-y-3">
          <div className="text-xs text-gray-600">类型: <span className="text-gray-900">{promptEditing?.prompt_type}</span></div>
          <textarea
            className="h-80 w-full rounded-md border border-gray-300 bg-white p-3 font-mono text-sm text-gray-900 outline-none focus:border-blue-500"
            value={promptDraft}
            onChange={(e) => setPromptDraft(e.target.value)}
          />
          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => setPromptDialogOpen(false)}
              className="rounded-md border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50">取消</button>
            <button onClick={savePrompt}
              className="flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-500">
              <Save size={14} /> 保存
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
