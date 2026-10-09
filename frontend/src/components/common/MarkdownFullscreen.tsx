import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Maximize2, Minus, Plus, X } from "lucide-react";
import { MarkdownContent } from "./MarkdownContent";

const FULLSCREEN_ZOOM_STEPS = [0.85, 1, 1.15, 1.3, 1.5, 1.8];

interface MarkdownFullscreenProps {
  title: string;
  markdown: string;
  onClose: () => void;
}

/**
 * Full-viewport Markdown reader with zoom steps (85%–180%). Renders any
 * MarkdownContent report — ASCII diagrams keep their gap-free monospace
 * columns via the ```text handling inside MarkdownContent.
 */
export function MarkdownFullscreen({
  title,
  markdown,
  onClose,
}: MarkdownFullscreenProps) {
  const { t } = useTranslation();
  const [zoomIdx, setZoomIdx] = useState(1);
  const zoom = FULLSCREEN_ZOOM_STEPS[zoomIdx];

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-background/95"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid="report-fullscreen"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <span className="min-w-0 truncate text-sm font-semibold">{title}</span>
        <div className="flex items-center gap-1.5">
          <span
            className="mr-1 font-mono text-xs text-muted-foreground"
            data-testid="fullscreen-zoom"
          >
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            onClick={() => setZoomIdx((i) => Math.max(0, i - 1))}
            disabled={zoomIdx === 0}
            aria-label={t("common.zoomOut")}
            className="rounded-md border border-border p-1.5 hover:bg-muted/60 disabled:opacity-40"
            data-testid="fullscreen-zoom-out"
          >
            <Minus className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={() => setZoomIdx(1)}
            aria-label={t("common.resetZoom")}
            className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted/60"
            data-testid="fullscreen-zoom-reset"
          >
            100%
          </button>
          <button
            type="button"
            onClick={() =>
              setZoomIdx((i) => Math.min(FULLSCREEN_ZOOM_STEPS.length - 1, i + 1))
            }
            disabled={zoomIdx === FULLSCREEN_ZOOM_STEPS.length - 1}
            aria-label={t("common.zoomIn")}
            className="rounded-md border border-border p-1.5 hover:bg-muted/60 disabled:opacity-40"
            data-testid="fullscreen-zoom-in"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("common.close")}
            className="ml-1 rounded-md border border-border p-1.5 hover:bg-muted/60"
            data-testid="fullscreen-close"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-6 py-4">
        <div className="mx-auto w-full max-w-[1600px]" style={{ zoom }}>
          <MarkdownContent content={markdown} />
        </div>
      </div>
    </div>
  );
}

interface MarkdownFullscreenButtonProps {
  /** Dialog title shown in the fullscreen toolbar. */
  title: string;
  markdown: string;
  /** Visible text; omit for a compact icon-only button (uses ariaLabel). */
  label?: string;
  /** Accessible name; defaults to the generic "Fullscreen" label. */
  ariaLabel?: string;
  testId?: string;
  buttonClassName?: string;
}

/** Trigger button that opens a MarkdownFullscreen dialog on click. */
export function MarkdownFullscreenButton({
  title,
  markdown,
  label,
  ariaLabel,
  testId = "markdown-fullscreen-btn",
  buttonClassName,
}: MarkdownFullscreenButtonProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const accessibleName = ariaLabel ?? label ?? t("common.fullscreen");

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={accessibleName}
        title={accessibleName}
        className={
          buttonClassName ??
          "inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs hover:bg-muted/60"
        }
        data-testid={testId}
      >
        <Maximize2 className={label ? "h-3.5 w-3.5" : "h-4 w-4"} aria-hidden="true" />
        {label}
      </button>
      {open && (
        <MarkdownFullscreen
          title={title}
          markdown={markdown}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
