import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useTranslation } from "react-i18next";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Loader2,
  Plus,
  Search,
  Star,
  X,
} from "lucide-react";
import {
  ApiError,
  api,
  type WatchCandidate,
  type WatchEntry,
} from "@/lib/api";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { Skeleton } from "@/components/common/Skeleton";

type SortKey = "price" | "total_market_cap" | "pe" | "pb";
type SortState = { key: SortKey; dir: "asc" | "desc" } | null;

/** Nulls always sort last regardless of the sort direction. */
function compareValues(
  a: number | null | undefined,
  b: number | null | undefined,
  dir: "asc" | "desc",
): number {
  const av = a ?? null;
  const bv = b ?? null;
  if (av === null && bv === null) return 0;
  if (av === null) return 1;
  if (bv === null) return -1;
  return dir === "asc" ? av - bv : bv - av;
}

export function formatNumber(
  value: number | null | undefined,
  locale: string,
  options?: Intl.NumberFormatOptions,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  return new Intl.NumberFormat(locale, options).format(value);
}

export function Watchlist() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const locale = i18n.language || "en";

  const [entries, setEntries] = useState<WatchEntry[]>([]);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [sort, setSort] = useState<SortState>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [confirmTarget, setConfirmTarget] = useState<WatchEntry | null>(null);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState(false);
  const [compareHint, setCompareHint] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const resp = await api.listWatch();
      setEntries(resp.items);
      setQuoteError(resp.quote_error);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sorted = useMemo(() => {
    if (!sort) return entries;
    const { key, dir } = sort;
    return [...entries].sort((a, b) =>
      compareValues(a.quote?.[key], b.quote?.[key], dir),
    );
  }, [entries, sort]);

  const toggleSort = (key: SortKey) => {
    setSort((prev) => {
      if (!prev || prev.key !== key) return { key, dir: "desc" };
      return prev.dir === "desc" ? { key, dir: "asc" } : null;
    });
  };

  const allChecked = entries.length > 0 && selected.size === entries.length;
  const toggleAll = () => {
    setSelected(allChecked ? new Set() : new Set(entries.map((e) => e.symbol)));
  };
  const toggleOne = (symbol: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  };

  const onAdded = useCallback(() => {
    setSelected(new Set());
    void load();
  }, [load]);

  const confirmRemove = async () => {
    if (!confirmTarget) return;
    setRemoving(true);
    setRemoveError(false);
    try {
      await api.removeWatch(confirmTarget.symbol);
      setConfirmTarget(null);
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(confirmTarget.symbol);
        return next;
      });
      await load();
    } catch {
      // Keep the dialog open so the user can retry; surface the failure.
      setRemoveError(true);
    } finally {
      setRemoving(false);
    }
  };

  const fmt = (v: number | null | undefined, digits = 2) => {
    const text = formatNumber(v, locale, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    return text || t("watch.noData");
  };
  const fmtCompact = (v: number | null | undefined) => {
    const text = formatNumber(v, locale, {
      notation: "compact",
      maximumFractionDigits: 2,
    });
    return text || t("watch.noData");
  };

  const sortIcon = (key: SortKey) => {
    if (!sort || sort.key !== key) {
      return <ArrowUpDown className="h-3 w-3 opacity-50" aria-hidden="true" />;
    }
    return sort.dir === "asc" ? (
      <ArrowUp className="h-3 w-3" aria-hidden="true" />
    ) : (
      <ArrowDown className="h-3 w-3" aria-hidden="true" />
    );
  };

  const sortableHeader = (key: SortKey, label: string) => (
    <button
      type="button"
      onClick={() => toggleSort(key)}
      className="inline-flex items-center gap-1 hover:text-foreground"
      aria-label={`${label} ${sort?.key === key ? sort.dir : ""}`.trim()}
    >
      {label}
      {sortIcon(key)}
    </button>
  );

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <Star className="h-5 w-5 text-primary" aria-hidden="true" />
            {t("watch.title")}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("watch.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted/60"
            onClick={() => setCompareHint(true)}
            data-testid="ai-compare-btn"
          >
            {t("watch.aiBatchCompare")}
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90"
            onClick={() => setAddOpen(true)}
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            {t("watch.addWatch")}
          </button>
        </div>
      </div>

      {compareHint && (
        <div
          role="status"
          className="mb-3 flex items-center justify-between rounded-md border border-border bg-muted/40 px-3 py-2 text-sm"
          data-testid="compare-hint"
        >
          <span>{t("watch.compareToast")}</span>
          <button
            type="button"
            aria-label={t("watch.cancel")}
            onClick={() => setCompareHint(false)}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      )}

      {quoteError && (
        <div
          role="alert"
          className="mb-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm"
        >
          {t("watch.quoteError")}
        </div>
      )}

      {loading ? (
        <div className="space-y-2" data-testid="watch-loading">
          <Skeleton className="h-10 w-full" />
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : loadError ? (
        <div className="rounded-md border border-border p-8 text-center">
          <p className="text-sm text-muted-foreground">
            {t("watch.detail.loadFailed")}
          </p>
          <button
            type="button"
            className="mt-3 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60"
            onClick={() => void load()}
          >
            {t("watch.action.refresh")}
          </button>
        </div>
      ) : entries.length === 0 ? (
        <div
          className="rounded-md border border-dashed border-border p-12 text-center"
          data-testid="watch-empty"
        >
          <Star className="mx-auto h-8 w-8 text-muted-foreground/50" aria-hidden="true" />
          <p className="mt-3 font-medium">{t("watch.empty.title")}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("watch.empty.hint")}
          </p>
          <button
            type="button"
            className="mt-4 inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90"
            onClick={() => setAddOpen(true)}
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            {t("watch.addWatch")}
          </button>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                <th className="w-10 px-3 py-2.5">
                  <input
                    type="checkbox"
                    aria-label={t("watch.col.select")}
                    checked={allChecked}
                    onChange={toggleAll}
                  />
                </th>
                <th className="px-3 py-2.5">{t("watch.col.name")}</th>
                <th className="px-3 py-2.5">{t("watch.col.industry")}</th>
                <th className="px-3 py-2.5">{sortableHeader("price", t("watch.col.price"))}</th>
                <th className="px-3 py-2.5">{sortableHeader("total_market_cap", t("watch.col.marketCap"))}</th>
                <th className="px-3 py-2.5">{sortableHeader("pe", t("watch.col.pe"))}</th>
                <th className="px-3 py-2.5">{sortableHeader("pb", t("watch.col.pb"))}</th>
                <th className="px-3 py-2.5 text-right">{t("watch.col.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((entry) => (
                <tr
                  key={entry.symbol}
                  className="border-t border-border/60 hover:bg-muted/30"
                >
                  <td className="px-3 py-2.5">
                    <input
                      type="checkbox"
                      aria-label={`${t("watch.col.select")} ${entry.name}`}
                      checked={selected.has(entry.symbol)}
                      onChange={() => toggleOne(entry.symbol)}
                    />
                  </td>
                  <td className="px-3 py-2.5">
                    <button
                      type="button"
                      className="text-left font-medium text-primary hover:underline"
                      onClick={() => navigate(`/watch/${encodeURIComponent(entry.symbol)}`)}
                    >
                      {entry.name || entry.symbol}
                    </button>
                    <div className="text-xs text-muted-foreground">{entry.symbol}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    {entry.quote?.industry || entry.industry || (
                      <span className="text-muted-foreground">{t("watch.noData")}</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">{fmt(entry.quote?.price)}</td>
                  <td className="px-3 py-2.5">{fmtCompact(entry.quote?.total_market_cap)}</td>
                  <td className="px-3 py-2.5">{fmt(entry.quote?.pe)}</td>
                  <td className="px-3 py-2.5">{fmt(entry.quote?.pb)}</td>
                  <td className="px-3 py-2.5 text-right">
                    <button
                      type="button"
                      className="mr-3 text-primary hover:underline"
                      onClick={() => navigate(`/watch/${encodeURIComponent(entry.symbol)}`)}
                    >
                      {t("watch.action.view")}
                    </button>
                    <button
                      type="button"
                      className="text-red-500 hover:underline"
                      onClick={() => setConfirmTarget(entry)}
                    >
                      {t("watch.action.cancel")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {addOpen && (
        <AddWatchDialog
          onClose={() => setAddOpen(false)}
          onAdded={onAdded}
          existing={new Set(entries.map((e) => e.symbol))}
        />
      )}

      <ConfirmDialog
        open={confirmTarget !== null}
        title={t("watch.confirmCancel.title")}
        description={
          confirmTarget
            ? t("watch.confirmCancel.message", {
                name: confirmTarget.name || confirmTarget.symbol,
                symbol: confirmTarget.symbol,
              })
            : undefined
        }
        confirmLabel={removing ? t("watch.ov.updating") : t("watch.confirm")}
        cancelLabel={t("watch.cancel")}
        tone="destructive"
        confirmDisabled={removing}
        onConfirm={() => void confirmRemove()}
        onCancel={() => {
          setRemoveError(false);
          setConfirmTarget(null);
        }}
      >
        {removeError && (
          <p role="alert" className="text-sm text-red-500" data-testid="remove-error">
            {t("watch.error.dataFailed")}
          </p>
        )}
      </ConfirmDialog>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add-symbol dialog with debounced (>=300ms) A-share search.
// ---------------------------------------------------------------------------
const SEARCH_DEBOUNCE_MS = 350;

function AddWatchDialog({
  onClose,
  onAdded,
  existing,
}: {
  onClose: () => void;
  onAdded: () => void;
  existing: Set<string>;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState<WatchCandidate[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestSeq = useRef(0);

  useEffect(() => {
    const keyword = query.trim();
    if (keyword.length < 1) {
      setCandidates([]);
      setSearched(false);
      setSearching(false);
      return;
    }
    setSearching(true);
    const seq = ++requestSeq.current;
    const timer = setTimeout(async () => {
      try {
        const resp = await api.searchWatch(keyword);
        if (seq !== requestSeq.current) return;
        setCandidates(resp.items);
      } catch {
        if (seq !== requestSeq.current) return;
        setCandidates([]);
      } finally {
        if (seq === requestSeq.current) {
          setSearching(false);
          setSearched(true);
        }
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const add = async (candidate: WatchCandidate) => {
    setError(null);
    setAdding(candidate.symbol);
    try {
      await api.addWatch({
        symbol: candidate.symbol,
        name: candidate.name,
        industry: candidate.industry,
      });
      onAdded();
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(`${t("watch.error.duplicate")}: ${candidate.symbol}`);
      } else {
        setError(t("watch.error.dataFailed"));
      }
      setAdding(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-24"
      role="dialog"
      aria-modal="true"
      aria-label={t("watch.addWatch")}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-lg border border-border bg-background p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">{t("watch.addWatch")}</h2>
          <button type="button" aria-label={t("watch.cancel")} onClick={onClose}>
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("watch.searchPlaceholder")}
            className="w-full rounded-md border border-border bg-background py-2 pl-8 pr-3 text-sm outline-none focus:border-primary"
            data-testid="watch-search-input"
          />
        </div>

        {error && (
          <div role="alert" className="mt-2 text-sm text-red-500" data-testid="watch-add-error">
            {error}
          </div>
        )}

        <div className="mt-3 max-h-80 overflow-auto">
          {searching ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              {t("watch.searching")}
            </div>
          ) : searched && candidates.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {t("watch.searchNoResult")}
            </p>
          ) : (
            <ul className="divide-y divide-border/60">
              {candidates.map((c) => {
                const already = existing.has(c.symbol);
                return (
                  <li key={c.symbol} className="flex items-center justify-between py-2.5">
                    <div>
                      <div className="text-sm font-medium">{c.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {c.symbol}
                        {c.industry ? ` · ${c.industry}` : ""}
                      </div>
                    </div>
                    <button
                      type="button"
                      disabled={already || adding === c.symbol}
                      className="rounded-md border border-border px-2.5 py-1 text-xs hover:bg-muted/60 disabled:opacity-50"
                      onClick={() => void add(c)}
                    >
                      {adding === c.symbol ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                      ) : already ? (
                        t("watch.error.duplicate")
                      ) : (
                        t("watch.addWatch")
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
