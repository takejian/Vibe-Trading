import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import {
  api,
  type WatchKlineInterval,
  type WatchKlineLevel,
  type WatchKlineSource,
  type WatchKlineStatusValue,
} from "@/lib/api";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";

/**
 * Multi-level K-line readiness card for the Objective-data tab (BDD US-08A).
 *
 * Shows the five levels the Chanlun analyst requires (day/week/month/
 * quarter/year) with one-button bulk update and per-level retry, plus a
 * standalone optional 30-minute fetch. All updates hit data APIs directly
 * (never the AI stack); a failed level keeps its old bars and shows the
 * failure with retry guidance. The data vendor is user-selectable (same
 * vocabulary/order as Settings -> data-source priority) and any failed
 * attempt is surfaced in an error dialog carrying the vendor error text.
 */
const REQUIRED_INTERVALS: WatchKlineInterval[] = ["1d", "1w", "1mo", "1q", "1y"];

const SOURCE_STORAGE_KEY = "vibe_watch_kline_source";

const STATUS_STYLES: Record<WatchKlineStatusValue, string> = {
  ready: "border-green-500/40 bg-green-500/10 text-green-700 dark:text-green-400",
  insufficient:
    "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  not_fetched: "border-border bg-muted/50 text-muted-foreground",
  failed: "border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400",
};

interface ErrorEntry {
  interval: WatchKlineInterval | null;
  source: string | null;
  error: string;
}

