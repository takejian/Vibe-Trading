import { useTranslation } from "react-i18next";
import { AlertTriangle, Play, RotateCcw } from "lucide-react";
import type { GraphIssue } from "@/lib/swarmGraph";

interface LaunchBarProps {
  target: string;
  question: string;
  issues: GraphIssue[];
  launching: boolean;
  onTargetChange: (v: string) => void;
  onQuestionChange: (v: string) => void;
  onReset: () => void;
  onLaunch: () => void;
}

const ISSUE_ORDER: GraphIssue["code"][] = [
  "emptyGraph",
  "cycle",
  "noStart",
  "orphan",
  "danglingEdge",
  "selfLoop",
  "invalidNodeId",
  "duplicateNode",
  "emptyRole",
  "emptyDuty",
  "invalidTimeout",
];

export function LaunchBar({
  target,
  question,
  issues,
  launching,
  onTargetChange,
  onQuestionChange,
  onReset,
  onLaunch,
}: LaunchBarProps) {
  const { t } = useTranslation();
  const targetMissing = !target.trim();
  const questionMissing = !question.trim();
  const launchable = issues.length === 0 && !targetMissing && !questionMissing && !launching;

  const sortedIssues = [...issues].sort(
    (a, b) => ISSUE_ORDER.indexOf(a.code) - ISSUE_ORDER.indexOf(b.code),
  );

  return (
    <div
      className="rounded-lg border border-border bg-card p-4"
      data-testid="launch-bar"
    >
      <div className="grid gap-3 md:grid-cols-2">
        <label className="block">
          <span className="text-xs font-medium text-foreground">
            {t("swarmStudio.launch.target")}
          </span>
          <input
            value={target}
            onChange={(e) => onTargetChange(e.target.value)}
            placeholder="600519.SH"
            data-testid="target-input"
            className={`mt-1 w-full rounded border bg-background px-2 py-1.5 text-sm ${
              targetMissing ? "border-red-400" : "border-border"
            }`}
          />
          {targetMissing && (
            <span className="mt-1 block text-xs text-red-600">
              {t("swarmStudio.launch.targetRequired")}
            </span>
          )}
        </label>
        <label className="block">
          <span className="text-xs font-medium text-foreground">
            {t("swarmStudio.launch.question")}
          </span>
          <input
            value={question}
            onChange={(e) => onQuestionChange(e.target.value)}
            placeholder={t("swarmStudio.launch.questionPlaceholder")}
            data-testid="question-input"
            className={`mt-1 w-full rounded border bg-background px-2 py-1.5 text-sm ${
              questionMissing ? "border-red-400" : "border-border"
            }`}
          />
          {questionMissing && (
            <span className="mt-1 block text-xs text-red-600">
              {t("swarmStudio.launch.questionRequired")}
            </span>
          )}
        </label>
      </div>

      {sortedIssues.length > 0 && (
        <ul className="mt-3 space-y-1" data-testid="validation-issues">
          {sortedIssues.map((issue, idx) => (
            <li
              key={`${issue.code}-${idx}`}
              className="flex items-start gap-1.5 text-xs text-red-600"
              data-testid={`issue-${issue.code}`}
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                {t(`swarmStudio.validation.${issue.code}`)}
                {issue.nodeIds.length > 0 && (
                  <span className="ml-1 font-mono">（{issue.nodeIds.join(", ")}）</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {sortedIssues.length === 0 && !targetMissing && !questionMissing && (
        <p className="mt-3 text-xs text-emerald-600" data-testid="graph-valid">
          {t("swarmStudio.validation.valid")}
        </p>
      )}

      <div className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          onClick={onReset}
          disabled={launching}
          className="inline-flex items-center gap-1.5 rounded border border-border px-3 py-1.5 text-xs text-foreground hover:bg-accent disabled:opacity-40"
          data-testid="reset-preset-btn"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          {t("swarmStudio.launch.reset")}
        </button>
        <button
          type="button"
          onClick={onLaunch}
          disabled={!launchable}
          data-testid="launch-btn"
          className="inline-flex items-center gap-1.5 rounded bg-foreground px-4 py-1.5 text-xs font-medium text-background hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Play className="h-3.5 w-3.5" />
          {t("swarmStudio.launch.submit")}
        </button>
      </div>
    </div>
  );
}
