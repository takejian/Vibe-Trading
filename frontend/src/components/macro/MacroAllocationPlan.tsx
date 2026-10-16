import { useTranslation } from "react-i18next";
import { Target } from "lucide-react";
import type { SynthesisAllocationDetail } from "@/lib/api";

interface Props {
  details: SynthesisAllocationDetail[];
  posture: string | null | undefined;
  riskBudget: number | null | undefined;
}

const GROUP_ORDER = ["equity", "bond", "commodity", "property", "cash"] as const;
const CATEGORY_ORDER = [
  "cn_large",
  "cn_growth",
  "cn_dividend",
  "hk_equity",
  "global_equity",
  "rate_bond",
  "credit_bond",
  "precious_metal",
  "industrial_metal",
  "energy",
  "agriculture",
  "property_chain",
  "cash",
] as const;

function ratingClass(rating: number): string {
  if (rating >= 2) return "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400";
  if (rating === 1) return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
  if (rating === -1) return "bg-red-500/10 text-red-600 dark:text-red-400";
  if (rating <= -2) return "bg-red-500/15 text-red-700 dark:text-red-400";
  return "bg-muted text-muted-foreground";
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

/** 细分品类战术配置卡：评级、建议比例区间、操作语、触发条件与工具。 */
export function MacroAllocationPlan({ details, posture, riskBudget }: Props) {
  const { t } = useTranslation();

  if (!details || details.length === 0) return null;

  const byCategory = new Map(details.map((d) => [d.category, d]));
  const ordered = CATEGORY_ORDER.map((key) => byCategory.get(key)).filter(
    (d): d is SynthesisAllocationDetail => Boolean(d),
  );
  const risk = typeof riskBudget === "number" ? riskBudget : null;
  const postureKey = posture === "offensive" || posture === "defensive" ? posture : "balanced";

  return (
    <div
      data-testid="macro-syn-allocation-plan"
      className="rounded-lg border border-border/50 bg-background/50 p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-medium text-foreground">
          {t("macro.board.syn.planTitle")}
        </p>
        <div className="flex items-center gap-2">
          <span
            data-testid="macro-syn-posture"
            className="rounded-md bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
          >
            {t(`macro.board.syn.posture.${postureKey}` as never)}
          </span>
          {risk !== null && (
            <span className="text-[10px] text-muted-foreground">
              {t("macro.board.syn.riskBudget")} {(risk * 100).toFixed(0)}%
            </span>
          )}
        </div>
      </div>

      {risk !== null && (
        <div
          className="mt-2 flex h-2 w-full overflow-hidden rounded-full bg-muted"
          title={t("macro.board.syn.riskBudgetHint")}
        >
          <div className="h-full bg-emerald-500/70" style={{ width: `${risk * 100}%` }} />
          <div className="h-full flex-1 bg-blue-400/50" />
        </div>
      )}

      <div className="mt-3 space-y-3">
        {GROUP_ORDER.map((group) => {
          const items = ordered.filter((d) => d.asset_group === group);
          if (items.length === 0) return null;
          const groupWeight = items.reduce((sum, d) => sum + d.weight_mid, 0);
          return (
            <div key={group}>
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-semibold text-foreground">
                  {t(`macro.board.syn.assetGroup.${group}` as never)}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {pct(groupWeight)}
                </span>
                <span className="h-px flex-1 bg-border/50" />
              </div>
              <div className="mt-1.5 grid gap-1.5 md:grid-cols-2">
                {items.map((detail) => (
                  <div
                    key={detail.category}
                    data-testid={`macro-syn-asset-${detail.category}`}
                    className="rounded-lg border border-border/40 bg-card p-2"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-medium text-foreground">
                        {t(`macro.board.syn.assetCat.${detail.category}` as never)}
                      </span>
                      <span
                        className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium ${ratingClass(detail.rating)}`}
                      >
                        {t(`macro.board.syn.alloc.${detail.rating}` as never)}
                      </span>
                      <span className="ml-auto text-[11px] font-medium tabular-nums text-foreground">
                        {detail.weight_low === detail.weight_high
                          ? pct(detail.weight_mid)
                          : `${pct(detail.weight_low)}~${pct(detail.weight_high)}`}
                      </span>
                    </div>
                    <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className={`h-full rounded-full ${detail.weight_mid === 0 ? "bg-transparent" : "bg-primary/70"}`}
                        style={{ width: `${Math.min(detail.weight_mid / 0.15, 1) * 100}%` }}
                      />
                    </div>
                    {(detail.rationale || detail.trigger) && (
                      <p className="mt-1 text-[10px] leading-snug text-muted-foreground">
                        {detail.rationale}
                        {detail.rationale && detail.trigger ? "；" : ""}
                        {detail.trigger && (
                          <span className="text-amber-600 dark:text-amber-400">
                            <Target className="mr-0.5 inline h-2.5 w-2.5" aria-hidden="true" />
                            {detail.trigger}
                          </span>
                        )}
                      </p>
                    )}
                    <p className="mt-0.5 text-[10px] text-muted-foreground/80">
                      {detail.vehicle}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