export function KlineReadinessCard({ symbol }: { symbol: string }) {
  const { t } = useTranslation();
  const [items, setItems] = useState<WatchKlineLevel[]>([]);
  const [sources, setSources] = useState<WatchKlineSource[]>([]);
  const [source, setSource] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [busyAll, setBusyAll] = useState(false);
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null,
  );
  const [errorEntries, setErrorEntries] = useState<ErrorEntry[] | null>(null);

  const sourceName = useCallback(
    (id: string | null | undefined): string => {
      if (!id) return "—";
      const fallback = `watch.kline.sources.${id}`;
      const translated = t(`watch.kline.sources.${id}` as never);
      return translated === fallback ? id : translated;
    },
    [t],
  );

  const load = useCallback(async () => {
    setLoadError(false);
    const [statusResult, sourcesResult] = await Promise.allSettled([
      api.getWatchKlineStatus(symbol),
      api.getWatchKlineSources(symbol),
    ]);
    if (statusResult.status === "fulfilled") {
      setItems(statusResult.value.items);
    } else {
      setLoadError(true);
    }
    if (sourcesResult.status === "fulfilled") {
      setSources(sourcesResult.value.items);
    }
    setLoading(false);
  }, [symbol]);

  useEffect(() => {
    void load();
  }, [load]);

  // Pick the remembered vendor when it is still available, otherwise the
  // first available vendor in Settings-priority order (never force
  // eastmoney, which may be unreachable on the current network).
  useEffect(() => {
    if (sources.length === 0) return;
    const byId = new Map(sources.map((entry) => [entry.id, entry]));
    const stored = safeReadStoredSource();
    if (stored && byId.get(stored)?.available) {
      setSource(stored);
      return;
    }
    const firstAvailable = sources.find((entry) => entry.available);
    setSource(firstAvailable?.id ?? sources[0]?.id ?? "");
  }, [sources]);

  const changeSource = (next: string) => {
    setSource(next);
    try {
      localStorage.setItem(SOURCE_STORAGE_KEY, next);
    } catch {
      /* private mode etc. - selection still works for this session */
    }
  };

  const markBusy = (intervals: string[], on: boolean) => {
    setBusy((prev) => {
      const next = new Set(prev);
      for (const interval of intervals) {
        if (on) next.add(interval);
        else next.delete(interval);
      }
      return next;
    });
  };

  const update = useCallback(
    async (intervals: WatchKlineInterval[]) => {
      setMessage(null);
      markBusy(intervals as string[], true);
      if (intervals.length === REQUIRED_INTERVALS.length) setBusyAll(true);
      try {
        const resp = await api.updateWatchKline(symbol, intervals, source || undefined);
        setItems(resp.items);
        const failed = resp.items.filter(
          (item) =>
            intervals.includes(item.interval) &&
            (item.fetch_failed || item.status === "failed"),
        );
        setMessage(
          failed.length > 0
            ? { kind: "err", text: t("watch.kline.updatePartial") }
            : { kind: "ok", text: t("watch.kline.updateDone") },
        );
        if (failed.length > 0) {
          // The error belongs to THIS attempt, so show the vendor the user
          // selected; the table badge separately keeps the bars' provenance
          // (a failed attempt never overwrites the previous source).
          setErrorEntries(
            failed.map((item) => ({
              interval: item.interval,
              source: source || item.source,
              error: item.last_error ?? t("watch.kline.loadFailed"),
            })),
          );
        }
      } catch (err) {
        // Whole-request failure (network error, 400 for an unavailable
        // vendor, ...) - still surface the detail in the error dialog.
        setMessage({ kind: "err", text: t("watch.kline.loadFailed") });
        setErrorEntries([
          {
            interval: null,
            source: source || null,
            error: err instanceof Error ? err.message : t("watch.kline.loadFailed"),
          },
        ]);
      } finally {
        markBusy(intervals as string[], false);
        setBusyAll(false);
      }
    },
    [symbol, source, t],
  );

  const retryFailedIntervals = () => {
    if (!errorEntries) return;
    const intervals = errorEntries
      .map((entry) => entry.interval)
      .filter((interval): interval is WatchKlineInterval => interval !== null);
    setErrorEntries(null);
    if (intervals.length > 0) void update(intervals);
  };

  if (loading) {
    return (
      <section
        className="rounded-md border border-border p-4"
        data-testid="kline-card"
      >
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      </section>
    );
  }

  if (loadError) {
    return (
      <section
        className="rounded-md border border-border p-4 text-sm"
        data-testid="kline-card"
      >
        <p role="alert" className="text-red-500" data-testid="kline-load-error">
          {t("watch.kline.loadFailed")}
        </p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-2 text-xs text-primary hover:underline"
        >
          {t("watch.kline.retry")}
        </button>
      </section>
    );
  }

  const requiredRows = REQUIRED_INTERVALS.map(
    (interval) => items.find((item) => item.interval === interval),
  ).filter((item): item is WatchKlineLevel => Boolean(item));
  const optional = items.find((item) => item.interval === "30m");
  const anyFailure = items.some(
    (item) =>
      item.interval !== "30m" &&
      (item.fetch_failed || item.status === "failed"),
  );
  const anyBusy = busyAll || busy.size > 0;
  const dialogRetryIntervals = (errorEntries ?? [])
    .map((entry) => entry.interval)
    .some((interval) => interval !== null);

  return (
    <section className="rounded-md border border-border p-4" data-testid="kline-card">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t("watch.kline.title")}</h3>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span>{t("watch.kline.sourceLabel")}</span>
            <select
              className="rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground disabled:opacity-60"
              value={source}
              disabled={anyBusy}
              onChange={(event) => changeSource(event.target.value)}
              data-testid="kline-source-select"
              aria-label={t("watch.kline.sourceLabel")}
            >
              {sources.map((entry) => {
                const reasonText = entry.reason
                  ? t(`watch.kline.reason.${entry.reason}`)
                  : "";
                const authNote =
                  entry.requires_auth && entry.available
                    ? ` (${t("watch.kline.reason.needs_auth")})`
                    : "";
                const disabledNote = !entry.available ? ` (${reasonText})` : "";
                return (
                  <option
                    key={entry.id}
                    value={entry.id}
                    disabled={!entry.available}
                  >
                    {sourceName(entry.id)}
                    {authNote}
                    {disabledNote}
                  </option>
                );
              })}
            </select>
          </label>
          <button
            type="button"
            disabled={anyBusy || !source}
            onClick={() => void update(REQUIRED_INTERVALS)}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="kline-update-all"
          >
            {anyBusy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
            {t("watch.kline.updateAll")}
          </button>
        </div>
      </div>
      <p className="mb-3 text-xs text-muted-foreground">
        {t("watch.kline.subtitle")}
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="whitespace-nowrap px-2 py-1.5">
                {t("watch.kline.levelCol")}
              </th>
              <th className="whitespace-nowrap px-2 py-1.5">
                {t("watch.kline.statusCol")}
              </th>
              <th className="whitespace-nowrap px-2 py-1.5">
                {t("watch.kline.barsCol")}
              </th>
              <th className="whitespace-nowrap px-2 py-1.5">
                {t("watch.kline.firstCol")}
              </th>
              <th className="whitespace-nowrap px-2 py-1.5">
                {t("watch.kline.latestCol")}
              </th>
              <th className="whitespace-nowrap px-2 py-1.5">
                {t("watch.kline.updatedCol")}
              </th>
              <th className="whitespace-nowrap px-2 py-1.5">
                {t("watch.kline.actionCol")}
              </th>
            </tr>
          </thead>
          <tbody>
            {requiredRows.map((row) => {
              const isBusy = busy.has(row.interval);
              const needsRetry = row.status !== "ready" || row.fetch_failed;
              return (
                <tr key={row.interval} className="border-t border-border/40">
                  <td className="whitespace-nowrap px-2 py-1.5 font-medium">
                    {t(`watch.kline.levels.${row.interval}`)}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5">
                    <span
                      className={`inline-block rounded border px-1.5 py-0.5 ${STATUS_STYLES[row.status]}`}
                      data-testid={`kline-status-${row.interval}`}
                    >
                      {t(`watch.kline.state.${row.status}`)}
                    </span>
                    {row.fetch_failed && row.status === "ready" && (
                      <span
                        className="ml-1 rounded border border-red-500/40 bg-red-500/10 px-1.5 py-0.5 text-red-600 dark:text-red-400"
                        data-testid={`kline-stale-${row.interval}`}
                      >
                        {t("watch.kline.state.failed")}
                      </span>
                    )}
                    {row.source && (
                      <span
                        className="ml-1 rounded border border-border bg-muted/40 px-1.5 py-0.5 text-muted-foreground"
                        data-testid={`kline-source-badge-${row.interval}`}
                      >
                        {sourceName(row.source)}
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5">
                    {row.bars_count}
                  </td>
                  <td
                    className="whitespace-nowrap px-2 py-1.5"
                    data-testid={`kline-earliest-${row.interval}`}
                  >
                    {row.earliest_bar_time
                      ? String(row.earliest_bar_time).slice(0, 10)
                      : t("watch.noData")}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5">
                    {row.latest_bar_time
                      ? String(row.latest_bar_time).slice(0, 10)
                      : t("watch.noData")}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5">
                    {row.last_ok_at ? row.last_ok_at.replace("T", " ") : "—"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5">
                    {needsRetry && (
                      <button
                        type="button"
                        disabled={isBusy}
                        onClick={() => void update([row.interval])}
                        className="inline-flex items-center gap-1 rounded border border-primary/40 px-2 py-0.5 text-primary hover:underline disabled:opacity-60"
                        data-testid={`kline-retry-${row.interval}`}
                      >
                        {isBusy && (
                          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                        )}
                        {t("watch.kline.retry")}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {anyFailure && (
        <p
          role="alert"
          className="mt-2 rounded border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-600 dark:text-red-400"
          data-testid="kline-fail-hint"
        >
          {t("watch.kline.failHint")}
        </p>
      )}

      {message && (
        <p
          role="status"
          className={`mt-2 text-xs ${
            message.kind === "ok" ? "text-green-600 dark:text-green-400" : "text-red-500"
          }`}
          data-testid="kline-message"
        >
          {message.text}
        </p>
      )}

      {optional && (
        <div
          className="mt-4 rounded-md border border-dashed border-border p-3"
          data-testid="kline-30m"
        >
          <p className="mb-2 text-xs text-muted-foreground">
            {t("watch.kline.optional30m")}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={busy.has("30m") || !source}
              onClick={() => void update(["30m"])}
              className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-xs hover:bg-muted/60 disabled:opacity-60"
              data-testid="kline-30m-btn"
            >
              {busy.has("30m") && (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              )}
              {optional.status === "ready" && !optional.fetch_failed
                ? t("watch.kline.retry")
                : t("watch.kline.fetch30m")}
            </button>
            <span
              className={`rounded border px-1.5 py-0.5 ${STATUS_STYLES[optional.status]}`}
              data-testid="kline-status-30m"
            >
              {t(`watch.kline.state.${optional.status}`)}
            </span>
            {optional.source && (
              <span className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-xs text-muted-foreground">
                {sourceName(optional.source)}
              </span>
            )}
            {optional.earliest_bar_time && (
              <span
                className="text-xs text-muted-foreground"
                data-testid="kline-earliest-30m"
              >
                {String(optional.earliest_bar_time).slice(0, 16)}
                {optional.latest_bar_time ? " → " : ""}
                {optional.latest_bar_time
                  ? String(optional.latest_bar_time).slice(0, 16)
                  : ""}
              </span>
            )}
            {!optional.earliest_bar_time && optional.latest_bar_time && (
              <span className="text-xs text-muted-foreground">
                {optional.bars_count} · {String(optional.latest_bar_time).slice(0, 16)}
              </span>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={errorEntries !== null}
        title={t("watch.kline.errorDialogTitle")}
        description={t("watch.kline.errorDialogHint")}
        confirmLabel={t("watch.kline.retryFailed")}
        cancelLabel={t("watch.kline.close")}
        tone="destructive"
        confirmDisabled={!dialogRetryIntervals || anyBusy}
        onConfirm={retryFailedIntervals}
        onCancel={() => setErrorEntries(null)}
      >
        <ul className="max-h-64 space-y-2 overflow-y-auto text-xs" data-testid="kline-error-dialog">
          {(errorEntries ?? []).map((entry, idx) => (
            <li
              key={entry.interval ?? `request-${idx}`}
              className="rounded border border-red-500/30 bg-red-500/5 p-2"
              data-testid={
                entry.interval
                  ? `kline-error-row-${entry.interval}`
                  : "kline-error-row-request"
              }
            >
              <p className="font-medium text-foreground">
                {entry.interval
                  ? t(`watch.kline.levels.${entry.interval}`)
                  : t("watch.kline.errorDialogRequest")}
                {" · "}
                {sourceName(entry.source)}
              </p>
              <p className="mt-1 break-all text-red-600 dark:text-red-400">
                {entry.error}
              </p>
            </li>
          ))}
        </ul>
      </ConfirmDialog>
    </section>
  );
}

function safeReadStoredSource(): string | null {
  try {
    return localStorage.getItem(SOURCE_STORAGE_KEY);
  } catch {
    return null;
  }
}
