import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Search, X } from "lucide-react";
import type { SwarmRunSummary } from "@/lib/api";

export interface HistoryFilters {
  target: string;
  from: string;
  to: string;
}

export const EMPTY_HISTORY_FILTERS: HistoryFilters = { target: "", from: "", to: "" };

interface HistoryListProps {
  runs: SwarmRunSummary[];
  loading: boolean;
  error: string;
  filters?: HistoryFilters;
  /** Trial-history mode relabels a few columns for single-skill trials. */
  trialMode?: boolean;
  onSearch?: (filters: HistoryFilters) => void;
  onOpen: (runId: string) => void;
}

export function HistoryList({
  runs,
  loading,
  error,
  filters: initialFilters,
  trialMode = false,
  onSearch,
  onOpen,
}: HistoryListProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<HistoryFilters>(
    initialFilters ?? EMPTY_HISTORY_FILTERS,
  );

  const submit = () => {
    onSearch?.(draft);
  };

  const clear = () => {
    setDraft(EMPTY_HISTORY_FILTERS);
    onSearch?.(EMPTY_HISTORY_FILTERS);
  };

  if (loading) {
    return (
      <p className="mt-8 text-sm text-muted-foreground" data-testid="history-loading">
        {t("swarmStudio.history.loading")}
      </p>
    );
  }
  if (error) {
    return (
      <p className="mt-8 text-sm text-destructive" data-testid="history-error">
        {error}
      </p>
    );
  }

  return (
    <div className="mt-4 space-y-3">
      <form
        className="flex flex-wrap items-end gap-2"
        data-testid="history-filters"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          {t("swarmStudio.history.filterTarget")}
          <input
            value={draft.target}
            onChange={(e) => setDraft({ ...draft, target: e.target.value })}
            data-testid="history-filter-target"
            placeholder={t("swarmStudio.history.filterTargetPlaceholder")}
            className="w-52 rounded border border-border bg-background px-2 py-1.5 text-xs text-foreground"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          {t("swarmStudio.history.filterFrom")}
          <input
            type="date"
            value={draft.from}
            onChange={(e) => setDraft({ ...draft, from: e.target.value })}
            data-testid="history-filter-from"
            className="rounded border border-border bg-background px-2 py-1.5 text-xs text-foreground"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          {t("swarmStudio.history.filterTo")}
          <input
            type="date"
            value={draft.to}
            onChange={(e) => setDraft({ ...draft, to: e.target.value })}
            data-testid="history-filter-to"
            className="rounded border border-border bg-background px-2 py-1.5 text-xs text-foreground"
          />
        </label>
        <button
          type="submit"
          data-testid="history-filter-search"
          className="inline-flex items-center gap-1 rounded bg-foreground px-3 py-1.5 text-xs text-background"
        >
          <Search className="h-3.5 w-3.5" />
          {t("swarmStudio.history.filterSearch")}
        </button>
        <button
          type="button"
          onClick={clear}
          data-testid="history-filter-clear"
          className="inline-flex items-center gap-1 rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
        >
          <X className="h-3.5 w-3.5" />
          {t("swarmStudio.history.filterClear")}
        </button>
      </form>

      <div className="overflow-x-auto rounded-lg border border-border" data-testid="history-list">
        <table className="w-full min-w-[720px] text-left text-xs">
          <thead className="bg-accent/40 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">{t("swarmStudio.history.createdAt")}</th>
              <th className="px-3 py-2 font-medium">
                {trialMode
                  ? t("swarmStudio.history.skillColumn")
                  : t("swarmStudio.history.preset")}
              </th>
              <th className="px-3 py-2 font-medium">{t("swarmStudio.history.target")}</th>
              {!trialMode && (
                <th className="px-3 py-2 font-medium">{t("swarmStudio.history.question")}</th>
              )}
              <th className="px-3 py-2 font-medium">{t("swarmStudio.history.statusLabel")}</th>
              <th className="px-3 py-2 font-medium">{t("swarmStudio.history.excerpt")}</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id} className="border-t border-border align-top">
                <td className="px-3 py-2 text-muted-foreground">
                  {new Date(run.created_at).toLocaleString()}
                </td>
                <td className="px-3 py-2 font-mono">
                  {trialMode ? run.trial_skill ?? run.preset_name : run.preset_name}
                </td>
                <td className="px-3 py-2">{run.research_target || "—"}</td>
                {!trialMode && (
                  <td className="max-w-[14rem] truncate px-3 py-2" title={run.research_question ?? ""}>
                    {run.research_question || "—"}
                  </td>
                )}
                <td className="px-3 py-2">
                  {t(`swarmStudio.history.status.${run.status}`, {
                    defaultValue: run.status,
                  })}
                </td>
                <td className="max-w-[18rem] truncate px-3 py-2 text-muted-foreground" title={run.final_report_excerpt ?? ""}>
                  {run.final_report_excerpt || "—"}
                </td>
                <td className="px-3 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => onOpen(run.id)}
                    data-testid={`open-history-${run.id}`}
                    className="rounded border border-border px-2 py-1 hover:bg-accent"
                  >
                    {t("swarmStudio.history.viewSnapshot")}
                  </button>
                </td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr>
                <td
                  colSpan={trialMode ? 6 : 7}
                  className="px-3 py-6 text-center text-muted-foreground"
                >
                  {t("swarmStudio.history.empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
