import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, RefreshCw, Sparkles, Trash2, FileText, Save, X, Pencil } from "lucide-react";
import {
  superReboundApi,
  type IndicatorDef,
  type IndicatorEvalResult,
  type IndicatorPrompt,
  type CompareOperator,
} from "../../lib/superRebound";

const INDEX_OPTIONS = ["沪深300", "上证A500", "上证50", "中证500", "中证1000", "创业板", "科创50"];
const DIMENSION_ORDER = ["赔率层", "技术超卖", "资金承接", "情绪广度", "外部流动性/政策"];
const DIMENSION_WEIGHTS: Record<string, number> = {
  "赔率层": 30, "技术超卖": 20, "资金承接": 25,
  "情绪广度": 15, "外部流动性/政策": 10,
};
const OPERATOR_OPTIONS: CompareOperator[] = [">", ">=", "<", "<=", "==", "!=", "定性"];

function scoreSignalBg(score: number | null | undefined): string {
  if (score === null || score === undefined) return "bg-gray-100";
  if (score <= 30) return "bg-green-100";
  if (score <= 70) return "bg-yellow-100";
  return "bg-red-100";
}
function scoreSignalText(score: number | null | undefined): string {
  if (score === null || score === undefined) return "text-gray-500";
  if (score <= 30) return "text-green-700";
  if (score <= 70) return "text-yellow-700";
  return "text-red-700";
}

type IndicatorFormState = {
  id?: number;
  dimension: string;
  indicator_name: string;
  threshold_value: string;
  compare_operator: CompareOperator;
  judgment_criteria: string;
  weight: number;
};

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

