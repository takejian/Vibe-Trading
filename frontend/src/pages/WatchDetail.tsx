import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Loader2 } from "lucide-react";
import {
  ApiError,
  api,
  type CompanyProfile,
  type ObjectiveRawData,
  type ObjectiveRecord,
  type WatchProfileResponse,
} from "@/lib/api";
import { Skeleton } from "@/components/common/Skeleton";
import { MarkdownContent } from "@/components/common/MarkdownContent";
import { AnalysisTab } from "@/components/watch/AnalysisTab";
import { ChanlunHistory } from "@/components/watch/ChanlunHistory";
import { KlineReadinessCard } from "@/components/watch/KlineReadinessCard";

type TabKey = "overview" | "objective" | "fundamental" | "technical" | "ai";
const TABS: TabKey[] = ["overview", "objective", "fundamental", "technical", "ai"];

export function WatchDetail() {
  const { t, i18n } = useTranslation();
  const params = useParams<{ symbol: string }>();
  const symbol = decodeURIComponent(params.symbol ?? "");
  const locale = i18n.language || "en";

  const [tab, setTab] = useState<TabKey>("overview");
  const [profile, setProfile] = useState<WatchProfileResponse | null>(null);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [loading, setLoading] = useState(true);

  const [quotesBusy, setQuotesBusy] = useState(false);
  const [profileBusy, setProfileBusy] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const [raw, setRaw] = useState<ObjectiveRawData | null>(null);
  const [fetches, setFetches] = useState<ObjectiveRecord[]>([]);
  const [objectiveLoaded, setObjectiveLoaded] = useState(false);
  const [objectiveLoading, setObjectiveLoading] = useState(false);
  const [note, setNote] = useState("");
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState("");
  const [fetchRunId, setFetchRunId] = useState("");

  const loadProfile = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const resp = await api.getWatchProfile(symbol);
      setProfile(resp);
      setNotFound(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setNotFound(true);
      else setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [symbol]);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  const loadObjective = useCallback(async () => {
    setObjectiveLoading(true);
    try {
      const resp = await api.getObjective(symbol);
      setRaw(resp.raw);
      setFetches(resp.fetches);
      setObjectiveLoaded(true);
      // The background fetch has finished once its run shows up in the archive.
      setFetchRunId((prev) =>
        prev && resp.fetches.some((f) => f.run_id === prev) ? "" : prev,
      );
    } finally {
      setObjectiveLoading(false);
    }
  }, [symbol]);

  useEffect(() => {
    // Re-read on every entry: a background fetch may have archived meanwhile.
    if (tab === "objective" || tab === "fundamental") void loadObjective();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const fmt = (v: number | null | undefined, digits = 2) => {
    if (v === null || v === undefined || Number.isNaN(v)) return t("watch.noData");
    return new Intl.NumberFormat(locale, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(v);
  };
  const fmtCompact = (v: number | null | undefined) => {
    if (v === null || v === undefined || Number.isNaN(v)) return t("watch.noData");
    return new Intl.NumberFormat(locale, {
      notation: "compact",
      maximumFractionDigits: 2,
    }).format(v);
  };
  const textOrEmpty = (v: unknown) =>
    v === null || v === undefined || v === "" ? t("watch.noData") : String(v);

  const refreshQuotes = async () => {
    setQuotesBusy(true);
    setRefreshMsg(null);
    try {
      await api.refreshWatchQuotes(symbol);
      setRefreshMsg({ kind: "ok", text: t("watch.ov.updateSuccess") });
      await loadProfile();
    } catch {
      setRefreshMsg({ kind: "err", text: t("watch.ov.updateFailed") });
    } finally {
      setQuotesBusy(false);
    }
  };

  const refreshProfile = async () => {
    setProfileBusy(true);
    setRefreshMsg(null);
    try {
      const resp = await api.refreshWatchProfile(symbol);
      setCompany(resp);
      setRefreshMsg({ kind: "ok", text: t("watch.ov.updateSuccess") });
      await loadProfile();
    } catch {
      setRefreshMsg({ kind: "err", text: t("watch.ov.updateFailed") });
    } finally {
      setProfileBusy(false);
    }
  };

  const startFetch = async () => {
    if (!note.trim()) return;
    setFetching(true);
    setFetchError("");
    setFetchRunId("");
    try {
      const run = await api.startObjectiveFetch(symbol, note.trim());
      setFetchRunId(run.id);
      setNote("");
      await loadObjective();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setFetchError(t("watch.an.inProgress"));
      } else {
        setFetchError(t("watch.obj.fetchFailed"));
      }
    } finally {
      setFetching(false);
    }
  };

  // ---- states -------------------------------------------------------
  if (loading) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="mt-4 h-40 w-full" />
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-12 text-center" data-testid="watch-detail-404">
        <p className="text-lg font-medium">{t("watch.detail.notFound")}</p>
        <p className="mt-2 text-sm text-muted-foreground">
          {t("watch.detail.notFoundHint")}
        </p>
        <Link
          to="/watch"
          className="mt-4 inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {t("watch.detail.back")}
        </Link>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-12 text-center" data-testid="watch-detail-load-error">
        <p className="text-sm text-muted-foreground">{t("watch.detail.loadFailed")}</p>
        <button
          type="button"
          className="mt-3 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60"
          onClick={() => void loadProfile()}
        >
          {t("watch.action.refresh")}
        </button>
      </div>
    );
  }

  const entry = profile?.entry ?? null;
  const instrument = profile?.instrument ?? null;
  const name = entry?.name || company?.name || symbol;

  const overviewRows: [string, string][] = [
    [t("watch.ov.name"), textOrEmpty(name === symbol ? symbol : name)],
    [t("watch.ov.symbol"), symbol],
    [t("watch.ov.industry"), textOrEmpty(entry?.quote?.industry ?? entry?.industry ?? company?.industry ?? instrument?.industry)],
    [t("watch.ov.price"), fmt(entry?.quote?.price)],
    [t("watch.ov.marketCap"), fmtCompact(entry?.quote?.total_market_cap)],
    [t("watch.ov.listDate"), textOrEmpty(company?.list_date ?? instrument?.list_date)],
    [t("watch.ov.registeredCapital"), fmt(company?.registered_capital, 0)],
    [t("watch.ov.updatedAt"), textOrEmpty(entry?.quote?.quote_updated_at)],
  ];

  const sectionTitles: Record<keyof ObjectiveRawData, string> = {
    daily_bar: t("watch.obj.market"),
    valuation: t("watch.obj.valuation"),
    financial: t("watch.obj.financial"),
    instrument: t("watch.obj.instrument"),
  };

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            to="/watch"
            className="mb-1 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
            {t("watch.detail.back")}
          </Link>
          <h1 className="text-xl font-semibold">
            {name} <span className="ml-1 text-sm font-normal text-muted-foreground">{symbol}</span>
          </h1>
        </div>
      </div>

      <div role="tablist" aria-label={name} className="mb-5 flex flex-wrap gap-1 border-b border-border">
        {TABS.map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm ${
              tab === key
                ? "border-primary font-medium text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t(`watch.tabs.${key}`)}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <section data-testid="tab-overview">
          <div className="mb-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void refreshQuotes()}
              disabled={quotesBusy}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-60"
              data-testid="refresh-quotes-btn"
            >
              {quotesBusy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
              {t("watch.ov.updateQuotes")}
            </button>
            <button
              type="button"
              onClick={() => void refreshProfile()}
              disabled={profileBusy}
              className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60 disabled:opacity-60"
              data-testid="refresh-profile-btn"
            >
              {profileBusy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
              {t("watch.ov.updateProfile")}
            </button>
          </div>
          {refreshMsg && (
            <div
              role="status"
              className={`mb-3 rounded-md px-3 py-2 text-sm ${
                refreshMsg.kind === "ok"
                  ? "border border-green-500/40 bg-green-500/10"
                  : "border border-red-500/40 bg-red-500/10 text-red-500"
              }`}
              data-testid="refresh-msg"
            >
              {refreshMsg.text}
            </div>
          )}
          <dl className="grid grid-cols-1 gap-x-8 gap-y-3 rounded-md border border-border p-4 sm:grid-cols-2">
            {overviewRows.map(([label, value]) => (
              <div key={label} className="flex justify-between gap-4 border-b border-border/40 pb-2 text-sm">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="text-right">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {(tab === "objective" || tab === "fundamental") && (
        <ObjectivePanel
          active={tab}
          symbol={symbol}
          loading={objectiveLoading || !objectiveLoaded}
          raw={raw}
          fetches={fetches}
          sectionTitles={sectionTitles}
          note={note}
          setNote={setNote}
          fetching={fetching}
          fetchError={fetchError}
          fetchRunId={fetchRunId}
          onFetch={() => void startFetch()}
          onReload={() => void loadObjective()}
        />
      )}

      {tab === "fundamental" && (
        <div className="mt-8">
          <AnalysisTab category="fundamental" symbol={symbol} symbolName={name} />
        </div>
      )}
      {tab === "technical" && (
        <div className="space-y-8">
          <AnalysisTab
            category="technical"
            symbol={symbol}
            symbolName={name}
            onGotoObjective={() => setTab("objective")}
          />
          <ChanlunHistory symbol={symbol} />
        </div>
      )}
      {tab === "ai" && (
        <AnalysisTab category="general" symbol={symbol} symbolName={name} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
function RawTable({
  title,
  rows,
}: {
  title: string;
  rows: Record<string, unknown>[];
}) {
  const { t } = useTranslation();
  const shown = rows.slice(0, 20);
  const keys = shown.reduce<string[]>((acc, row) => {
    for (const k of Object.keys(row)) if (!acc.includes(k)) acc.push(k);
    return acc;
  }, []);

  return (
    <section className="rounded-md border border-border">
      <div className="border-b border-border/60 bg-muted/40 px-3 py-2 text-sm font-medium">
        {title}
        <span className="ml-2 text-xs font-normal text-muted-foreground">
          {rows.length}
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="px-3 py-5 text-center text-sm text-muted-foreground">
          {t("watch.noData")}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-muted-foreground">
                {keys.map((k) => (
                  <th key={k} className="whitespace-nowrap px-3 py-1.5">{k}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((row, i) => (
                <tr key={i} className="border-t border-border/40">
                  {keys.map((k) => (
                    <td key={k} className="whitespace-nowrap px-3 py-1.5">
                      {row[k] === null || row[k] === undefined
                        ? t("watch.noData")
                        : String(row[k])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > shown.length && (
            <p className="border-t border-border/40 px-3 py-1.5 text-xs text-muted-foreground">
              20 / {rows.length}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function ObjectivePanel({
  active,
  symbol,
  loading,
  raw,
  fetches,
  sectionTitles,
  note,
  setNote,
  fetching,
  fetchError,
  fetchRunId,
  onFetch,
  onReload,
}: {
  active: TabKey;
  symbol: string;
  loading: boolean;
  raw: ObjectiveRawData | null;
  fetches: ObjectiveRecord[];
  sectionTitles: Record<keyof ObjectiveRawData, string>;
  note: string;
  setNote: (v: string) => void;
  fetching: boolean;
  fetchError: string;
  fetchRunId: string;
  onFetch: () => void;
  onReload: () => void;
}) {
  const { t } = useTranslation();
  const sections: (keyof ObjectiveRawData)[] =
    active === "fundamental"
      ? ["financial"]
      : ["instrument", "daily_bar", "valuation", "financial"];

  const financialOnly = active === "fundamental";
  return (
    <section data-testid="tab-objective" className="space-y-5">
      {!financialOnly && <KlineReadinessCard symbol={symbol} />}
      {!financialOnly && (
      <div className="rounded-md border border-border p-4">
        <h3 className="mb-2 text-sm font-semibold">{t("watch.obj.fetchTitle")}</h3>
        <textarea
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={t("watch.obj.fetchPlaceholder")}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
          data-testid="objective-note"
        />
        <div className="mt-2 flex items-center gap-3">
          <button
            type="button"
            disabled={!note.trim() || fetching}
            onClick={onFetch}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="objective-fetch-btn"
          >
            {fetching && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
            {t("watch.obj.fetchButton")}
          </button>
          {!note.trim() && (
            <span className="text-xs text-muted-foreground">
              {t("watch.obj.fetchDisabled")}
            </span>
          )}
          {fetchRunId && (
            <span
              className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-xs text-amber-700 dark:text-amber-400"
              data-testid="objective-run-id"
              role="status"
            >
              {t("watch.obj.fetchRunning")} · {fetchRunId}
            </span>
          )}
        </div>
        {fetchError && (
          <div role="alert" className="mt-2 text-sm text-red-500" data-testid="objective-fetch-error">
            {fetchError}
          </div>
        )}
        <button
          type="button"
          onClick={onReload}
          className="mt-2 text-xs text-primary hover:underline"
        >
          {t("watch.action.refresh")}
        </button>
      </div>
      )}

      <div className="space-y-4">
        {loading || !raw ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          sections.map((key) => (
            <RawTable key={key} title={sectionTitles[key]} rows={raw[key]} />
          ))
        )}
      </div>

      {!financialOnly && (
      <div>
        <h3 className="mb-2 text-sm font-semibold">{t("watch.obj.recordsTitle")}</h3>
        {fetches.length === 0 ? (
          <p className="rounded-md border border-dashed border-border px-4 py-5 text-center text-sm text-muted-foreground" data-testid="objective-records-empty">
            {t("watch.obj.recordEmpty")}
          </p>
        ) : (
          <ul className="space-y-2">
            {fetches.map((rec) => (
              <li key={rec.id} className="rounded-md border border-border p-3">
                <p className="text-xs text-muted-foreground">
                  {t("watch.rec.note")}: {rec.request_note || t("watch.noData")} ·{" "}
                  {t("watch.rec.source")}: {rec.source || t("watch.noData")} ·{" "}
                  {t("watch.rec.time")}: {rec.created_at}
                </p>
                <div className="mt-2 text-sm" data-testid="objective-record-payload">
                  <MarkdownContent content={rec.payload} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      )}
    </section>
  );
}
