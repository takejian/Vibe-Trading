import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";

interface Props {
  open: boolean;
  /** Only prompt "a" is editable; the caller enforces this. */
  code: string;
  initialText: string;
  onClose: () => void;
  onSaved?: (text: string) => void;
}

export function PromptEditDialog({ open, code, initialText, onClose, onSaved }: Props) {
  const { t } = useTranslation();
  const [text, setText] = useState(initialText);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const textRef = useRef<HTMLTextAreaElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (open) {
      setText(initialText);
      setError("");
      setSaving(false);
      setTimeout(() => textRef.current?.focus(), 0);
    }
  }, [open, initialText]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;

  const save = async () => {
    if (!text.trim() || saving) return;
    setSaving(true);
    setError("");
    try {
      await api.updateMacroPrompt(code, text);
      onSaved?.(text);
      onClose();
    } catch {
      setError(t("macro.prompts.saveFailed"));
      setSaving(false);
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("macro.prompts.editTitle")}
        className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-2xl border bg-background p-4 shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="text-sm font-semibold text-foreground">{t("macro.prompts.editTitle")}</h2>
        <textarea
          ref={textRef}
          data-testid="macro-prompt-textarea"
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={18}
          className="mt-3 w-full flex-1 resize-none rounded-lg border border-border/60 bg-card p-3 font-mono text-xs leading-relaxed text-foreground outline-none focus:ring-2 focus:ring-primary/40"
        />
        {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded-lg border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          >
            {t("macro.prompts.cancel")}
          </button>
          <button
            type="button"
            data-testid="macro-prompt-save"
            onClick={save}
            disabled={!text.trim() || saving}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {saving && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
            {t("macro.prompts.save")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
