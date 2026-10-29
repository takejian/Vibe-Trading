import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Loader2,
  Pencil,
  Plus,
  Search,
  Star,
  Trash2,
  X,
} from "lucide-react";
import {
  ApiError,
  api,
  type WatchCandidate,
  type WatchEntry,
  type WatchGroup,
} from "@/lib/api";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { PaperTradeDialog } from "@/components/paper/PaperTradeDialog";
import { Skeleton } from "@/components/common/Skeleton";

const DEFAULT_GROUP_ID = "default";
const CANCELED_GROUP_ID = "canceled";

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

interface PendingAction {
  kind: "cancel" | "delete" | "restore" | "move";
  entry: WatchEntry;
  targetGroupId?: string;
}

export function Watchlist() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const locale = i18n.language || "en";

  // -- Groups state -------------------------------------------------------
  const [groups, setGroups] = useState<WatchGroup[]>([]);
  const [activeGroupId, setActiveGroupId] = useState<string>(DEFAULT_GROUP_ID);

  // -- Entries state ------------------------------------------------------
  const [entries, setEntries] = useState<WatchEntry[]>([]);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  // -- UI state -----------------------------------------------------------
  const [sort, setSort] = useState<SortState>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [addOpen, setAddOpen] = useState(false);
  const [groupDialog, setGroupDialog] = useState<
    | null
    | { kind: "create"; existingNames: Set<string> }
    | { kind: "rename"; group: WatchGroup; existingNames: Set<string> }
    | { kind: "delete"; group: WatchGroup }
  >(null);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [movingSymbol, setMovingSymbol] = useState<string | null>(null);
  const [buyTarget, setBuyTarget] = useState<WatchEntry | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState(false);
  const [compareHint, setCompareHint] = useState(false);

  // ------------------------------------------------------------------
  // Data loading
  // ------------------------------------------------------------------
  const loadGroups = useCallback(async () => {
    try {
      const resp = await api.listWatchGroups();
      setGroups(resp.items);
    } catch {
      // Non-fatal — keep existing groups visible.
    }
  }, []);

  const loadEntries = useCallback(
    async (groupId: string = activeGroupId) => {
      setLoading(true);
      setLoadError(false);
      setSelected(new Set());
      setSort(null);
      try {
        const resp = await api.listWatch({ group_id: groupId });
        setEntries(resp.items);
        setQuoteError(resp.quote_error);
      } catch {
        setLoadError(true);
      } finally {
        setLoading(false);
      }
    },
    [activeGroupId],
  );

  const loadAll = useCallback(async () => {
    await loadGroups();
    await loadEntries(activeGroupId);
  }, [loadGroups, loadEntries, activeGroupId]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  // ------------------------------------------------------------------
  // Sorted view
  // ------------------------------------------------------------------
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

  // ------------------------------------------------------------------
  // Selection
  // ------------------------------------------------------------------
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

  const onAdded = useCallback(async () => {
    await loadAll();
  }, [loadAll]);

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------
  const isCanceledGroup = activeGroupId === CANCELED_GROUP_ID;

  const confirmAction = async () => {
    if (!pendingAction) return;
    setActionBusy(true);
    setActionError(false);
    const { kind, entry, targetGroupId } = pendingAction;
    try {
      if (kind === "cancel") {
        await api.cancelWatch(entry.symbol);
      } else if (kind === "delete") {
        await api.removeWatch(entry.symbol);
      } else if (kind === "restore") {
        await api.restoreWatch(entry.symbol);
      } else if (kind === "move" && targetGroupId) {
        await api.moveWatch(entry.symbol, targetGroupId);
      }
      setPendingAction(null);
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(entry.symbol);
        return next;
      });
      await loadAll();
    } catch {
      setActionError(true);
    } finally {
      setActionBusy(false);
    }
  };

  const handleMove = async (symbol: string, targetGroupId: string) => {
    setMovingSymbol(symbol);
    try {
      await api.moveWatch(symbol, targetGroupId);
      await loadAll();
    } finally {
      setMovingSymbol(null);
    }
  };

  // ------------------------------------------------------------------
  // Group management
  // ------------------------------------------------------------------
  const openCreateGroup = () => {
    setGroupDialog({
      kind: "create",
      existingNames: new Set(groups.map((g) => g.name)),
    });
  };

  const openRenameGroup = (group: WatchGroup) => {
    setGroupDialog({
      kind: "rename",
      group,
      existingNames: new Set(
        groups.filter((g) => g.id !== group.id).map((g) => g.name),
      ),
    });
  };

  const openDeleteGroup = (group: WatchGroup) => {
    setGroupDialog({ kind: "delete", group });
  };

  const handleGroupSubmit = async (name: string) => {
    if (!groupDialog) return;
    const clean = name.trim();
    if (!clean) return;

    if (groupDialog.kind === "create") {
      try {
        await api.createWatchGroup(clean);
        setGroupDialog(null);
        await loadGroups();
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          throw new Error(t("watch.group.nameExists"));
        }
        throw err;
      }
    } else if (groupDialog.kind === "rename") {
      try {
        await api.renameWatchGroup(groupDialog.group.id, clean);
        setGroupDialog(null);
        await loadGroups();
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          throw new Error(t("watch.group.nameExists"));
        }
        throw err;
      }
    } else if (groupDialog.kind === "delete") {
      try {
        await api.deleteWatchGroup(groupDialog.group.id);
        if (activeGroupId === groupDialog.group.id) {
          setActiveGroupId(DEFAULT_GROUP_ID);
        }
        setGroupDialog(null);
        await loadAll();
      } catch {
        // keep dialog open for retry
      }
    }
  };

  // ------------------------------------------------------------------
  // Formatting helpers
  // ------------------------------------------------------------------
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

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  const isEmptyState = !loading && !loadError && sorted.length === 0;

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
          {!isCanceledGroup && (
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90"
              onClick={() => setAddOpen(true)}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              {t("watch.addWatch")}
            </button>
          )}
          <button
            type="button"
            className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted/60"
            onClick={() => setCompareHint(true)}
            data-testid="ai-compare-btn"
          >
            {t("watch.aiBatchCompare")}
          </button>
        </div>
      </div>

      {/* Group tabs */}
      <div className="mb-4 flex items-center gap-1 overflow-x-auto border-b border-border pb-1">
        {groups.map((group) => {
          const isActive = group.id === activeGroupId;
          const isSystem = group.system;
          const isCanceled = group.id === CANCELED_GROUP_ID;
          return (
            <div key={group.id} className="group/tab relative inline-flex">
              <button
                type="button"
                onClick={() => setActiveGroupId(group.id)}
                className={[
                  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-t-md px-3 py-1.5 text-sm font-medium transition-colors",
                  isActive
                    ? "border-b-2 border-primary text-primary"
                    : isCanceled
                      ? "text-muted-foreground hover:text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                ].join(" ")}
              >
                <span>{group.name}</span>
                <span className="text-xs opacity-60">({group.count ?? 0})</span>
              </button>
              {!isSystem && (
                <div
                  className="ml-1 hidden items-center gap-0.5 group-hover/tab:flex"
                  aria-label="group-actions"
                >
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      openRenameGroup(group);
                    }}
                    className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                    aria-label={t("watch.group.renameTitle")}
                  >
                    <Pencil className="h-3 w-3" />
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      openDeleteGroup(group);
                    }}
                    className="rounded p-1 text-muted-foreground hover:bg-red-500/10 hover:text-red-500"
                    aria-label={t("watch.group.deleteTitle")}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              )}
            </div>
          );
        })}
        <button
          type="button"
          onClick={openCreateGroup}
          className="ml-1 inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm text-muted-foreground hover:bg-muted/60 hover:text-foreground"
          aria-label={t("watch.group.addNew")}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="whitespace-nowrap">{t("watch.group.addNew")}</span>
        </button>
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
            onClick={() => void loadAll()}
          >
            {t("watch.action.refresh")}
          </button>
        </div>
      ) : isEmptyState ? (
        // Empty state differs between canceled and regular groups.
        isCanceledGroup ? (
          <div
            className="rounded-md border border-dashed border-border p-12 text-center"
            data-testid="watch-empty"
          >
            <Star
              className="mx-auto h-8 w-8 text-muted-foreground/50"
              aria-hidden="true"
            />
            <p className="mt-3 font-medium">{t("watch.emptyCanceled.title")}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("watch.emptyCanceled.hint")}
            </p>
          </div>
        ) : (
          <div
            className="rounded-md border border-dashed border-border p-12 text-center"
            data-testid="watch-empty"
          >
            <Star
              className="mx-auto h-8 w-8 text-muted-foreground/50"
              aria-hidden="true"
            />
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
        )
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
                <th className="px-3 py-2.5">
                  {sortableHeader("price", t("watch.col.price"))}
                </th>
                <th className="px-3 py-2.5">
                  {sortableHeader("total_market_cap", t("watch.col.marketCap"))}
                </th>
                <th className="px-3 py-2.5">
                  {sortableHeader("pe", t("watch.col.pe"))}
                </th>
                <th className="px-3 py-2.5">
                  {sortableHeader("pb", t("watch.col.pb"))}
                </th>
                <th className="px-3 py-2.5 text-right">
                  {t("watch.col.actions")}
                </th>
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
                      onClick={() =>
                        navigate(`/watch/${encodeURIComponent(entry.symbol)}`)
                      }
                    >
                      {entry.name || entry.symbol}
                    </button>
                    <div className="text-xs text-muted-foreground">
                      {entry.symbol}
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    {entry.quote?.industry || entry.industry || (
                      <span className="text-muted-foreground">
                        {t("watch.noData")}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">{fmt(entry.quote?.price)}</td>
                  <td className="px-3 py-2.5">
                    {fmtCompact(entry.quote?.total_market_cap)}
                  </td>
                  <td className="px-3 py-2.5">{fmt(entry.quote?.pe)}</td>
                  <td className="px-3 py-2.5">{fmt(entry.quote?.pb)}</td>
                  <td className="px-3 py-2.5 text-right">
                    {!isCanceledGroup && (
                      <>
                        <button
                          type="button"
                          className="mr-3 rounded-md border border-red-500/50 px-2 py-0.5 text-xs text-red-500 hover:bg-red-500/10"
                          onClick={() => setBuyTarget(entry)}
                        >
                          {t("paper.buy")}
                        </button>
                        <button
                          type="button"
                          className="mr-3 text-primary hover:underline"
                          onClick={() =>
                            navigate(`/watch/${encodeURIComponent(entry.symbol)}`)
                          }
                        >
                          {t("watch.action.view")}
                        </button>
                        {/* Move dropdown */}
                        <MoveMenu
                          groups={groups.filter(
                            (g) =>
                              g.id !== activeGroupId &&
                              g.id !== CANCELED_GROUP_ID,
                          )}
                          busy={movingSymbol === entry.symbol}
                          onMove={(targetId) =>
                            void handleMove(entry.symbol, targetId)
                          }
                          trigger={
                            <button
                              type="button"
                              className="mr-3 text-xs text-muted-foreground hover:text-foreground"
                            >
                              {t("watch.action.moveTo")}
                            </button>
                          }
                        />
                        <button
                          type="button"
                          className="text-red-500 hover:underline"
                          onClick={() =>
                            setPendingAction({
                              kind: "cancel",
                              entry,
                            })
                          }
                        >
                          {t("watch.action.cancel")}
                        </button>
                      </>
                    )}
                    {isCanceledGroup && (
                      <>
                        <button
                          type="button"
                          className="mr-3 text-primary hover:underline"
                          onClick={() =>
                            navigate(`/watch/${encodeURIComponent(entry.symbol)}`)
                          }
                        >
                          {t("watch.action.view")}
                        </button>
                        <button
                          type="button"
                          className="mr-3 text-primary hover:underline"
                          onClick={() =>
                            setPendingAction({ kind: "restore", entry })
                          }
                        >
                          {t("watch.action.restore")}
                        </button>
                        <button
                          type="button"
                          className="text-red-500 hover:underline"
                          onClick={() =>
                            setPendingAction({ kind: "delete", entry })
                          }
                        >
                          {t("watch.action.hardDelete")}
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add dialog */}
      {addOpen && (
        <AddWatchDialog
          groups={groups.filter((g) => g.id !== CANCELED_GROUP_ID)}
          defaultGroupId={DEFAULT_GROUP_ID}
          activeGroupId={
            activeGroupId === CANCELED_GROUP_ID ? DEFAULT_GROUP_ID : activeGroupId
          }
          onClose={() => setAddOpen(false)}
          onAdded={onAdded}
          existing={new Set(entries.map((e) => e.symbol))}
        />
      )}

      {buyTarget && (
        <PaperTradeDialog
          mode="buy"
          symbol={buyTarget.symbol}
          name={buyTarget.name}
          onClose={() => setBuyTarget(null)}
          onDone={() => void loadAll()}
        />
      )}

      {/* Confirm dialog for row actions */}
      <ConfirmDialog
        open={pendingAction !== null}
        title={
          pendingAction
            ? pendingAction.kind === "cancel"
              ? t("watch.group.confirmCancelTitle")
              : pendingAction.kind === "delete"
                ? t("watch.group.confirmDeleteTitle")
                : pendingAction.kind === "restore"
                  ? t("watch.group.confirmRestoreTitle")
                  : ""
            : ""
        }
        description={
          pendingAction
            ? (pendingAction.kind === "cancel"
                ? t("watch.group.confirmCancelMessage", {
                    name: pendingAction.entry.name || pendingAction.entry.symbol,
                    symbol: pendingAction.entry.symbol,
                  })
                : pendingAction.kind === "delete"
                  ? t("watch.group.confirmDeleteMessage", {
                      name: pendingAction.entry.name || pendingAction.entry.symbol,
                      symbol: pendingAction.entry.symbol,
                    })
                  : pendingAction.kind === "restore"
                    ? t("watch.group.confirmRestoreMessage", {
                        name: pendingAction.entry.name || pendingAction.entry.symbol,
                        symbol: pendingAction.entry.symbol,
                      })
                    : undefined)
            : undefined
        }
        confirmLabel={
          actionBusy ? t("watch.ov.updating") : t("watch.confirm")
        }
        cancelLabel={t("watch.cancel")}
        tone={
          pendingAction?.kind === "delete" ? "destructive" : "primary"
        }
        confirmDisabled={actionBusy}
        onConfirm={() => void confirmAction()}
        onCancel={() => {
          setActionError(false);
          setPendingAction(null);
        }}
      >
        {actionError && (
          <p
            role="alert"
            className="text-sm text-red-500"
            data-testid="remove-error"
          >
            {t("watch.error.dataFailed")}
          </p>
        )}
      </ConfirmDialog>

      {/* Group management dialogs */}
      {groupDialog && (
        <GroupDialog
          dialog={groupDialog}
          onClose={() => setGroupDialog(null)}
          onSubmit={handleGroupSubmit}
          t={t}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Move-menu primitive: click-triggered popover of target groups.
// ---------------------------------------------------------------------------
function MoveMenu({
  groups,
  busy,
  onMove,
  trigger,
}: {
  groups: WatchGroup[];
  busy: boolean;
  onMove: (groupId: string) => void;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  if (groups.length === 0) {
    // No destination except current group — hide the control.
    return null;
  }

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {trigger}
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-20 mt-1 min-w-[120px] overflow-hidden rounded-md border border-border bg-background shadow-lg"
        >
          {groups.map((g) => (
            <button
              key={g.id}
              type="button"
              role="menuitem"
              disabled={busy}
              onClick={() => {
                setOpen(false);
                onMove(g.id);
              }}
              className="block w-full px-3 py-1.5 text-left text-sm hover:bg-muted disabled:opacity-50"
            >
              {g.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Group create / rename / delete dialog.
// ---------------------------------------------------------------------------
function GroupDialog({
  dialog,
  onClose,
  onSubmit,
  t,
}: {
  dialog:
    | { kind: "create"; existingNames: Set<string> }
    | { kind: "rename"; group: WatchGroup; existingNames: Set<string> }
    | { kind: "delete"; group: WatchGroup };
  onClose: () => void;
  onSubmit: (name: string) => Promise<void> | void;
  t: TFunction<"translation">;
}) {
  const [value, setValue] = useState<string>(
    dialog.kind === "rename" ? dialog.group.name : "",
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError(null);
    if (dialog.kind === "delete") {
      setBusy(true);
      try {
        await onSubmit(dialog.group.name);
      } catch {
        setError(t("watch.error.dataFailed"));
      } finally {
        setBusy(false);
      }
      return;
    }
    const clean = value.trim();
    if (!clean) {
      setError(t("watch.group.createPlaceholder"));
      return;
    }
    if (dialog.existingNames.has(clean)) {
      setError(t("watch.group.nameExists"));
      return;
    }
    setBusy(true);
    try {
      await onSubmit(clean);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("watch.error.dataFailed"));
    } finally {
      setBusy(false);
    }
  };

  const title =
    dialog.kind === "create"
      ? t("watch.group.createTitle")
      : dialog.kind === "rename"
        ? t("watch.group.renameTitle")
        : t("watch.group.deleteTitle");

  const description =
    dialog.kind === "delete"
      ? t("watch.group.deleteMessage", { name: dialog.group.name })
      : undefined;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-24"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg border border-border bg-background p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">{title}</h2>
          <button type="button" aria-label={t("watch.cancel")} onClick={onClose}>
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        {description && (
          <p className="mb-3 text-sm text-muted-foreground">{description}</p>
        )}
        {dialog.kind !== "delete" && (
          <input
            autoFocus
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={t("watch.group.createPlaceholder")}
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
            data-testid="group-name-input"
            maxLength={30}
          />
        )}
        {error && (
          <p role="alert" className="mt-2 text-sm text-red-500">
            {error}
          </p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60"
          >
            {t("watch.cancel")}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void submit()}
            className={[
              "inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-sm",
              dialog.kind === "delete"
                ? "bg-red-500 text-white hover:bg-red-600 disabled:opacity-50"
                : "bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50",
            ].join(" ")}
          >
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {busy ? t("watch.ov.updating") : t("watch.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add-symbol dialog — same debounced A-share search, with optional group.
// ---------------------------------------------------------------------------
const SEARCH_DEBOUNCE_MS = 350;

function AddWatchDialog({
  groups,
  defaultGroupId,
  activeGroupId,
  onClose,
  onAdded,
  existing,
}: {
  groups: WatchGroup[];
  defaultGroupId: string;
  activeGroupId: string;
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
  const [groupId, setGroupId] = useState<string>(
    groups.some((g) => g.id === activeGroupId) ? activeGroupId : defaultGroupId,
  );
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
        group_id: groupId,
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
          <Search
            className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("watch.searchPlaceholder")}
            className="w-full rounded-md border border-border bg-background py-2 pl-8 pr-3 text-sm outline-none focus:border-primary"
            data-testid="watch-search-input"
          />
        </div>

        {groups.length > 1 && (
          <div className="mt-3 flex items-center gap-2 text-sm">
            <label className="text-muted-foreground">
              {t("watch.group.addNew") === "新增分组" ? "分组：" : "Group:"}
            </label>
            <select
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
            >
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="mt-2 text-sm text-red-500"
            data-testid="watch-add-error"
          >
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
                  <li
                    key={c.symbol}
                    className="flex items-center justify-between py-2.5"
                  >
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
