import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  FileText,
  Flag,
  History,
  Loader2,
  Radar,
  RefreshCw,
  ShieldQuestion,
  Sparkles,
  Users,
  X,
  XCircle,
} from "lucide-react";
import {
  api,
  type EventReport,
  type RadarEvent,
  type RadarEventDetail,
  type RadarScanRun,
  type RadarScope,
} from "@/lib/api";
import { MarkdownContent } from "@/components/common/MarkdownContent";
import { cn } from "@/lib/utils";

type MainTab = "radar" | "taskforce";

const STATUS_META: Record<string, { label: string; cls: string }> = {
  unverified: { label: "未证实", cls: "bg-zinc-500/15 text-zinc-500" },
  verifying: { label: "核验中", cls: "bg-amber-500/15 text-amber-600" },
  confirmed: { label: "已证实", cls: "bg-emerald-500/15 text-emerald-600" },
  disputed: { label: "有争议", cls: "bg-orange-500/15 text-orange-600" },
  rumor: { label: "谣言", cls: "bg-red-500/15 text-red-600" },
  dismissed: { label: "已丢弃", cls: "bg-zinc-500/15 text-zinc-400 line-through" },
};

const NOVELTY_META: Record<string, { label: string; cls: string }> = {
  known_continuation: { label: "已知延续", cls: "bg-zinc-500/10 text-zinc-500" },
  known_escalation: { label: "已知升级", cls: "bg-sky-500/15 text-sky-600" },
  new_paradigm: { label: "重大机会候选", cls: "bg-violet-500/15 text-violet-600" },
};

const IMPACT_META: Record<string, string> = {
  high: "高影响",
  medium: "中影响",
  low: "低影响",
};

const TYPE_LABELS: Record<string, string> = {
  geopolitical: "地缘冲突",
  monetary_fiscal: "货币财政",
  trade: "贸易关税",
  public_health: "公共卫生",
  climate_disaster: "气候灾害",
  technology: "技术突破",
  regulation: "产业监管",
  politics: "大选政治",
  financial_credit: "金融信用",
  commodity_supply: "商品供给",
};

const REPORT_STATUS_META: Record<string, { label: string; cls: string }> = {
  pending: { label: "排队中", cls: "bg-zinc-500/15 text-zinc-500" },
  running: { label: "分析中", cls: "bg-sky-500/15 text-sky-600" },
  completed: { label: "已完成", cls: "bg-emerald-500/15 text-emerald-600" },
  incomplete: { label: "章节不完整", cls: "bg-amber-500/15 text-amber-600" },
  failed: { label: "失败", cls: "bg-red-500/15 text-red-600" },
};

const RETRO_PRESETS = [
  { title: "新冠疫情（COVID-19）", period: "2020-01 至 2021-12" },
  { title: "AI 产业浪潮（生成式人工智能）", period: "2022-11 至 2024-12" },
  { title: "俄乌战争", period: "2022-02 至 2023-06" },
];

function timeAgo(iso?: string) {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso.replace(" ", "T")).getTime();
  if (Number.isNaN(diff)) return "";
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

function Badge({ label, cls }: { label: string; cls: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium", cls)}>
      {label}
    </span>
  );
}

