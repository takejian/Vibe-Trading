// API client for super-rebound (超跌反弹) finance module.

import { authHeaders } from "./apiAuth";

const BASE = "";

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options?.headers || {}),
    },
    ...options,
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${msg || res.statusText}`);
  }
  return res.json();
}

// --- Types ---

export interface MarginRatioHistoryPoint {
  date: string;
  ratio: number;
}

export interface MarginRatioData {
  trade_date: string;
  margin_ratio: number;
  margin_ratio_pct: string;
  six_year_percentile: number;
  six_year_percentile_display: string;
  ten_year_percentile: number;
  ten_year_percentile_display: string;
  vs_range_high_pct: number | null;
  vs_range_high_display: string | null;
  range_high: number | null;
  range_high_display: string | null;
  range_high_date: string | null;
  range_low: number | null;
  range_low_display: string | null;
  range_low_date: string | null;
  sample_count: number;
  data_range_start: string;
  data_range_end: string;
  warning_line: number;
  history_series: MarginRatioHistoryPoint[];
  source?: string | null;
  updated_at: string;
}

export interface EtfMonitorLatestStrongestEtf {
  etf_code: string;
  etf_name: string;
  index_group: string;
  net_flow_bn: number;
}

export interface EtfMonitorAvgLargestEtf {
  etf_code: string;
  etf_name: string;
  index_group: string;
  avg_net_flow_bn: number;
}

export interface EtfMonitorSummary {
  latest_total_net_flow_bn: number;
  latest_day_net_flow_bn: number;
  latest_day: string | null;
  range_high_net_flow_bn: number;
  range_high_net_flow_date: string | null;
  latest_strongest_etf: EtfMonitorLatestStrongestEtf | null;
  avg_largest_etf: EtfMonitorAvgLargestEtf | null;
  monitor_days: number;
  sample_etf_count: number;
  date_range_start: string;
  date_range_end: string;
}

export interface EtfMonitorDailyRow {
  trade_date: string;
  values: {
    per_group: Record<string, number> & { __total__: number };
    per_etf: Record<string, number>;
    total: number;
  };
  is_latest: boolean;
  is_cumulative?: boolean;
}

export interface EtfMonitorDetail {
  date_range_start: string;
  date_range_end: string;
  groups: string[];
  etf_codes_by_group: Record<string, string[]>;
  daily_rows: EtfMonitorDailyRow[];
  cumulative_row: EtfMonitorDailyRow;
  latest_date: string | null;
  note?: string;
}

export interface RefreshResult {
  success: boolean;
  message: string;
  margin_rows: number;
  etf_rows: number;
  fetched_at?: string | null;
}

// --- New indicator / daily status / prompt / schedule types ---

export type CompareOperator = ">" | ">=" | "<" | "<=" | "==" | "!=" | "定性";

export interface IndicatorDef {
  id: number;
  dimension: string;
  indicator_name: string;
  threshold_value: number | null;
  compare_operator: CompareOperator;
  judgment_criteria: string | null;
  weight: number;
  sort_order: number;
  is_active: number;
}

export interface IndicatorPrompt {
  id: number;
  prompt_type: "oversold_indicator" | "volume_price_chip" | "rebound_tracking" | string;
  prompt_name: string;
  prompt_content: string;
  updated_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface IndicatorEvalResult {
  trade_date: string;
  index_code: string;
  dimension_scores: Record<string, number | null>;
  total_score: number | null;
  signal_light: "green" | "yellow" | "red" | "pending";
  indicators: {
    id: number;
    dimension: string;
    indicator_name: string;
    threshold_value: number | null;
    compare_operator: CompareOperator;
    judgment_criteria: string | null;
    weight: number;
    indicator_value: string | null | undefined;
    judgment_result: number | null;
  }[];
  error?: string;
  message?: string;
}

export interface DailyStatusRow {
  id: number;
  trade_date: string;
  index_code: string;
  odds_score: number | null;
  technical_score: number | null;
  capital_score: number | null;
  sentiment_score: number | null;
  external_score: number | null;
  total_score: number | null;
  signal_light: string | null;
  volume_price_chip: string | null;
  rebound_tracking: string | null;
  is_latest?: boolean;
}

export interface DailyStatusListResponse {
  index_code: string;
  date_range_start: string;
  date_range_end: string;
  daily_rows: DailyStatusRow[];
  indicator_defs: IndicatorDef[];
  prompts: IndicatorPrompt[];
}

export interface ScheduleConfig {
  id: number;
  task_name: string;
  is_enabled: number;
  run_time: string;
  timezone: string;
  updated_by?: string | null;
}

// --- API client ---

export const superReboundApi = {
  marginRatio: () =>
    fetchJson<MarginRatioData>("/api/super-rebound/finance/margin-ratio"),

  etfMonitor: (startDate?: string, endDate?: string) => {
    const params = new URLSearchParams();
    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);
    const qs = params.toString();
    return fetchJson<EtfMonitorSummary>(
      `/api/super-rebound/finance/etf-monitor${qs ? `?${qs}` : ""}`
    );
  },

  etfMonitorDetail: (startDate?: string, endDate?: string) => {
    const params = new URLSearchParams();
    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);
    const qs = params.toString();
    return fetchJson<EtfMonitorDetail>(
      `/api/super-rebound/finance/etf-monitor-detail${qs ? `?${qs}` : ""}`
    );
  },

  refreshNeeded: () =>
    fetchJson<{ needed: boolean; reason?: string; latest?: string }>(
      "/api/super-rebound/finance/refresh-needed"
    ),

  refresh: () =>
    fetchJson<RefreshResult>("/api/super-rebound/finance/refresh", { method: "POST" }),

  // --- Indicator defs ---
  indicatorDefs: () =>
    fetchJson<{ indicator_defs: IndicatorDef[] }>("/api/super-rebound/indicator/defs"),

  upsertIndicatorDef: (def: Partial<IndicatorDef>) =>
    fetchJson<{ created: boolean; indicator: IndicatorDef }>(
      "/api/super-rebound/indicator/defs",
      { method: "POST", body: JSON.stringify(def) }
    ),

  deleteIndicatorDef: (defId: number) =>
    fetchJson<{ deleted: boolean; def_id: number }>(
      `/api/super-rebound/indicator/defs/${defId}`, { method: "DELETE" }
    ),

  // --- Prompts ---
  prompts: () =>
    fetchJson<{ prompts: IndicatorPrompt[] }>("/api/super-rebound/indicator/prompts"),

  upsertPrompt: (prompt: Partial<IndicatorPrompt>) =>
    fetchJson<{ created: boolean; prompt_type: string }>(
      "/api/super-rebound/indicator/prompts",
      { method: "PUT", body: JSON.stringify(prompt) }
    ),

  // --- Eval (manual trigger) ---
  evalIndicator: (indexCode = "沪深300") =>
    fetchJson<IndicatorEvalResult>(
      `/api/super-rebound/indicator/eval?index_code=${encodeURIComponent(indexCode)}`,
      { method: "POST" }
    ),

  // --- Daily status ---
  dailyStatusList: (opts?: {
    startDate?: string;
    endDate?: string;
    indexCode?: string;
    days?: number;
  }) => {
    const params = new URLSearchParams();
    if (opts?.startDate) params.set("start_date", opts.startDate);
    if (opts?.endDate) params.set("end_date", opts.endDate);
    if (opts?.indexCode) params.set("index_code", opts.indexCode);
    if (opts?.days) params.set("days", String(opts.days));
    const qs = params.toString();
    return fetchJson<DailyStatusListResponse>(
      `/api/super-rebound/daily-status/list${qs ? `?${qs}` : ""}`
    );
  },

  refreshVolumePriceChip: (indexCode = "沪深300") =>
    fetchJson<{ trade_date: string; result: { result: string; reason: string } }>(
      `/api/super-rebound/daily-status/volume-price-chip/refresh?index_code=${encodeURIComponent(indexCode)}`,
      { method: "POST" }
    ),

  refreshReboundTracking: (indexCode = "沪深300") =>
    fetchJson<{ trade_date: string; result: { result: string; reason: string } }>(
      `/api/super-rebound/daily-status/rebound-tracking/refresh?index_code=${encodeURIComponent(indexCode)}`,
      { method: "POST" }
    ),

  // --- Schedule ---
  schedule: (taskName = "daily_status_auto") =>
    fetchJson<{ schedule: ScheduleConfig }>(
      `/api/super-rebound/daily-status/schedule?task_name=${encodeURIComponent(taskName)}`
    ),

  toggleSchedule: (taskName: string, isEnabled: boolean) =>
    fetchJson<{ task_name: string; is_enabled: boolean }>(
      "/api/super-rebound/daily-status/schedule",
      { method: "PUT", body: JSON.stringify({ task_name: taskName, is_enabled: isEnabled }) }
    ),

  // --- Schema ensure ---
  ensureSchema: () =>
    fetchJson<{ schema: string; seeded: Record<string, number> }>(
      "/api/super-rebound/schema/ensure", { method: "POST" }
    ),
};
