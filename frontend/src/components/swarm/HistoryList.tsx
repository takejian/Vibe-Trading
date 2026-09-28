import { useTranslation } from "react-i18next";
import type { SwarmRunSummary } from "@/lib/api";

interface HistoryListProps {
  runs: SwarmRunSummary[];
  loading: boolean;
  error: string;
  onOpen: (runId: string) => void;
}

export function HistoryList({ runs, loading, error, onOpen }: HistoryListProps) {
  const { t } = useTranslation();

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
    <div className="mt-6 overflow-x-auto rounded-lg border border-border" data-testid="history-list">
      <table className="w-full min-w-[720px] text-left text-xs">
        <thead className="bg-accent/40 text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">{t("swarmStudio.history.createdAt")}</th>
            <th className="px-3 py-2 font-medium">{t("swarmStudio.history.preset")}</th>
            <th className="px-3 py-2 font-medium">{t("swarmStudio.history.target")}</th>
            <th className="px-3 py-2 font-medium">{t("swarmStudio.history.question")}</th>
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
              <td className="px-3 py-2 font-mono">{run.preset_name}</td>
              <td className="px-3 py-2">{run.research_target || "—"}</td>
              <td className="max-w-[14rem] truncate px-3 py-2" title={run.research_question ?? ""}>
                {run.research_question || "—"}
              </td>
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
              <td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">
                {t("swarmStudio.history.empty")}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
