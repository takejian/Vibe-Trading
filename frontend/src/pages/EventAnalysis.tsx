import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Archive,
  ArrowRight,
  Ban,
  BookmarkCheck,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ClipboardCheck,
  ExternalLink,
  FileText,
  Flag,
  GitCompare,
  History,
  Loader2,
  Radar,
  RefreshCw,
  RotateCcw,
  ShieldQuestion,
  Sparkles,
  Trash2,
  Trophy,
  Users,
  X,
  XCircle,
} from "lucide-react";
import {
  api,
  type ArchiveEvent,
  type DailyPick,
  type EvalRating,
  type EventReport,
  type LeaderboardEntry,
  type RadarEvent,
  type RadarEventDetail,
  type RadarScanRun,
  type RadarScope,
  type ReviewRecord,
} from "@/lib/api";
import { MarkdownContent } from "@/components/common/MarkdownContent";
import { cn } from "@/lib/utils";

type MainTab = "radar" | "archive" | "taskforce";

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
  canceled: { label: "已取消", cls: "bg-zinc-500/15 text-zinc-400" },
};

const REVIEW_META: Record<string, { label: string; cls: string }> = {
  true: { label: "查证为真", cls: "bg-emerald-500/15 text-emerald-600" },
  false: { label: "查证为假", cls: "bg-red-500/15 text-red-600" },
  unverified: { label: "未有定论", cls: "bg-zinc-500/15 text-zinc-500" },
  error: { label: "复查失败", cls: "bg-amber-500/15 text-amber-600" },
};

