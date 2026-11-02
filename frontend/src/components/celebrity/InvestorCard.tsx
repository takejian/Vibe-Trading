import { useEffect, useState } from "react";
import { Edit2, Loader2 } from "lucide-react";
import {
  api,
  type CelebrityCard,
  type CelebrityInvestor,
} from "@/lib/api";
import { PromptEditorDialog } from "./PromptEditorDialog";

interface InvestorCardProps {
  investor: CelebrityInvestor;
}

export function InvestorCard({ investor }: InvestorCardProps) {
  const [card, setCard] = useState<CelebrityCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editingStyle, setEditingStyle] = useState(false);
  const [styleDraft, setStyleDraft] = useState("");
  const [savingStyle, setSavingStyle] = useState(false);

  const [perfDraft, setPerfDraft] = useState<Record<string, string>>({});
  const [editingPerf, setEditingPerf] = useState(false);
  const [loadingPerf, setLoadingPerf] = useState(false);

  const [selectedOpinions, setSelectedOpinions] = useState<Set<string>>(new Set());
  const [selectedAdjusts, setSelectedAdjusts] = useState<Set<string>>(new Set());
  const [reviewing, setReviewing] = useState<"opinions" | "adjusts" | null>(null);

  const [backfilling, setBackfilling] = useState(false);

  const [promptDialog, setPromptDialog] = useState<{ key: string; title: string } | null>(null);

  const loadCard = () => {
    setLoading(true);
    setError(null);
    api.celebrityCard(investor.id)
      .then((c) => setCard(c))
      .catch(() => setError("加载投资人数据失败"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadCard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [investor.id]);

  // Sync style draft when card loads
  useEffect(() => {
    if (card) setStyleDraft(card.investor.invest_style ?? "");
  }, [card?.investor.invest_style]);

  const handleSaveStyle = async () => {
    setSavingStyle(true);
    try {
      await api.celebrityUpdateStyle(investor.id, styleDraft);
      setEditingStyle(false);
      loadCard();
    } catch {
      setError("保存投资风格失败");
    } finally {
      setSavingStyle(false);
    }
  };

  const handleGeneratePerformance = async () => {
    setLoadingPerf(true);
    try {
      const res = await api.celebrityGeneratePerformance(investor.id);
      if (res.performance) {
        setCard((prev) => (prev ? { ...prev, performance: res.performance } : prev));
      }
    } catch {
      setError("生成绩效评价失败");
    } finally {
      setLoadingPerf(false);
    }
  };

  const handleSavePerformance = async () => {
    setLoadingPerf(true);
    try {
      await api.celebritySavePerformance(investor.id, perfDraft);
      setEditingPerf(false);
      loadCard();
    } catch {
      setError("保存绩效评价失败");
    } finally {
      setLoadingPerf(false);
    }
  };

  const toggleOpinion = (id: string) => {
    setSelectedOpinions((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleAdjust = (id: string) => {
    setSelectedAdjusts((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleReviewOpinions = async () => {
    if (!card || selectedOpinions.size === 0) return;
    const items = card.history_opinions
      .filter((o) => selectedOpinions.has(o.id))
      .map((o) => ({ id: o.id, publish_time: o.publish_time, content: o.content }));
    setReviewing("opinions");
    try {
      await api.celebrityReviewOpinions(investor.id, items);
      setSelectedOpinions(new Set());
      loadCard();
    } catch {
      setError("观点复查失败");
    } finally {
      setReviewing(null);
    }
  };

  const handleReviewAdjusts = async () => {
    if (!card || selectedAdjusts.size === 0) return;
    const items = card.adjusts
      .filter((a) => selectedAdjusts.has(a.id))
      .map((a) => ({ id: a.id, time: a.time, action: a.action, target: a.target }));
    setReviewing("adjusts");
    try {
      await api.celebrityReviewAdjusts(investor.id, items);
      setSelectedAdjusts(new Set());
      loadCard();
    } catch {
      setError("调仓复查失败");
    } finally {
      setReviewing(null);
    }
  };

  const handleBackfill = async () => {
    setBackfilling(true);
    try {
      await api.celebrityBackfill(investor.id);
      loadCard();
    } catch {
      setError("历史回灌失败");
    } finally {
      setBackfilling(false);
    }
  };

  const perf = card?.performance;
  const perfFields: Array<[string, string]> = [
    ["recent_performance", "近期业绩"],
    ["return_1y", "近1年收益"],
    ["return_3y", "近3年收益"],
    ["return_5y", "近5年收益"],
    ["return_10y", "近10年收益"],
    ["max_drawdown", "最大回撤"],
    ["stability_tag", "稳健性标签"],
    ["stability_desc", "稳健性说明"],
    ["peer_compare", "同行对比"],
    ["risk_note", "风险备注"],
  ];

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> 加载中…
        </div>
      ) : !card ? (
        <p className="text-sm text-muted-foreground">暂无数据</p>
      ) : (
        <>
          {/* 投资人名称 */}
          <div className="text-lg font-semibold">{card.investor.name}</div>

          {/* 投资风格 */}
          <Section title="投资风格" actions={
            <div className="flex gap-1">
              <button
                onClick={() => setEditingStyle((v) => !v)}
                className="rounded p-1 text-muted-foreground hover:bg-muted"
                title="编辑"
              >
                <Edit2 className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => setPromptDialog({ key: "latest_dynamics", title: "最新动态提示词" })}
                className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
              >
                提示词
              </button>
            </div>
          }>
            {editingStyle ? (
              <div className="space-y-2">
                <textarea
                  value={styleDraft}
                  onChange={(e) => setStyleDraft(e.target.value)}
                  className="h-24 w-full rounded-md border border-border bg-card p-2 text-sm"
                />
                <div className="flex gap-2">
                  <button
                    onClick={handleSaveStyle}
                    disabled={savingStyle}
                    className="flex items-center gap-1 rounded bg-primary px-2 py-1 text-xs text-primary-foreground"
                  >
                    {savingStyle && <Loader2 className="h-3 w-3 animate-spin" />} 保存
                  </button>
                  <button
                    onClick={() => { setEditingStyle(false); setStyleDraft(card.investor.invest_style ?? ""); }}
                    className="rounded border border-border px-2 py-1 text-xs"
                  >
                    取消
                  </button>
                </div>
              </div>
            ) : (
              <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                {card.investor.invest_style || "暂无投资风格介绍"}
              </p>
            )}
          </Section>

          {/* 客观绩效评价 */}
          <Section title="客观绩效评价" actions={
            <div className="flex gap-1">
              <button
                onClick={handleGeneratePerformance}
                disabled={loadingPerf}
                className="flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
              >
                {loadingPerf && <Loader2 className="h-3 w-3 animate-spin" />} 获取评价
              </button>
              <button
                onClick={() => {
                  setPerfDraft(Object.fromEntries(perfFields.map(([k]) => [k, String(perf?.[k as keyof typeof perf] ?? "")])));
                  setEditingPerf(true);
                }}
                className="rounded p-1 text-muted-foreground hover:bg-muted"
                title="手动填写"
              >
                <Edit2 className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => setPromptDialog({ key: "performance", title: "绩效评价提示词" })}
                className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
              >
                提示词
              </button>
            </div>
          }>
            {editingPerf ? (
              <div className="space-y-2">
                {perfFields.map(([key, label]) => (
                  <div key={key} className="grid grid-cols-[100px_1fr] gap-2">
                    <label className="pt-1 text-xs text-muted-foreground">{label}</label>
                    <input
                      value={perfDraft[key] ?? ""}
                      onChange={(e) => setPerfDraft((p) => ({ ...p, [key]: e.target.value }))}
                      className="rounded border border-border bg-card px-2 py-1 text-xs"
                    />
                  </div>
                ))}
                <div className="flex gap-2">
                  <button onClick={handleSavePerformance} disabled={loadingPerf}
                    className="flex items-center gap-1 rounded bg-primary px-2 py-1 text-xs text-primary-foreground">
                    {loadingPerf && <Loader2 className="h-3 w-3 animate-spin" />} 保存
                  </button>
                  <button onClick={() => setEditingPerf(false)} className="rounded border border-border px-2 py-1 text-xs">取消</button>
                </div>
              </div>
            ) : perf ? (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                {perfFields.map(([key, label]) => (
                  <div key={key} className="flex gap-2">
                    <dt className="text-muted-foreground">{label}：</dt>
                    <dd>{String(perf[key as keyof typeof perf] ?? "—")}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">暂无绩效评价，点击「获取评价」生成</p>
            )}
          </Section>

          {/* 当前持仓 */}
          <Section title="当前持仓 · 前15大重仓" actions={
            <button
              onClick={handleBackfill}
              disabled={backfilling}
              className="flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
            >
              {backfilling && <Loader2 className="h-3 w-3 animate-spin" />} 回灌历史
            </button>
          }>
            <Table headers={["标的", "持仓占比", "来源", "更新时间", "置信度"]}>
              {card.positions.length === 0 ? (
                <tr><td colSpan={5} className="py-4 text-center text-sm text-muted-foreground">暂无持仓数据</td></tr>
              ) : card.positions.map((p) => (
                <tr key={p.id}>
                  <td>{p.target}</td>
                  <td>{p.percentage || "—"}</td>
                  <td>{p.source || "—"}</td>
                  <td>{p.update_time || "—"}</td>
                  <td><ConfidenceTag value={p.confidence} /></td>
                </tr>
              ))}
            </Table>
          </Section>

          {/* 最新观点 */}
          <Section title="最新观点">
            {card.latest_opinion ? (
              <div className="rounded-md border border-border bg-card/50 p-3">
                <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
                  <span>{card.latest_opinion.publish_time || "—"}</span>
                  <ConfidenceTag value={card.latest_opinion.confidence} />
                </div>
                <p className="text-sm">{card.latest_opinion.content}</p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">暂无最新观点</p>
            )}
          </Section>

          {/* 历史观点 */}
          <Section title="历史观点" actions={
            <div className="flex gap-1">
              <button
                onClick={handleReviewOpinions}
                disabled={selectedOpinions.size === 0 || reviewing === "opinions"}
                className="flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
              >
                {reviewing === "opinions" && <Loader2 className="h-3 w-3 animate-spin" />} 复查 ({selectedOpinions.size})
              </button>
              <button
                onClick={() => setPromptDialog({ key: "opinion_review", title: "观点复查提示词" })}
                className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
              >
                提示词
              </button>
            </div>
          }>
            <Table headers={["", "发布时间", "观点原文", "置信度", "事后评判"]}>
              {card.history_opinions.length === 0 ? (
                <tr><td colSpan={5} className="py-4 text-center text-sm text-muted-foreground">暂无历史观点</td></tr>
              ) : card.history_opinions.map((o) => (
                <tr key={o.id}>
                  <td className="w-8">
                    <input
                      type="checkbox"
                      checked={selectedOpinions.has(o.id)}
                      onChange={() => toggleOpinion(o.id)}
                    />
                  </td>
                  <td>{o.publish_time || "—"}</td>
                  <td className="max-w-md truncate" title={o.content ?? ""}>{o.content}</td>
                  <td><ConfidenceTag value={o.confidence} /></td>
                  <td className="max-w-xs truncate" title={o.review_result ?? ""}>{o.review_result || "—"}</td>
                </tr>
              ))}
            </Table>
          </Section>

          {/* 调仓动向 */}
          <Section title="最新调仓动向" actions={
            <div className="flex gap-1">
              <button
                onClick={handleReviewAdjusts}
                disabled={selectedAdjusts.size === 0 || reviewing === "adjusts"}
                className="flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
              >
                {reviewing === "adjusts" && <Loader2 className="h-3 w-3 animate-spin" />} 复查 ({selectedAdjusts.size})
              </button>
              <button
                onClick={() => setPromptDialog({ key: "adjust_review", title: "调仓复查提示词" })}
                className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
              >
                提示词
              </button>
            </div>
          }>
            <Table headers={["", "时间", "动作", "标的", "账面收益", "事后评判"]}>
              {card.adjusts.length === 0 ? (
                <tr><td colSpan={6} className="py-4 text-center text-sm text-muted-foreground">暂无调仓记录</td></tr>
              ) : card.adjusts.map((a) => (
                <tr key={a.id}>
                  <td className="w-8">
                    <input
                      type="checkbox"
                      checked={selectedAdjusts.has(a.id)}
                      onChange={() => toggleAdjust(a.id)}
                    />
                  </td>
                  <td>{a.time || "—"}</td>
                  <td><ActionTag value={a.action} /></td>
                  <td>{a.target || "—"}</td>
                  <td>{a.profit_desc || "—"}</td>
                  <td className="max-w-xs truncate" title={a.review_result ?? ""}>{a.review_result || "—"}</td>
                </tr>
              ))}
            </Table>
          </Section>
        </>
      )}

      {promptDialog && (
        <PromptEditorDialog
          open={!!promptDialog}
          promptKey={promptDialog.key}
          title={promptDialog.title}
          onClose={() => setPromptDialog(null)}
        />
      )}
    </div>
  );
}

// --- Small presentational helpers ---

function Section({ title, actions, children }: { title: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card/40 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-sm font-semibold">{title}</h4>
        {actions}
      </div>
      {children}
    </div>
  );
}

function Table({ headers, children }: { headers: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            {headers.map((h, i) => <th key={i} className="py-1.5 px-2 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/50">{children}</tbody>
      </table>
    </div>
  );
}

function ConfidenceTag({ value }: { value: string | null }) {
  const map: Record<string, string> = {
    高: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    中: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
    低: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    无效: "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400",
  };
  if (!value) return <span className="text-muted-foreground">—</span>;
  return <span className={`rounded px-1.5 py-0.5 text-xs ${map[value] ?? "bg-gray-100 text-gray-600"}`}>{value}</span>;
}

function ActionTag({ value }: { value: string | null }) {
  const map: Record<string, string> = {
    增持: "text-green-600",
    减持: "text-red-600",
    新建: "text-blue-600",
    新建仓: "text-blue-600",
    清仓: "text-gray-500",
  };
  if (!value) return <span className="text-muted-foreground">—</span>;
  return <span className={`text-xs font-medium ${map[value] ?? ""}`}>{value}</span>;
}