export function EventAnalysis() {
  const [mainTab, setMainTab] = useState<MainTab>("radar");

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4">
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <Radar className="h-5 w-5 text-violet-500" />
          事件分析
        </h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          突发新闻雷达：多源采集 · 真实性核验 · 新事物识别；Macro Event-Driven Task Force：影响传导、历史类比与机会复盘
        </p>
      </div>

      <div className="mb-4 inline-flex rounded-lg border border-border p-0.5">
        {(
          [
            { key: "radar", label: "突发雷达", icon: Radar },
            { key: "taskforce", label: "Task Force 分析", icon: Users },
          ] as const
        ).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setMainTab(key)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm",
              mainTab === key ? "bg-primary text-primary-foreground" : "hover:bg-muted/60",
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {mainTab === "radar" ? (
        <RadarTab onGoTaskForce={() => setMainTab("taskforce")} />
      ) : (
        <TaskForceTab />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 1: breaking radar
// ---------------------------------------------------------------------------

function RadarTab({ onGoTaskForce }: { onGoTaskForce: () => void }) {
  const [scope, setScope] = useState<RadarScope>("all");
  const [scanning, setScanning] = useState(false);
  const [scanRuns, setScanRuns] = useState<RadarScanRun[]>([]);
  const [events, setEvents] = useState<RadarEvent[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [noveltyFilter, setNoveltyFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [runsRes, eventsRes] = await Promise.all([
        api.radarScanRuns(),
        api.radarEvents({ status: statusFilter, novelty: noveltyFilter }),
      ]);
      setScanRuns(runsRes);
      setEvents(eventsRes.items);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, noveltyFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const scanRunning = scanRuns.some((r) => r.status === "running");
  useEffect(() => {
    if (!scanRunning) return;
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [scanRunning, load]);

  const startScan = async () => {
    setScanning(true);
    try {
      await api.radarScan(scope);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "扫描启动失败");
    } finally {
      setScanning(false);
    }
  };

  const latestRun = scanRuns[0];

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value as RadarScope)}
          className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
        >
          <option value="all">中国 + 全球</option>
          <option value="china">仅中国</option>
          <option value="global">仅全球</option>
        </select>
        <button
          type="button"
          onClick={() => void startScan()}
          disabled={scanning || scanRunning}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          {scanning || scanRunning ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Radar className="h-4 w-4" />
          )}
          立即扫描
        </button>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-sm hover:bg-muted/60"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          刷新
        </button>
        {latestRun && (
          <span className="text-xs text-muted-foreground">
            最近批次：{latestRun.status === "running" ? "进行中…" : latestRun.status === "partial" ? "部分完成" : latestRun.status === "failed" ? "失败" : "完成"}
            {latestRun.status !== "running" && (
              <>
                {" · 候选 "}
                {latestRun.candidates} · 去重 {latestRun.duplicates} · 新事件{" "}
                {latestRun.new_events} · {timeAgo(latestRun.finished_at || latestRun.started_at)}
              </>
            )}
          </span>
        )}
      </div>

      <div className="mb-3 flex items-center gap-2 text-xs">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-border bg-background px-2 py-1"
        >
          <option value="all">全部状态</option>
          <option value="unverified">未证实</option>
          <option value="verifying">核验中</option>
          <option value="confirmed">已证实</option>
          <option value="disputed">有争议</option>
          <option value="rumor">谣言</option>
        </select>
        <select
          value={noveltyFilter}
          onChange={(e) => setNoveltyFilter(e.target.value)}
          className="rounded-md border border-border bg-background px-2 py-1"
        >
          <option value="all">全部新颖度</option>
          <option value="new_paradigm">重大机会候选</option>
          <option value="known_escalation">已知升级</option>
          <option value="known_continuation">已知延续</option>
        </select>
      </div>

      {error && (
        <div className="mb-3 rounded-md border border-red-500/40 bg-red-500/10 p-2.5 text-sm text-red-500">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex h-40 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
        </div>
      ) : events.length === 0 ? (
        <div className="flex h-40 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-sm text-muted-foreground">
          <ShieldQuestion className="h-6 w-6" />
          暂无事件，点击「立即扫描」开始
        </div>
      ) : (
        <div className="space-y-2">
          {events.map((event) => (
            <button
              key={event.event_id}
              type="button"
              onClick={() => setDetailId(event.event_id)}
              className={cn(
                "w-full rounded-lg border border-border bg-card p-3 text-left transition hover:border-primary/40 hover:shadow-sm",
                event.novelty_class === "new_paradigm" && "border-violet-500/40",
              )}
            >
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge label={STATUS_META[event.verify_status]?.label ?? event.verify_status} cls={STATUS_META[event.verify_status]?.cls ?? ""} />
                {NOVELTY_META[event.novelty_class] && (
                  <Badge label={NOVELTY_META[event.novelty_class].label} cls={NOVELTY_META[event.novelty_class].cls} />
                )}
                <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                  {TYPE_LABELS[event.event_type] ?? event.event_type}
                </span>
                {event.impact_level && (
                  <span className="text-[11px] text-muted-foreground">
                    {IMPACT_META[event.impact_level]}
                  </span>
                )}
                <span className="ml-auto text-[11px] text-muted-foreground">
                  {event.source_count} 信源 · {timeAgo(event.last_update_at)}
                </span>
              </div>
              <div className="mt-1.5 text-sm font-medium">{event.title}</div>
              {event.summary && (
                <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{event.summary}</div>
              )}
              {event.long_term_themes && event.long_term_themes.length > 0 && (
                <div className="mt-1.5 flex flex-wrap items-center gap-1">
                  <Sparkles className="h-3 w-3 text-violet-500" />
                  {event.long_term_themes.map((theme) => (
                    <span key={theme} className="rounded bg-violet-500/10 px-1.5 py-0.5 text-[11px] text-violet-600">
                      {theme}
                    </span>
                  ))}
                  {event.paradigm_total != null && (
                    <span className="text-[11px] text-muted-foreground">范式分 {event.paradigm_total}/20</span>
                  )}
                </div>
              )}
            </button>
          ))}
        </div>
      )}

      {detailId && (
        <EventDetailDialog
          eventId={detailId}
          onClose={() => setDetailId(null)}
          onChanged={() => {
            void load();
          }}
          onAnalyzed={() => {
            setDetailId(null);
            onGoTaskForce();
          }}
        />
      )}
    </div>
  );
}

function EventDetailDialog({
  eventId,
  onClose,
  onChanged,
  onAnalyzed,
}: {
  eventId: string;
  onClose: () => void;
  onChanged: () => void;
  onAnalyzed: () => void;
}) {
  const [detail, setDetail] = useState<RadarEventDetail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setDetail(await api.radarEventDetail(eventId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }, [eventId]);

  useEffect(() => {
    void load();
  }, [load]);

  const verify = async (action: "confirm" | "flag_dispute" | "mark_rumor" | "dismiss") => {
    setBusy(true);
    try {
      await api.radarVerify(eventId, { action });
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const analyze = async () => {
    if (!detail) return;
    setBusy(true);
    try {
      await api.radarAnalyze(detail.event_id, { mode: "live" });
      onAnalyzed();
    } catch (e) {
      setError(e instanceof Error ? e.message : "启动失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4" onClick={onClose}>
      <div
        className="my-8 w-full max-w-3xl rounded-xl border border-border bg-card shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        {detail ? (
          <div className="p-5">
            <div className="flex items-start justify-between gap-3">
              <h2 className="text-base font-semibold">{detail.title}</h2>
              <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Badge label={STATUS_META[detail.verify_status]?.label ?? detail.verify_status} cls={STATUS_META[detail.verify_status]?.cls ?? ""} />
              {NOVELTY_META[detail.novelty_class] && (
                <Badge label={NOVELTY_META[detail.novelty_class].label} cls={NOVELTY_META[detail.novelty_class].cls} />
              )}
              <span className="text-xs text-muted-foreground">
                置信度 {detail.confidence != null ? Math.round(detail.confidence * 100) : "—"}%
              </span>
            </div>
            {detail.summary && <p className="mt-3 text-sm text-muted-foreground">{detail.summary}</p>}
            {detail.long_term_themes && detail.long_term_themes.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {detail.long_term_themes.map((t) => (
                  <span key={t} className="rounded bg-violet-500/10 px-1.5 py-0.5 text-[11px] text-violet-600">{t}</span>
                ))}
              </div>
            )}

            <h3 className="mt-4 text-sm font-medium">证据链（{detail.evidence.length}）</h3>
            <ul className="mt-1.5 space-y-1.5">
              {detail.evidence.map((ev) => (
                <li key={ev.id} className="rounded-md border border-border p-2 text-xs">
                  <div className="flex items-center gap-1.5">
                    <span className="rounded bg-muted px-1.5 py-0.5 font-medium">T{ev.source_tier ?? 4}</span>
                    <span className="text-muted-foreground">{ev.source_name || "未知来源"}</span>
                    {!ev.is_independent && <span className="text-amber-600">转载（非独立信源）</span>}
                    <a href={ev.url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center text-primary hover:underline">
                      原文 <ExternalLink className="ml-0.5 h-3 w-3" />
                    </a>
                  </div>
                  {ev.title && <div className="mt-1">{ev.title}</div>}
                </li>
              ))}
            </ul>

            <h3 className="mt-4 text-sm font-medium">状态时间线</h3>
            <ul className="mt-1.5 space-y-1">
              {detail.timeline.map((item, idx) => (
                <li key={idx} className="text-xs text-muted-foreground">
                  {new Date(item.created_at).toLocaleString()} · {item.change_type}
                  {item.from && item.to ? `：${item.from} → ${item.to}` : ""}
                  {item.note ? `（${item.note}）` : ""}
                </li>
              ))}
            </ul>

            {error && <div className="mt-3 rounded-md border border-red-500/40 bg-red-500/10 p-2 text-xs text-red-500">{error}</div>}

            <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-border pt-4">
              <button
                type="button"
                onClick={() => void analyze()}
                disabled={busy || detail.verify_status !== "confirmed"}
                title={detail.verify_status !== "confirmed" ? "仅已证实事件可发起分析" : ""}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Users className="h-4 w-4" />
                启动 Task Force（当下影响分析）
              </button>
              <div className="mx-1 h-5 w-px bg-border" />
              <button type="button" disabled={busy} onClick={() => void verify("confirm")} className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 px-2.5 py-1.5 text-xs text-emerald-600 hover:bg-emerald-500/10 disabled:opacity-50">
                <CheckCircle2 className="h-3.5 w-3.5" /> 证实
              </button>
              <button type="button" disabled={busy} onClick={() => void verify("flag_dispute")} className="inline-flex items-center gap-1 rounded-md border border-orange-500/40 px-2.5 py-1.5 text-xs text-orange-600 hover:bg-orange-500/10 disabled:opacity-50">
                <AlertTriangle className="h-3.5 w-3.5" /> 有争议
              </button>
              <button type="button" disabled={busy} onClick={() => void verify("mark_rumor")} className="inline-flex items-center gap-1 rounded-md border border-red-500/40 px-2.5 py-1.5 text-xs text-red-600 hover:bg-red-500/10 disabled:opacity-50">
                <Flag className="h-3.5 w-3.5" /> 谣言
              </button>
              <button type="button" disabled={busy} onClick={() => void verify("dismiss")} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted/60 disabled:opacity-50">
                <XCircle className="h-3.5 w-3.5" /> 丢弃
              </button>
            </div>
          </div>
        ) : (
          <div className="flex h-40 items-center justify-center text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 2: macro Task Force
// ---------------------------------------------------------------------------

function TaskForceTab() {
  const [events, setEvents] = useState<RadarEvent[]>([]);
  const [reports, setReports] = useState<EventReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedEventId, setSelectedEventId] = useState("");
  const [customTitle, setCustomTitle] = useState("");
  const [customPeriod, setCustomPeriod] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [openReportId, setOpenReportId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [confirmed, reportsRes] = await Promise.all([
        api.radarEvents({ status: "confirmed" }),
        api.eventReports(),
      ]);
      setEvents(confirmed.items);
      setReports(reportsRes.items);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const anyRunning = reports.some((r) => r.status === "pending" || r.status === "running");
  useEffect(() => {
    if (!anyRunning) return;
    const timer = setInterval(() => void load(), 5000);
    return () => clearInterval(timer);
  }, [anyRunning, load]);

  const startLive = async () => {
    if (!selectedEventId) return;
    setSubmitting(true);
    try {
      await api.radarAnalyze(selectedEventId, { mode: "live" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "启动失败");
    } finally {
      setSubmitting(false);
    }
  };

  const startRetro = async (title: string, period: string) => {
    setSubmitting(true);
    try {
      await api.eventAnalyzeCustom({ event_title: title, event_period: period });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "启动失败");
    } finally {
      setSubmitting(false);
    }
  };

  const openReport = openReportId ? reports.find((r) => r.id === openReportId) : null;

  return (
    <div>
      {error && (
        <div className="mb-3 rounded-md border border-red-500/40 bg-red-500/10 p-2.5 text-sm text-red-500">{error}</div>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {/* Live outlook */}
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="flex items-center gap-1.5 text-sm font-medium">
            <Radar className="h-4 w-4 text-sky-500" /> 当下事件影响分析（live）
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            选择已证实的雷达事件，由四角色团队（情报官 → 影响分析 → 历史类比 → 策略）产出未来 3–6 个月影响报告。
          </p>
          <div className="mt-3 flex gap-2">
            <select
              value={selectedEventId}
              onChange={(e) => setSelectedEventId(e.target.value)}
              className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            >
              <option value="">选择已证实事件…</option>
              {events.map((e) => (
                <option key={e.event_id} value={e.event_id}>
                  {e.title.slice(0, 60)}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={!selectedEventId || submitting}
              onClick={() => void startLive()}
              className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-40"
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
              分析
            </button>
          </div>
          {events.length === 0 && (
            <p className="mt-2 text-xs text-muted-foreground">暂无已证实事件，请先在雷达页扫描并核验。</p>
          )}
        </div>

        {/* Retrospective */}
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="flex items-center gap-1.5 text-sm font-medium">
            <History className="h-4 w-4 text-amber-500" /> 历史事件复盘（retrospective）
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            复盘错过的大机会：早期信号、资产真实表现、没抓住的机会清单与「若重演」预案。
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {RETRO_PRESETS.map((preset) => (
              <button
                key={preset.title}
                type="button"
                disabled={submitting}
                onClick={() => void startRetro(preset.title, preset.period)}
                className="rounded-md border border-border px-2 py-1 text-xs hover:border-primary/40 hover:bg-muted/60 disabled:opacity-40"
              >
                {preset.title}
              </button>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <input
              value={customTitle}
              onChange={(e) => setCustomTitle(e.target.value)}
              placeholder="自定义历史事件，如：欧债危机"
              className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            />
            <input
              value={customPeriod}
              onChange={(e) => setCustomPeriod(e.target.value)}
              placeholder="区间，如 2011-01 至 2012-12"
              className="w-44 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            />
            <button
              type="button"
              disabled={!customTitle.trim() || submitting}
              onClick={() => void startRetro(customTitle.trim(), customPeriod.trim())}
              className="inline-flex items-center gap-1 rounded-md border border-primary px-3 py-1.5 text-sm text-primary hover:bg-primary/10 disabled:opacity-40"
            >
              复盘
            </button>
          </div>
        </div>
      </div>

      <h2 className="mb-2 mt-5 flex items-center gap-1.5 text-sm font-medium">
        <FileText className="h-4 w-4" /> 分析报告
        <button type="button" onClick={() => void load()} className="ml-1 text-muted-foreground hover:text-foreground" title="刷新">
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </h2>

      {loading ? (
        <div className="flex h-32 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
        </div>
      ) : reports.length === 0 ? (
        <div className="flex h-32 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-sm text-muted-foreground">
          <ChevronDown className="h-5 w-5" />
          还没有报告，从上方发起一次分析
        </div>
      ) : (
        <div className="space-y-2">
          {reports.map((report) => {
            const meta = REPORT_STATUS_META[report.status] ?? { label: report.status, cls: "" };
            const running = report.status === "pending" || report.status === "running";
            return (
              <button
                key={report.id}
                type="button"
                onClick={() => (report.markdown ? setOpenReportId(report.id) : undefined)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg border border-border bg-card p-3 text-left",
                  report.markdown ? "hover:border-primary/40" : "cursor-default opacity-90",
                )}
              >
                {running ? <Loader2 className="h-4 w-4 animate-spin text-sky-500" /> : <FileText className="h-4 w-4 text-muted-foreground" />}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{report.title}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {report.mode === "live" ? "当下展望" : "历史复盘"} · {report.time_horizon || "—"} · {timeAgo(report.created_at)}
                  </div>
                </div>
                <Badge label={meta.label} cls={meta.cls} />
                {report.markdown && <ArrowRight className="h-4 w-4 text-muted-foreground" />}
              </button>
            );
          })}
        </div>
      )}

      {openReport && <ReportDialog report={openReport} onClose={() => setOpenReportId(null)} />}
    </div>
  );
}

function ReportDialog({ report, onClose }: { report: EventReport; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4" onClick={onClose}>
      <div
        className="my-8 w-full max-w-4xl rounded-xl border border-border bg-card shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border p-4">
          <div>
            <h2 className="text-base font-semibold">{report.title}</h2>
            <div className="mt-0.5 text-xs text-muted-foreground">
              {report.mode === "live" ? "当下事件影响报告" : "历史事件复盘报告"} · {report.time_horizon}
            </div>
          </div>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto p-5">
          {report.markdown ? (
            <MarkdownContent content={report.markdown} />
          ) : (
            <div className="text-sm text-muted-foreground">报告尚未生成完成。</div>
          )}
        </div>
      </div>
    </div>
  );
}
