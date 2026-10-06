/**
 * Shared loader and hook for macro evaluation records.
 *
 * Evaluations come from two sources and are normalized into one flat shape:
 *  1. Standalone role runs (``kind=role_run``) — one record per run.
 *  2. Per-task summaries inside team swarm runs (``kind=team``, resolved via
 *     run detail) — one record per completed task, so work done by a role
 *     inside a team run is attributable to that role on the board.
 *
 * Run details carry a session-scoped cache and the shared in-flight promise
 * de-duplicates loads across the board / team / role tabs.
 */

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type RoleGroup,
  type SwarmRunDetail,
  type SwarmRunSummary,
} from "@/lib/api";
import { extractLeadConclusion } from "./boardConclusion";

export interface MacroEvalRecord {
  /** Unique key: role runs use run id; team tasks use ``runId#taskId``. */
  key: string;
  runId: string;
  taskId?: string;
  kind: "team" | "role_run";
  /** "preset_name:agent_id"; run-level fallback rows use "__run__" agent. */
  roleRef: string;
  presetName: string;
  agentId: string;
  /** Resolved display name (falls back to agent id / preset name). */
  roleName: string;
  target: string;
  question: string;
  status: string;
  /** YYYY-MM-DD. */
  date: string;
  /** Full ISO creation timestamp (run rows only; "" otherwise). */
  createdAt: string;
  /** Lead conclusion extracted from the (possibly full) report. */
  excerpt: string;
}

export interface MacroEvalData {
  records: MacroEvalRecord[];
  groups: RoleGroup[];
}

const TEAM_RUN_LIMIT = 40;
const ROLE_RUN_LIMIT = 100;
const DETAIL_CONCURRENCY = 6;

/** Run-level rows used for non-completed team runs (not attributable roles). */
export const RUN_LEVEL_AGENT = "__run__";

const detailCache = new Map<string, SwarmRunDetail>();

async function pooledMap<T, R>(
  items: T[],
  limit: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let cursor = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      results[index] = await worker(items[index], index);
    }
  });
  await Promise.all(runners);
  return results;
}

/** Fetch (and cache) one team run detail; returns null on failure. */
async function fetchDetail(summary: SwarmRunSummary): Promise<SwarmRunDetail | null> {
  const cached = detailCache.get(summary.id);
  if (cached) return cached;
  try {
    const detail = await api.getSwarmRun(summary.id);
    detailCache.set(summary.id, detail);
    return detail;
  } catch {
    return null;
  }
}

function roleRefOf(presetName: string, agentId: string): string {
  return `${presetName}:${agentId}`;
}

async function loadMacroEvalData(): Promise<MacroEvalData> {
  const [teamSummaries, roleSummaries, roleRes] = await Promise.all([
    api.listSwarmRuns({ limit: TEAM_RUN_LIMIT }),
    api.listRoleRuns({ limit: ROLE_RUN_LIMIT }),
    api.listRoleGroups(),
  ]);

  // Details for every recent team run: completed tasks inside failed/partial
  // runs (e.g. one stream finished) must still surface as role records.
  const details = await pooledMap(
    teamSummaries,
    DETAIL_CONCURRENCY,
    fetchDetail,
  );

  const nameByRef = new Map<string, string>();
  for (const group of roleRes.groups) {
    for (const role of group.roles) nameByRef.set(role.ref, role.name);
  }

  const records: MacroEvalRecord[] = [];
  const seen = new Set<string>();

  const push = (record: MacroEvalRecord) => {
    if (seen.has(record.key)) return;
    seen.add(record.key);
    records.push(record);
  };

  for (const detail of details) {
    if (!detail) continue;

    for (const task of detail.tasks) {
      if (task.status !== "completed" || !task.summary) continue;
      const ref = roleRefOf(detail.preset_name, task.agent_id);
      push({
        key: `${detail.id}#${task.id}`,
        runId: detail.id,
        taskId: task.id,
        kind: "team",
        roleRef: ref,
        presetName: detail.preset_name,
        agentId: task.agent_id,
        roleName: nameByRef.get(ref) || task.agent_id,
        target: detail.research_target || "",
        question: detail.research_question || "",
        status: "completed",
        date: (
          task.completed_at ||
          detail.completed_at ||
          detail.created_at ||
          ""
        ).slice(0, 10),
        createdAt: "",
        excerpt: extractLeadConclusion(task.summary),
      });
    }

    // One run-level row per team run (mirrors the orchestration history):
    // createdAt / target / question / status / final-report excerpt.
    push({
      key: `${detail.id}#run`,
      runId: detail.id,
      kind: "team",
      roleRef: roleRefOf(detail.preset_name, RUN_LEVEL_AGENT),
      presetName: detail.preset_name,
      agentId: RUN_LEVEL_AGENT,
      roleName: detail.preset_name,
      target: detail.research_target || "",
      question: detail.research_question || "",
      status: detail.status,
      date: (detail.completed_at || detail.created_at || "").slice(0, 10),
      createdAt: detail.created_at || "",
      excerpt: extractLeadConclusion(detail.final_report),
    });
  }

  for (const summary of roleSummaries) {
    const ref = summary.trial_role || "";
    const [presetName, agentId] = ref.split(":");
    push({
      key: summary.id,
      runId: summary.id,
      kind: "role_run",
      roleRef: ref,
      presetName: presetName || summary.preset_name,
      agentId: agentId || "",
      roleName: nameByRef.get(ref) || agentId || summary.preset_name,
      target: summary.research_target || "",
      question: summary.research_question || "",
      status: summary.status,
      date: (summary.completed_at || summary.created_at || "").slice(0, 10),
      createdAt: summary.created_at || "",
      excerpt: extractLeadConclusion(summary.final_report_excerpt),
    });
  }

  records.sort(
    (a, b) => b.date.localeCompare(a.date) || b.key.localeCompare(a.key),
  );
  return { records, groups: roleRes.groups };
}

// ---------------------------------------------------------------------------
// Shared singleton state across mounted hooks
// ---------------------------------------------------------------------------

let cachedData: MacroEvalData | null = null;
let inflight: Promise<MacroEvalData> | null = null;

/** Test-only: drop cached data, in-flight state and detail cache. */
export function resetMacroEvalCache(): void {
  cachedData = null;
  inflight = null;
  detailCache.clear();
}

export interface UseMacroEvalData {
  records: MacroEvalRecord[];
  groups: RoleGroup[];
  loading: boolean;
  error: string;
  reload: () => void;
}

export function useMacroEvalData(): UseMacroEvalData {
  const [data, setData] = useState<MacroEvalData | null>(cachedData);
  const [loading, setLoading] = useState(cachedData === null);
  const [error, setError] = useState("");

  const load = useCallback((force: boolean) => {
    if (!force && cachedData) {
      setData(cachedData);
      setLoading(false);
      setError("");
      return;
    }
    setLoading(true);
    setError("");
    if (force || !inflight) {
      inflight = loadMacroEvalData();
    }
    const promise = inflight;
    promise
      .then((result) => {
        cachedData = result;
        setData(result);
      })
      .catch(() => {
        setError("loadFailed");
        if (inflight === promise) inflight = null;
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    load(false);
  }, [load]);

  return {
    records: data?.records ?? [],
    groups: data?.groups ?? [],
    loading,
    error,
    reload: () => load(true),
  };
}
