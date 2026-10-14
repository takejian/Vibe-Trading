import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Loader2, RefreshCw, RotateCcw } from "lucide-react";
import {
  api,
  type PaperAccount,
  type PaperClose,
  type PaperCloseStats,
  type PaperNavPoint,
  type PaperOrder,
  type PaperPosition,
} from "@/lib/api";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { PaperTradeDialog, fmtMoney, fmtPct } from "@/components/paper/PaperTradeDialog";
import { PaperNavChart } from "@/components/paper/PaperNavChart";

type Tab = "positions" | "orders" | "closes" | "nav";
const POLL_INTERVAL_MS = 2 * 60 * 60 * 1000; // 2h in-session cadence

/** A-share convention: gains red, losses green. */
function pnlClass(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "";
  if (v > 0) return "text-red-500";
  if (v < 0) return "text-green-600";
  return "text-muted-foreground";
}

function signedMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return "-";
  const prefix = v > 0 ? "+" : "";
  return prefix + fmtMoney(v);
}

export function Paper() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("positions");
  const [account, setAccount] = useState<PaperAccount | null>(null);
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [orders, setOrders] = useState<PaperOrder[]>([]);
  const [closes, setCloses] = useState<PaperClose[]>([]);
  const [stats, setStats] = useState<PaperCloseStats | null>(null);
  const [totalFees, setTotalFees] = useState<number>(0);
  const [nav, setNav] = useState<PaperNavPoint[]>([]);
  const [navRange, setNavRange] = useState<"all" | "5d" | "20d">("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [trade, setTrade] = useState<{
    mode: "buy" | "sell";
    position: PaperPosition;
  } | null>(null);

  const loadOverview = useCallback(async () => {
    const [acc, pos] = await Promise.all([
      api.paperAccount(),
      api.paperPositions(),
    ]);
    setAccount(acc);
    setPositions(pos.items);
  }, []);

  const loadOrders = useCallback(async () => {
    const resp = await api.paperOrders({ limit: 200 });
    setOrders(resp.items);
  }, []);

  const loadCloses = useCallback(async () => {
    const resp = await api.paperCloses({ limit: 200 });
    setCloses(resp.items);
    setStats(resp.stats);
    setTotalFees(resp.total_fees);
  }, []);

  const loadNav = useCallback(async () => {
    const resp = await api.paperNav(navRange);
    setNav(resp.items);
  }, [navRange]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        await loadOverview();
        if (!cancelled) setLoading(false);
      } catch {
        if (!cancelled) {
          setError(t("paper.loadFailed"));
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadOverview, t]);

  // Server anchors own persistence; this is the in-page 2h fallback.
  useEffect(() => {
    if (!account?.is_live) return;
    const timer = setInterval(() => void loadOverview(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [account?.is_live, loadOverview]);

  useEffect(() => {
    if (tab === "orders") void loadOrders();
    if (tab === "closes") void loadCloses();
    if (tab === "nav") void loadNav();
  }, [tab, loadOrders, loadCloses, loadNav]);

  useEffect(() => {
    if (tab === "nav") void loadNav();
  }, [navRange, tab, loadNav]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      await api.paperRefresh();
      await loadOverview();
      if (tab === "orders") await loadOrders();
      if (tab === "closes") await loadCloses();
      if (tab === "nav") await loadNav();
    } finally {
      setRefreshing(false);
    }
  };

  const doReset = async () => {
    setResetting(true);
    try {
      await api.paperReset();
      setResetOpen(false);
      await Promise.all([loadOverview(), loadOrders(), loadCloses(), loadNav()]);
    } finally {
      setResetting(false);
    }
  };

  const tabs = useMemo(
    () =>
      (["positions", "orders", "closes", "nav"] as Tab[]).map((key) => ({
        key,
        label: t(`paper.tabs.${key}`),
      })),
    [t],
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{t("paper.title")}</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {account?.is_live ? t("paper.session.liveTag") : t("paper.session.closedTag")}
            {account ? ` · ${account.trade_date}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60 disabled:opacity-50"
            onClick={() => void refresh()}
            disabled={refreshing}
          >
            {refreshing ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
            )}
            {t("paper.refresh")}
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted/60"
            onClick={() => setResetOpen(true)}
          >
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            {t("paper.reset")}
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-500">
          {error}
        </div>
      )}

      {loading || !account ? (
        <div className="flex h-40 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
          {t("paper.loading")}
        </div>
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard label={t("paper.account.initial")} value={fmtMoney(account.initial_capital)} />
            <StatCard label={t("paper.account.cash")} value={fmtMoney(account.cash)} />
            <StatCard label={t("paper.account.marketValue")} value={fmtMoney(account.market_value)} />
            <StatCard label={t("paper.account.totalAsset")} value={fmtMoney(account.total_asset)} />
            <StatCard
              label={t("paper.account.cumPnl")}
              value={signedMoney(account.cumulative_pnl)}
              sub={fmtPct(account.cumulative_return_pct)}
              valueClass={pnlClass(account.cumulative_pnl)}
            />
            <StatCard
              label={t("paper.account.dayPnl")}
              value={signedMoney(account.day_pnl)}
              valueClass={pnlClass(account.day_pnl)}
            />
          </div>

          <div className="mb-4 flex gap-1 border-b border-border">
            {tabs.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`-mb-px border-b-2 px-3 py-2 text-sm ${
                  tab === item.key
                    ? "border-primary font-medium text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
                onClick={() => setTab(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>

          {tab === "positions" && (
            <PositionsTable
              positions={positions}
              onSell={(position) => setTrade({ mode: "sell", position })}
              t={t}
            />
          )}
          {tab === "orders" && <OrdersTable orders={orders} t={t} />}
          {tab === "closes" && (
            <ClosesView closes={closes} stats={stats} totalFees={totalFees} t={t} />
          )}
          {tab === "nav" && (
            <div>
              <div className="mb-3 flex gap-1">
                {(["5d", "20d", "all"] as const).map((r) => (
                  <button
                    key={r}
                    type="button"
                    className={`rounded-md border px-2.5 py-1 text-xs ${
                      navRange === r
                        ? "border-primary text-primary"
                        : "border-border text-muted-foreground hover:bg-muted/60"
                    }`}
                    onClick={() => setNavRange(r)}
                  >
                    {t(`paper.nav.range.${r}`)}
                  </button>
                ))}
              </div>
              <PaperNavChart points={nav} initialCapital={account.initial_capital} />
            </div>
          )}
        </>
      )}

      {trade && (
        <PaperTradeDialog
          mode="sell"
          symbol={trade.position.symbol}
          name={trade.position.name}
          sellableQty={trade.position.sellable_qty}
          onClose={() => setTrade(null)}
          onDone={() => void loadOverview()}
        />
      )}

      <ConfirmDialog
        open={resetOpen}
        title={t("paper.resetConfirm.title")}
        description={t("paper.resetConfirm.message")}
        confirmLabel={resetting ? t("paper.resetting") : t("paper.reset")}
        cancelLabel={t("paper.dialog.cancel")}
        tone="destructive"
        confirmDisabled={resetting}
        onConfirm={() => void doReset()}
        onCancel={() => setResetOpen(false)}
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  valueClass,
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${valueClass ?? ""}`}>
        {value}
        {sub && <span className="ml-1 text-xs font-normal">{sub}</span>}
      </div>
    </div>
  );
}

type Translate = TFunction;

function PositionsTable({
  positions,
  onSell,
  t,
}: {
  positions: PaperPosition[];
  onSell: (position: PaperPosition) => void;
  t: Translate;
}) {
  if (positions.length === 0) {
    return <EmptyHint text={t("paper.positions.empty")} />;
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
          <tr>
            <Th>{t("paper.col.name")}</Th>
            <Th>{t("paper.col.qty")}</Th>
            <Th>{t("paper.col.sellable")}</Th>
            <Th>{t("paper.col.avgCost")}</Th>
            <Th>{t("paper.col.currentPrice")}</Th>
            <Th>{t("paper.col.marketValue")}</Th>
            <Th>{t("paper.col.unrealizedPnl")}</Th>
            <Th>{t("paper.col.returnPct")}</Th>
            <Th>{t("paper.col.chanlunScore")}</Th>
            <Th>{t("paper.col.actions")}</Th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.symbol} className="border-t border-border/60">
              <td className="px-3 py-2.5">
                <Link
                  to={`/watch/${encodeURIComponent(p.symbol)}?tab=technical`}
                  className="block hover:text-primary"
                  title={t("watch.tabs.technical")}
                >
                  <div className="font-medium">{p.name || p.symbol}</div>
                  <div className="text-xs text-muted-foreground">{p.symbol}</div>
                </Link>
              </td>
              <td className="px-3 py-2.5">{p.qty}</td>
              <td className="px-3 py-2.5">{p.sellable_qty}</td>
              <td className="px-3 py-2.5">{fmtMoney(p.avg_cost)}</td>
              <td className="px-3 py-2.5">
                {fmtMoney(p.current_price)}
                {p.stale && (
                  <span className="ml-1 text-xs text-amber-500">{t("paper.stale")}</span>
                )}
              </td>
              <td className="px-3 py-2.5">{fmtMoney(p.market_value)}</td>
              <td className={`px-3 py-2.5 ${pnlClass(p.unrealized_pnl)}`}>
                {signedMoney(p.unrealized_pnl)}
              </td>
              <td className={`px-3 py-2.5 ${pnlClass(p.return_pct)}`}>{fmtPct(p.return_pct)}</td>
              <td className="px-3 py-2.5">
                {p.chanlun_score === null || p.chanlun_score === undefined ? (
                  <span className="text-muted-foreground">-</span>
                ) : (
                  <span title={p.chanlun_score_text ?? undefined}>
                    {p.chanlun_score} / 5
                  </span>
                )}
              </td>
              <td className="px-3 py-2.5">
                <button
                  type="button"
                  disabled={p.sellable_qty <= 0}
                  className="rounded-md border border-border px-2.5 py-1 text-xs hover:bg-muted/60 disabled:opacity-40"
                  title={p.sellable_qty <= 0 ? t("paper.t1Disabled") : undefined}
                  onClick={() => onSell(p)}
                >
                  {t("paper.sell")}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OrdersTable({ orders, t }: { orders: PaperOrder[]; t: Translate }) {
  if (orders.length === 0) return <EmptyHint text={t("paper.orders.empty")} />;
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
          <tr>
            <Th>{t("paper.col.time")}</Th>
            <Th>{t("paper.col.side")}</Th>
            <Th>{t("paper.col.name")}</Th>
            <Th>{t("paper.col.qty")}</Th>
            <Th>{t("paper.col.price")}</Th>
            <Th>{t("paper.col.amount")}</Th>
            <Th>{t("paper.col.commission")}</Th>
            <Th>{t("paper.col.stampTax")}</Th>
            <Th>{t("paper.col.transferFee")}</Th>
            <Th>{t("paper.col.session")}</Th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id} className="border-t border-border/60">
              <td className="px-3 py-2.5 text-xs text-muted-foreground">
                {o.traded_at.replace("T", " ").slice(0, 16)}
              </td>
              <td className="px-3 py-2.5">
                <span
                  className={`rounded px-1.5 py-0.5 text-xs ${
                    o.side === "buy"
                      ? "bg-red-500/10 text-red-500"
                      : "bg-green-600/10 text-green-600"
                  }`}
                >
                  {t(`paper.side.${o.side}`)}
                </span>
              </td>
              <td className="px-3 py-2.5">{o.name || o.symbol}</td>
              <td className="px-3 py-2.5">{o.qty}</td>
              <td className="px-3 py-2.5">{fmtMoney(o.price)}</td>
              <td className="px-3 py-2.5">{fmtMoney(o.amount)}</td>
              <td className="px-3 py-2.5">{fmtMoney(o.commission)}</td>
              <td className="px-3 py-2.5">{fmtMoney(o.stamp_tax)}</td>
              <td className="px-3 py-2.5">{fmtMoney(o.transfer_fee)}</td>
              <td className="px-3 py-2.5 text-xs text-muted-foreground">
                {o.price_session === "live"
                  ? t("paper.session.live")
                  : t("paper.session.close")}
                {" · "}
                {o.price_trade_date}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ClosesView({
  closes,
  stats,
  totalFees,
  t,
}: {
  closes: PaperClose[];
  stats: PaperCloseStats | null;
  totalFees: number;
  t: Translate;
}) {
  return (
    <div>
      {stats && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label={t("paper.stats.closes")} value={String(stats.closes)} />
          <StatCard
            label={t("paper.stats.winRate")}
            value={`${(stats.win_rate * 100).toFixed(1)}%`}
            sub={`${stats.wins}/${stats.closes}`}
          />
          <StatCard
            label={t("paper.stats.avgReturn")}
            value={fmtPct(stats.avg_return_pct)}
            valueClass={pnlClass(stats.avg_return_pct)}
          />
          <StatCard
            label={t("paper.stats.totalPnl")}
            value={signedMoney(stats.total_realized_pnl)}
            valueClass={pnlClass(stats.total_realized_pnl)}
          />
          <StatCard
            label={t("paper.stats.avgPnl")}
            value={signedMoney(stats.avg_pnl)}
            valueClass={pnlClass(stats.avg_pnl)}
          />
          <StatCard
            label={t("paper.stats.avgHoldingDays")}
            value={String(Math.round(stats.avg_holding_days))}
          />
          <StatCard label={t("paper.stats.totalFees")} value={fmtMoney(totalFees)} />
        </div>
      )}
      {closes.length === 0 ? (
        <EmptyHint text={t("paper.closes.empty")} />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                <Th>{t("paper.col.name")}</Th>
                <Th>{t("paper.col.qty")}</Th>
                <Th>{t("paper.closes.buyPrice")}</Th>
                <Th>{t("paper.closes.sellPrice")}</Th>
                <Th>{t("paper.closes.buyCost")}</Th>
                <Th>{t("paper.closes.proceeds")}</Th>
                <Th>{t("paper.col.unrealizedPnl")}</Th>
                <Th>{t("paper.col.returnPct")}</Th>
                <Th>{t("paper.closes.holdingDays")}</Th>
                <Th>{t("paper.col.chanlunScore")}</Th>
              </tr>
            </thead>
            <tbody>
              {closes.map((c) => (
                <tr key={c.id} className="border-t border-border/60">
                  <td className="px-3 py-2.5">
                    <div className="font-medium">{c.name || c.symbol}</div>
                    <div className="text-xs text-muted-foreground">
                      {c.bought_at?.replace("T", " ").slice(0, 10)} →{" "}
                      {c.sold_at?.replace("T", " ").slice(0, 10)}
                    </div>
                  </td>
                  <td className="px-3 py-2.5">{c.qty}</td>
                  <td className="px-3 py-2.5">{fmtMoney(c.buy_price)}</td>
                  <td className="px-3 py-2.5">{fmtMoney(c.sell_price)}</td>
                  <td className="px-3 py-2.5">{fmtMoney(c.buy_cost)}</td>
                  <td className="px-3 py-2.5">{fmtMoney(c.sell_proceeds)}</td>
                  <td className={`px-3 py-2.5 ${pnlClass(c.realized_pnl)}`}>
                    {signedMoney(c.realized_pnl)}
                  </td>
                  <td className={`px-3 py-2.5 ${pnlClass(c.return_pct)}`}>
                    {fmtPct(c.return_pct)}
                  </td>
                  <td className="px-3 py-2.5">{c.holding_days}</td>
                  <td className="px-3 py-2.5">
                    {c.chanlun_score === null || c.chanlun_score === undefined
                      ? "-"
                      : `${c.chanlun_score} / 5`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-3 py-2.5 font-medium">{children}</th>;
}

function EmptyHint({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}
