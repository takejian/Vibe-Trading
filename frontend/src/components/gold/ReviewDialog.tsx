import { AlertTriangle } from "lucide-react";
import type { GoldDiffField } from "@/lib/api";

interface Props {
  kind: "diff" | "cycle";
  title: string;
  diff?: { has_diff: boolean; fields: Record<string, GoldDiffField> };
  newValues?: Record<string, number | null>;
  cycleName?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

const FIELD_LABELS: Record<string, string> = {
  gold_price: "金价 (美元/盎司)",
  ffr: "联邦基金利率 (%)",
  yield_nominal: "10Y名义利率 (%)",
  bei: "10Y BEI (%)",
  tips_real: "10Y实际利率 (%)",
};

export function ReviewDialog({ kind, title, diff, cycleName, onConfirm, onCancel }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-lg border border-border bg-card shadow-lg">
        <div className="flex items-center gap-3 border-b border-border p-4">
          <AlertTriangle className="h-5 w-5 text-amber-500" />
          <h2 className="font-semibold">{title}</h2>
        </div>

        <div className="p-4 space-y-3 text-sm">
          {kind === "diff" && diff && (
            <>
              <p className="text-muted-foreground">检测到以下数据差异，请确认是否覆盖本地值：</p>
              <div className="space-y-2 max-h-60 overflow-y-auto">
                {Object.entries(diff.fields).map(([fname, finfo]) => (
                  <div key={fname} className={`rounded border p-2 ${finfo.diff ? "border-amber-500/40 bg-amber-500/5" : "border-border/50"}`}>
                    <div className="text-xs font-medium mb-1">{FIELD_LABELS[fname] ?? fname}</div>
                    {finfo.diff ? (
                      <div className="flex items-center justify-between text-xs gap-2">
                        <div><span className="text-muted-foreground">本地:</span> <span className="font-mono">{finfo.old !== null ? String(finfo.old) : "—"}</span></div>
                        <span className="text-amber-500">→</span>
                        <div><span className="text-muted-foreground">新值:</span> <span className="font-mono font-medium">{finfo.new !== null ? String(finfo.new) : "—"}</span></div>
                      </div>
                    ) : (
                      <div className="text-xs text-muted-foreground">本地值与新值一致</div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
          {kind === "cycle" && (
            <>
              <p className="text-muted-foreground">系统自动识别到新的政策周期，需要您审核确认后才会生效。</p>
              <div className="rounded border border-primary/40 bg-primary/5 p-3">
                <div className="text-xs text-muted-foreground">周期名称</div>
                <div className="font-medium text-sm">{cycleName ?? "(未命名)"}</div>
              </div>
            </>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-border p-4">
          <button
            type="button"
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60"
            onClick={onCancel}
          >
            {kind === "diff" ? "保留本地值" : "驳回"}
          </button>
          <button
            type="button"
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            onClick={onConfirm}
          >
            {kind === "diff" ? "使用新值覆盖" : "确认生效"}
          </button>
        </div>
      </div>
    </div>
  );
}
