import i18n from "@/i18n";
import { authHeaders, withAuthTicket } from "@/lib/apiAuth";
import type {
  OptionsChainResponse,
  OptionsPayoffRequest,
  OptionsPayoffResponse,
} from "@/lib/options";
import type {
  CustomSpecPayload,
  SwarmPresetDetail,
} from "@/lib/swarmGraph";

const BASE = "";

// --- Macro analysis types (contract with src/api/macro_routes.py) ---

export interface MacroPrompt {
  code: "a" | "b" | "c" | string;
  name: string;
  prompt_text: string;
  enabled: boolean;
  sort_order: number;
  /** True for prompt a (the only editable structure this iteration). */
  editable: boolean;
  /** True when the current principal holds settings-write authorization. */
  can_edit: boolean;
  orchestration_config?: string | null;
  update_time?: string | null;
}

export interface MacroJudgment {
  id?: number | null;
  economy: string;
  statistics_date: string; // YYYY-MM
  current_cycle: string;
  judgment_result: string;
  dimension_check: string;
  meso_verify: string;
  history_cycle_anchor: string;
  judgment_confidence: string;
  core_support: string;
  core_risk: string;
  extended_remark: string;
  create_time?: string | null;
}

export interface MacroReadiness {
  ready: boolean;
  latest_month: string;
  reason?: string | null;
}

export interface MacroJudgeRequestBody {
  economy: string;
  statistics_date?: string;
  supplement?: string;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  /** Full structured error detail when the backend sends an object body
   *  (e.g. the macro 422 envelope carrying a `readiness` probe result). */
  payload?: { readiness?: MacroReadiness; [key: string]: unknown };

  constructor(
    message: string,
    status: number,
    code?: string,
    payload?: { readiness?: MacroReadiness; [key: string]: unknown },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

const AUTH_REQUIRED_MESSAGE_KEY = "agent.authRequired";

function getAuthRequiredMessage(): string {
  return i18n.t(AUTH_REQUIRED_MESSAGE_KEY as never);
}

// Keep the existing string export compatible with consumers while updating its
// live ES-module binding whenever the active locale changes.
export let AUTH_REQUIRED_MESSAGE = getAuthRequiredMessage();
i18n.on("languageChanged", () => {
  AUTH_REQUIRED_MESSAGE = getAuthRequiredMessage();
});

export function isAuthRequiredError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

export interface CorrelationResponse {
  labels: string[];
  matrix: number[][];
}

export interface RegimeEpisode {
  start: string;
  end: string | null;
}

export interface CorrelationRegimeResponse {
  labels: string[];
  dates: string[];
  density: (number | null)[];
  smoothed: (number | null)[];
  fused: number[];
  episodes: RegimeEpisode[];
  params: {
    days: number;
    corr_window: number;
    edge_threshold: number;
    smooth_window: number;
    enter_threshold: number;
    exit_threshold: number;
  };
}

export interface PortfolioPosition {
  source_id?: string;
  profile_id?: string;
  source_label?: string;
  broker: string;
  symbol: string;
  name: string;
  asset_type: string;
  market: string;
  currency: string;
  quantity: number;
  cost_price?: number | null;
  market_price?: number | null;
  market_value_usd: number;
  market_value_cny: number;
  unrealized_pnl_usd?: number | null;
  priced: boolean;
  updated_at: string;
  pricing_basis?: string;
  price_error?: string;
}

export interface PortfolioConnectorCompatibility {
  level: "native" | "contract_tested" | "experimental";
  contract_version: number;
  asset_scope: string;
  note: string;
}

/**
 * One portfolio source as of the last refresh.
 *
 * A source that could not be read has `status === "error"`, no totals, and
 * contributes nothing to the snapshot totals; `last_success_at` (when present)
 * is the timestamp of the last read that did succeed, and is only ever shown
 * as history — never as a current valuation.
 */
export interface PortfolioAccount {
  source_id?: string;
  profile_id?: string;
  label?: string;
  broker: string;
  status: "ok" | "error";
  last_success_at?: string;
  total_usd?: number | null;
  total_cny?: number | null;
  total_display?: number | null;
  priced_value_usd?: number;
  cash_usd?: number;
  unpriced_or_other_usd?: number;
  position_count?: number;
  priced_position_count?: number;
  unpriced_position_count?: number;
  error_code?: string;
  error?: string;
  failure_kind?: "authorization" | "transient";
  reconnect_required?: boolean;
  auth?: {
    method: string;
    renewal: "automatic" | "session" | "provider_managed";
    readonly: boolean;
    detail: string;
  };
  portfolio_compatibility?: PortfolioConnectorCompatibility;
}

export interface PortfolioSnapshot {
  snapshot_id: string;
  created_at: string;
  /** False whenever any enabled source did not reach `status === "ok"`. */
  complete: boolean;
  display_currency?: string;
  totals: { usd: number; cny: number; display?: number };
  valuation?: {
    priced_usd: number;
    cash_usd: number;
    unpriced_or_other_usd: number;
    identified_coverage: number;
  };
  fx: { usd_cny: number; usd_hkd: number; rates?: Record<string, number>; fetched_at: string; stale: boolean };
  accounts: PortfolioAccount[];
  positions: PortfolioPosition[];
  combined_holdings?: Array<{
    symbol: string;
    market_value_usd: number;
    asset_type?: string;
    brokers?: string[];
    unrealized_pnl_usd?: number;
  }>;
  /** Backend-authored English notes; rendered verbatim, not translated. */
  warnings: string[];
}

export interface PortfolioHistoryPoint {
  id: string;
  created_at: string;
  complete: number;
  total_usd: string;
  total_cny: string;
}

export interface PortfolioRefreshState {
  running: boolean;
  current: string | null;
  sources?: Record<string, { status: "idle" | "pending" | "refreshing" | "ok" | "error"; error?: string | null }>;
  brokers?: Record<string, { status: "idle" | "pending" | "refreshing" | "ok" | "error"; error?: string | null }>;
}

export interface PortfolioReconnectState {
  running: boolean;
  source_id: string | null;
  status: "idle" | "authorizing" | "authorized" | "error" | "timeout";
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface PortfolioSourceSettings {
  connection_id: string;
  label: string;
  enabled: boolean;
  order: number;
  include_cash: boolean;
}

export interface PortfolioSettings {
  display_currency: string;
  sources: PortfolioSourceSettings[];
}

export interface PortfolioSourceCatalogItem {
  id: string;
  connection_id: string;
  profile_id: string;
  connector: string;
  label: string;
  environment: "paper" | "live";
  transport: "local_tws" | "remote_mcp" | "broker_sdk" | "local_plugin";
  capabilities: string[];
  readonly: boolean;
  notes: string;
  selected: boolean;
  source_id?: string | null;
  supports_reconnect: boolean;
  credential_fields: CredentialField[];
  credential_status: Record<string, boolean>;
  credentials_configured: boolean;
  portfolio_compatibility: PortfolioConnectorCompatibility;
}

export interface CredentialField {
  name: string;
  label: string;
  secret: boolean;
  required: boolean;
}

export interface ConnectorOnboarding {
  schema_version: number;
  auth_type: string;
  credential_fields: CredentialField[];
  dependency: string | null;
  install_command: string | null;
  test_operation: string;
  setup_hint: string;
  secret_storage: "os_keyring" | null;
}

export interface LocalConnection {
  id: string;
  profile_id: string;
  label: string;
  /** Broker account the reads are scoped to; empty until the user selects one. */
  account_ref: string;
  /** True when this connection reads nothing until an account is selected. */
  account_selection_required: boolean;
  connector: string;
  environment: "paper" | "live";
  transport: "local_tws" | "remote_mcp" | "broker_sdk" | "local_plugin";
  readonly: boolean;
  capabilities: string[];
  supports_reconnect: boolean;
  credential_fields: CredentialField[];
  credential_status: Record<string, boolean>;
  credentials_configured: boolean;
  onboarding?: ConnectorOnboarding;
  portfolio_compatibility: PortfolioConnectorCompatibility;
}

export interface ReadonlyConnectionProfile {
  id: string;
  connector: string;
  label: string;
  environment: "paper" | "live";
  transport: "local_tws" | "remote_mcp" | "broker_sdk" | "local_plugin";
  capabilities: string[];
  readonly: boolean;
  notes: string;
  local_plugin: boolean;
  credential_fields: CredentialField[];
  onboarding?: ConnectorOnboarding;
  supports_reconnect: boolean;
  account_selection_required: boolean;
  portfolio_compatibility: PortfolioConnectorCompatibility;
  invalid_plugin?: boolean;
  directory?: string;
  error?: string;
}

/** One account a broker login can reach, as the backend maps it for a picker. */
export interface BrokerAccountChoice {
  account_ref: string;
  label: string;
  is_default: boolean;
  agentic_allowed: boolean;
  deactivated: boolean;
}

export interface ConnectionsResponse {
  status: string;
  connections: LocalConnection[];
  profiles: ReadonlyConnectionProfile[];
  plugin_directory: string;
}

export interface PortfolioSettingsResponse {
  status: string;
  settings: PortfolioSettings;
  catalog: PortfolioSourceCatalogItem[];
}

async function errorFromResponse(res: Response): Promise<ApiError> {
  let detail = `HTTP ${res.status}`;
  let code: string | undefined;
  let payload: ApiError["payload"];
  try {
    const body = await res.json();
    // Options endpoints report errors under an `error` key
    // ({status:"error", error} / {ok:false, error}) rather than detail/message.
    const raw = body.detail ?? body.message ?? body.error;
    if (typeof raw === "string" && raw) {
      detail = raw;
    } else if (raw && typeof raw === "object") {
      const structured = raw as {
        code?: unknown;
        message?: unknown;
        readiness?: unknown;
        [key: string]: unknown;
      };
      if (typeof structured.code === "string" && structured.code) code = structured.code;
      if (typeof structured.message === "string" && structured.message) detail = structured.message;
      else if (code) detail = code;
      if (structured.readiness && typeof structured.readiness === "object") {
        payload = { readiness: structured.readiness as MacroReadiness };
      }
      // Generic structured envelope fields, e.g. the watchlist 412 Chanlun
      // gate carries an `items` list of missing K-line levels.
      if (Array.isArray(structured.items)) {
        payload = { ...(payload ?? {}), items: structured.items };
      }
    }
  } catch { /* ignore */ }
  if (res.status === 401 || res.status === 403) {
    detail = getAuthRequiredMessage();
  }
  return new ApiError(detail, res.status, code, payload);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { headers, body, ...rest } = options ?? {};
  const mergedHeaders: Record<string, string> = { "Content-Type": "application/json", ...authHeaders() };
  if (headers) {
    new Headers(headers).forEach((value, key) => {
      mergedHeaders[key] = value;
    });
  }
  // Let the browser set the multipart boundary for FormData uploads.
  if (typeof FormData !== "undefined" && body instanceof FormData) {
    delete mergedHeaders["Content-Type"];
  }
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    body: body as BodyInit | null | undefined,
    headers: mergedHeaders,
  });
  if (!res.ok) {
    throw await errorFromResponse(res);
  }
  const text = await res.text();
  if (!text) return {} as T;

  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    const preview = text.slice(0, 80).replace(/\s+/g, " ");
    throw new ApiError(
      `Expected JSON from ${path}, got ${contentType || "unknown content type"}: ${preview}`,
      res.status,
    );
  }

