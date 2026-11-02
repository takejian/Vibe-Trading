import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api, type CelebrityWeeklyItem } from "@/lib/api";

interface WeeklyDynamicsProps {
  onSelectInvestor: (investorId: number) => void;
}

export function WeeklyDynamics({ onSelectInvestor }: WeeklyDynamicsProps) {
  const [items, setItems] = useState<CelebrityWeeklyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api.celebrityWeekly()
      .then((res) => setItems(res.items ?? []))
      .catch(() => setError("加载周动态失败"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6 text-center">
        <h2 className="text-xl font-semibold">名人周动态</h2>
        <p className="mt-1 text-xs text-muted-foreground">汇聚全部投资人的最新观点与调仓动向</p>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>
      )}

      {loading ? (
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground py-12">
          <Loader2 className="h-4 w-4 animate-spin" /> 加载中…
        </div>
      ) : items.length === 0 ? (
        <p className="text-center text-sm text-muted-foreground py-12">暂无周动态数据</p>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <div
              key={item.investor_id}
              className="rounded-lg border border-border bg-card/40 p-4"
            >
              <button
                onClick={() => onSelectInvestor(item.investor_id)}
                className="mb-2 text-sm font-semibold text-primary hover:underline"
              >
                {item.name}
              </button>
              {item.updated_at && (
                <span className="ml-2 text-xs text-muted-foreground">更新于 {String(item.updated_at).slice(0, 19).replace("T", " ")}</span>
              )}

              {!item.latest_opinion && !item.latest_adjust ? (
                <p className="text-sm text-muted-foreground">本周暂无新公开动态</p>
              ) : (
                <div className="space-y-2">
                  {item.latest_opinion && (
                    <div className="rounded border border-border/60 bg-card p-2">
                      <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
                        <span>最新观点 · {item.latest_opinion.publish_time || "—"}</span>
                        <ConfidenceTag value={item.latest_opinion.confidence} />
                      </div>
                      <p className="text-sm">{item.latest_opinion.content || "—"}</p>
                    </div>
                  )}
                  {item.latest_adjust && (
                    <div className="rounded border border-border/60 bg-card p-2">
                      <div className="mb-1 text-xs text-muted-foreground">
                        最新调仓 · {item.latest_adjust.time || "—"}
                      </div>
                      <p className="text-sm">
                        <ActionTag value={item.latest_adjust.action} /> {item.latest_adjust.target || "—"}
                        {item.latest_adjust.review_result && (
                          <span className="ml-2 text-xs text-muted-foreground">· {item.latest_adjust.review_result}</span>
                        )}
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ConfidenceTag({ value }: { value: string | null }) {
  const map: Record<string, string> = {
    高: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    中: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
    低: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  };
  if (!value) return null;
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
  if (!value) return null;
  return <span className={`text-xs font-medium ${map[value] ?? ""}`}>{value}</span>;
}