const EVAL_META: Record<EvalRating, { label: string; cls: string }> = {
  accurate: { label: "评价：准确", cls: "bg-emerald-500/15 text-emerald-600" },
  partial: { label: "评价：部分准确", cls: "bg-sky-500/15 text-sky-600" },
  off: { label: "评价：方向偏离", cls: "bg-orange-500/15 text-orange-600" },
  wrong: { label: "评价：判断错误", cls: "bg-red-500/15 text-red-600" },
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

function fmtDateTime(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso.replace(" ", "T"));
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
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
          突发新闻雷达：多源采集 · 真实性核验 · 新事物识别；事件档案：Top5 留存与日/周/月复核；Macro Event-Driven Task Force：影响传导、历史类比与机会复盘
        </p>
      </div>

      <div className="mb-4 inline-flex rounded-lg border border-border p-0.5">
        {(
          [
            { key: "radar", label: "突发雷达", icon: Radar },
            { key: "archive", label: "事件档案", icon: Archive },
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
      ) : mainTab === "archive" ? (
        <ArchiveTab onGoTaskForce={() => setMainTab("taskforce")} />
      ) : (
        <TaskForceTab onGoArchive={() => setMainTab("archive")} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared: event detail dialog
// ---------------------------------------------------------------------------

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
  const [rechecking, setRechecking] = useState(false);
  const [openReport, setOpenReport] = useState<EventReport | null>(null);

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

  const recheck = async () => {
    setRechecking(true);
    setError("");
    try {
      await api.radarRecheck(eventId);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "复查失败");
    } finally {
      setRechecking(false);
    }
  };

  const toggleArchive = async () => {
    if (!detail) return;
    setBusy(true);
    try {
      await api.radarArchive(eventId, !detail.archived);
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const openReportById = async (reportId: string) => {
    try {
      setOpenReport(await api.eventReport(reportId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "报告加载失败");
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
              {detail.archived && <Badge label="事件档案" cls="bg-violet-500/15 text-violet-600" />}
              <span className="text-xs text-muted-foreground">
                置信度 {detail.confidence != null ? Math.round(detail.confidence * 100) : "—"}%
              </span>
              {detail.pick_stats && detail.pick_stats.pick_days > 0 && (
                <span className="text-xs text-muted-foreground">
                  · 近30天入榜 {detail.pick_stats.pick_days} 天
                  {detail.pick_stats.last_pick_date ? `（最近 ${detail.pick_stats.last_pick_date}）` : ""}
                </span>
              )}
            </div>
            {detail.summary && <p className="mt-3 text-sm text-muted-foreground">{detail.summary}</p>}
            {detail.long_term_themes && detail.long_term_themes.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {detail.long_term_themes.map((t) => (
                  <span key={t} className="rounded bg-violet-500/10 px-1.5 py-0.5 text-[11px] text-violet-600">{t}</span>
                ))}
              </div>
            )}

            {detail.archived && (
              <div className="mt-4 rounded-lg border border-border p-3">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-medium">真实性跟踪复核</h3>
                  <button
                    type="button"
                    onClick={() => void recheck()}
                    disabled={rechecking}
                    className="inline-flex items-center gap-1 rounded-md border border-primary/40 px-2.5 py-1 text-xs text-primary hover:bg-primary/10 disabled:opacity-50"
                  >
                    {rechecking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                    立即复查（覆盖月复核）
                  </button>
                </div>
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  <ReviewBlock label="日复核" review={detail.review_daily} />
                  <ReviewBlock label="周复核（每周一）" review={detail.review_weekly} />
                  <ReviewBlock label="月复核 / 手动" review={detail.review_monthly} />
                </div>
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

            {detail.reports.length > 0 && (
              <>
                <h3 className="mt-4 text-sm font-medium">Task Force 报告（{detail.reports.length}）</h3>
                <ul className="mt-1.5 space-y-1.5">
                  {detail.reports.map((r) => (
                    <li key={r.id} className="rounded-md border border-border p-2 text-xs">
                      <div className="flex items-center gap-2">
                        <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="font-medium">{r.title}</span>
                        <Badge
                          label={REPORT_STATUS_META[r.status]?.label ?? r.status}
                          cls={REPORT_STATUS_META[r.status]?.cls ?? ""}
                        />
                        {r.eval_rating && EVAL_META[r.eval_rating] && (
                          <Badge label={EVAL_META[r.eval_rating].label} cls={EVAL_META[r.eval_rating].cls} />
                        )}
                        <span className="ml-auto text-muted-foreground">{fmtDateTime(r.completed_at || r.created_at)}</span>
                      </div>
                      {r.expected_outcome && (
                        <div className="mt-1 text-muted-foreground">预期结果：{r.expected_outcome}</div>
                      )}
                      {r.guidance && (
                        <div className="text-muted-foreground">指导建议：{r.guidance}</div>
                      )}
                      <div className="mt-1 text-right">
                        <button
                          type="button"
                          onClick={() => void openReportById(r.id)}
                          className="inline-flex items-center gap-0.5 text-primary hover:underline"
                        >
                          打开报告 <ArrowRight className="h-3 w-3" />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}

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
              <button
                type="button"
                onClick={() => void toggleArchive()}
                disabled={busy}
                className={cn(
                  "inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs disabled:opacity-50",
                  detail.archived
                    ? "border-border text-muted-foreground hover:bg-muted/60"
                    : "border-violet-500/40 text-violet-600 hover:bg-violet-500/10",
                )}
              >
                <BookmarkCheck className="h-3.5 w-3.5" />
                {detail.archived ? "移出档案" : "保留入档案"}
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
                <XCircle className="h-3.5 w-3.5" /> 标记丢弃
              </button>
            </div>
          </div>
        ) : (
          <div className="flex h-40 items-center justify-center text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
          </div>
        )}
      </div>

      {openReport && (
        <ReportDialog
          report={openReport}
          onClose={() => setOpenReport(null)}
          onChanged={() => void openReportById(openReport.id)}
        />
      )}
    </div>
  );
}

function ReviewBlock({ label, review }: { label: string; review: ReviewRecord | null | undefined }) {
  if (!review) {
    return (
      <div className="rounded-md border border-dashed border-border p-2 text-xs text-muted-foreground">
        {label}：暂无记录
      </div>
    );
  }
  const meta = REVIEW_META[review.verdict] ?? REVIEW_META.unverified;
  return (
    <div className="rounded-md border border-border p-2 text-xs">
      <div className="flex items-center gap-1.5">
        <span className="text-muted-foreground">{label}</span>
        <Badge label={meta.label} cls={meta.cls} />
      </div>
      {review.checked_at && (
        <div className="mt-1 text-[11px] text-muted-foreground">{fmtDateTime(review.checked_at)}</div>
      )}
      {review.reason && <div className="mt-1 leading-relaxed">{review.reason}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 1: breaking radar (daily Top-5 workbench)
// ---------------------------------------------------------------------------

function RadarTab({ onGoTaskForce }: { onGoTaskForce: () => void }) {
  const [scope, setScope] = useState<RadarScope>("all");
  const [scanning, setScanning] = useState(false);
  const [scanRuns, setScanRuns] = useState<RadarScanRun[]>([]);
  const [events, setEvents] = useState<RadarEvent[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [noveltyFilter, setNoveltyFilter] = useState("all");
  const [topOnly, setTopOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [runsRes, eventsRes] = await Promise.all([
        api.radarScanRuns(),
        api.radarEvents({
          status: statusFilter,
          novelty: noveltyFilter,
          limit: topOnly ? 5 : 300,
        }),
      ]);
      setScanRuns(runsRes);
      setEvents(eventsRes.items);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, noveltyFilter, topOnly]);

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

  const keep = async (event: RadarEvent) => {
    setActionId(event.event_id);
    try {
      await api.radarArchive(event.event_id, true);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setActionId(null);
    }
  };

  const discard = async (event: RadarEvent) => {
    if (!window.confirm(`确认丢弃「${event.title.slice(0, 40)}」？\n丢弃后事件将被物理删除，不进入事件档案（当日 Top5 快照保留标题）。`)) return;
    setActionId(event.event_id);
    try {
      await api.radarDiscard(event.event_id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setActionId(null);
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

      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
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
        <button
          type="button"
          onClick={() => setTopOnly((v) => !v)}
          className={cn(
            "rounded-md border px-2.5 py-1",
            topOnly
              ? "border-primary/50 bg-primary/10 text-primary"
              : "border-border hover:bg-muted/60",
          )}
        >
          {topOnly ? "仅看最重要 5 条" : "查看全部"}
        </button>
        <span className="ml-auto text-muted-foreground">
          信源：财联社深度 · 华尔街见闻｜每日 04:00 自动扫描 · 05:00 档案复查
        </span>
      </div>

      {topOnly && (
        <p className="mb-2 text-xs text-muted-foreground">
          当日工作台：最重要的 5 条可「保留入档案」长期跟踪，其余事件下一轮扫描自动清除；丢弃的事件物理删除、不进档案。
        </p>
      )}

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
            <div
              key={event.event_id}
              role="button"
              tabIndex={0}
              onClick={() => setDetailId(event.event_id)}
              onKeyDown={(e) => {
                if (e.key === "Enter") setDetailId(event.event_id);
              }}
              className={cn(
                "w-full cursor-pointer rounded-lg border border-border bg-card p-3 text-left transition hover:border-primary/40 hover:shadow-sm",
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
                {event.archived && <Badge label="已入档案" cls="bg-violet-500/15 text-violet-600" />}
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
              {topOnly && (
                <div className="mt-2.5 flex items-center justify-end gap-2 border-t border-border/60 pt-2">
                  <button
                    type="button"
                    disabled={actionId === event.event_id}
                    onClick={(e) => {
                      e.stopPropagation();
                      void discard(event);
                    }}
                    className="inline-flex items-center gap-1 rounded-md border border-red-500/40 px-2 py-1 text-xs text-red-600 hover:bg-red-500/10 disabled:opacity-50"
                  >
                    {actionId === event.event_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                    丢弃
                  </button>
                  <button
                    type="button"
                    disabled={actionId === event.event_id || event.archived}
                    onClick={(e) => {
                      e.stopPropagation();
                      void keep(event);
                    }}
                    className="inline-flex items-center gap-1 rounded-md border border-violet-500/40 px-2 py-1 text-xs text-violet-600 hover:bg-violet-500/10 disabled:opacity-50"
                  >
                    <BookmarkCheck className="h-3.5 w-3.5" />
                    {event.archived ? "已保留" : "保留入档案"}
                  </button>
                </div>
              )}
            </div>
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

// ---------------------------------------------------------------------------
// Tab 2: archive (kept Top-5 events, reviews, leaderboard, daily picks)
// ---------------------------------------------------------------------------

function defaultDateFrom() {
  const d = new Date();
  d.setDate(d.getDate() - 29);
  return d.toISOString().slice(0, 10);
}

function ArchiveTab({ onGoTaskForce }: { onGoTaskForce: () => void }) {
  const [items, setItems] = useState<ArchiveEvent[]>([]);
  const [board, setBoard] = useState<LeaderboardEntry[]>([]);
  const [picks, setPicks] = useState<DailyPick[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [noveltyFilter, setNoveltyFilter] = useState("all");
  const [keyword, setKeyword] = useState("");
  const [dateFrom, setDateFrom] = useState(defaultDateFrom);
  const [dateTo, setDateTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [archiveRes, boardRes, picksRes] = await Promise.all([
        api.radarArchiveList({
          status: statusFilter,
          novelty: noveltyFilter,
          keyword: keyword.trim() || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          limit: 200,
        }),
        api.radarLeaderboard(30, 10),
        api.radarDailyPicks(dateFrom || undefined, dateTo || undefined, 300),
      ]);
      setItems(archiveRes.items);
      setBoard(boardRes.items);
      setPicks(picksRes.items);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, noveltyFilter, keyword, dateFrom, dateTo]);

  useEffect(() => {
    void load();
  }, [load]);

  const picksByDate = picks.reduce<Record<string, DailyPick[]>>((acc, pick) => {
    (acc[pick.pick_date] ||= []).push(pick);
    return acc;
  }, {});
  const pickDates = Object.keys(picksByDate).sort().reverse();

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-border bg-background px-2 py-1.5"
        >
          <option value="all">全部状态</option>
          <option value="confirmed">已证实</option>
          <option value="disputed">有争议</option>
          <option value="rumor">谣言</option>
          <option value="verifying">核验中</option>
          <option value="unverified">未证实</option>
        </select>
        <select
          value={noveltyFilter}
          onChange={(e) => setNoveltyFilter(e.target.value)}
          className="rounded-md border border-border bg-background px-2 py-1.5"
        >
          <option value="all">全部新颖度</option>
          <option value="new_paradigm">重大机会候选</option>
          <option value="known_escalation">已知升级</option>
          <option value="known_continuation">已知延续</option>
        </select>
        <input
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="关键词"
          className="w-36 rounded-md border border-border bg-background px-2 py-1.5"
        />
        <CalendarDays className="h-3.5 w-3.5 text-muted-foreground" />
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          className="rounded-md border border-border bg-background px-2 py-1.5"
        />
        <span className="text-muted-foreground">至</span>
        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          className="rounded-md border border-border bg-background px-2 py-1.5"
        />
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 hover:bg-muted/60"
        >
          <RefreshCw className="h-3.5 w-3.5" /> 刷新
        </button>
      </div>

      {error && (
        <div className="mb-3 rounded-md border border-red-500/40 bg-red-500/10 p-2.5 text-sm text-red-500">{error}</div>
      )}

      <div className="grid gap-3 lg:grid-cols-3">
        <div className="rounded-lg border border-border bg-card p-4 lg:col-span-2">
          <h2 className="flex items-center gap-1.5 text-sm font-medium">
            <Archive className="h-4 w-4 text-violet-500" /> 留存事件（{items.length}）
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            来自每日雷达 Top5 的保留事件；待核验事件每日/每周一/每月 1 日 05:00 自动复查真假。
          </p>
          {loading ? (
            <div className="flex h-32 items-center justify-center text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
            </div>
          ) : items.length === 0 ? (
            <div className="mt-3 flex h-28 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border text-sm text-muted-foreground">
              档案为空，在突发雷达 Top5 中选择「保留入档案」
            </div>
          ) : (
            <ul className="mt-3 space-y-2">
              {items.map((event) => (
                <li key={event.event_id}>
                  <button
                    type="button"
                    onClick={() => setDetailId(event.event_id)}
                    className="w-full rounded-lg border border-border p-3 text-left hover:border-primary/40 hover:shadow-sm"
                  >
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge label={STATUS_META[event.verify_status]?.label ?? event.verify_status} cls={STATUS_META[event.verify_status]?.cls ?? ""} />
                      {NOVELTY_META[event.novelty_class] && (
                        <Badge label={NOVELTY_META[event.novelty_class].label} cls={NOVELTY_META[event.novelty_class].cls} />
                      )}
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                        {TYPE_LABELS[event.event_type] ?? event.event_type}
                      </span>
                      <span className="ml-auto text-[11px] text-muted-foreground">
                        入榜 {event.pick_days} 天 · 报告 {event.report_count}
                      </span>
                    </div>
                    <div className="mt-1.5 text-sm font-medium">{event.title}</div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                      首次入榜 {event.first_pick_date || "—"} · 最近 {event.last_pick_date || "—"}
                      {" · "}更新 {timeAgo(event.last_update_at)}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-3">
          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="flex items-center gap-1.5 text-sm font-medium">
              <Trophy className="h-4 w-4 text-amber-500" /> 近 30 天入榜次数榜
            </h2>
            {board.length === 0 ? (
              <p className="mt-2 text-xs text-muted-foreground">暂无数据</p>
            ) : (
              <ol className="mt-2 space-y-1.5">
                {board.map((entry, idx) => (
                  <li key={entry.event_id || `${entry.title}-${idx}`} className="text-xs">
                    {entry.event_id ? (
                      <button
                        type="button"
                        onClick={() => setDetailId(entry.event_id!)}
                        className="flex w-full items-center gap-2 text-left hover:text-primary"
                      >
                        <span className="w-5 shrink-0 font-mono text-muted-foreground">{idx + 1}</span>
                        <span className="min-w-0 flex-1 truncate">{entry.title}</span>
                        <span className="shrink-0 font-medium text-amber-600">{entry.pick_days} 天</span>
                      </button>
                    ) : (
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <span className="w-5 font-mono">{idx + 1}</span>
                        <span className="min-w-0 flex-1 truncate">{entry.title}</span>
                        <span>{entry.pick_days} 天</span>
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </div>

          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="flex items-center gap-1.5 text-sm font-medium">
              <CalendarDays className="h-4 w-4 text-sky-500" /> 每日 Top5 记录
            </h2>
            {pickDates.length === 0 ? (
              <p className="mt-2 text-xs text-muted-foreground">所选区间暂无记录</p>
            ) : (
              <div className="mt-2 max-h-72 space-y-3 overflow-y-auto pr-1">
                {pickDates.map((date) => (
                  <div key={date}>
                    <div className="text-[11px] font-medium text-muted-foreground">{date}</div>
                    <ul className="mt-1 space-y-1">
                      {picksByDate[date]
                        .slice()
                        .sort((a, b) => a.rank_position - b.rank_position)
                        .map((pick) => (
                          <li key={pick.id} className="flex items-start gap-1.5 text-xs">
                            <span className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                              #{pick.rank_position}
                            </span>
                            <span className="min-w-0 flex-1">
                              {pick.event_id ? (
                                <button
                                  type="button"
                                  onClick={() => setDetailId(pick.event_id!)}
                                  className="text-left hover:text-primary"
                                >
                                  {pick.title_snapshot}
                                </button>
                              ) : (
                                <span className="text-muted-foreground line-through">
                                  {pick.title_snapshot}（已丢弃）
                                </span>
                              )}
                              <span className="mt-0.5 block text-[10px] text-muted-foreground">
                                {(pick.source_channels || []).join(" · ") || "来源未知"}
                              </span>
                            </span>
                          </li>
                        ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <p className="mt-3 text-xs text-muted-foreground">
        超过 7 天的已证实事件无法在 Task Force 页直接发起分析，可在此打开事件，通过详情中的「启动 Task Force」按钮发起。
        <button type="button" onClick={onGoTaskForce} className="ml-1 text-primary hover:underline">
          前往 Task Force
        </button>
      </p>

      {detailId && (
        <EventDetailDialog
          eventId={detailId}
          onClose={() => setDetailId(null)}
          onChanged={() => void load()}
          onAnalyzed={onGoTaskForce}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 3: macro Task Force
// ---------------------------------------------------------------------------

function TaskForceTab({ onGoArchive }: { onGoArchive: () => void }) {
  const [events, setEvents] = useState<RadarEvent[]>([]);
  const [reports, setReports] = useState<EventReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedEventId, setSelectedEventId] = useState("");
  const [customTitle, setCustomTitle] = useState("");
  const [customPeriod, setCustomPeriod] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [openReportId, setOpenReportId] = useState<string | null>(null);
  const [evalReportId, setEvalReportId] = useState<string | null>(null);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);
  const [actionId, setActionId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [candidates, reportsRes] = await Promise.all([
        api.radarTfCandidates(),
        api.eventReports(),
      ]);
      setEvents(candidates.items);
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
      setSelectedEventId("");
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

  const cancelReport = async (report: EventReport) => {
    if (!window.confirm(`确认取消「${report.title.slice(0, 40)}」的分析？`)) return;
    setActionId(report.id);
    try {
      await api.eventReportCancel(report.id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "取消失败");
    } finally {
      setActionId(null);
    }
  };

  const deleteReport = async (report: EventReport) => {
    if (!window.confirm(`确认删除报告「${report.title.slice(0, 40)}」？此操作不可恢复。`)) return;
    setActionId(report.id);
    try {
      await api.eventReportDelete(report.id);
      setCompareIds((ids) => ids.filter((id) => id !== report.id));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setActionId(null);
    }
  };

  const retryReport = async (report: EventReport) => {
    setActionId(report.id);
    try {
      await api.eventReportRetry(report.id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "重试失败");
    } finally {
      setActionId(null);
    }
  };

  const toggleCompare = (report: EventReport) => {
    if (!report.markdown) return;
    setCompareIds((ids) => {
      if (ids.includes(report.id)) return ids.filter((id) => id !== report.id);
      if (ids.length >= 2) return [ids[1], report.id];
      return [...ids, report.id];
    });
  };

  const openReport = openReportId ? reports.find((r) => r.id === openReportId) ?? null : null;
  const evalReport = evalReportId ? reports.find((r) => r.id === evalReportId) ?? null : null;

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
            仅支持近 7 天内已证实的雷达事件；四角色团队（情报官 → 影响分析 → 历史类比 → 策略）产出未来 3–6 个月影响报告。更早的事件请到
            <button type="button" onClick={onGoArchive} className="mx-0.5 text-primary hover:underline">事件档案</button>
            发起。
          </p>
          <div className="mt-3 flex gap-2">
            <select
              value={selectedEventId}
              onChange={(e) => setSelectedEventId(e.target.value)}
              className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            >
              <option value="">选择近 7 天已证实事件…</option>
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
            <p className="mt-2 text-xs text-muted-foreground">近 7 天暂无已证实事件。</p>
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

      <div className="mb-2 mt-5 flex items-center gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-medium">
          <FileText className="h-4 w-4" /> 分析报告
          <button type="button" onClick={() => void load()} className="ml-1 text-muted-foreground hover:text-foreground" title="刷新">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </h2>
        <button
          type="button"
          onClick={() => setComparing(true)}
          disabled={compareIds.length !== 2}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs hover:bg-muted/60 disabled:opacity-40"
        >
          <GitCompare className="h-3.5 w-3.5" />
          对比所选（{compareIds.length}/2）
        </button>
        {compareIds.length > 0 && (
          <button
            type="button"
            onClick={() => setCompareIds([])}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            清除勾选
          </button>
        )}
      </div>

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
            const retryable = report.status === "failed" || report.status === "incomplete" || report.status === "canceled";
            const evaluatable = report.status === "completed" || report.status === "incomplete";
            const checked = compareIds.includes(report.id);
            const busy = actionId === report.id;
            return (
              <div
                key={report.id}
                className={cn(
                  "rounded-lg border bg-card p-3",
                  checked ? "border-primary/60 ring-1 ring-primary/30" : "border-border",
                )}
              >
                <div className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!report.markdown}
                    title={report.markdown ? "勾选后与另一篇报告并排对比" : "报告尚未产出"}
                    onChange={() => toggleCompare(report)}
                    className="mt-1 h-4 w-4 accent-primary"
                  />
                  <div
                    role={report.markdown ? "button" : undefined}
                    onClick={() => report.markdown && setOpenReportId(report.id)}
                    className={cn("min-w-0 flex-1", report.markdown && "cursor-pointer")}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      {running ? <Loader2 className="h-4 w-4 animate-spin text-sky-500" /> : <FileText className="h-4 w-4 text-muted-foreground" />}
                      <span className="truncate text-sm font-medium">{report.title}</span>
                      <Badge label={meta.label} cls={meta.cls} />
                      {report.eval_rating && EVAL_META[report.eval_rating] && (
                        <Badge label={EVAL_META[report.eval_rating].label} cls={EVAL_META[report.eval_rating].cls} />
                      )}
                      {report.markdown && <ArrowRight className="h-4 w-4 text-muted-foreground" />}
                    </div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                      {report.mode === "live" ? "当下展望" : "历史复盘"} · {report.time_horizon || "—"}
                    </div>
                    <div className="text-[11px] text-muted-foreground">
                      生成于 {fmtDateTime(report.completed_at || report.created_at)}
                    </div>
                    {(report.expected_outcome || report.guidance) && (
                      <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                        {report.expected_outcome && (
                          <div className="line-clamp-2">预期结果：{report.expected_outcome}</div>
                        )}
                        {report.guidance && (
                          <div className="line-clamp-2">指导建议：{report.guidance}</div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap items-center justify-end gap-1.5 border-t border-border/60 pt-2">
                  {running && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void cancelReport(report)}
                      className="inline-flex items-center gap-1 rounded-md border border-zinc-400/40 px-2 py-1 text-[11px] text-zinc-500 hover:bg-muted/60 disabled:opacity-50"
                    >
                      {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Ban className="h-3 w-3" />}
                      取消
                    </button>
                  )}
                  {retryable && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void retryReport(report)}
                      className="inline-flex items-center gap-1 rounded-md border border-sky-500/40 px-2 py-1 text-[11px] text-sky-600 hover:bg-sky-500/10 disabled:opacity-50"
                    >
                      {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
                      失败重试
                    </button>
                  )}
                  {evaluatable && (
                    <button
                      type="button"
                      onClick={() => setEvalReportId(report.id)}
                      className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 px-2 py-1 text-[11px] text-amber-600 hover:bg-amber-500/10"
                    >
                      <ClipboardCheck className="h-3 w-3" />
                      事后评价
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void deleteReport(report)}
                    className="inline-flex items-center gap-1 rounded-md border border-red-500/40 px-2 py-1 text-[11px] text-red-600 hover:bg-red-500/10 disabled:opacity-50"
                  >
                    <Trash2 className="h-3 w-3" />
                    删除
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {openReport && (
        <ReportDialog
          report={openReport}
          onClose={() => setOpenReportId(null)}
          onChanged={() => void load()}
        />
      )}
      {evalReport && (
        <EvaluateDialog
          report={evalReport}
          onClose={() => setEvalReportId(null)}
          onSaved={() => {
            setEvalReportId(null);
            void load();
          }}
        />
      )}
      {comparing && compareIds.length === 2 && (
        <CompareDialog reportIds={compareIds} onClose={() => setComparing(false)} />
      )}
    </div>
  );
}

function ReportDialog({
  report,
  onClose,
  onChanged,
}: {
  report: EventReport;
  onClose: () => void;
  onChanged?: () => void;
}) {
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
              {" · 生成于 "}{fmtDateTime(report.completed_at || report.created_at)}
            </div>
            {(report.expected_outcome || report.guidance) && (
              <div className="mt-1.5 max-w-2xl space-y-0.5 rounded-md border border-border p-2 text-xs text-muted-foreground">
                {report.expected_outcome && <div>预期结果：{report.expected_outcome}</div>}
                {report.guidance && <div>指导建议：{report.guidance}</div>}
              </div>
            )}
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
        {onChanged && (
          <div className="border-t border-border p-3 text-right">
            <button
              type="button"
              onClick={onChanged}
              className="rounded-md border border-border px-2.5 py-1 text-xs hover:bg-muted/60"
            >
              <RefreshCw className="mr-1 inline h-3 w-3 align-text-bottom" />
              刷新报告状态
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function EvaluateDialog({
  report,
  onClose,
  onSaved,
}: {
  report: EventReport;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [rating, setRating] = useState<EvalRating>(report.eval_rating ?? "accurate");
  const [note, setNote] = useState(report.eval_note ?? "");
  const [periodStart, setPeriodStart] = useState(report.eval_period_start ?? "");
  const [periodEnd, setPeriodEnd] = useState(report.eval_period_end ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await api.eventReportEvaluate(report.id, {
        rating,
        note: note.trim() || undefined,
        period_start: periodStart || undefined,
        period_end: periodEnd || undefined,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4" onClick={onClose}>
      <div className="my-8 w-full max-w-lg rounded-xl border border-border bg-card shadow-lg" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b border-border p-4">
          <div>
            <h2 className="text-base font-semibold">事后复盘评价</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">{report.title}</p>
          </div>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-3 p-4 text-sm">
          <div>
            <label className="text-xs text-muted-foreground">分析结果准确性</label>
            <select
              value={rating}
              onChange={(e) => setRating(e.target.value as EvalRating)}
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5"
            >
              <option value="accurate">准确 — 方向与节奏基本兑现</option>
              <option value="partial">部分准确 — 大方向对、细节偏差</option>
              <option value="off">偏离 — 与实际发展明显不符</option>
              <option value="wrong">错误 — 判断完全失误</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">复盘说明</label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={4}
              placeholder="数月/数年后回看：哪些判断兑现了，哪些错了，为什么？"
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            />
          </div>
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">观察区间起</label>
              <input
                type="date"
                value={periodStart}
                onChange={(e) => setPeriodStart(e.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5"
              />
            </div>
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">观察区间止</label>
              <input
                type="date"
                value={periodEnd}
                onChange={(e) => setPeriodEnd(e.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5"
              />
            </div>
          </div>
          {error && <div className="rounded-md border border-red-500/40 bg-red-500/10 p-2 text-xs text-red-500">{error}</div>}
        </div>
        <div className="flex justify-end gap-2 border-t border-border p-3">
          <button type="button" onClick={onClose} className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60">
            取消
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving}
            className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            保存评价
          </button>
        </div>
      </div>
    </div>
  );
}

function CompareDialog({ reportIds, onClose }: { reportIds: string[]; onClose: () => void }) {
  const [reports, setReports] = useState<EventReport[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const loaded = await Promise.all(reportIds.map((id) => api.eventReport(id)));
        if (!cancelled) setReports(loaded);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "报告加载失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reportIds]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4" onClick={onClose}>
      <div className="my-8 w-full max-w-6xl rounded-xl border border-border bg-card shadow-lg" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-3 border-b border-border p-4">
          <h2 className="flex items-center gap-1.5 text-base font-semibold">
            <GitCompare className="h-4 w-4" /> 报告并排对比
            <span className="text-xs font-normal text-muted-foreground">（原文对照，不做 AI 总结）</span>
          </h2>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        {error ? (
          <div className="p-4 text-sm text-red-500">{error}</div>
        ) : reports.length !== 2 ? (
          <div className="flex h-40 items-center justify-center text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
          </div>
        ) : (
          <div className="grid max-h-[75vh] grid-cols-1 gap-0 overflow-hidden md:grid-cols-2">
            {reports.map((report, idx) => (
              <div key={report.id} className={cn("min-w-0 overflow-y-auto p-4", idx === 0 && "md:border-r md:border-border")}>
                <div className="mb-2">
                  <div className="text-sm font-semibold">{report.title}</div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    {report.mode === "live" ? "当下展望" : "历史复盘"} · 生成于 {fmtDateTime(report.completed_at || report.created_at)}
                  </div>
                </div>
                {report.markdown ? (
                  <MarkdownContent content={report.markdown} />
                ) : (
                  <div className="text-sm text-muted-foreground">报告尚未产出。</div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
