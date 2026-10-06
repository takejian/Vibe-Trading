/**
 * Reusable macro evaluation-records section.
 *
 * Two column layouts:
 *  - "role" (default): standalone role runs — date / role / source / target.
 *  - "team": mirrors the orchestration history — one row per team run with
 *    createdAt / target / question / status / excerpt (no role/source cols).
 *
 * Both layouts provide a search bar (keyword/target + date range applied on
 * submit), per-row checkboxes (completed rows only, max 5) and an AI
 * comparison that opens a new agent session. Parent-driven filters (clicked
 * role/agent) arrive via ``filterName`` with an ``onClearFilter`` callback;
 * ``records`` are expected to be pre-filtered by the parent.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import {
  ArrowLeftRight,
  CheckSquare,
  Loader2,
  Search,
  Square,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { MacroEvalRecord } from "./macroEvalRecords";

const MAX_COMPARE = 5;

interface SearchDraft {
  keyword: string;
  from: string;
  to: string;
}

const EMPTY_DRAFT: SearchDraft = { keyword: "", from: "", to: "" };

interface MacroEvalHistoryProps {
  records: MacroEvalRecord[];
  loading: boolean;
  error: string;
  /** Unique testid root, e.g. "macro-team-history". */
  testId: string;
  /** Open a run snapshot for the given record. */
  onView: (record: MacroEvalRecord) => void;
  variant?: "role" | "team";
  /** When set, shows the active filter chip with this display name. */
  filterName?: string;
  /** Called when the chip's clear button is pressed. */
  onClearFilter?: () => void;
}

