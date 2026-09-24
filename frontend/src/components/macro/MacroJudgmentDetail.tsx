import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import type { MacroJudgment } from "@/lib/api";
import { cn } from "@/lib/utils";

interface SectionDef {
  key:
    | "judgment_result"
    | "dimension_check"
    | "meso_verify"
    | "history_cycle_anchor"
    | "core_support"
    | "core_risk";
  labelKey: string;
}

// Conclusion-first rendering order: head judgment, then the evidence chain.
const SECTIONS: SectionDef[] = [
  { key: "judgment_result", labelKey: "macro.detail.sectionJudgmentResult" },
  { key: "dimension_check", labelKey: "macro.detail.sectionDimensionCheck" },
  { key: "meso_verify", labelKey: "macro.detail.sectionMesoVerify" },
  { key: "history_cycle_anchor", labelKey: "macro.detail.sectionHistoryAnchor" },
  { key: "core_support", labelKey: "macro.detail.sectionCoreSupport" },
  { key: "core_risk", labelKey: "macro.detail.sectionCoreRisk" },
];

interface Props {
  judgment: MacroJudgment;
  /** Cached results carry a "already analyzed for the month" badge. */
  cached?: boolean;
}

export function MacroJudgmentDetail({ judgment, cached = false }: Props) {
  const { t } = useTranslation();
  const [remarkOpen, setRemarkOpen] = useState(false);
  const hasRemark = judgment.extended_remark.trim().length > 0;

  return (
    <article
      data-testid="macro-judgment-detail"
      className="rounded-xl border border-border/60 bg-card text-start"
    >
      {/* Header: economy / month / current cycle / confidence */}
      <header className="border-b border-border/60 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-base font-semibold text-foreground">{judgment.economy}</h3>
          <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground">
            {judgment.statistics_date}
          </span>
          {cached && (
            <span
              data-testid="macro-cached-badge"
              className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary"
            >
              {t("macro.panel.reuseCached")}
            </span>
          )}
        </div>
        <p className="mt-2 text-sm leading-relaxed text-foreground">
          {judgment.current_cycle}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("macro.detail.confidence")}：{judgment.judgment_confidence}
        </p>
      </header>

      {/* Six fixed-order sections */}
      <div className="divide-y divide-border/60">
        {SECTIONS.map(({ key, labelKey }) => (
          <section key={key} className="p-4">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t(labelKey as never)}
            </h4>
            <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-foreground">
              {judgment[key]}
            </p>
          </section>
        ))}

        {hasRemark && (
          <section className="p-4">
            <button
              type="button"
              aria-expanded={remarkOpen}
              onClick={() => setRemarkOpen((open) => !open)}
              className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground"
            >
              {t("macro.detail.extendedRemark")}
              <ChevronDown
                className={cn("h-3.5 w-3.5 transition-transform", remarkOpen && "rotate-180")}
                aria-hidden="true"
              />
            </button>
            {remarkOpen && (
              <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                {judgment.extended_remark}
              </p>
            )}
          </section>
        )}
      </div>
    </article>
  );
}
