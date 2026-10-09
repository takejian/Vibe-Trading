import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Loader2 } from "lucide-react";
import {
  api,
  type ChanlunCardRecord,
  type ChanlunLiveStatus,
  type ChanlunOutcomeLabel,
  type ChanlunUserVerdict,
} from "@/lib/api";

const RED = "text-red-600 dark:text-red-400";
const GREEN = "text-green-600 dark:text-green-400";

export function fmtPrice(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : v.toFixed(2);
}

export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return "";
  return v > 0 ? RED : GREEN;
}

export function liveStatusClass(status: ChanlunLiveStatus | null): string {
  switch (status) {
    case "target_hit":
      return "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400";
    case "stopped":
      return "border-green-500/40 bg-green-500/10 text-green-700 dark:text-green-400";
    case "active":
      return "border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-400";
    case "insufficient_data":
      return "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400";
    default:
      return "border-border bg-muted/40 text-muted-foreground";
  }
}

export function outcomeClass(label: ChanlunOutcomeLabel | null): string {
  switch (label) {
    case "win":
    case "timeout_correct":
      return "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400";
    case "loss":
    case "timeout_wrong":
      return "border-green-500/40 bg-green-500/10 text-green-700 dark:text-green-400";
    case "partial":
      return "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400";
    default:
      return "border-border bg-muted/40 text-muted-foreground";
  }
}

function PriceItem({ label, value, valueClass = "" }: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-md border border-border/70 bg-background px-2 py-1">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={`font-mono text-xs font-semibold ${valueClass}`}>{value}</div>
    </div>
  );
}

function Chips({ record }: {
  record: ChanlunCardRecord;
}) {
  const { t } = useTranslation();
  const dir = record.direction;
  const dirBadge =
    dir === "bullish"
      ? "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400"
      : dir === "bearish"
        ? "border-green-500/40 bg-green-500/10 text-green-700 dark:text-green-400"
        : "border-border bg-muted/40 text-muted-foreground";
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className={`rounded border px-1.5 py-0.5 text-[11px] font-semibold ${dirBadge}`}>
        {t(`watch.ch.dir.${dir ?? "neutral"}`)}
      </span>
      {record.action && (
        <span className="rounded border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-[11px]">
          {t(`watch.ch.act.${record.action}`)}
        </span>
      )}
      {record.setup_class && record.setup_class !== "none" && (
        <span className="rounded border border-border bg-muted/50 px-1.5 py-0.5 text-[11px]">
          {record.setup_class}
        </span>
      )}
      <span className="text-[11px] text-muted-foreground">
        {t("watch.ch.card.confidence")} {Math.round((record.card_confidence ?? 0))}%
      </span>
      {record.live_status && (
        <span
          className={`rounded border px-1.5 py-0.5 text-[10px] ${liveStatusClass(
            record.live_status,
          )}`}
          data-testid="card-live-status"
        >
          {t(`watch.ch.live.${record.live_status}`)}
        </span>
      )}
      {record.eval_status === "verified" && record.outcome_label && (
        <span
          className={`rounded border px-1.5 py-0.5 text-[10px] ${outcomeClass(
            record.outcome_label,
          )}`}
          data-testid="card-outcome"
        >
          {t(`watch.ch.out.${record.outcome_label}`)}
        </span>
      )}
      {record.eval_status === "insufficient_data" && (
        <span
          className={`rounded border px-1.5 py-0.5 text-[10px] ${liveStatusClass(
            "insufficient_data",
          )}`}
        >
          {t("watch.ch.out.insufficient_data")}
        </span>
      )}
    </div>
  );
}

