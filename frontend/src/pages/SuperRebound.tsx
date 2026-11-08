import { useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { FinancePanel } from "./super-rebound/FinancePanel";
import { IndicatorPanel } from "./super-rebound/IndicatorPanel";

type TabKey = "finance" | "indicator";

export function SuperRebound() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabKey>("finance");

  const tabs: { key: TabKey; label: string }[] = [
    { key: "finance", label: t("superRebound.financeTab") },
    { key: "indicator", label: t("superRebound.indicatorTab") },
  ];

  return (
    <div className="min-h-full px-4 py-6 md:px-8">
      {/* Tab bar */}
      <div className="mb-6 flex gap-1 border-b border-border/60">
        {tabs.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              "relative px-4 py-2 text-sm font-medium transition-colors",
              tab === key
                ? "text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {label}
            {tab === key && (
              <span className="absolute inset-x-0 -bottom-px h-0.5 bg-primary rounded-full" />
            )}
          </button>
        ))}
      </div>

      {/* Panel content */}
      {tab === "finance" ? <FinancePanel /> : <IndicatorPanel />}
    </div>
  );
}
