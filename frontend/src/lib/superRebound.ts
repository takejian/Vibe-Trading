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

export interface IndicatorScoreStub {
  index_code: string;
  total_score: number | null;
  signal: string;
  message: string;
  dimensions: { name: string; weight: number; score: number | null; status: string }[];
  todo: string[];
}

export interface IndicatorDimensionsStub {
  index_code: string;
  dimensions: {
    name: string;
    weight: number;
    indicators: {
      name: string;
      criterion: string;
      value: number | null;
      score: number | null;
      auto_from_finance?: boolean;
    }[];
  }[];
  todo: string;
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

  indicatorScore: (indexCode = "沪深300") =>
    fetchJson<IndicatorScoreStub>(
      `/api/super-rebound/indicator/score?index_code=${encodeURIComponent(indexCode)}`
    ),

  indicatorDimensions: (indexCode = "沪深300") =>
    fetchJson<IndicatorDimensionsStub>(
      `/api/super-rebound/indicator/dimensions?index_code=${encodeURIComponent(indexCode)}`
    ),
};