export function MacroEvalHistory({
  records,
  loading,
  error,
  testId,
  onView,
  variant = "role",
  filterName = "",
  onClearFilter,
}: MacroEvalHistoryProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<SearchDraft>(EMPTY_DRAFT);
  const [applied, setApplied] = useState<SearchDraft>(EMPTY_DRAFT);
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState("");

  const matchesRole = (record: MacroEvalRecord, keyword: string) => {
    const haystack = [
      record.roleName,
      record.presetName,
      record.agentId,
      record.target,
      record.question,
      record.excerpt,
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(keyword.trim().toLowerCase());
  };

  const matchesTeam = (record: MacroEvalRecord, keyword: string) => {
    const haystack = [record.target, record.question, record.excerpt]
      .join(" ")
      .toLowerCase();
    return haystack.includes(keyword.trim().toLowerCase());
  };

  const visible = records.filter((record) => {
    if (applied.keyword) {
      const ok =
        variant === "team"
          ? matchesTeam(record, applied.keyword)
          : matchesRole(record, applied.keyword);
      if (!ok) return false;
    }
    if (applied.from && record.date < applied.from) return false;
    if (applied.to && record.date > applied.to) return false;
    return true;
  });

  const selectedRecords = records.filter((record) =>
    selectedKeys.includes(record.key),
  );

  const submitSearch = () => setApplied(draft);

  const clearSearch = () => {
    setDraft(EMPTY_DRAFT);
    setApplied(EMPTY_DRAFT);
  };

  const toggleSelect = (record: MacroEvalRecord) => {
    setCompareError("");
    setSelectedKeys((prev) => {
      if (prev.includes(record.key)) {
        return prev.filter((key) => key !== record.key);
      }
      if (prev.length >= MAX_COMPARE) return prev;
      return [...prev, record.key];
    });
  };

  const buildComparePrompt = (picked: MacroEvalRecord[]) => {
    const parts: string[] = [
      t("macro.evalHistory.promptIntro", { n: picked.length }),
      "",
    ];
    picked.forEach((record, i) => {
      if (variant === "team") {
        parts.push(
          t("macro.evalHistory.promptItemTeam", {
            index: i + 1,
            team: record.presetName,
            target: record.target || "-",
            date: record.date || "-",
            conclusion: record.excerpt || "-",
          }),
        );
      } else {
        parts.push(
          t("macro.evalHistory.promptItem", {
            index: i + 1,
            role: record.roleName,
            team: record.presetName,
            kind: t("macro.evalHistory.kindRoleRun"),
            target: record.target || "-",
            date: record.date || "-",
            conclusion: record.excerpt || "-",
          }),
        );
      }
    });
    parts.push("", t("macro.evalHistory.promptTasks"));
    return parts.join("\n");
  };

  const runCompare = async () => {
    const picked = selectedRecords;
    if (picked.length < 2) {
      setCompareError(t("macro.evalHistory.needTwo"));
      return;
    }
    setComparing(true);
    setCompareError("");
    try {
      const session = await api.createSession(
        t("macro.evalHistory.sessionTitle"),
      );
      await api.sendMessage(session.session_id, buildComparePrompt(picked));
      navigate(`/agent?session=${encodeURIComponent(session.session_id)}`);
    } catch {
      setCompareError(t("macro.evalHistory.compareFailed"));
      setComparing(false);
    }
  };

  return (
    <section
      data-testid={testId}
      className="mt-8 rounded-xl border border-border/60 bg-card p-4"
    >
      <h2 className="text-sm font-semibold text-foreground">
        {t("macro.evalHistory.sectionTitle")}
      </h2>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
        {variant === "team"
          ? t("macro.evalHistory.introTeam")
          : t("macro.evalHistory.intro")}
      </p>

      {loading && (
        <div className="mt-5 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          {t("macro.evalHistory.loading")}
        </div>
      )}
      {error && (
        <p
          data-testid={`${testId}-error`}
          className="mt-4 text-xs text-destructive"
        >
          {t("macro.evalHistory.loadError")}
        </p>
      )}

      {!loading && !error && (
        <>
          <form
            className="mt-4 flex flex-wrap items-end gap-2"
            data-testid={`${testId}-search`}
            onSubmit={(e) => {
              e.preventDefault();
              submitSearch();
            }}
          >
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              {variant === "team"
                ? t("swarmStudio.history.filterTarget")
                : t("macro.evalHistory.keyword")}
              <input
                value={draft.keyword}
                onChange={(e) =>
                  setDraft({ ...draft, keyword: e.target.value })
                }
                data-testid={`${testId}-search-keyword`}
                placeholder={
                  variant === "team"
                    ? t("swarmStudio.history.filterTargetPlaceholder")
                    : t("macro.evalHistory.keywordPlaceholder")
                }
                className={
                  variant === "team"
                    ? "w-52 rounded-lg border border-border/60 bg-background px-2.5 py-1.5 text-xs text-foreground outline-none focus:ring-2 focus:ring-primary/40"
                    : "w-60 rounded-lg border border-border/60 bg-background px-2.5 py-1.5 text-xs text-foreground outline-none focus:ring-2 focus:ring-primary/40"
                }
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              {t("macro.evalHistory.from")}
              <input
                type="date"
                value={draft.from}
                onChange={(e) => setDraft({ ...draft, from: e.target.value })}
                data-testid={`${testId}-search-from`}
                className="rounded-lg border border-border/60 bg-background px-2.5 py-1.5 text-xs text-foreground"
              />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              {t("macro.evalHistory.to")}
              <input
                type="date"
                value={draft.to}
                onChange={(e) => setDraft({ ...draft, to: e.target.value })}
                data-testid={`${testId}-search-to`}
                className="rounded-lg border border-border/60 bg-background px-2.5 py-1.5 text-xs text-foreground"
              />
            </label>
            <button
              type="submit"
              data-testid={`${testId}-search-submit`}
              className="inline-flex items-center gap-1 rounded-lg bg-foreground px-3 py-1.5 text-xs text-background"
            >
              <Search className="h-3.5 w-3.5" />
              {t("macro.evalHistory.search")}
            </button>
            <button
              type="button"
              onClick={clearSearch}
              data-testid={`${testId}-search-clear`}
              className="inline-flex items-center gap-1 rounded-lg border border-border/60 px-3 py-1.5 text-xs text-foreground transition-colors hover:bg-muted"
            >
              <X className="h-3.5 w-3.5" />
              {t("macro.evalHistory.clear")}
            </button>
          </form>

          {filterName && (
            <div
              data-testid={`${testId}-role-filter`}
              className="mt-3 inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-[11px] text-primary"
            >
              <span>
                {variant === "team"
                  ? t("macro.evalHistory.agentFilterChip", {
                      name: filterName,
                    })
                  : t("macro.evalHistory.roleFilterChip", {
                      name: filterName,
                    })}
              </span>
              <button
                type="button"
                data-testid={`${testId}-role-filter-clear`}
                onClick={() => onClearFilter?.()}
                className="inline-flex items-center gap-0.5 hover:underline"
              >
                <X className="h-3 w-3" aria-hidden="true" />
                {variant === "team"
                  ? t("macro.evalHistory.agentFilterClear")
                  : t("macro.evalHistory.roleFilterClear")}
              </button>
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-3">
            <span
              data-testid={`${testId}-selected-count`}
              className="text-[11px] font-medium text-foreground"
            >
              {t("macro.evalHistory.selectedCount", {
                n: selectedKeys.length,
              })}
            </span>
            <span
              data-testid={`${testId}-match-count`}
              className="text-[11px] text-muted-foreground"
            >
              {t("macro.evalHistory.matchCount", { n: visible.length })}
            </span>
            <div className="ml-auto flex items-center gap-2">
              {compareError && (
                <span
                  data-testid={`${testId}-compare-error`}
                  className="text-[11px] text-destructive"
                >
                  {compareError}
                </span>
              )}
              <button
                type="button"
                data-testid={`${testId}-clear-selection`}
                disabled={selectedKeys.length === 0 || comparing}
                onClick={() => setSelectedKeys([])}
                className="rounded-lg border border-border/60 px-2.5 py-1 text-[11px] text-foreground transition-colors hover:bg-muted disabled:opacity-40"
              >
                {t("macro.evalHistory.clearSelection")}
              </button>
              <button
                type="button"
                data-testid={`${testId}-compare`}
                disabled={selectedKeys.length < 2 || comparing}
                onClick={() => void runCompare()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-[11px] font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {comparing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <ArrowLeftRight className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {t("macro.evalHistory.compare")}
              </button>
            </div>
          </div>

          <div className="mt-3 overflow-x-auto rounded-lg border border-border/60">
            <table className="w-full min-w-[720px] text-left text-xs">
              <thead className="bg-accent/40 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2" />
                  {variant === "team" ? (
                    <>
                      <th className="px-3 py-2 font-medium">
                        {t("macro.evalHistory.colCreatedAt")}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {t("macro.evalHistory.colTarget")}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {t("macro.evalHistory.colQuestion")}
                      </th>
                    </>
                  ) : (
                    <>
                      <th className="px-3 py-2 font-medium">
                        {t("macro.evalHistory.colDate")}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {t("macro.evalHistory.colRole")}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {t("macro.evalHistory.colPreset")}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {t("macro.evalHistory.colTarget")}
                      </th>
                    </>
                  )}
                  <th className="px-3 py-2 font-medium">
                    {t("macro.evalHistory.colStatus")}
                  </th>
                  <th className="px-3 py-2 font-medium">
                    {t("macro.evalHistory.colExcerpt")}
                  </th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {visible.map((record) => {
                  const checked = selectedKeys.includes(record.key);
                  const selectable =
                    record.status === "completed" &&
                    (checked || selectedKeys.length < MAX_COMPARE);
                  return (
                    <tr
                      key={record.key}
                      data-testid={`${testId}-row-${record.key}`}
                      className="border-t border-border/60 align-top"
                    >
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          role="checkbox"
                          aria-checked={checked}
                          disabled={!selectable}
                          data-testid={`${testId}-checkbox-${record.key}`}
                          title={
                            record.status !== "completed"
                              ? t("macro.evalHistory.onlyCompleted")
                              : !selectable
                                ? t("macro.evalHistory.maxSelected")
                                : ""
                          }
                          onClick={() => toggleSelect(record)}
                          className="text-foreground disabled:opacity-40"
                        >
                          {checked ? (
                            <CheckSquare
                              className="h-3.5 w-3.5 text-primary"
                              aria-hidden="true"
                            />
                          ) : (
                            <Square className="h-3.5 w-3.5" aria-hidden="true" />
                          )}
                        </button>
                      </td>
                      {variant === "team" ? (
                        <>
                          <td className="px-3 py-2 text-muted-foreground">
                            {record.createdAt
                              ? new Date(record.createdAt).toLocaleString()
                              : "-"}
                          </td>
                          <td className="px-3 py-2">{record.target || "-"}</td>
                          <td
                            className="max-w-[14rem] truncate px-3 py-2"
                            title={record.question}
                          >
                            {record.question || "-"}
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="px-3 py-2 text-muted-foreground">
                            {record.date || "-"}
                          </td>
                          <td className="px-3 py-2 font-medium text-foreground">
                            {record.roleName}
                          </td>
                          <td className="px-3 py-2 font-mono text-muted-foreground">
                            {record.presetName}
                          </td>
                          <td
                            className="max-w-[12rem] truncate px-3 py-2"
                            title={record.target}
                          >
                            {record.target || "-"}
                          </td>
                        </>
                      )}
                      <td className="px-3 py-2">
                        {t(`swarmStudio.history.status.${record.status}`, {
                          defaultValue: record.status,
                        })}
                      </td>
                      <td
                        className="max-w-[18rem] truncate px-3 py-2 text-muted-foreground"
                        title={record.excerpt}
                      >
                        {record.excerpt || "-"}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          type="button"
                          data-testid={`${testId}-view-${record.key}`}
                          onClick={() => onView(record)}
                          className="rounded-lg border border-border/60 px-2 py-1 text-[11px] text-foreground transition-colors hover:bg-muted"
                        >
                          {t("macro.evalHistory.view")}
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {visible.length === 0 && (
                  <tr>
                    <td
                      colSpan={variant === "team" ? 7 : 8}
                      className="px-3 py-6 text-center text-muted-foreground"
                    >
                      {records.length === 0
                        ? t("macro.evalHistory.empty")
                        : t("macro.evalHistory.noMatch")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