function RatingBlock({ record, symbol, onRated }: {
  record: ChanlunCardRecord;
  symbol: string;
  onRated?: () => void;
}) {
  const { t } = useTranslation();
  const [verdict, setVerdict] = useState<ChanlunUserVerdict | "">(
    record.user_verdict ?? "",
  );
  const [note, setNote] = useState(record.user_note ?? "");
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(record.user_rated_at ?? "");

  const choices: ChanlunUserVerdict[] = ["accurate", "partial", "wrong"];
  const submit = async () => {
    if (!verdict || saving) return;
    setSaving(true);
    try {
      const res = await api.rateChanlunCard(
        symbol,
        record.run_id,
        verdict,
        note.trim() || undefined,
      );
      setSavedAt(res.user_rated_at ?? "");
      onRated?.();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="mt-2 rounded-md border border-dashed border-border bg-muted/20 px-2.5 py-2"
      data-testid="card-rating"
    >
      <div className="mb-1 text-[11px] font-semibold text-muted-foreground">
        {t("watch.ch.card.rating")}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {choices.map((choice) => (
          <button
            key={choice}
            type="button"
            onClick={() => setVerdict(choice)}
            aria-pressed={verdict === choice}
            className={`rounded border px-2 py-0.5 text-[11px] ${
              verdict === choice
                ? "border-primary bg-primary/15 text-primary"
                : "border-border hover:bg-muted/60"
            }`}
            data-testid={`rate-${choice}`}
          >
            {t(`watch.ch.rate.${choice}`)}
          </button>
        ))}
        <button
          type="button"
          disabled={!verdict || saving}
          onClick={() => void submit()}
          className="ml-auto inline-flex items-center gap-1 rounded-md bg-primary px-2 py-0.5 text-[11px] text-primary-foreground disabled:opacity-40"
          data-testid="rate-save"
        >
          {saving ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : null}
          {t("watch.ch.card.saveRating")}
        </button>
        {savedAt && !saving && (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground">
            <Check className="h-3 w-3" aria-hidden="true" />
            {t("watch.ch.card.ratedAt", { when: savedAt })}
          </span>
        )}
      </div>
      <input
        type="text"
        value={note}
        maxLength={200}
        onChange={(e) => setNote(e.target.value)}
        placeholder={t("watch.ch.card.notePlaceholder")}
        className="mt-1.5 w-full rounded-md border border-border bg-background px-2 py-1 text-xs outline-none focus:border-primary"
        data-testid="rate-note"
      />
    </div>
  );
}

export function ChanlunActionCard({
  record,
  symbol,
  compact = false,
  onRated,
}: {
  record: ChanlunCardRecord;
  symbol: string;
  compact?: boolean;
  onRated?: () => void;
}) {
  const { t } = useTranslation();
  if (record.card_parse !== "ok" || !record.direction) return null;
  const isPlan = record.direction !== "neutral";
  const targets = record.target_prices ?? [];

  return (
    <div
      className="rounded-lg border border-border bg-muted/10 px-3 py-2 text-sm"
      data-testid="chanlun-action-card"
    >
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold">{t("watch.ch.card.title")}</span>
        <Chips record={record} />
      </div>
      {record.one_liner && (
        <p className="mb-2 text-[13px] font-medium" data-testid="card-one-liner">
          {record.one_liner}
        </p>
      )}
      {isPlan && (
        <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
          <PriceItem
            label={t("watch.ch.card.base")}
            value={`${fmtPrice(record.base_price)}${
              record.base_date ? ` ${record.base_date.slice(5)}` : ""
            }`}
          />
          <PriceItem
            label={t("watch.ch.card.trigger")}
            value={fmtPrice(record.trigger_price)}
            valueClass={RED}
          />
          <PriceItem
            label={t("watch.ch.card.stop")}
            value={fmtPrice(record.stop_price)}
            valueClass={GREEN}
          />
          <PriceItem
            label={t("watch.ch.card.target")}
            value={targets.length ? targets.map((v) => v.toFixed(2)).join("/") : "—"}
            valueClass={RED}
          />
          <PriceItem
            label={t("watch.ch.card.rr")}
            value={
              record.rr_at_t1 === null || record.rr_at_t1 === undefined
                ? "—"
                : record.rr_at_t1.toFixed(2)
            }
          />
          <PriceItem
            label={t("watch.ch.card.horizon")}
            value={t("watch.ch.card.days", { n: record.horizon_days ?? "—" })}
          />
        </div>
      )}
      {!compact && isPlan && (record.invalidation || record.key_risks) && (
        <div className="mt-2 grid gap-1 text-[11px] text-muted-foreground sm:grid-cols-2">
          {record.invalidation && (
            <p>
              <span className="font-semibold">{t("watch.ch.card.invalidation")}：</span>
              {record.invalidation}
            </p>
          )}
          {record.key_risks && (
            <p>
              <span className="font-semibold">{t("watch.ch.card.risks")}：</span>
              {record.key_risks}
            </p>
          )}
        </div>
      )}
      {!compact && record.eval_status === "verified" &&
        record.outcome_label && record.outcome_label !== "neutral" && (
          <div
            className="mt-2 flex flex-wrap gap-x-4 gap-y-1 border-t border-border/60 pt-2 text-[11px]"
            data-testid="card-outcome-stats"
          >
            <span>
              {t("watch.ch.card.mfe")}：
              <span className={`font-mono font-semibold ${pctClass(record.mfe_pct)}`}>
                {fmtPct(record.mfe_pct)}
              </span>
            </span>
            <span>
              {t("watch.ch.card.mae")}：
              <span className={`font-mono font-semibold ${pctClass(record.mae_pct)}`}>
                {fmtPct(record.mae_pct)}
              </span>
            </span>
            <span>
              {t("watch.ch.card.exitReturn")}：
              <span className={`font-mono font-semibold ${pctClass(record.exit_return_pct)}`}>
                {fmtPct(record.exit_return_pct)}
              </span>
            </span>
            {record.window_end_date && (
              <span className="text-muted-foreground">
                {t("watch.ch.card.windowEnd")}：{record.window_end_date}
              </span>
            )}
          </div>
        )}
      {!compact && <RatingBlock record={record} symbol={symbol} onRated={onRated} />}
    </div>
  );
}
