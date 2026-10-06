import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, RotateCw } from "lucide-react";
import {
  api,
  type PriceBar,
  type WatchKlineInterval,
  type WatchKlineLevel,
} from "@/lib/api";
import { CandlestickChart } from "@/components/charts/CandlestickChart";
import { cn } from "@/lib/utils";

/**
 * Multi-level K-line chart panel for the Objective-data tab.
 *
 * Read-only view of the bars already fetched for the Chanlun analyst
 * (30m / day / week / month / quarter / year). Levels without stored bars
 * are hidden — switching tabs never triggers a network fetch; the refresh
 * action only re-reads local state. Bars are rendered with the shared
 * ECharts CandlestickChart (MA/BOLL overlays + volume/MACD/RSI/KDJ).
 */

// Tab order (low to high level).
const TAB_ORDER: WatchKlineInterval[] = [
  "30m",
  "1d",
  "1w",
  "1mo",
  "1q",
  "1y",
];

export function KlineChartPanel({ symbol }: { symbol: string }) {
  const { t } = useTranslation();
  const [levels, setLevels] = useState<WatchKlineLevel[]>([]);
  const [active, setActive] = useState<WatchKlineInterval | null>(null);
  const [barsCache, setBarsCache] = useState<
    Partial<Record<WatchKlineInterval, PriceBar[]>>
  >({});
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [statusError, setStatusError] = useState(false);
  const [loadingBars, setLoadingBars] = useState(false);
  const [barsError, setBarsError] = useState(false);

  // Guards against out-of-order responses when switching levels quickly.
  const barsReqId = useRef(0);

  const availableIntervals = useCallback(
    (rows: WatchKlineLevel[]): WatchKlineInterval[] => {
      const withBars = new Set(
        rows.filter((row) => row.bars_count > 0).map((row) => row.interval),
      );
      return TAB_ORDER.filter((interval) => withBars.has(interval));
    },
    [],
  );

  const loadBars = useCallback(
    async (interval: WatchKlineInterval) => {
      const reqId = ++barsReqId.current;
      setLoadingBars(true);
      setBarsError(false);
      try {
        const resp = await api.getWatchKlineBars(symbol, interval);
        if (reqId !== barsReqId.current) return;
        setBarsCache((prev) => ({ ...prev, [interval]: resp.items }));
      } catch {
        if (reqId !== barsReqId.current) return;
        setBarsError(true);
      } finally {
        if (reqId === barsReqId.current) setLoadingBars(false);
      }
    },
    [symbol],
  );

  const loadStatus = useCallback(async () => {
    setLoadingStatus(true);
    setStatusError(false);
    try {
      const resp = await api.getWatchKlineStatus(symbol);
      setLevels(resp.items);
      const available = availableIntervals(resp.items);
      setActive((prev) =>
        prev && available.includes(prev) ? prev : available[0] ?? null,
      );
    } catch {
      setStatusError(true);
    } finally {
      setLoadingStatus(false);
    }
  }, [symbol, availableIntervals]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  // Lazily load the selected level's bars once (cached afterwards).
  useEffect(() => {
    if (active && barsCache[active] === undefined) {
      void loadBars(active);
    }
  }, [active, barsCache, loadBars]);

  const refresh = useCallback(() => {
    void loadStatus();
    if (active) {
      // Drop the cached bars so the active level is re-read too.
      barsReqId.current += 1;
      setBarsCache((prev) => ({ ...prev, [active]: undefined }));
    }
  }, [active, loadStatus]);

  const retryBars = useCallback(() => {
    if (active) void loadBars(active);
  }, [active, loadBars]);

  const visibleLevels = availableIntervals(levels);
  const activeBars = active ? barsCache[active] : undefined;

  return (
    <section
      className="rounded-md border border-border p-4"
      data-testid="kline-chart-panel"
    >
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{t("watch.kline.chartTitle")}</h3>
        <button
          type="button"
          onClick={refresh}
          disabled={loadingStatus || visibleLevels.length === 0}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="kline-chart-refresh"
        >
          <RotateCw className="h-3 w-3" aria-hidden="true" />
          {t("watch.kline.chartRefresh")}
        </button>
      </div>
      <p className="mb-3 text-xs text-muted-foreground">
        {t("watch.kline.chartSubtitle")}
      </p>

      {loadingStatus && (
        <div className="py-6 text-center" data-testid="kline-chart-loading">
          <Loader2 className="mx-auto h-4 w-4 animate-spin" aria-hidden="true" />
        </div>
      )}

      {!loadingStatus && statusError && (
        <div className="py-2 text-sm" data-testid="kline-chart-status-error">
          <p role="alert" className="text-red-500">
            {t("watch.kline.chartLoadFailed")}
          </p>
          <button
            type="button"
            onClick={() => void loadStatus()}
            className="mt-2 text-xs text-primary hover:underline"
          >
            {t("watch.kline.retry")}
          </button>
        </div>
      )}

      {!loadingStatus && !statusError && visibleLevels.length === 0 && (
        <p
          className="rounded border border-dashed border-border px-3 py-4 text-xs text-muted-foreground"
          data-testid="kline-chart-empty"
        >
          {t("watch.kline.chartEmpty")}
        </p>
      )}

      {!loadingStatus && !statusError && visibleLevels.length > 0 && (
        <>
          <div className="mb-2 flex flex-wrap gap-1" role="tablist">
            {visibleLevels.map((interval) => (
              <button
                key={interval}
                type="button"
                role="tab"
                aria-selected={active === interval}
                onClick={() => setActive(interval)}
                className={cn(
                  "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                  active === interval
                    ? "bg-primary/15 text-primary"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
                data-testid={`kline-tab-${interval}`}
              >
                {t(`watch.kline.levels.${interval}`)}
              </button>
            ))}
          </div>

          {loadingBars && (
            <div className="py-10 text-center" data-testid="kline-bars-loading">
              <Loader2
                className="mx-auto h-4 w-4 animate-spin"
                aria-hidden="true"
              />
            </div>
          )}

          {!loadingBars && barsError && (
            <div
              className="py-6 text-center text-sm"
              data-testid="kline-bars-error"
            >
              <p role="alert" className="text-red-500">
                {t("watch.kline.chartLoadFailed")}
              </p>
              <button
                type="button"
                onClick={retryBars}
                className="mt-2 text-xs text-primary hover:underline"
              >
                {t("watch.kline.retry")}
              </button>
            </div>
          )}

          {!loadingBars && !barsError && activeBars !== undefined && (
            <div data-testid="kline-chart-body">
              <CandlestickChart data={activeBars} height={480} />
            </div>
          )}
        </>
      )}
    </section>
  );
}
