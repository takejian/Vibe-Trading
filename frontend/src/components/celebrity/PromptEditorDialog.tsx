import { useEffect, useState } from "react";
import { Loader2, X } from "lucide-react";
import { api, type CelebrityPrompt } from "@/lib/api";

interface PromptEditorDialogProps {
  open: boolean;
  promptKey: string;
  title: string;
  onClose: () => void;
}

export function PromptEditorDialog({ open, promptKey, title, onClose }: PromptEditorDialogProps) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !promptKey) return;
    setLoading(true);
    setError(null);
    api.celebrityPromptGet(promptKey)
      .then((p: CelebrityPrompt) => setContent(p.content ?? ""))
      .catch(() => setError("加载提示词失败"))
      .finally(() => setLoading(false));
  }, [open, promptKey]);

  if (!open) return null;

  const handleSave = async () => {
    if (!content.trim()) {
      setError("提示词内容不能为空");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.celebrityPromptUpdate(promptKey, content);
      onClose();
    } catch {
      setError("保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setResetting(true);
    setError(null);
    try {
      const res = await api.celebrityPromptReset(promptKey);
      setContent(res.content ?? "");
    } catch {
      setError("恢复默认失败");
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-lg border border-border bg-background shadow-xl">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h3 className="text-sm font-semibold">{title}</h3>
          <button onClick={onClose} className="rounded p-1 hover:bg-muted" aria-label="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> 加载中…
            </div>
          ) : (
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="h-[50vh] w-full resize-none rounded-md border border-border bg-card p-3 font-mono text-xs leading-relaxed focus:outline-none focus:ring-2 focus:ring-primary/40"
              spellCheck={false}
            />
          )}
          {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
        </div>
        <div className="flex justify-between gap-2 border-t border-border px-4 py-3">
          <button
            onClick={handleReset}
            disabled={loading || saving || resetting}
            className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted disabled:opacity-50"
          >
            {resetting ? "恢复中…" : "恢复默认"}
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
            >
              取消
            </button>
            <button
              onClick={handleSave}
              disabled={loading || saving}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {saving ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
