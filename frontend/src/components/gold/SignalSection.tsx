import { useState } from "react";
import { RefreshCw, History, Edit3, X, Loader2, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { api, type GoldSignal, type GoldSignalsResponse, type GoldPrompt } from "@/lib/api";

interface Props {
  signals: GoldSignalsResponse | null;
  onChanged: () => void;
}

const INDICATOR_LABELS: Record<string, string> = {
  ffr_drivers: "增长与就业（FFR 路径）",
  bei_drivers: "通胀预期（BEI）",
  usd_fx: "美元与汇率",
  tail_risk: "尾部风险溢价",
  physical_flow: "实物与资金流",
};

const INDICATOR_ORDER = ["ffr_drivers", "bei_drivers", "usd_fx", "tail_risk", "physical_flow"];

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
  if (j === "bullish") return <TrendingUp className="h-3.5 w-3.5" />;
  if (j === "bearish") return <TrendingDown className="h-3.5 w-3.5" />;
  return <Minus className="h-3.5 w-3.5" />;
}

function fmtConfidence(c: number | null): string {
  if (c === null || c === undefined) return "—";
  return `${Math.round(c * 100)}%`;
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace("T", " ").slice(0, 16);
}

export function SignalSection({ signals, onChanged }: Props) {
  const [refreshingKey, setRefreshingKey] = useState<string | null>(null);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [historyKey, setHistoryKey] = useState<string | null>(null);
  const [promptKey, setPromptKey] = useState<string | null>(null);

  const items = signals?.items ?? [];
  const byKey = new Map(items.map(i => [i.indicator_key, i.signal]));

  const handleRefresh = async (key: string) => {
    setRefreshingKey(key);
    try {
      await api.goldSignalRefresh(key);
      await onChanged();
    } catch (e) {
      alert("刷新失败：" + (e as Error).message);
    } finally {
      setRefreshingKey(null);
    }
  };

  const handleRefreshAll = async () => {
    setRefreshingAll(true);
    try {
      await api.goldSignalsRefreshAll();
      await onChanged();
    } catch (e) {
      alert("全部刷新失败：" + (e as Error).message);
    } finally {
      setRefreshingAll(false);
    }
  };

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-semibold">五维指标分析（LLM）</h2>
        <button
          type="button"
          onClick={handleRefreshAll}
          disabled={refreshingAll}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60 disabled:opacity-50"
        >
          {refreshingAll ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          全部刷新
        </button>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {INDICATOR_ORDER.map(key => {
          const signal = byKey.get(key) ?? null;
          const label = INDICATOR_LABELS[key] ?? key;
          const isRefreshing = refreshingKey === key;
          return (
            <div key={key} className="flex flex-col rounded-lg border border-border bg-card p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-medium">{label}</span>
                {signal && (
                  <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${judgmentClass(signal.judgment)}`}>
                    {judgmentIcon(signal.judgment)}
                    {judgmentLabel(signal.judgment)}
                  </span>
                )}
              </div>

              {signal ? (
                <>
                  <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                    <span>可信度：<span className="font-medium text-foreground">{fmtConfidence(signal.confidence)}</span></span>
                    <span>·</span>
                    <span>{fmtDate(signal.created_at)}</span>
                    <span>·</span>
                    <span>{signal.source}</span>
                  </div>
                  <p className="mb-3 flex-1 text-sm leading-relaxed text-foreground/90">{signal.summary ?? "（无摘要）"}</p>
                </>
              ) : (
                <div className="mb-3 flex flex-1 items-center justify-center text-xs text-muted-foreground">
                  暂无分析，点击刷新
                </div>
              )}

              <div className="flex flex-wrap gap-1.5 border-t border-border pt-2">
                <button
                  type="button"
                  onClick={() => handleRefresh(key)}
                  disabled={isRefreshing}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted/60 disabled:opacity-50"
                >
                  {isRefreshing ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                  刷新
                </button>
                <button
                  type="button"
                  onClick={() => setHistoryKey(key)}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted/60"
                >
                  <History className="h-3 w-3" />
                  历史
                </button>
                <button
                  type="button"
                  onClick={() => setPromptKey(key)}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted/60"
                >
                  <Edit3 className="h-3 w-3" />
                  编辑提示词
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {historyKey && (
        <HistoryDialog
          indicatorKey={historyKey}
          label={INDICATOR_LABELS[historyKey] ?? historyKey}
          onClose={() => setHistoryKey(null)}
          onChanged={onChanged}
        />
      )}

      {promptKey && (
        <PromptDialog
          indicatorKey={promptKey}
          label={INDICATOR_LABELS[promptKey] ?? promptKey}
          onClose={() => setPromptKey(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// History dialog
// ---------------------------------------------------------------------------

function HistoryDialog({
  indicatorKey,
  label,
  onClose,
  onChanged,
}: {
  indicatorKey: string;
  label: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [items, setItems] = useState<GoldSignal[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  if (items === null && loading) {
    setLoading(false);
    api.goldSignalHistory(indicatorKey).then(r => setItems(r.items)).catch(() => setItems([]));
  }

  const startEdit = (s: GoldSignal) => {
    setEditingId(s.signal_id);
    setEditValue(s.confidence !== null ? String(s.confidence) : "");
  };

  const saveEdit = async () => {
    if (!editingId) return;
    const v = parseFloat(editValue);
    if (Number.isNaN(v) || v < 0 || v > 1) {
      alert("可信度需为 0 ~ 1 之间的数字");
      return;
    }
    try {
      await api.goldSignalUpdateConfidence(editingId, v);
      setItems(prev => prev?.map(s => s.signal_id === editingId ? { ...s, confidence: v } : s) ?? prev);
      await onChanged();
      setEditingId(null);
    } catch (e) {
      alert("保存失败：" + (e as Error).message);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-lg border border-border bg-card shadow-lg" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border p-4">
          <h2 className="font-semibold">历史记录 — {label}</h2>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {items === null ? (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />加载中...
            </div>
          ) : items.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">暂无历史记录</div>
          ) : (
            <div className="space-y-2">
              {items.map(s => (
                <div key={s.signal_id} className="rounded-md border border-border p-3 text-sm">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${judgmentClass(s.judgment)}`}>
                      {judgmentIcon(s.judgment)}
                      {judgmentLabel(s.judgment)}
                    </span>
                    {editingId === s.signal_id ? (
                      <span className="inline-flex items-center gap-1">
                        <span className="text-xs text-muted-foreground">可信度：</span>
                        <input
                          type="number" step="0.05" min="0" max="1"
                          value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          className="w-20 rounded border border-border bg-background px-1.5 py-0.5 text-xs"
                        />
                        <button onClick={saveEdit} className="rounded bg-primary px-2 py-0.5 text-xs text-primary-foreground hover:bg-primary/90">保存</button>
                        <button onClick={() => setEditingId(null)} className="rounded border border-border px-2 py-0.5 text-xs hover:bg-muted/60">取消</button>
                      </span>
                    ) : (
                      <button onClick={() => startEdit(s)} className="text-xs text-muted-foreground hover:text-foreground hover:underline">
                        可信度：{fmtConfidence(s.confidence)}
                      </button>
                    )}
                    <span className="ml-auto text-xs text-muted-foreground">{fmtDate(s.created_at)} · {s.source}</span>
                  </div>
                  <p className="text-xs leading-relaxed text-foreground/80">{s.summary ?? "（无摘要）"}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Prompt edit dialog
// ---------------------------------------------------------------------------

function PromptDialog({
  indicatorKey,
  label,
  onClose,
}: {
  indicatorKey: string;
  label: string;
  onClose: () => void;
}) {
  const [prompt, setPrompt] = useState<GoldPrompt | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  if (prompt === null && loading) {
    setLoading(false);
    api.goldPromptGet(indicatorKey).then(p => setPrompt(p)).catch(() => setPrompt({ indicator_key: indicatorKey, system_prompt: "", user_prompt: "", updated_at: "" }));
  }

  const save = async () => {
    if (!prompt) return;
    setSaving(true);
    try {
      await api.goldPromptUpdate(indicatorKey, prompt.system_prompt, prompt.user_prompt);
      onClose();
    } catch (e) {
      alert("保存失败：" + (e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-lg border border-border bg-card shadow-lg" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border p-4">
          <h2 className="font-semibold">编辑提示词 — {label}</h2>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {prompt === null ? (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />加载中...
            </div>
          ) : (
            <>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">System Prompt（角色设定）</label>
                <textarea
                  value={prompt.system_prompt}
                  onChange={e => setPrompt({ ...prompt, system_prompt: e.target.value })}
                  rows={8}
                  className="w-full resize-y rounded-md border border-border bg-background p-2 text-sm font-mono"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-muted-foreground">User Prompt（任务指令）</label>
                <textarea
                  value={prompt.user_prompt}
                  onChange={e => setPrompt({ ...prompt, user_prompt: e.target.value })}
                  rows={12}
                  className="w-full resize-y rounded-md border border-border bg-background p-2 text-sm font-mono"
                />
              </div>
              {prompt.updated_at && (
                <div className="text-xs text-muted-foreground">上次更新：{fmtDate(prompt.updated_at)}</div>
              )}
            </>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-border p-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60"
          >
            取消
          </button>
          <button
            type="button"
            onClick={save}
            disabled={saving || !prompt}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {saving ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin inline" /> : null}
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
