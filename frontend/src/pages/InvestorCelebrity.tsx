import { useEffect, useState } from "react";
import { Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api, type CelebrityInvestor } from "@/lib/api";
import { InvestorCard } from "@/components/celebrity/InvestorCard";
import { WeeklyDynamics } from "@/components/celebrity/WeeklyDynamics";
import { PublicHoldingTab } from "@/components/celebrity/PublicHoldingTab";
import { PromptEditorDialog } from "@/components/celebrity/PromptEditorDialog";

type Tab = "detail" | "weekly" | "public";

export function InvestorCelebrity() {
  const [tab, setTab] = useState<Tab>("detail");
  const [investors, setInvestors] = useState<CelebrityInvestor[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loadingInv, setLoadingInv] = useState(true);

  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);

  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState({ name: "", invest_style: "", remark: "" });

  const [promptDialog, setPromptDialog] = useState<{ key: string; title: string } | null>(null);

  const loadInvestors = () => {
    setLoadingInv(true);
    api.celebrityInvestors()
      .then((res) => {
        const list = res.items ?? [];
        setInvestors(list);
        setSelectedId((prev) => (prev && list.find((i) => i.id === prev) ? prev : list[0]?.id ?? null));
      })
      .finally(() => setLoadingInv(false));
  };

  useEffect(() => { loadInvestors(); }, []);

  const selected = investors.find((i) => i.id === selectedId) ?? null;

  const handleRefresh = async () => {
    if (!selectedId) return;
    setRefreshing(true);
    setRefreshMsg("开始拉取大模型最新持仓言论…");
    try {
      const res = await api.celebrityRefresh(selectedId);
      setRefreshMsg(res.message ?? (res.status === "no_new_info" ? "暂无新公开信息" : "刷新成功"));
      loadInvestors();
    } catch {
      setRefreshMsg("刷新失败，请重试");
    } finally {
      setRefreshing(false);
      setTimeout(() => setRefreshMsg(null), 3000);
    }
  };

  const handleAddInvestor = async () => {
    if (!addForm.name.trim()) return;
    try {
      await api.celebrityAddInvestor(addForm.name, addForm.invest_style, addForm.remark);
      setShowAdd(false);
      setAddForm({ name: "", invest_style: "", remark: "" });
      loadInvestors();
    } catch {
      setRefreshMsg("新增投资人失败");
    }
  };

  const handleDeleteInvestor = async () => {
    if (!selected || selected.is_builtin) return;
    if (!confirm(`确认删除投资人「${selected.name}」及其全部数据？`)) return;
    try {
      await api.celebrityDeleteInvestor(selected.id);
      loadInvestors();
    } catch {
      setRefreshMsg("删除失败");
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* Tab 导航 */}
      <div className="flex items-center gap-1 border-b border-border px-4">
        <TabButton active={tab === "detail"} onClick={() => setTab("detail")}>投资人详情</TabButton>
        <TabButton active={tab === "weekly"} onClick={() => setTab("weekly")}>名人周动态</TabButton>
        <TabButton active={tab === "public"} onClick={() => setTab("public")}>公募持仓</TabButton>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {tab === "detail" ? (
          <div className="mx-auto max-w-4xl">
            {/* 投资人切换栏 */}
            <div className="mb-4 flex flex-wrap items-center gap-2">
              {loadingInv ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <select
                  value={selectedId ?? ""}
                  onChange={(e) => setSelectedId(Number(e.target.value))}
                  className="rounded-md border border-border bg-card px-3 py-1.5 text-sm"
                >
                  {investors.map((i) => (
                    <option key={i.id} value={i.id}>{i.name}</option>
                  ))}
                </select>
              )}
              <button
                onClick={() => setShowAdd(true)}
                className="flex items-center gap-1 rounded-md border border-border px-2 py-1.5 text-sm hover:bg-muted"
              >
                <Plus className="h-3.5 w-3.5" /> 新增
              </button>
              {selected && !selected.is_builtin && (
                <button
                  onClick={handleDeleteInvestor}
                  className="flex items-center gap-1 rounded-md border border-border px-2 py-1.5 text-sm text-destructive hover:bg-destructive/10"
                >
                  <Trash2 className="h-3.5 w-3.5" /> 删除
                </button>
              )}
              <button
                onClick={() => setPromptDialog({ key: "latest_dynamics", title: "最新动态提示词" })}
                className="ml-auto rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted"
              >
                刷新提示词
              </button>
            </div>

            {selected ? (
              <InvestorCard investor={selected} />
            ) : (
              <p className="text-sm text-muted-foreground">请选择或新增投资人</p>
            )}
          </div>
        ) : tab === "weekly" ? (
          <WeeklyDynamics
            onSelectInvestor={(id) => {
              setSelectedId(id);
              setTab("detail");
            }}
          />
        ) : (
          <PublicHoldingTab
            onSelectInvestor={(id) => {
              setSelectedId(id);
              setTab("detail");
            }}
          />
        )}
      </div>

      {/* 悬浮刷新按钮（仅详情 Tab 显示） */}
      {tab === "detail" && selected && (
        <div className="fixed bottom-6 right-6 flex flex-col items-end gap-2">
          {refreshMsg && (
            <div className="rounded-md border border-border bg-card px-3 py-1.5 text-xs shadow-lg">
              {refreshMsg}
            </div>
          )}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg hover:bg-primary/90 disabled:opacity-50"
            title="刷新当前投资人最新持仓言论"
          >
            <RefreshCw className={`h-5 w-5 ${refreshing ? "animate-spin" : ""}`} />
          </button>
        </div>
      )}

      {/* 新增投资人弹窗 */}
      {showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-lg border border-border bg-background p-4 shadow-xl">
            <h3 className="mb-3 text-sm font-semibold">新增投资人</h3>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs text-muted-foreground">投资人名称 *</label>
                <input
                  value={addForm.name}
                  onChange={(e) => setAddForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full rounded-md border border-border bg-card px-3 py-1.5 text-sm"
                  placeholder="如：但斌（东方港湾）"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-muted-foreground">投资风格（经典体系介绍）</label>
                <textarea
                  value={addForm.invest_style}
                  onChange={(e) => setAddForm((f) => ({ ...f, invest_style: e.target.value }))}
                  className="h-20 w-full rounded-md border border-border bg-card px-3 py-1.5 text-sm"
                  placeholder="该投资人的经典投资体系介绍"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-muted-foreground">备注</label>
                <input
                  value={addForm.remark}
                  onChange={(e) => setAddForm((f) => ({ ...f, remark: e.target.value }))}
                  className="w-full rounded-md border border-border bg-card px-3 py-1.5 text-sm"
                />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setShowAdd(false)} className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted">取消</button>
              <button onClick={handleAddInvestor} className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:bg-primary/90">确定</button>
            </div>
          </div>
        </div>
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

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`border-b-2 px-4 py-2.5 text-sm transition-colors ${
        active ? "border-primary text-primary font-medium" : "border-transparent text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}