  return JSON.parse(text) as T;
}

export interface UploadResult {
  status: string;
  file_path: string;
  filename: string;
}

async function uploadFile(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/upload`, { method: "POST", headers: authHeaders(), body: form });
  if (!res.ok) {
    throw await errorFromResponse(res);
  }
  return res.json();
}

function appendQueryParam(url: string, key: string, value: string): string {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}${encodeURIComponent(key)}=${encodeURIComponent(value)}`;
}

export const api = {
  uploadFile,
  getCorrelation: (codes: string, days: number, method: "pearson" | "spearman") =>
    request<CorrelationResponse>(
      `/correlation?codes=${encodeURIComponent(codes)}&days=${encodeURIComponent(String(days))}&method=${encodeURIComponent(method)}`,
    ),
  getCorrelationRegime: (codes: string, days: number) =>
    request<CorrelationRegimeResponse>(
      `/correlation/regime?codes=${encodeURIComponent(codes)}&days=${encodeURIComponent(String(days))}`,
    ),
  getPortfolio: () => request<{ status: string; snapshot: PortfolioSnapshot | null }>("/api/portfolio"),
  refreshPortfolio: () => request<{ status: string; snapshot: PortfolioSnapshot }>("/api/portfolio/refresh", { method: "POST" }),
  getPortfolioRefreshStatus: () => request<{ status: string; refresh: PortfolioRefreshState }>("/api/portfolio/refresh-status"),
  reconnectPortfolioSource: (sourceId: string) =>
    request<{ status: string; reconnect: PortfolioReconnectState }>(`/api/portfolio/sources/${encodeURIComponent(sourceId)}/reconnect`, { method: "POST" }),
  getPortfolioReconnectStatus: () =>
    request<{ status: string; reconnect: PortfolioReconnectState }>("/api/portfolio/reconnect-status"),
  getPortfolioSettings: () => request<PortfolioSettingsResponse>("/api/portfolio/settings"),
  updatePortfolioSettings: (settings: PortfolioSettings) =>
    request<PortfolioSettingsResponse>("/api/portfolio/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  getConnections: () => request<ConnectionsResponse>("/api/connections"),
  createConnection: (payload: { id: string; profile_id: string; label: string }) =>
    request<{ status: string; connection: LocalConnection }>("/api/connections", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  saveConnectionCredentials: (connectionId: string, values: Record<string, string>) =>
    request<{ status: string; credential_status: Record<string, boolean> }>(
      `/api/connections/${encodeURIComponent(connectionId)}/credentials`,
      { method: "POST", body: JSON.stringify({ values }) },
    ),
  checkConnection: (connectionId: string) =>
    request<{ status: string; connection_id: string; report: Record<string, unknown> }>(
      `/api/connections/${encodeURIComponent(connectionId)}/check`,
      { method: "POST" },
    ),
  getConnectionAccounts: (connectionId: string) =>
    request<{ status: string; connection_id: string; account_ref: string; accounts: BrokerAccountChoice[] }>(
      `/api/connections/${encodeURIComponent(connectionId)}/accounts`,
    ),
  selectConnectionAccount: (connectionId: string, accountRef: string) =>
    request<{ status: string; connection: LocalConnection }>(
      `/api/connections/${encodeURIComponent(connectionId)}/account`,
      { method: "PUT", body: JSON.stringify({ account_ref: accountRef }) },
    ),
  deleteConnection: (connectionId: string) =>
    request<{ status: string; deleted: string }>(
      `/api/connections/${encodeURIComponent(connectionId)}`,
      { method: "DELETE" },
    ),
  getPortfolioHistory: (limit = 180) =>
    request<{ status: string; history: PortfolioHistoryPoint[] }>(`/api/portfolio/history?limit=${encodeURIComponent(String(limit))}`),
  downloadPortfolioCsv: async () => {
    const response = await fetch(`${BASE}/api/portfolio/export.csv`, { headers: authHeaders() });
    if (!response.ok) throw await errorFromResponse(response);
    return response.blob();
  },
  listRuns: (limit?: number) => request<RunListItem[]>(`/runs${limit ? `?limit=${encodeURIComponent(String(limit))}` : ""}`),
  getRun: (id: string, params: RunDetailParams = {}) => {
    const q = new URLSearchParams();
    if (params.chart_payload) q.set("chart_payload", params.chart_payload);
    if (params.chart_symbol) q.set("chart_symbol", params.chart_symbol);
    const qs = q.toString();
    return request<RunData>(`/runs/${id}${qs ? `?${qs}` : ""}`);
  },
  getRunCode: (id: string) => request<Record<string, string>>(`/runs/${id}/code`),
  getRunFactor: (id: string) => request<FactorReportPayload>(`/runs/${id}/factor`),
  getRunAttribution: (id: string) => request<AttributionResponse>(`/runs/${encodeURIComponent(id)}/attribution`),
  getRunPine: (id: string) => request<PineScriptResult>(`/runs/${id}/pine`),
  listSessions: () => request<SessionItem[]>("/sessions"),
  createSession: (title?: string) => request<SessionItem>("/sessions", { method: "POST", body: JSON.stringify({ title: title || "" }) }),
  deleteSession: (sid: string) => request<{ status: string }>(`/sessions/${sid}`, { method: "DELETE" }),
  renameSession: (sid: string, title: string) => request<{ status: string }>(`/sessions/${sid}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  // Codex-style LLM summary title from the first exchange; backend refuses to
  // overwrite a manual rename, so this is safe to fire-and-forget.
  autoTitleSession: (sid: string) => request<{ status: string; title: string }>(`/sessions/${sid}/title/auto`, { method: "POST" }),
  // Scheduled research: cadence + timezone are stored as authored (local
  // wall-clock cron + IANA key), so list rows render without any UTC math.
  listScheduledRuns: (signal?: AbortSignal) => request<ScheduledRun[]>("/scheduled-runs", { signal }),
  createScheduledRun: (body: CreateScheduledRunRequest) =>
    request<ScheduledRun>("/scheduled-runs", { method: "POST", body: JSON.stringify(body) }),
  deleteScheduledRun: (id: string) =>
    request<void>(`/scheduled-runs/${encodeURIComponent(id)}`, { method: "DELETE" }),
  commitScheduledResearchProposal: (proposalId: string) =>
    request<ScheduledResearchProposal>(
      `/scheduled-runs/proposals/${encodeURIComponent(proposalId)}/commit`,
      { method: "POST" },
    ),
  discardScheduledResearchProposal: (proposalId: string) =>
    request<ScheduledResearchProposal>(
      `/scheduled-runs/proposals/${encodeURIComponent(proposalId)}/discard`,
      { method: "POST" },
    ),
  sendMessage: (sid: string, content: string) => request<{ message_id: string; attempt_id: string }>(`/sessions/${sid}/messages`, { method: "POST", body: JSON.stringify({ content }) }),
  cancelSession: (sid: string) => request<{ status: string }>(`/sessions/${sid}/cancel`, { method: "POST" }),
  getSessionMessages: (sid: string) => request<MessageItem[]>(`/sessions/${sid}/messages`),
  createGoal: (sid: string, body: CreateGoalRequest) =>
    request<GoalSnapshot>(`/sessions/${sid}/goal`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getGoal: (sid: string) => request<GoalSnapshot>(`/sessions/${sid}/goal`),
  updateGoal: (sid: string, body: UpdateGoalRequest) =>
    request<UpdateGoalResponse>(`/sessions/${sid}/goal`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  addGoalEvidence: (sid: string, body: AddGoalEvidenceRequest) =>
    request<AddGoalEvidenceResponse>(`/sessions/${sid}/goal/evidence`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateGoalStatus: (sid: string, body: UpdateGoalStatusRequest) =>
    request<UpdateGoalStatusResponse>(`/sessions/${sid}/goal/status`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  // Returns the bare stream URL (no auth in the query string). The SSE ticket
  // is minted per connect/reconnect inside useSSE (tickets are single-use, so
  // baking one into a cached URL would break reconnection).
  sseUrl: (sid: string, options?: { replay?: "active" }) => {
    let url = `${BASE}/sessions/${sid}/events`;
    if (options?.replay) url = appendQueryParam(url, "replay", options.replay);
    return url;
  },

  // Swarm API
  listSwarmPresets: () => request<SwarmPreset[]>("/swarm/presets"),
  getSwarmPresetDetail: (name: string) =>
    request<SwarmPresetDetail>(`/swarm/presets/${encodeURIComponent(name)}/detail`),
  createSwarmRun: (
    preset_name: string,
    user_vars: Record<string, string>,
    custom?: CustomSpecPayload,
    skillTrial?: SkillTrialRequest,
  ) =>
    request<{ id: string; status: string; kind?: string; trial_skill?: string | null }>(
      "/swarm/runs",
      {
        method: "POST",
        body: JSON.stringify({
          preset_name,
          user_vars,
          ...(custom ? { custom } : {}),
          ...(skillTrial ? { skill_trial: skillTrial } : {}),
        }),
      },
    ),
  listSwarmRuns: (options?: SwarmRunListOptions) => {
    const params = new URLSearchParams();
    if (options?.kind && options.kind !== "team") params.set("kind", options.kind);
    if (options?.target) params.set("target", options.target);
    if (options?.from) params.set("from", options.from);
    if (options?.to) params.set("to", options.to);
    if (options?.skillName) params.set("skill_name", options.skillName);
    if (options?.limit) params.set("limit", String(options.limit));
    const query = params.toString();
    return request<SwarmRunSummary[]>(`/swarm/runs${query ? `?${query}` : ""}`);
  },
  getSwarmRun: (id: string) => request<SwarmRunDetail>(`/swarm/runs/${id}`),
  swarmSseUrl: (id: string) => withAuthTicket(`${BASE}/swarm/runs/${id}/events`),
  cancelSwarmRun: (id: string) =>
    request<{ status: string }>(`/swarm/runs/${id}/cancel`, { method: "POST" }),
  retrySwarmRun: (id: string) =>
    request<{ id: string; status: string; preset_name: string }>(`/swarm/runs/${id}/retry`, { method: "POST" }),

  // Personal custom teams ("my teams")
  listCustomTeams: () => request<CustomTeamSummary[]>("/swarm/custom-teams"),
  getCustomTeam: (id: string) =>
    request<CustomTeam>(`/swarm/custom-teams/${encodeURIComponent(id)}`),
  createCustomTeam: (body: CustomTeamRequest) =>
    request<{ id: string; name: string; updated_at: string }>("/swarm/custom-teams", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateCustomTeam: (id: string, body: CustomTeamRequest) =>
    request<{ id: string; name: string; updated_at: string }>(
      `/swarm/custom-teams/${encodeURIComponent(id)}`,
      { method: "PUT", body: JSON.stringify(body) },
    ),
  deleteCustomTeam: (id: string) =>
    request<{ status: string }>(`/swarm/custom-teams/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  // Skill Square
  getSkillCapabilities: () => request<SkillCapabilities>("/swarm/skills/capabilities"),
  getSkillCatalog: () =>
    request<{ skills: SkillCatalogEntry[] }>("/swarm/skills/catalog"),
  createSkillTrial: (body: SkillTrialRequest) =>
    request<{ id: string; status: string; kind: string; trial_skill: string }>(
      "/swarm/skill-trials",
      { method: "POST", body: JSON.stringify(body) },
    ),
  listSkillTrials: (options?: Omit<SwarmRunListOptions, "kind">) => {
    const params = new URLSearchParams();
    if (options?.target) params.set("target", options.target);
    if (options?.from) params.set("from", options.from);
    if (options?.to) params.set("to", options.to);
    if (options?.skillName) params.set("skill_name", options.skillName);
    if (options?.scope) params.set("scope", options.scope);
    if (options?.limit) params.set("limit", String(options.limit));
    const query = params.toString();
    return request<SwarmRunSummary[]>(
      `/swarm/skill-trials${query ? `?${query}` : ""}`,
    );
  },
  getSkillDetail: (skillRef: string) =>
    request<SkillProfile>(
      `/swarm/skills/${encodeURIComponent(skillRef)}/detail`,
    ),
  createCustomSkill: (body: CustomSkillRequest) =>
    request<{
      id: string;
      name: string;
      approved: boolean;
      derived_from?: string | null;
      updated_at: string;
    }>("/swarm/skills/custom", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateCustomSkill: (skillId: string, body: CustomSkillRequest) =>
    request<{ id: string; name: string; approved: boolean; updated_at: string }>(
      `/swarm/skills/custom/${encodeURIComponent(skillId)}`,
      { method: "PUT", body: JSON.stringify(body) },
    ),
  deleteCustomSkill: (skillId: string) =>
    request<{ status: string }>(
      `/swarm/skills/custom/${encodeURIComponent(skillId)}`,
      { method: "DELETE" },
    ),
  approveCustomSkill: (skillId: string) =>
    request<{ id: string; approved: boolean; approved_at?: string | null }>(
      `/swarm/skills/custom/${encodeURIComponent(skillId)}/approve`,
      { method: "POST" },
    ),
  unapproveCustomSkill: (skillId: string) =>
    request<{ id: string; approved: boolean }>(
      `/swarm/skills/custom/${encodeURIComponent(skillId)}/unapprove`,
      { method: "POST" },
    ),
  importPersonalSkillPackage: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ installed: { id: string; name: string }[] }>(
      "/swarm/skills/import-personal",
      { method: "POST", body: form },
    );
  },
  importSkillPackage: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<SkillImportResult>("/swarm/skills/import", {
      method: "POST",
      body: form,
    });
  },
  syncSkills: () =>
    request<SkillSyncResult>("/swarm/skills/sync", { method: "POST" }),

  // Role Square
  listRoleGroups: (q?: string) =>
    request<{ groups: RoleGroup[]; tool_catalog?: string[] }>(
      `/swarm/roles${q ? `?q=${encodeURIComponent(q)}` : ""}`,
    ),
  getRoleDetail: (roleRef: string) =>
    request<RoleProfile>(
      `/swarm/roles/${encodeURIComponent(roleRef)}/detail`,
    ),
  createCustomRole: (body: CustomRoleRequest) =>
    request<{ id: string; name: string; approved: boolean; updated_at: string }>(
      "/swarm/roles",
      { method: "POST", body: JSON.stringify(body) },
    ),
  updateCustomRole: (roleId: string, body: CustomRoleRequest) =>
    request<{ id: string; name: string; approved: boolean; updated_at: string }>(
      `/swarm/roles/${encodeURIComponent(roleId)}`,
      { method: "PUT", body: JSON.stringify(body) },
    ),
  deleteCustomRole: (roleId: string) =>
    request<{ status: string }>(
      `/swarm/roles/${encodeURIComponent(roleId)}`,
      { method: "DELETE" },
    ),
  approveRole: (roleId: string) =>
    request<{ id: string; approved: boolean; approved_at?: string }>(
      `/swarm/roles/${encodeURIComponent(roleId)}/approve`,
      { method: "POST" },
    ),
  unapproveRole: (roleId: string) =>
    request<{ id: string; approved: boolean }>(
      `/swarm/roles/${encodeURIComponent(roleId)}/unapprove`,
      { method: "POST" },
    ),
  createRoleRun: (body: RoleRunRequest) =>
    request<{ id: string; status: string; kind: string; trial_role: string }>(
      "/swarm/role-runs",
      { method: "POST", body: JSON.stringify(body) },
    ),
  listRoleRuns: (options?: RoleRunListOptions) => {
    const params = new URLSearchParams();
    if (options?.roleRef) params.set("role_ref", options.roleRef);
    if (options?.target) params.set("target", options.target);
    if (options?.from) params.set("from", options.from);
    if (options?.to) params.set("to", options.to);
    if (options?.scope) params.set("scope", options.scope);
    if (options?.limit) params.set("limit", String(options.limit));
    const query = params.toString();
    return request<SwarmRunSummary[]>(
      `/swarm/role-runs${query ? `?${query}` : ""}`,
    );
  },
  getLLMSettings: () => request<LLMSettings>("/settings/llm"),
  updateLLMSettings: (settings: UpdateLLMSettingsRequest) =>
    request<LLMSettings>("/settings/llm", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  listLLMModels: (settings: ListLLMModelsRequest) =>
    request<LLMModelsResponse>("/settings/llm/models", {
      method: "POST",
      body: JSON.stringify(settings),
    }),
  getDataSourceSettings: () => request<DataSourceSettings>("/settings/data-sources"),
  updateDataSourceSettings: (settings: UpdateDataSourceSettingsRequest) =>
    request<DataSourceSettings>("/settings/data-sources", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  getChannelStatus: () => request<ChannelRuntimeStatus>("/channels/status"),
  startChannels: () => request<ChannelRuntimeActionResponse>("/channels/start", { method: "POST" }),
  stopChannels: () => request<ChannelRuntimeActionResponse>("/channels/stop", { method: "POST" }),
  runChannelPairingCommand: (body: ChannelPairingCommandRequest) =>
    request<ChannelPairingCommandResponse>("/channels/pairing/command", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  // Web-based IM channel configuration; non-2xx (400/422) throws ApiError.
  getChannelsConfig: () => request<ChannelsConfigResponse>("/channels/config"),
  putChannelConfig: (name: string, body: ChannelPutBody) =>
    request<ChannelPutResult>(`/channels/config/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  testChannel: (name: string, body?: ChannelTestBody) =>
    request<ChannelTestResult>(`/channels/${encodeURIComponent(name)}/test`, {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),
  // Alpha Zoo API
  listAlphas: (params: AlphaListParams = {}) => {
    const q = new URLSearchParams();
    if (params.zoo) q.set("zoo", params.zoo);
    if (params.theme) q.set("theme", params.theme);
    if (params.universe) q.set("universe", params.universe);
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<AlphaListResponse>(`/alpha/list${qs ? `?${qs}` : ""}`);
  },
  getAlpha: (alphaId: string) =>
    request<AlphaDetailResponse>(`/alpha/${encodeURIComponent(alphaId)}`),
  createAlphaBench: (body: AlphaBenchRequest) =>
    request<{ status: string; job_id: string }>("/alpha/bench", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  alphaBenchStreamUrl: (jobId: string) =>
    withAuthTicket(`${BASE}/alpha/bench/${encodeURIComponent(jobId)}/stream`),
  createAlphaCompare: (body: AlphaCompareRequest) =>
    request<{ status: string; job_id: string }>("/alpha/compare", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  alphaCompareStreamUrl: (jobId: string) =>
    withAuthTicket(`${BASE}/alpha/compare/${encodeURIComponent(jobId)}/stream`),

  // Options Lab
  analyzeOptionsPayoff: (body: OptionsPayoffRequest) =>
    request<OptionsPayoffResponse>("/options/payoff", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getOptionsChain: (ticker: string, expiration?: number) => {
    const q = new URLSearchParams();
    q.set("ticker", ticker);
    if (expiration !== undefined) q.set("expiration", String(expiration));
    return request<OptionsChainResponse>(`/options/chain?${q.toString()}`);
  },

  // Macro economic analysis
  listMacroPrompts: () =>
    request<{ status: string; prompts: MacroPrompt[] }>("/api/macro/prompts"),
  updateMacroPrompt: (code: string, prompt_text: string) =>
    request<{ status: string; prompt: MacroPrompt }>(
      `/api/macro/prompts/${encodeURIComponent(code)}`,
      { method: "PUT", body: JSON.stringify({ prompt_text }) },
    ),
  listMacroEconomies: () =>
    request<{ status: string; economies: string[] }>("/api/macro/economies"),
  getMacroReadiness: (economy: string) =>
    request<{ status: string; readiness: MacroReadiness }>(
      `/api/macro/readiness?economy=${encodeURIComponent(economy)}`,
    ),
  runMacroCycleJudgment: (body: MacroJudgeRequestBody) =>
    request<{ status: string; cached: boolean; judgment: MacroJudgment }>(
      "/api/macro/cycle/judgments",
      { method: "POST", body: JSON.stringify(body) },
    ),
  listMacroJudgments: (economy: string) =>
    request<{ status: string; economy: string; judgments: MacroJudgment[] }>(
      `/api/macro/cycle/judgments?economy=${encodeURIComponent(economy)}`,
    ),
  getMacroJudgment: (economy: string, statisticsDate: string) =>
    request<{ status: string; judgment: MacroJudgment }>(
      `/api/macro/cycle/judgments/${encodeURIComponent(economy)}/${encodeURIComponent(statisticsDate)}`,
    ),

  // Connector runtime channel — privileged surface actions (NOT agent tools).
  // commit is the ONLY action that writes a mandate; halt trips the kill switch.
  getLiveAccounts: (broker: string) =>
    request<{ status: string; broker: string; account_selection_required: boolean; accounts: BrokerAccountChoice[] }>(
      `/live/accounts?broker=${encodeURIComponent(broker)}`,
    ),
  commitMandate: (body: CommitMandateRequest) =>
    request<CommitMandateResponse>("/mandate/commit", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  haltLive: (session_id?: string, broker?: string, reason?: string) =>
    request<HaltLiveResponse>("/live/halt", {
      method: "POST",
      body: JSON.stringify({ session_id, broker, reason }),
    }),
  resumeLive: (session_id?: string, broker?: string) =>
    request<HaltLiveResponse>("/live/resume", {
      method: "POST",
      body: JSON.stringify({ session_id, broker }),
    }),
  // Read the persistent runtime status across all authorized brokers (SPEC §7.5).
  // Polled by the RunnerStatus panel; a plain authenticated GET, never a chat message.
  getLiveStatus: (signal?: AbortSignal) => request<LiveStatus>("/live/status", { signal }),
  verifyConnector: (profileId: string) =>
    request<ConnectorVerifyResponse>(`/live/connectors/${encodeURIComponent(profileId)}/verify?force=true`, {
      method: "POST",
    }),
  authorizeLive: (broker: string) =>
    request<LiveAuthorizeResponse>("/live/authorize", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),
  // Start/stop the persistent runner (SPEC §7.5). Privileged surface actions, not agent tools.
  startLiveRunner: (broker: string) =>
    request<LiveRunnerResponse>("/live/runner/start", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),
  stopLiveRunner: (broker: string) =>
    request<LiveRunnerResponse>("/live/runner/stop", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),

  // --- M16 personal A-share watchlist -------------------------------------
  listWatch: () => request<WatchListResponse>("/watch/list"),
  addWatch: (body: AddWatchRequest) =>
    request<WatchEntry>("/watch", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  removeWatch: (symbol: string) =>
    request<{ ok: boolean; symbol: string }>(
      `/watch/${encodeURIComponent(symbol)}`,
      { method: "DELETE" },
    ),
  searchWatch: (q: string) =>
    request<{ items: WatchCandidate[] }>(
      `/watch/search?q=${encodeURIComponent(q)}`,
    ),
  getWatchProfile: (symbol: string) =>
    request<WatchProfileResponse>(
      `/watch/${encodeURIComponent(symbol)}/profile`,
    ),
  refreshWatchQuotes: (symbol: string) =>
    request<{ symbol: string; quote: QuoteSnapshot; updated_at: string }>(
      `/watch/${encodeURIComponent(symbol)}/refresh-quotes`,
      { method: "POST" },
    ),
  refreshWatchProfile: (symbol: string) =>
    request<CompanyProfile>(
      `/watch/${encodeURIComponent(symbol)}/refresh-profile`,
      { method: "POST" },
    ),
  getObjective: (symbol: string) =>
    request<ObjectiveResponse>(
      `/watch/${encodeURIComponent(symbol)}/objective`,
    ),
  startObjectiveFetch: (symbol: string, note: string) =>
    request<WatchRunSummary>(
      `/watch/${encodeURIComponent(symbol)}/objective-fetch`,
      { method: "POST", body: JSON.stringify({ note }) },
    ),
  listWatchAgents: (category?: WatchCategory) => {
    const query = category ? `?category=${encodeURIComponent(category)}` : "";
    return request<{ items: WatchAgent[] }>(`/watch/agents${query}`);
  },
  startWatchAnalysis: (
    symbol: string,
    body: {
      category: WatchCategory;
      role_ref: string;
      question?: string;
      skip_kline_gate?: boolean;
    },
  ) =>
    request<WatchRunSummary>(
      `/watch/${encodeURIComponent(symbol)}/analyze`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  listWatchAnalyses: (
    symbol: string,
    options?: WatchAnalysisQuery,
  ) => {
    const params = new URLSearchParams();
    if (options?.category) params.set("category", options.category);
    if (options?.roleRef) params.set("role_ref", options.roleRef);
    if (options?.from) params.set("from", options.from);
    if (options?.to) params.set("to", options.to);
    if (options?.limit) params.set("limit", String(options.limit));
    const query = params.toString();
    return request<{ items: WatchAnalysisSummary[] }>(
      `/watch/${encodeURIComponent(symbol)}/analyses${query ? `?${query}` : ""}`,
    );
  },
  listChanlun: (symbol: string, options?: ChanlunHistoryQuery) => {
    const params = new URLSearchParams();
    if (options?.from) params.set("from", options.from);
    if (options?.to) params.set("to", options.to);
    if (options?.limit) params.set("limit", String(options.limit));
    const query = params.toString();
    return request<{ items: ChanlunRecord[] }>(
      `/watch/${encodeURIComponent(symbol)}/chanlun${query ? `?${query}` : ""}`,
    );
  },
  getWatchKlineStatus: (symbol: string) =>
    request<WatchKlineStatusResponse>(
      `/watch/${encodeURIComponent(symbol)}/kline/status`,
    ),
  getWatchKlineBars: (
    symbol: string,
    interval: WatchKlineInterval,
    limit?: number,
  ) => {
    const params = new URLSearchParams({ interval });
    if (limit) params.set("limit", String(limit));
    return request<WatchKlineBarsResponse>(
      `/watch/${encodeURIComponent(symbol)}/kline/bars?${params.toString()}`,
    );
  },
  getWatchKlineSources: (symbol: string) =>
    request<WatchKlineSourcesResponse>(
      `/watch/${encodeURIComponent(symbol)}/kline/sources`,
    ),
  updateWatchKline: (
    symbol: string,
    intervals?: WatchKlineInterval[],
    source?: string,
  ) =>
    request<WatchKlineStatusResponse>(
      `/watch/${encodeURIComponent(symbol)}/kline/update`,
      {
        method: "POST",
        body: JSON.stringify({
          intervals: intervals ?? ["1d", "1w", "1mo", "1q", "1y"],
          ...(source ? { source } : {}),
        }),
      },
    ),
};

// --- Scheduled research types ---

export interface VerdictItem {
  symbol: string;
  state: string;
  reason: string;
}

export interface VerdictRecord {
  session_id: string;
  recorded_at: number;
  parse: string;
  outcome: string;
  items: VerdictItem[];
  previous: VerdictRecord | null;
}

export interface ScheduledRun {
  id: string;
  prompt: string;
  title: string;
  source_type: "prompt" | "playbook";
  playbook_slug: string | null;
  end_at: number | null;
  schedule: string;
  next_run_at: number;
  status: string;
  created_at: number;
  last_run_at: number | null;
  consecutive_failures: number;
  last_error: string | null;
  failure_kind: string | null;
  config: Record<string, unknown>;
  timezone: string | null;
  // Delivery is opt-in per monitor: a null channel means results stay in the
  // app, which is what every monitor created before this did.
  delivery_channel: string | null;
  delivery_target: string | null;
  delivery_target_ref: string | null;
  delivery_target_label: string | null;
  delivery_status: string;
  delivery_error: string | null;
  delivery_updated_at: number | null;
  delivery_attempts: number;
  delivery_provider_message_id: string | null;
  // The latest run's parsed verdict, embedded with its predecessor so the list
  // renders a delta in one query. Null until a completed run records one.
  last_verdict: VerdictRecord | null;
}

export interface CreateScheduledRunRequest {
  id?: string;
  title?: string | null;
  prompt: string;
  schedule: string;
  timezone?: string | null;
  end_at?: number | null;
  config?: Record<string, unknown>;
  delivery_channel?: string | null;
  delivery_target?: string | null;
  delivery_target_ref?: string | null;
}

export interface ScheduledResearchProposalJob {
  id: string;
  title: string;
  state: string;
  source: { kind: string; playbook_slug?: string | null; prompt?: string | null };
  schedule: {
    expression: string;
    timezone: string | null;
    next_run_at: number | null;
    end_at: number | null;
  };
  delivery: {
    channel: string | null;
    target_ref: string | null;
    target_label: string | null;
    status: string;
  };
}

export interface ScheduledResearchProposal {
  type: "scheduled_research.proposal";
  proposal_id: string;
  operation: "create" | "cancel";
  status: "pending" | "committed" | "discarded" | "expired";
  expires_at: number;
  job: ScheduledResearchProposalJob;
  job_id?: string | null;
  committed_job_id?: string | null;
}

// --- Swarm types ---

export interface SwarmPreset {
  name: string;
  title: string;
  description: string;
  /** Research category id; see swarmStudio.category.* i18n keys. */
  category: string;
  agent_count: number;
  variables: { name: string; description: string; required: boolean }[];
}

export interface SwarmRunSummary {
  id: string;
  preset_name: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
  is_stale?: boolean;
  task_count: number;
  completed_count: number;
  customized?: boolean;
  research_target?: string | null;
  research_question?: string | null;
  final_report_excerpt?: string | null;
  /** Server-side qualified-result verdict for skill_trial rows. */
  qualified?: boolean;
  /** "team" (default/old records), "skill_trial" or "role_run". */
  kind?: string;
  trial_skill?: string | null;
  trial_role?: string | null;
}

export interface SwarmRunListOptions {
  /** "team" (default), "skill_trial", "role_run" or "all". */
  kind?: "team" | "skill_trial" | "role_run" | "all";
  target?: string;
  /** ISO date prefix, inclusive (YYYY-MM-DD). */
  from?: string;
  to?: string;
  skillName?: string;
  /** "mine" (default) or "all" (operator view; admin-gated server-side). */
  scope?: "mine" | "all";
  limit?: number;
}

export interface CustomTeamSummary {
  id: string;
  name: string;
  description: string;
  source_preset: string;
  role_count: number;
  created_at: string;
  updated_at: string;
}

export interface CustomTeam {
  id: string;
  name: string;
  description: string;
  source_preset: string;
  nodes: CustomTeamNode[];
  edges: { upstream: string; downstream: string }[];
  created_at: string;
  updated_at: string;
}

export interface CustomTeamNode {
  id: string;
  role: string;
  duty: string;
  tools: string[];
  skills?: string[] | null;
  timeout_seconds: number;
  source_task_id?: string | null;
  is_new: boolean;
  /** Role Square reference; nodes without it are legacy snapshots. */
  role_ref?: string | null;
}

export interface CustomTeamRequest {
  name: string;
  description?: string;
  source_preset: string;
  nodes: CustomTeamNode[];
  edges: { upstream: string; downstream: string }[];
}

export interface SkillCatalogEntry {
  name: string;
  description: string;
  category: string;
  /** "bundled" ships with Vibe Trading; "user" was imported/synced/materialized. */
  source: "bundled" | "user";
  /** "bundled"/"user" assembled package, or "custom" personal skill. */
  kind: "bundled" | "user" | "custom";
  /** Stable reference: "assembled:<name>" or the custom skill id. */
  ref: string;
  /** Globally approved after at least one successful Skill Square trial. */
  approved: boolean;
  /** For custom skills derived via "save as new": the source skill ref. */
  derived_from?: string | null;
}

export interface SkillProfile {
  kind: "assembled" | "custom";
  ref: string;
  name: string;
  purpose: string;
  methodology: string;
  inputs: string;
  outputs: string;
  category: string;
  approved: boolean;
  derived_from?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface CustomSkillRequest {
  name: string;
  purpose?: string;
  methodology: string;
  inputs?: string;
  outputs?: string;
  /** Approved skill ref used as the "save as new" derivation template. */
  template_ref?: string;
}

export interface SkillCapabilities {
  admin_enabled: boolean;
  sync_source_configured: boolean;
}

export interface SkillTrialRequest {
  skill_name: string;
  target: string;
  question: string;
}

// ---------------------------------------------------------------------------
// Role Square
// ---------------------------------------------------------------------------

export interface RoleGroupItem {
  ref: string;
  name: string;
  purpose: string;
  approved: boolean;
}

export interface RoleGroup {
  kind: "builtin" | "custom";
  /** Preset name for builtin groups; "custom" for the custom group. */
  ref: string;
  title: string;
  description: string;
  /** Research category id; see swarmStudio.category.* i18n keys. */
  category: string;
  roles: RoleGroupItem[];
}

export interface RoleProfile {
  kind: "builtin" | "custom";
  ref: string;
  name: string;
  purpose: string;
  system_prompt: string;
  tools: string[];
  skills: string[];
  max_iterations: number;
  timeout_seconds: number;
  approved: boolean;
  created_at?: string;
  updated_at?: string;
  derived_from?: string | null;
}

export interface CustomRoleRequest {
  name: string;
  purpose?: string;
  system_prompt: string;
  tools: string[];
  skills: string[];
  max_iterations: number;
  timeout_seconds: number;
  /** Approved role ref used as the derivation template. */
  template_ref?: string;
}

export interface RoleRunRequest {
  role_ref: string;
  target: string;
  question: string;
}

export interface RoleRunListOptions {
  roleRef?: string;
  target?: string;
  from?: string;
  to?: string;
  scope?: "mine" | "all";
  limit?: number;
}

export interface SkillImportResult {
  installed: Array<{ name: string; slug: string }>;
  rejected: Array<{ package?: string; reasons: string[] }>;
}

export interface SkillSyncResult {
  added: string[];
  updated: string[];
  removed: string[];
  rejected: Array<{ package?: string; reasons: string[] }>;
}

export interface SwarmRunAgent {
  id: string;
  role: string;
  system_prompt: string;
  tools: string[];
  skills: string[];
  max_iterations: number;
  timeout_seconds: number;
}

export interface SwarmRunTask {
  id: string;
  agent_id: string;
  status: string;
  depends_on: string[];
  input_from?: Record<string, string>;
  summary?: string | null;
  error?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  worker_iterations?: number;
  iterations?: number;
}

export interface SwarmRunDetail {
  id: string;
  preset_name: string;
  status: string;
  is_stale?: boolean;
  user_vars: Record<string, string>;
  agents: SwarmRunAgent[];
  tasks: SwarmRunTask[];
  created_at: string;
  completed_at?: string | null;
  final_report?: string | null;
  customized?: boolean;
  research_target?: string | null;
  research_question?: string | null;
  kind?: string;
  trial_skill?: string | null;
  trial_role?: string | null;
}

export interface LLMProviderOption {
  name: string;
  label: string;
  api_key_env?: string | null;
  base_url_env: string;
  default_model: string;
  default_base_url: string;
  base_url_options?: string[];
  api_key_required: boolean;
  auth_type?: string;
  login_command?: string | null;
}

export interface LLMSettings {
  provider: string;
  model_name: string;
  base_url: string;
  api_key_env?: string | null;
  api_key_configured: boolean;
  api_key_hint?: string | null;
  api_key_required: boolean;
  temperature: number;
  timeout_seconds: number;
  max_retries: number;
  reasoning_effort: string;
  sse_timeout_seconds: number;
  env_path: string;
  providers: LLMProviderOption[];
}

export interface UpdateLLMSettingsRequest {
  provider: string;
  model_name: string;
  base_url: string;
  api_key?: string;
  clear_api_key?: boolean;
  temperature: number;
  timeout_seconds: number;
  max_retries: number;
  reasoning_effort?: string;
}

export interface ListLLMModelsRequest {
  provider: string;
  base_url?: string;
  api_key?: string;
}

export interface LLMModelsResponse {
  provider: string;
  models: string[];
  source: "provider" | "default";
  warning_code?:
    | "oauth_discovery_unsupported"
    | "api_key_required"
    | "model_list_unavailable"
    | null;
}

export interface SourceOrderEntry {
  market: string;
  env_var: string;
  default_order: string[];
  effective_order: string[];
  override?: string[] | null;
  override_invalid: boolean;
}

export interface SourceOrderUpdate {
  market: string;
  /** New order (permutation of default_order). null/omitted = reset to default. */
  order?: string[] | null;
}

export interface DataSourceSettings {
  tushare_token_configured: boolean;
  tushare_token_hint?: string | null;
  gildata_token_configured: boolean;
  gildata_token_hint?: string | null;
  baostock_supported: boolean;
  baostock_installed: boolean;
  baostock_message: string;
  env_path: string;
  source_orders?: SourceOrderEntry[];
}

export interface UpdateDataSourceSettingsRequest {
  tushare_token?: string;
  clear_tushare_token?: boolean;
  gildata_token?: string;
  clear_gildata_token?: boolean;
  source_orders?: SourceOrderUpdate[];
}

export interface ChannelAdapterStatus {
  name: string;
  display_name: string;
  configured: boolean;
  enabled: boolean;
  available: boolean;
  loaded: boolean;
  running: boolean;
  error?: string;
  install_hint?: string;
}

export interface ChannelRuntimeStatus {
  running: boolean;
  inbound_queue: number;
  outbound_queue: number;
  session_count: number;
  channels: Record<string, ChannelAdapterStatus>;
}

export interface ChannelRuntimeActionResponse extends ChannelRuntimeStatus {
  status: string;
}

export interface ChannelPairingCommandRequest {
  channel: string;
  command: string;
}

export interface ChannelPairingCommandResponse {
  channel: string;
  reply: string;
}

export interface ChannelFieldHint {
  key: string;
  type: "text" | "password" | "bool" | "list";
  secret: boolean;
  required: boolean;
  help_key?: string | null;
}

export interface ChannelSecretStatus {
  set: boolean;
  masked: string;
}

export interface ChannelConfigEntry {
  display_name: string;
  available: boolean;
  loaded: boolean;
  install_hint: string;
  error: string;
  supports_test: boolean;
  sdk_available: boolean;
  fields: ChannelFieldHint[];
  values: Record<string, unknown>;
  secrets: Record<string, ChannelSecretStatus>;
}

export interface ChannelsConfigResponse {
  /** Display-only path (home-relative `~/...` or a bare basename), never absolute. */
  config_path: string;
  writable: boolean;
  runtime_running: boolean;
  channels: Record<string, ChannelConfigEntry>;
}

// Merge-patches one channel section: an absent secret field is kept as-is,
// `clear_<field>: true` removes a stored secret, and an enable transition
// auto-verifies credentials unless `skip_verify` is set.
export type ChannelPutBody = {
  config: Record<string, unknown>;
  skip_verify?: boolean;
} & {
  [clearFlag: `clear_${string}`]: boolean | undefined;
};

export interface ChannelPutResult {
  channel: ChannelConfigEntry;
  applied: "hot_swapped" | "reset" | "deferred";
}

export type ChannelTestBody = {
  config?: Record<string, unknown>;
} & {
  [clearFlag: `clear_${string}`]: boolean | undefined;
};

export interface ChannelTestResult {
  ok: boolean;
  code: "ok" | "invalid_credentials" | "network" | "unsupported";
  detail?: string;
  sdk_available: boolean;
  tested_saved_config: boolean;
}

// --- Types matching backend API contracts ---

export interface RunListItem {
  run_id: string;
  status: string;
  created_at: string;
  prompt?: string;
  total_return?: number;
  sharpe?: number;
  codes?: string[];
  start_date?: string;
  end_date?: string;
}

export interface RunDetailParams {
  chart_payload?: "summary";
  chart_symbol?: string;
}

export interface PriceBar {
  time: string;
  timestamp?: string;
  code?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TradeMarker {
  time: string;
  timestamp?: string;
  code?: string;
  side: "BUY" | "SELL";
  price: number;
  qty?: number;
  reason?: string;
  text?: string;
}

export interface EquityPoint {
  time: string;
  equity: string | number;
  drawdown: string | number;
}

/** Monte Carlo fan-chart payload: percentile envelope + sampled paths over trade order. */
export interface MonteCarloEquityPaths {
  steps: number[];
  initial_capital: number;
  actual: number[];
  band_p5: number[];
  band_p25: number[];
  band_p50: number[];
  band_p75: number[];
  band_p95: number[];
  samples: number[][];
}

export interface ValidationData {
  monte_carlo?: {
    actual_sharpe: number;
    actual_max_dd: number;
    p_value_sharpe: number;
    p_value_max_dd: number;
    simulated_sharpe_mean: number;
    simulated_sharpe_std: number;
    simulated_sharpe_p5: number;
    simulated_sharpe_p95: number;
    n_simulations: number;
    n_trades: number;
    sharpe_samples?: number[];
    equity_paths?: MonteCarloEquityPaths;
    error?: string;
  };
  bootstrap?: {
    observed_sharpe: number;
    ci_lower: number;
    ci_upper: number;
    median_sharpe: number;
    prob_positive: number;
    confidence: number;
    n_bootstrap: number;
    sharpe_samples?: number[];
    error?: string;
  };
  walk_forward?: {
    n_windows: number;
    windows: Array<{
      window: number;
      start: string;
      end: string;
      return: number;
      sharpe: number;
      max_dd: number;
      trades: number;
      win_rate: number;
    }>;
    profitable_windows: number;
    consistency_rate: number;
    return_mean: number;
    return_std: number;
    sharpe_mean: number;
    sharpe_std: number;
    error?: string;
  };
}

export interface RiskXRayPayload {
  inputs?: {
    symbols?: string[];
    weights?: Record<string, number>;
    aligned_days?: number;
    return_observations?: number;
    first_date?: string;
    last_date?: string;
  };
  concentration?: { hhi?: number; effective_n?: number; top_weight?: number };
  volatility?: { annualized_vol?: number };
  drawdown?: { max_drawdown?: number };
  tail_risk?: Record<string, unknown>;
  diversification?: Record<string, unknown>;
  correlation?: Record<string, unknown>;
  skipped?: string[];
  warnings?: string[];
}

export interface RebalanceNotesPayload {
  rebalances?: Array<{
    date: string;
    turnover: number;
    entries?: Array<{ code: string; to: number }>;
    exits?: Array<{ code: string; from: number }>;
    top_moves?: Array<{ code: string; from: number; to: number; delta: number }>;
  }>;
  summary?: {
    target_change_count: number;
    /** Legacy key on runs produced before the #1275 execution-evidence fix. */
    rebalance_count?: number;
    turnover_total: number;
    turnover_mean: number;
    turnover_max: number;
    largest_rebalance_date?: string | null;
    rebalance_executed_bars?: number;
    rebalance_executed_fills?: number;
    rebalance_realized_turnover?: number;
  };
}

export interface FactorIcStats {
  ic_mean?: number | null;
  ic_std?: number | null;
  ir?: number | null;
  ic_positive_ratio?: number | null;
  ic_count?: number | null;
  [key: string]: unknown;
}

export interface FactorResult {
  name: string;
  path: string;
  ic_series: Array<{ date: string; ic: number }>;
  ic_stats?: FactorIcStats;
  group_equity: Array<{ date: string } & Record<string, number | string>>;
  n_groups: number;
  long_short_spread: number | null;
  group_final_equity: Record<string, number>;
  truncated?: {
    ic_series?: boolean;
    ic_stats?: boolean;
    group_equity?: boolean;
  };
}

export interface FactorReportPayload {
  exists: boolean;
  factors: FactorResult[];
  ic_correlation: { labels: string[]; matrix: number[][] } | null;
}

// --- Attribution types (GET /runs/{runId}/attribution) ---

export interface AttributionBenchmarkInfo {
  ticker: string | null;
  mode: "auto_equal_weight" | "explicit";
}

export interface AttributionRollingPoint {
  date: string;
  beta: number;
  alpha_annualized: number;
}

export interface AttributionCumulativePoint {
  date: string;
  portfolio: number;
  benchmark: number;
  /** Portfolio-minus-benchmark cumulative return; plotted as the active line. */
  active: number;
}

export interface AttributionFactor {
  beta: number;
  alpha_per_period: number;
  alpha_annualized: number;
  alpha_t_stat: number;
  r_squared: number;
  n_obs: number;
  rolling_window: number;
  rolling: AttributionRollingPoint[] | null;
  cumulative: AttributionCumulativePoint[];
}

export interface AttributionSectorEntry {
  sector: string;
  portfolio_weight: number;
  benchmark_weight: number;
  portfolio_return: number;
  benchmark_return: number;
  allocation: number;
  selection: number;
  interaction: number;
  total: number;
}

export interface AttributionBrinson {
  mode: "symbol" | "asset_class" | "invested_cash";
  portfolio_return: number;
  benchmark_return: number;
  active_return: number;
  allocation: number;
  selection: number;
  interaction: number;
  sectors: AttributionSectorEntry[];
}

export interface AttributionResponse {
  exists: boolean;
  benchmark: AttributionBenchmarkInfo | null;
  factor: AttributionFactor | null;
  brinson: AttributionBrinson | null;
  notes: string[];
}

export interface RunData {
  status: string;
  run_id: string;
  prompt?: string;
  elapsed_seconds?: number;
  run_directory?: string;
  run_stage?: string;
  run_context?: Record<string, unknown>;

  metrics?: BacktestMetrics;
  artifacts?: ArtifactInfo[];
  run_card?: RunCard;
  risk_xray?: RiskXRayPayload;
  rebalance_notes?: RebalanceNotesPayload;
  validation?: ValidationData;
  has_factor_artifacts?: boolean;

  chart_symbols?: string[];
  price_series?: Record<string, PriceBar[]>;
  indicator_series?: Record<string, Record<string, IndicatorPoint[]>>;
  trade_markers?: TradeMarker[];
  equity_curve?: EquityPoint[];
  trade_log?: Array<Record<string, string>>;
  /** Full equity.csv rows (timestamp/equity/drawdown as strings); not capped like equity_curve. */
  artifacts_equity_csv?: Array<Record<string, string>>;
  artifacts_metrics_csv?: Array<Record<string, string>>;
  artifacts_trades_csv?: Array<Record<string, string>>;
  /** Filled portfolio weights per date (rows: {timestamp, <symbol>: weight-string}). */
  artifacts_positions_csv?: Array<Record<string, string>>;
  /** Requested target weights per date, same row shape as artifacts_positions_csv. */
  artifacts_target_positions_csv?: Array<Record<string, string>>;
  run_logs?: Array<{ source?: string; line_number?: number; message?: string }>;
}

// --- Positions sector-map types (GET /runs/{runId}/positions/sectors) ---

/** Asset classes reported by the backend sector-map endpoint. */
export type SectorAssetClass =
  | "a_share"
  | "us_equity"
  | "hk_equity"
  | "india_equity"
  | "kr_equity"
  | "ca_equity"
  | "ar_equity"
  | "uk_equity"
  | "vietnam_equity"
  | "index"
  | "crypto"
  | "futures"
  | "forex";

export interface SectorInfo {
  asset_class: SectorAssetClass;
  /** Resolved industry name, or null when unresolved / not applicable. */
  industry: string | null;
  /** Provenance of `industry` (e.g. "eastmoney"), null when unresolved. */
  industry_source: string | null;
}

export interface SectorMapResponse {
  ok: boolean;
  run_id?: string;
  resolved_at?: string;
  cached?: boolean;
  symbols: Record<string, SectorInfo>;
  unresolved?: string[];
  /** Total symbol columns in positions.csv (may exceed `symbol_limit`). */
  total_symbols?: number;
  /** Max symbols that receive a network industry lookup per resolve. */
  symbol_limit?: number;
  /** Present when the run has no positions artifact. */
  note?: string;
}

/**
 * Fetch the resolved sector map for one run's positions artifact.
 * Uses the same auth-header + error-envelope conventions as every other
 * fetcher in this module (via the shared `request` helper).
 */
export function fetchRunSectorMap(runId: string, refresh?: boolean): Promise<SectorMapResponse> {
  const qs = refresh ? "?refresh=1" : "";
  return request<SectorMapResponse>(`/runs/${encodeURIComponent(runId)}/positions/sectors${qs}`);
}

export interface RunCard {
  schema_version?: string;
  generated_at?: string;
  run_dir?: string;
  backtest?: Record<string, unknown>;
  reproducibility?: Record<string, unknown>;
  data_sources?: string[];
  metrics?: Record<string, unknown>;
  // Carried alongside `metrics`, which is scalar-only: dict/list-shaped metrics
  // (e.g. which sleeve a plan rejection dropped) reach the card here.
  structured_metrics?: Record<string, unknown>;
  validation?: unknown;
  warnings?: string[];
  artifacts?: RunCardArtifact[];
  [key: string]: unknown;
}

export interface RunCardArtifact {
  path: string;
  size_bytes: number;
  sha256: string;
}

export interface BacktestMetrics {
  final_value: number;
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  sharpe: number;
  win_rate: number;
  trade_count: number;
  [key: string]: number;
}


export interface IndicatorPoint {
  time: string;
  value: number;
}

export interface ArtifactInfo {
  name: string;
  path: string;
  type: string;
  size: number;
  exists: boolean;
}

export interface PineScriptResult {
  exists: boolean;
  content: string | null;
}

export interface SessionItem {
  session_id: string;
  title?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  last_attempt_id?: string;
}

// --- Goal types ---

export type GoalStatus =
  | "active"
  | "paused"
  | "waiting_user"
  | "needs_refresh"
  | "insufficient_evidence"
  | "compliance_blocked"
  | "blocked"
  | "budget_limited"
  | "usage_limited"
  | "complete"
  | "cancelled"
  | "superseded";

export type GoalRiskTier =
  | "research_general"
  | "market_specific_short_term"
  | "personalized_advice_or_position_sizing";

export interface GoalRecord {
  goal_id: string;
  session_id: string;
  status: GoalStatus;
  objective: string;
  ui_summary: string;
  source: string;
  protocol: string;
  risk_tier: GoalRiskTier;
  token_budget?: number | null;
  tokens_used: number;
  turn_budget?: number | null;
  turns_used: number;
  time_budget_seconds?: number | null;
  time_used_seconds: number;
  budget_wrapup_sent: boolean;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  recap?: string | null;
}

export interface GoalClaim {
  claim_id: string;
  goal_id: string;
  session_id: string;
  claim_type: string;
  text: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface GoalCriterion {
  criterion_id: string;
  goal_id: string;
  session_id: string;
  text: string;
  required: boolean;
  status: string;
  freshness_requirement?: string | null;
  protocol_step?: string | null;
  created_at: string;
  updated_at: string;
}

export interface GoalEvidence {
  evidence_id: string;
  goal_id: string;
  session_id: string;
  text: string;
  criterion_id?: string | null;
  claim_id?: string | null;
  evidence_type: string;
  tool_call_id?: string | null;
  run_id?: string | null;
  source_provider?: string | null;
  source_type?: string | null;
  source_uri?: string | null;
  symbol_universe: string[];
  benchmark: string[];
  timeframe?: string | null;
  method?: string | null;
  assumptions: Record<string, unknown>;
  artifact_path?: string | null;
  artifact_hash?: string | null;
  retrieved_at: string;
  data_as_of?: string | null;
  freshness_status: string;
  verification_status: string;
  confidence?: string | null;
  caveat?: string | null;
  contradicts_claim_ids: string[];
  created_at: string;
}

export interface GoalSnapshot {
  goal: GoalRecord;
  claims: GoalClaim[];
  criteria: GoalCriterion[];
  evidence: GoalEvidence[];
  evidence_count: number;
}

export interface CreateGoalRequest {
  objective: string;
  criteria?: string[];
  ui_summary?: string;
  protocol?: string;
  risk_tier?: GoalRiskTier;
  token_budget?: number;
  turn_budget?: number;
  time_budget_seconds?: number;
}

export interface AddGoalEvidenceRequest {
  goal_id: string;
  expected_goal_id: string;
  text: string;
  criterion_id?: string | null;
  claim_id?: string | null;
  evidence_type?: string;
  tool_call_id?: string | null;
  run_id?: string | null;
  source_provider?: string | null;
  source_type?: string | null;
  source_uri?: string | null;
  symbol_universe?: string[];
  benchmark?: string[];
  timeframe?: string | null;
  method?: string | null;
  assumptions?: Record<string, unknown>;
  artifact_path?: string | null;
  artifact_hash?: string | null;
  data_as_of?: string | null;
  confidence?: string | null;
  caveat?: string | null;
  contradicts_claim_ids?: string[];
}

export interface UpdateGoalRequest {
  goal_id: string;
  expected_goal_id: string;
  objective?: string;
  ui_summary?: string;
}

export interface UpdateGoalResponse {
  goal: GoalRecord;
  snapshot: GoalSnapshot;
}

export interface AddGoalEvidenceResponse {
  evidence: GoalEvidence;
  snapshot: GoalSnapshot;
}

export interface GoalAuditRowRequest {
  criterion_id: string;
  result: string;
  evidence_ids?: string[];
  notes?: string;
}

export interface UpdateGoalStatusRequest {
  goal_id: string;
  expected_goal_id: string;
  status: GoalStatus;
  audit?: GoalAuditRowRequest[];
  recap?: string | null;
}

export interface UpdateGoalStatusResponse {
  goal: GoalRecord;
  snapshot: GoalSnapshot;
}

// --- Alpha Zoo types ---

export interface AlphaListParams {
  zoo?: string;
  theme?: string;
  universe?: string;
  limit?: number;
}

export interface AlphaSummary {
  id: string;
  zoo: string;
  theme: string[];
  universe: string[];
  nickname?: string;
  decay_horizon?: number | null;
  min_warmup_bars?: number | null;
  requires_sector?: boolean;
}

export interface AlphaListResponse {
  status: string;
  alphas: AlphaSummary[];
  total: number;
  returned: number;
  truncated: boolean;
}

export interface AlphaDetail {
  id: string;
  zoo: string;
  module_path?: string;
  meta: Record<string, unknown>;
}

export interface AlphaDetailResponse {
  status: string;
  alpha: AlphaDetail;
  source_code: string;
}

export interface AlphaBenchRequest {
  zoo: string;
  universe: string;
  period: string;
  top?: number;
}

export interface AlphaBenchTopRow {
  id: string;
  ic_mean: number;
  ir: number;
  theme: string[];
  formula_latex: string;
  category: "alive" | "reversed" | "dead";
}

export interface AlphaBenchResult {
  alive: number;
  reversed: number;
  dead: number;
  skipped?: number;
  top5_by_ir: AlphaBenchTopRow[];
  dead_examples: AlphaBenchTopRow[];
  by_theme: Record<string, { alive: number; reversed: number; dead: number }>;
}

export interface AlphaCompareRequest {
  alpha_ids: string[];
  universe: string;
  period: string;
  /** One of: ir | ic_mean | ic_positive_ratio | ic_count (default ir). */
  sort?: string;
}

export interface AlphaCompareRow {
  rank: number;
  id: string;
  zoo: string;
  ic_mean: number;
  ic_std: number;
  ir: number;
  ic_positive_ratio: number;
  ic_count: number;
  /** `delta_<sort>_vs_best` — gap to the top-ranked alpha on the active metric. */
  [deltaKey: string]: number | string;
}

export interface AlphaCompareSkip {
  id: string;
  reason: string;
}

export interface AlphaCompareResult {
  universe: string;
  period: string;
  sort: string;
  n_compared: number;
  n_skipped: number;
  winner: string;
  ranking: AlphaCompareRow[];
  skipped: AlphaCompareSkip[];
}

// --- Connector runtime channel types ---

/** One mandate profile inside a `mandate.proposal` event (SPEC Consent §1). */
export interface MandateProfile {
  ordinal: number;
  label: string;
  /** Concrete ticker list, or a structural universe descriptor (e.g. "tech_sector"). */
  universe: string[] | string;
  max_order_usd: number;
  daily_trade_cap: number;
  /** "none" for cash-only, otherwise a leverage descriptor/multiple. */
  leverage: string | number;
  instruments: string[];
  notes?: string;
}

/** Account block of a `mandate.proposal` event. */
export interface MandateProposalAccount {
  broker: string;
  type: string;
  funded_by: string;
}

/** Payload of the `mandate.proposal` SSE event (SPEC Consent §1). */
export interface MandateProposal {
  type?: string;
  proposal_id: string;
  session_id?: string;
  intent_normalized?: string;
  account?: MandateProposalAccount;
  ceilings_ref?: string;
  profiles: MandateProfile[];
  funding_note?: string;
  halt_note?: string;
  /** Present only when this proposal was triggered by a mandate breach (SPEC Consent §3). */
  reauth_for?: { breach_id?: string } | null;
}

/** Payload of the `mandate.committed` SSE event (SPEC Consent §1 COMMIT). */
export interface MandateCommitted {
  proposal_id?: string;
  mandate_id?: string;
  consent_record_id?: string;
  selected_ordinal?: number;
  broker?: string;
  /** Resolved limits, surfaced for the compact active-mandate badge. */
  max_order_usd?: number;
  daily_trade_cap?: number;
  expires_at?: string;
}

/** Payload of the `live.halted` SSE event (SPEC Consent §4). */
export interface LiveHalted {
  broker?: string | null;
  tripped_at?: string;
  by?: string;
  reason?: string;
}

/** Payload of the `live.action` SSE event (SPEC Consent §5 audit notify). */
export interface LiveAction {
  audit_id?: string;
  ts?: string;
  kind: string;
  intent_normalized?: string;
  outcome?: string;
  broker?: string;
  remote_tool?: string;
  error?: string | null;
}

export interface CommitMandateRequest {
  broker: string;
  proposal_id: string;
  selected_ordinal: number;
  /** Present only on the adjust path (SPEC Consent §3); null otherwise. */
  adjustments?: Record<string, unknown> | null;
  /** Explicit affirmative consent; the surface sets it on the user's click. */
  consent_ack: boolean;
  session_id?: string;
  account_ref?: string;
  lifetime_days?: number;
}

export interface CommitMandateResponse {
  mandate_id: string;
  consent_record_id: string;
  selected_ordinal?: number;
  broker?: string;
  max_order_usd?: number;
  daily_trade_cap?: number;
  expires_at?: string;
}

export interface HaltLiveResponse {
  halted: boolean;
  broker?: string | null;
  reason: string;
  sentinel: string;
}

export interface LiveAuthorizeRequest {
  broker: string;
}

export interface LiveAuthorizeResponse {
  broker: string;
  connector_profile: string;
  oauth_token_present: boolean;
  instruction: string;
  note?: string;
}

/** Mandate limits surfaced inside a `GET /live/status` broker entry (SPEC §7.5). */
export interface LiveMandateLimits {
  max_order_notional_usd?: number;
  max_total_exposure_usd?: number;
  max_leverage?: number;
  max_trades_per_day?: number;
  allowed_instruments?: string[];
  account_funding_usd?: number;
  [key: string]: unknown;
}

/** Active mandate block of a `GET /live/status` broker entry. */
export interface LiveMandateStatus {
  broker?: string;
  mandate_id?: string;
  account_ref?: string;
  created_at?: string;
  limits?: LiveMandateLimits;
  /** ISO timestamp the mandate auto-expires (SPEC §7.5 #7 proactive expiry). */
  expires_at?: string;
  expires_in_seconds?: number | null;
  expired?: boolean;
}

/** Runner liveness block of a `GET /live/status` broker entry (SPEC §7.5 #3). */
export interface LiveRunnerLiveness {
  broker?: string;
  alive: boolean;
  /** Unix epoch seconds of the last heartbeat tick; null if the runner never started. */
  last_tick?: number | string | null;
  last_tick_age_seconds?: number | null;
}

export interface LiveBrokerAuthStatus {
  broker: string;
  oauth_token_present: boolean;
  is_live_broker: boolean;
  /** Optional during rolling upgrades from OAuth-only runtime responses. */
  profile_id?: string | null;
  transport?: string | null;
  connection_state?: string | null;
  configured?: boolean | null;
  credential_source?: string | null;
  sdk_installed?: boolean | null;
  last_checked_at?: string | null;
  environment_identity?: string | null;
  readonly?: boolean | null;
  capabilities?: string[] | null;
  error_code?: string | null;
  error?: string | null;
}

export interface ConnectorVerifyResponse {
  status?: string;
  profile_id?: string | null;
  transport?: string | null;
  connection_state?: string | null;
  configured?: boolean | null;
  credential_source?: string | null;
  sdk_installed?: boolean | null;
  last_checked_at?: string | null;
  environment_identity?: string | null;
  readonly?: boolean | null;
  capabilities?: string[] | null;
  error_code?: string | null;
  error?: string | null;
  [key: string]: unknown;
}

/** One broker entry in the `GET /live/status` response. */
export interface LiveBrokerStatus {
  auth: LiveBrokerAuthStatus;
  mandate?: LiveMandateStatus | null;
  runner: LiveRunnerLiveness;
  halted: boolean;
}

/** Response of `GET /live/status` (SPEC §7.5 runner status panel + C2). */
export interface LiveStatus {
  brokers: LiveBrokerStatus[];
  global_halted: boolean;
}

/** Response of `POST /live/runner/start|stop`. */
export interface LiveRunnerResponse {
  broker: string;
  started?: boolean;
  already_running?: boolean;
  stopped?: boolean;
  was_running?: boolean;
}

export interface MessageItem {
  message_id: string;
  session_id: string;
  role: string;
  content: string;
  created_at: string;
  linked_attempt_id?: string;
  metadata?: Record<string, unknown>;
  tool_trail?: ToolTrailItem[];
}

export interface ToolTrailItem {
  tool: string;
  status: "running" | "ok" | "error";
  arguments?: Record<string, string>;
  elapsed_ms?: number;
  preview?: string;
  call_id?: string;
  timestamp?: number;
}

// --- M16 watchlist types (contract with src/api/watchlist_routes.py) ---

export type WatchCategory = "fundamental" | "technical" | "general";

export interface QuoteSnapshot {
  price: number | null;
  total_market_cap: number | null;
  pe: number | null;
  pb: number | null;
  industry: string | null;
  quote_updated_at: string | null;
}

export interface WatchEntry {
  symbol: string;
  name: string;
  industry: string | null;
  added_at: string;
  updated_at: string;
  quote: QuoteSnapshot | null;
}

export interface WatchListResponse {
  items: WatchEntry[];
  quote_error: string | null;
}

export interface AddWatchRequest {
  symbol: string;
  name?: string;
  industry?: string | null;
}

export interface WatchCandidate {
  symbol: string;
  name: string;
  industry: string | null;
}

export interface CompanyProfile {
  symbol: string;
  name: string;
  industry: string | null;
  list_date: string | null;
  registered_capital: number | null;
  total_shares: number | null;
  updated_at: string | null;
}

export interface WatchProfileResponse {
  symbol: string;
  instrument: Record<string, unknown> | null;
  latest_valuation: Record<string, unknown> | null;
  entry: WatchEntry;
}

export interface ObjectiveRawData {
  instrument: Record<string, unknown>[];
  daily_bar: Record<string, unknown>[];
  valuation: Record<string, unknown>[];
  financial: Record<string, unknown>[];
}

export interface ObjectiveRecord {
  id: string;
  symbol: string;
  category: string;
  request_note: string | null;
  payload: string;
  source: string | null;
  run_id: string | null;
  created_by: string | null;
  created_at: string;
}

export interface ObjectiveResponse {
  symbol: string;
  raw: ObjectiveRawData;
  fetches: ObjectiveRecord[];
}

export interface WatchRunSummary {
  id: string;
  status: string;
  kind: string;
  trial_role: string | null;
}

export interface WatchAgent {
  ref: string;
  name: string;
  purpose: string;
  category: WatchCategory;
  is_chanlun: boolean;
  /** Source agent team (preset title); empty for user-created custom roles. */
  team: string;
}

export interface WatchAnalysisQuery {
  category?: WatchCategory;
  roleRef?: string;
  from?: string;
  to?: string;
  limit?: number;
}

export interface WatchAnalysisSummary {
  id: string;
  status: string;
  role_ref: string | null;
  role_name: string;
  category: WatchCategory;
  is_chanlun: boolean;
  research_target: string;
  research_question: string;
  created_at: string | null;
  completed_at: string | null;
  final_report_excerpt: string;
  /** Full conclusion (AC-11); rendered with MarkdownContent on expand. */
  final_report?: string | null;
  qualified: boolean;
}

export interface ChanlunHistoryQuery {
  from?: string;
  to?: string;
  limit?: number;
}

export interface ChanlunRecord {
  id: string;
  run_id: string;
  symbol: string;
  analyzed_at: string;
  dim1_structure_read: string | null;
  dim2_active_pivots: string | null;
  dim3_divergence: string | null;
  dim4_buy_sell_points: string | null;
  dim5_multi_level_plan: string | null;
  dim6_elliott_corroboration: string | null;
  dim7_chanlun_score: string | null;
  score: number | null;
  confidence: number | null;
  structured: boolean;
  raw_report: string | null;
  created_at: string;
}

// --- M16 multi-level K-line readiness (Chanlun pre-run gate) ---

export type WatchKlineInterval = "1d" | "1w" | "1mo" | "1q" | "1y" | "30m";

export type WatchKlineStatusValue =
  | "ready"
  | "insufficient"
  | "not_fetched"
  | "failed";

export interface WatchKlineLevel {
  interval: WatchKlineInterval;
  required: boolean;
  status: WatchKlineStatusValue;
  /** True when the last attempt failed (old bars, if any, are kept). */
  fetch_failed: boolean;
  bars_count: number;
  earliest_bar_time: string | null;
  latest_bar_time: string | null;
  last_ok_at: string | null;
  last_attempt_at: string | null;
  last_error: string | null;
  /** Vendor that produced the current bars (null until first success). */
  source: string | null;
}

export type WatchKlineSourceId =
  | "tencent"
  | "mootdx"
  | "eastmoney"
  | "baostock"
  | "akshare"
  | "tushare"
  | "gildata"
  | "local"
  // backend may introduce new vendors before the frontend is rebuilt
  | (string & {});

export type WatchKlineUnavailableReason =
  | "not_installed"
  | "needs_auth"
  | "no_adapter";

export interface WatchKlineSource {
  id: WatchKlineSourceId;
  available: boolean;
  requires_auth: boolean;
  reason: WatchKlineUnavailableReason | null;
  intervals: WatchKlineInterval[];
}

export interface WatchKlineSourcesResponse {
  items: WatchKlineSource[];
}

export interface WatchKlineStatusResponse {
  items: WatchKlineLevel[];
  market_ref: {
    last_trading_date: string | null;
    threshold_date: string | null;
    source: string;
  };
}

export interface WatchKlineBarsResponse {
  symbol: string;
  interval: WatchKlineInterval;
  /** Stored OHLCV bars in ascending time order (empty when never fetched). */
  items: PriceBar[];
}