// Shared indicator form used by both add and edit dialogs
function IndicatorForm({
  form, setForm, onSubmit, submitLabel,
}: {
  form: IndicatorFormState;
  setForm: (f: IndicatorFormState) => void;
  onSubmit: () => void;
  submitLabel: string;
}) {
  const isQualitative = form.compare_operator === "定性";
  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs text-gray-600">所属维度</label>
        <select className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500"
          value={form.dimension}
          onChange={(e) => setForm({ ...form, dimension: e.target.value })}>
          {DIMENSION_ORDER.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </div>
      <div>
        <label className="text-xs text-gray-600">指标名称</label>
        <input className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500"
          value={form.indicator_name}
          onChange={(e) => setForm({ ...form, indicator_name: e.target.value })}
          placeholder="如 RSI(14)、ERP" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-600">比较操作符</label>
          <select className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500 font-mono"
            value={form.compare_operator}
            onChange={(e) => setForm({ ...form, compare_operator: e.target.value as CompareOperator })}>
            {OPERATOR_OPTIONS.map((op) => <option key={op} value={op}>{op}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-600">判断阈值</label>
          <input type="number" step="any"
            className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500"
            value={form.threshold_value}
            disabled={isQualitative}
            placeholder={isQualitative ? "（定性指标无需阈值）" : "如 30, 5, 500"}
            onChange={(e) => setForm({ ...form, threshold_value: e.target.value })} />
        </div>
      </div>
      <div>
        <label className="text-xs text-gray-600">判断说明（备注）</label>
        <input className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500"
          value={form.judgment_criteria}
          onChange={(e) => setForm({ ...form, judgment_criteria: e.target.value })}
          placeholder="如 < 0 (明显负乖离)、底背离出现=1 等" />
      </div>
      <div>
        <label className="text-xs text-gray-600">维度内权重</label>
        <input type="number" step="0.1"
          className="mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-blue-500"
          value={form.weight}
          onChange={(e) => setForm({ ...form, weight: parseFloat(e.target.value) || 1 })} />
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <button onClick={() => onSubmit()}
          className="flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-500">
          <Save size={14} /> {submitLabel}
        </button>
      </div>
    </div>
  );
}

export function IndicatorPanel() {
  const [indexCode, setIndexCode] = useState("沪深300");
  const [evalResult, setEvalResult] = useState<IndicatorEvalResult | null>(null);
  const [defs, setDefs] = useState<IndicatorDef[]>([]);
  const [evalLoading, setEvalLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [promptDialogOpen, setPromptDialogOpen] = useState(false);
  const [promptEditing, setPromptEditing] = useState<IndicatorPrompt | null>(null);
  const [promptDraft, setPromptDraft] = useState("");

  const [formDialogOpen, setFormDialogOpen] = useState(false);
  const [formMode, setFormMode] = useState<"add" | "edit">("add");
  const [form, setForm] = useState<IndicatorFormState>({
    dimension: "赔率层", indicator_name: "", threshold_value: "",
    compare_operator: ">", judgment_criteria: "", weight: 1,
  });

  useEffect(() => {
    superReboundApi.indicatorDefs().then((r) => setDefs(r.indicator_defs)).catch(() => {});
    // 打开页面 + 切换指数 → 从 DB 加载上次结果（ms 级，不调 LLM）
    superReboundApi.latestIndicator(indexCode).then((r) => {
      if (r.has_data && r.result) setEvalResult(r.result);
    }).catch(() => {});
  }, [indexCode]);

  async function handleEval(silent = false) {
    if (!silent) setEvalLoading(true);
    setError(null);
    try {
      const result = await superReboundApi.evalIndicator(indexCode);
      setEvalResult(result);
    } catch (e: any) {
      setError(e?.message || "获取超跌指标失败");
      setEvalResult(null);
    } finally {
      setEvalLoading(false);
    }
  }

  const indicatorsByDimension = useMemo(() => {
    if (!evalResult) return {} as Record<string, IndicatorEvalResult["indicators"]>;
    const grouped: Record<string, IndicatorEvalResult["indicators"]> = {};
    for (const ind of evalResult.indicators) {
      (grouped[ind.dimension] ||= []).push(ind);
    }
    return grouped;
  }, [evalResult]);

  async function loadFullPrompt() {
    try {
      const r = await superReboundApi.promptFull();
      setPromptDraft(r.full_prompt);
    } catch {
      setPromptDraft("加载提示词失败，请确认后端已启动");
    }
  }

  function openPromptDialog(promptType: string) {
    setPromptEditing({ id: 0, prompt_type: promptType, prompt_name: "超跌指标取值提示词", prompt_content: "" } as IndicatorPrompt);
    loadFullPrompt();
    setPromptDialogOpen(true);
  }

  async function savePrompt() {
    if (!promptEditing) return;
    const r = await superReboundApi.savePromptFull({
      full_prompt: promptDraft,
      prompt_type: promptEditing.prompt_type,
      prompt_name: promptEditing.prompt_name,
    });
    // 保存后用服务端 regenerated 的版本（服务端会重新拼指标清单）
    setPromptDraft(r.full_prompt);
    setPromptDialogOpen(false);
  }

  function openAddForm(dimension: string) {
    setFormMode("add");
    setForm({ dimension, indicator_name: "", threshold_value: "", compare_operator: ">", judgment_criteria: "", weight: 1 });
    setFormDialogOpen(true);
  }

  function openEditForm(ind: { id: number; dimension: string; indicator_name: string; threshold_value: number | null; compare_operator: CompareOperator; judgment_criteria: string | null; weight: number }) {
    setFormMode("edit");
    setForm({
      id: ind.id,
      dimension: ind.dimension,
      indicator_name: ind.indicator_name,
      threshold_value: ind.threshold_value !== null ? String(ind.threshold_value) : "",
      compare_operator: ind.compare_operator,
      judgment_criteria: ind.judgment_criteria ?? "",
      weight: ind.weight,
    });
    setFormDialogOpen(true);
  }

  async function submitForm() {
    if (!form.dimension || !form.indicator_name) return;
    await superReboundApi.upsertIndicatorDef({
      id: form.id,
      dimension: form.dimension,
      indicator_name: form.indicator_name,
      threshold_value: form.compare_operator === "定性" ? null : parseFloat(form.threshold_value) || null,
      compare_operator: form.compare_operator,
      judgment_criteria: form.judgment_criteria || null,
      weight: form.weight,
      sort_order: formMode === "add" ? (defs.filter((d) => d.dimension === form.dimension).length + 1) * 10 : undefined,
      is_active: 1,
    } as any);
    const r = await superReboundApi.indicatorDefs();
    setDefs(r.indicator_defs);
    setFormDialogOpen(false);
  }

  async function handleDeleteDef(id: number) {
    if (!confirm("确认删除该指标？")) return;
    await superReboundApi.deleteIndicatorDef(id);
    const r = await superReboundApi.indicatorDefs();
    setDefs(r.indicator_defs);
  }

  const totalSignal = scoreSignalBg(evalResult?.total_score ?? null);
  const totalTextCls = scoreSignalText(evalResult?.total_score ?? null);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-700">宽基指数:</span>
          <select
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 outline-none focus:border-blue-500"
            value={indexCode}
            onChange={(e) => setIndexCode(e.target.value)}
          >
            {INDEX_OPTIONS.map((idx) => <option key={idx} value={idx}>{idx}</option>)}
          </select>
        </div>
        <button
          onClick={() => handleEval(false)}
          disabled={evalLoading}
          className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500 disabled:opacity-50"
        >
          {evalLoading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          手动触发判断
        </button>
        <button
          onClick={() => openPromptDialog("oversold_indicator")}
          className="flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
        >
          <FileText size={14} /> 编辑提示词
        </button>
        {evalResult?.trade_date && (
          <span className="text-xs text-gray-500 ml-auto">数据日期: {evalResult.trade_date}</span>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}

      {/* Score card */}
      <div className={`flex items-center gap-6 rounded-xl border border-gray-200 p-5 ${totalSignal}`}>
        <div>
          <div className="text-xs text-gray-600 mb-1">五维度加权综合得分</div>
          <div className="flex items-baseline gap-2">
            <span className={`text-4xl font-bold ${totalTextCls}`}>
              {evalResult?.total_score !== null && evalResult?.total_score !== undefined
                ? evalResult.total_score.toFixed(1) : "—"}
            </span>
            <span className="text-gray-500">/ 100</span>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2 rounded-full px-4 py-2 bg-white border border-gray-200">
          <Sparkles size={18} className={totalTextCls} />
          <span className={`text-sm font-semibold ${totalTextCls}`}>
            {evalResult?.total_score !== null && evalResult?.total_score !== undefined
              ? evalResult.total_score <= 30 ? "安全" : evalResult.total_score <= 70 ? "关注" : "超跌信号"
              : "待评估"}
          </span>
        </div>
      </div>

      {/* Dimension table (white bg, black text, monospace equal-width) */}
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 bg-gray-50 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-gray-700">
          维度详情 · 大模型取值 + 本地按阈值/操作符 0/1 判断
        </div>
        {DIMENSION_ORDER.map((dim) => {
          const score = evalResult?.dimension_scores?.[dim];
          const scoreCls = scoreSignalText(score);
          const inds = indicatorsByDimension[dim] || [];
          const curDefs = defs.filter((d) => d.dimension === dim && !inds.some((i) => i.id === d.id));
          const allRows = [...inds, ...curDefs.map((d) => ({
            id: d.id, indicator_name: d.indicator_name,
            indicator_value: null as string | null | undefined, judgment_result: null as number | null,
            threshold_value: d.threshold_value, compare_operator: d.compare_operator,
            judgment_criteria: d.judgment_criteria, weight: d.weight, dimension: dim,
          }))];

          return (
            <div key={dim} className="border-b border-gray-200 last:border-b-0 px-4 py-3">
              <div className="mb-2 flex items-center gap-3">
                <span className="font-semibold text-gray-900">{dim}</span>
                <span className="text-xs text-gray-600">权重 {DIMENSION_WEIGHTS[dim]}%</span>
                <span className={`ml-auto rounded px-2 py-0.5 text-xs font-semibold border border-gray-200 bg-white ${scoreCls}`}>
                  维度得分 {score !== null && score !== undefined ? score.toFixed(1) : "—"}
                </span>
                <button
                  onClick={() => openAddForm(dim)}
                  className="rounded p-1 text-green-600 hover:bg-green-50" title="新增指标"
                >
                  <Plus size={14} />
                </button>
              </div>
              {allRows.length === 0 ? (
                <div className="text-xs text-gray-500 py-2">暂无指标</div>
              ) : (
                <table className="w-full text-xs">
                  <colgroup>
                    <col className="w-[28%]" />
                    <col className="w-[12%]" />
                    <col className="w-[12%]" />
                    <col className="w-[14%]" />
                    <col className="w-[14%]" />
                    <col className="w-[10%]" />
                    <col className="w-[10%]" />
                  </colgroup>
                  <thead className="text-gray-600">
                    <tr>
                      <th className="py-1 pr-2 text-left font-medium">指标</th>
                      <th className="py-1 pr-2 text-left font-medium">操作符</th>
                      <th className="py-1 pr-2 text-right font-medium">阈值</th>
                      <th className="py-1 pr-2 text-right font-medium">大模型值</th>
                      <th className="py-1 pr-2 text-center font-medium">判断</th>
                      <th className="py-1 pr-2 text-center font-medium">操作</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {allRows.map((ind) => {
                      const isQualitative = ind.compare_operator === "定性";
                      return (
                        <tr key={ind.id} className="border-t border-gray-100">
                          <td className="py-1 pr-2 text-gray-900 font-medium">{ind.indicator_name}</td>
                          <td className="py-1 pr-2 text-gray-700 font-mono tabular-nums">{ind.compare_operator}</td>
                          <td className="py-1 pr-2 text-right text-gray-700 font-mono tabular-nums">
                            {isQualitative ? "—" : (ind.threshold_value ?? "—")}
                          </td>
                          <td className="py-1 pr-2 text-right font-mono tabular-nums text-gray-900">
                            {ind.indicator_value || "—"}
                          </td>
                          <td className="py-1 pr-2 text-center">
                            {ind.judgment_result === 1 ? (
                              <span className="inline-block rounded bg-red-100 px-2 py-0.5 font-bold text-red-700">1</span>
                            ) : ind.judgment_result === 0 ? (
                              <span className="inline-block rounded bg-green-100 px-2 py-0.5 font-bold text-green-700">0</span>
                            ) : (
                              <span className="text-gray-400">—</span>
                            )}
                          </td>
                          <td className="py-1 pr-2 text-center">
                            <div className="flex items-center justify-center gap-1">
                              <button
                                onClick={() => openEditForm(ind)}
                                className="rounded p-0.5 text-blue-600 hover:bg-blue-50" title="编辑"
                              >
                                <Pencil size={12} />
                              </button>
                              <button
                                onClick={() => handleDeleteDef(ind.id)}
                                className="rounded p-0.5 text-red-500 hover:bg-red-50" title="删除"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          </td>
                          <td></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          );
        })}
      </div>

      {/* Prompt edit dialog */}
      <Modal open={promptDialogOpen} onClose={() => setPromptDialogOpen(false)}
        title={promptEditing ? `编辑提示词: ${promptEditing.prompt_name}` : "编辑提示词"}>
        <div className="space-y-3">
          <div className="text-xs text-gray-600">提示词类型: <span className="text-gray-900">{promptEditing?.prompt_type}</span></div>
          <div>
            <div className="text-xs text-gray-600 mb-1">提示词内容（与后端运行时完全一致）</div>
            <textarea
              className="h-80 w-full rounded-md border border-gray-300 bg-white p-3 font-mono text-sm text-gray-900 outline-none focus:border-blue-500"
              value={promptDraft}
              onChange={(e) => setPromptDraft(e.target.value)}
            />
          </div>
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

      {/* Add/Edit indicator dialog (shared form) */}
      <Modal open={formDialogOpen} onClose={() => setFormDialogOpen(false)}
        title={formMode === "add" ? "新增指标" : "编辑指标"}>
        <IndicatorForm form={form} setForm={setForm} onSubmit={submitForm}
          submitLabel={formMode === "add" ? "添加" : "保存"} />
      </Modal>
    </div>
  );
}
