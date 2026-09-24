import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Workflow } from "lucide-react";

/**
 * Reserved entry for the future AI tool-orchestration flow. It never fires a
 * request — clicking only reveals a "coming soon" note.
 */
export function OrchestrationReserved() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-xl border border-dashed border-border/60 bg-card/60 p-4">
      <button
        type="button"
        data-testid="macro-orchestration-entry"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-3 text-start"
      >
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          <Workflow className="h-4 w-4" aria-hidden="true" />
        </span>
        <span className="flex-1">
          <span className="flex items-center gap-2 text-sm font-medium text-foreground">
            {t("macro.prompts.orchestrationTitle")}
            <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-normal text-muted-foreground">
              {t("macro.prompts.orchestrationSoon")}
            </span>
          </span>
          <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">
            {t("macro.prompts.orchestrationDesc")}
          </span>
        </span>
      </button>
      {open && (
        <p data-testid="macro-orchestration-note" className="mt-2 text-xs text-muted-foreground">
          {t("macro.prompts.orchestrationSoon")}
        </p>
      )}
    </div>
  );
}
