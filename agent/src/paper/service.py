"""Business logic for the simulated paper portfolio.

All money math uses :class:`decimal.Decimal` and is rounded to the fen
(0.01 yuan) before persistence; floats appear only at the DB/JSON boundary.

Key rules:
* buy/sell prices are always resolved server-side (live in-session, last
  close otherwise) — clients only submit ``{symbol, qty}``;
* A-share T+1: a lot bought on trade date D is sellable from the next open
  day (``bought_on < price.trade_date``);
* sells consume buy lots FIFO and write one ``paper_close`` row per consumed
  lot (a partial fill produces several close rows);
* every fill refreshes the symbol quote snapshot and appends one NAV row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from src.config.accessor import get_env_config
from src.paper import calendar as paper_calendar
from src.paper import db as paper_db
from src.paper.errors import PaperError
from src.paper.prices import Price, resolve_price, resolve_prices
from src.watchlist.market import normalize_a_share_symbol

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
ZERO = Decimal("0")
LOT_SIZE = 100


# ----------------------------------------------------------------------
# Policy / helpers
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class FeePolicy:
    initial_capital: Decimal
    commission_rate: Decimal
    commission_min: Decimal
    stamp_tax_rate: Decimal
    transfer_fee_rate: Decimal
    refresh_enabled: bool

    @classmethod
    def from_env(cls) -> "FeePolicy":
        p = get_env_config().paper
        return cls(
            initial_capital=Decimal(str(p.vibe_paper_initial_cash)),
            commission_rate=Decimal(str(p.vibe_paper_commission_rate)),
            commission_min=Decimal(str(p.vibe_paper_commission_min)),
            stamp_tax_rate=Decimal(str(p.vibe_paper_stamp_tax_rate)),
            transfer_fee_rate=Decimal(str(p.vibe_paper_transfer_fee_rate)),
            refresh_enabled=bool(p.vibe_paper_refresh_enabled),
        )


def _money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _as_float(value: Decimal) -> float:
    return float(_money(value))


def _naive(now: datetime | None) -> datetime:
    if now is None:
        return paper_calendar.now_cn().replace(tzinfo=None)
    if now.tzinfo is not None:
        return now.astimezone(paper_calendar.CN_TZ).replace(tzinfo=None)
    return now


def validate_qty(qty: Any) -> int:
    """A-share board lot validation: positive 100-share multiple."""
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise PaperError("买入/卖出数量必须为整数（股）")
    if qty <= 0:
        raise PaperError("买入/卖出数量必须大于 0")
    if qty % LOT_SIZE != 0:
        raise PaperError(f"A 股数量须为 {LOT_SIZE} 股的整数倍")
    return qty


def calc_fees(
    policy: FeePolicy, side: str, amount: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (commission, stamp_tax, transfer_fee) in yuan, rounded to fen."""
    commission = _money(max(amount * policy.commission_rate,
                            policy.commission_min))
    stamp_tax = (
        _money(amount * policy.stamp_tax_rate) if side == "sell" else ZERO
    )
    transfer_fee = _money(amount * policy.transfer_fee_rate)
    return commission, stamp_tax, transfer_fee


def get_or_create_account(
    conn: Any, policy: FeePolicy, *, now: datetime | None = None
) -> dict[str, Any]:
    ts = _naive(now)
    account = paper_db.get_account(conn)
    if account is None:
        account = paper_db.create_account(
            conn, float(policy.initial_capital), now=ts
        )
        paper_db.insert_nav(
            conn,
            snapped_at=ts,
            cash=float(policy.initial_capital),
            market_value=0.0,
            total_asset=float(policy.initial_capital),
            initial_capital=float(policy.initial_capital),
        )
    return account


def _default_membership() -> Any:
    # Localized import: paper (L2) uses the watchlist (L2) JSON membership.
    from src.watchlist.store import WatchlistStore

    return WatchlistStore()


def _require_watched(store: Any, symbol: str) -> None:
    if not store.contains(symbol):
        raise PaperError(f"该标的不在关注列表中，无法模拟买入: {symbol}")


# ----------------------------------------------------------------------
# NAV / valuation
# ----------------------------------------------------------------------
def _market_values(
    conn: Any, quotes: dict[str, dict[str, Any]] | None = None
) -> dict[str, Decimal]:
    """Current market value per open symbol using the latest quote."""
    lots = paper_db.list_open_lots(conn)
    if not lots:
        return {}
    quotes = quotes if quotes is not None else paper_db.latest_quotes(
        conn, sorted({lot["symbol"] for lot in lots})
    )
    values: dict[str, Decimal] = {}
    for lot in lots:
        quote = quotes.get(lot["symbol"])
        price = (
            Decimal(str(quote["price"]))
            if quote is not None
            else Decimal(str(lot["price"]))
        )
        values[lot["symbol"]] = (
            values.get(lot["symbol"], ZERO)
            + price * Decimal(lot["qty_remaining"])
        )
    return values


def _snapshot_nav(
    conn: Any, policy: FeePolicy, *, now: datetime | None = None
) -> dict[str, Any]:
    ts = _naive(now)
    account = paper_db.get_account(conn)
    assert account is not None
    values = _market_values(conn)
    market_value = _money(sum(values.values(), ZERO))
    cash = Decimal(str(account["cash_balance"]))
    total = _money(cash + market_value)
    paper_db.insert_nav(
        conn,
        snapped_at=ts,
        cash=_as_float(cash),
        market_value=_as_float(market_value),
        total_asset=_as_float(total),
        initial_capital=float(account["initial_capital"]),
    )
    return {"snapped_at": ts, "market_value": market_value, "total_asset": total}


# ----------------------------------------------------------------------
# Buy
# ----------------------------------------------------------------------
def buy(
    conn: Any,
    symbol: str,
    qty: int,
    *,
    now: datetime | None = None,
    fetcher: Any = None,
    watch_store: Any = None,
    policy: FeePolicy | None = None,
) -> dict[str, Any]:
    policy = policy or FeePolicy.from_env()
    symbol = normalize_a_share_symbol(symbol)
    qty = validate_qty(qty)
    store = watch_store or _default_membership()
    _require_watched(store, symbol)
    try:
        entry_name = (store.get_entry(symbol).name or "").strip() or None
    except Exception:  # noqa: BLE001 - name is display-only
        entry_name = None

    account = get_or_create_account(conn, policy, now=now)
    price: Price = resolve_price(conn, symbol, now=now, fetcher=fetcher)
    amount = _money(price.price * qty)
    commission, stamp_tax, transfer_fee = calc_fees(policy, "buy", amount)
    total_cost = _money(amount + commission + transfer_fee)

    cash = Decimal(str(account["cash_balance"]))
    if total_cost > cash:
        raise PaperError(
            f"可用资金不足：需要 {total_cost} 元，当前可用 {_money(cash)} 元"
        )

    chan = paper_db.latest_chanlun(conn, symbol)
    ts = _naive(now)
    order_id = paper_db.new_id()
    order = {
        "id": order_id,
        "side": "buy",
        "symbol": symbol,
        "name": entry_name,
        "qty": qty,
        "price": _as_float(price.price),
        "amount": _as_float(amount),
        "commission": _as_float(commission),
        "stamp_tax": _as_float(stamp_tax),
        "transfer_fee": _as_float(transfer_fee),
        "price_session": price.session,
        "price_trade_date": price.trade_date,
        "chanlun_run_id": (chan or {}).get("run_id"),
        "chanlun_score": (chan or {}).get("score"),
        "chanlun_confidence": (chan or {}).get("confidence"),
        "chanlun_score_text": (chan or {}).get("dim7_chanlun_score"),
        "chanlun_analyzed_at": (chan or {}).get("analyzed_at"),
        "traded_at": ts,
    }
    paper_db.insert_order(conn, order)
    paper_db.insert_lot(
        conn,
        {
            "buy_order_id": order_id,
            "symbol": symbol,
            "qty_original": qty,
            "qty_remaining": qty,
            "price": _as_float(price.price),
            "buy_fees": _as_float(commission + transfer_fee),
            "bought_on": price.trade_date,
            "created_at": ts,
        },
    )
    paper_db.update_cash(conn, _as_float(cash - total_cost), now=ts)
    paper_db.upsert_quote(
        conn,
        symbol=symbol,
        price=_as_float(price.price),
        snapped_at=ts,
        source=price.source,
    )
    _snapshot_nav(conn, policy, now=ts)
    return {"order": order, "price_session": price.session,
            "price_trade_date": price.trade_date}


# ----------------------------------------------------------------------
# Sell (T+1, FIFO)
# ----------------------------------------------------------------------
def sell(
    conn: Any,
    symbol: str,
    qty: int,
    *,
    now: datetime | None = None,
    fetcher: Any = None,
    policy: FeePolicy | None = None,
) -> dict[str, Any]:
    policy = policy or FeePolicy.from_env()
    symbol = normalize_a_share_symbol(symbol)
    qty = validate_qty(qty)
    account = get_or_create_account(conn, policy, now=now)
    price = resolve_price(conn, symbol, now=now, fetcher=fetcher)

    lots = [
        lot
        for lot in paper_db.list_open_lots(conn, symbol)
        if lot["bought_on"] < price.trade_date
    ]
    sellable = sum(int(lot["qty_remaining"]) for lot in lots)
    if sellable <= 0:
        raise PaperError("当前没有 T+1 可卖数量（今日及以后买入的份额下一交易日才可卖）")
    if qty > sellable:
        raise PaperError(f"卖出数量超过可卖数量（当前可卖 {sellable} 股）")

    amount = _money(price.price * qty)
    commission, stamp_tax, transfer_fee = calc_fees(policy, "sell", amount)
    total_fees = _money(commission + stamp_tax + transfer_fee)

    # FIFO allocation; the final lot absorbs the fen rounding remainder.
    allocations: list[dict[str, Any]] = []
    remaining = qty
    fee_allocated = ZERO
    qty_dec = Decimal(qty)
    for idx, lot in enumerate(lots):
        take = min(remaining, int(lot["qty_remaining"]))
        if take <= 0:
            continue
        is_last = (remaining - take) == 0
        gross = _money(price.price * take)
        if is_last:
            fee_part = _money(total_fees - fee_allocated)
        else:
            fee_part = _money(total_fees * Decimal(take) / qty_dec)
            fee_allocated += fee_part
        proceeds = _money(gross - fee_part)

        original = Decimal(int(lot["qty_original"]))
        buy_cost = _money(
            Decimal(str(lot["price"])) * take
            + Decimal(str(lot["buy_fees"])) * Decimal(take) / original
        )
        realized = _money(proceeds - buy_cost)
        return_pct = (
            (realized / buy_cost).quantize(Decimal("0.000001"),
                                           rounding=ROUND_HALF_UP)
            if buy_cost > 0
            else ZERO
        )
        buy_order = paper_db.get_order_by_id(conn, str(lot["buy_order_id"]))
        allocations.append(
            {
                "lot": lot,
                "take": take,
                "buy_cost": buy_cost,
                "proceeds": proceeds,
                "realized": realized,
                "return_pct": return_pct,
                "chanlun_score": (buy_order or {}).get("chanlun_score"),
                "holding_days": (price.trade_date
                                 - lot["bought_on"]).days,
            }
        )
        remaining -= take
        if remaining == 0:
            break
    assert remaining == 0

    ts = _naive(now)
    sell_order_id = paper_db.new_id()
    last_buy_name = None
    for alloc in allocations:
        lot = alloc["lot"]
        paper_db.set_lot_remaining(
            conn, str(lot["id"]), int(lot["qty_remaining"]) - alloc["take"]
        )
        paper_db.insert_close(
            conn,
            {
                "sell_order_id": sell_order_id,
                "buy_order_id": str(lot["buy_order_id"]),
                "symbol": symbol,
                "qty": alloc["take"],
                "buy_cost": _as_float(alloc["buy_cost"]),
                "sell_proceeds": _as_float(alloc["proceeds"]),
                "realized_pnl": _as_float(alloc["realized"]),
                "return_pct": float(alloc["return_pct"]),
                "holding_days": alloc["holding_days"],
                "chanlun_score": alloc["chanlun_score"],
                "created_at": ts,
            },
        )
        bo = paper_db.get_order_by_id(conn, str(lot["buy_order_id"]))
        if bo and bo.get("name"):
            last_buy_name = bo["name"]

    cash = Decimal(str(account["cash_balance"]))
    net_proceeds = _money(amount - total_fees)
    order = {
        "id": sell_order_id,
        "side": "sell",
        "symbol": symbol,
        "name": last_buy_name,
        "qty": qty,
        "price": _as_float(price.price),
        "amount": _as_float(amount),
        "commission": _as_float(commission),
        "stamp_tax": _as_float(stamp_tax),
        "transfer_fee": _as_float(transfer_fee),
        "price_session": price.session,
        "price_trade_date": price.trade_date,
        "chanlun_run_id": None,
        "chanlun_score": None,
        "chanlun_confidence": None,
        "chanlun_score_text": None,
        "chanlun_analyzed_at": None,
        "traded_at": ts,
    }
    paper_db.insert_order(conn, order)
    paper_db.update_cash(conn, _as_float(cash + net_proceeds), now=ts)
    paper_db.upsert_quote(
        conn,
        symbol=symbol,
        price=_as_float(price.price),
        snapped_at=ts,
        source=price.source,
    )
    _snapshot_nav(conn, policy, now=ts)
    return {"order": order, "closes": [
        {"realized_pnl": _as_float(a["realized"]),
         "return_pct": float(a["return_pct"])} for a in allocations
    ], "price_session": price.session,
        "price_trade_date": price.trade_date}





# ----------------------------------------------------------------------
# Queries
# ----------------------------------------------------------------------
def positions(
    conn: Any,
    *,
    now: datetime | None = None,
    policy: FeePolicy | None = None,
) -> dict[str, Any]:
    policy = policy or FeePolicy.from_env()
    get_or_create_account(conn, policy, now=now)
    clock = paper_calendar.market_clock(conn, now=now)
    lots = paper_db.list_open_lots(conn)
    symbols = sorted({lot["symbol"] for lot in lots})
    quotes = paper_db.latest_quotes(conn, symbols)

    # Most recent open lot's buy order per symbol drives the displayed
    # name / decision score (lots arrive FIFO = oldest first).
    latest_buy: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for lot in lots:
        grouped.setdefault(lot["symbol"], []).append(lot)
        latest_buy[lot["symbol"]] = (
            paper_db.get_order_by_id(conn, str(lot["buy_order_id"])) or {}
        )

    items: list[dict[str, Any]] = []
    for symbol in symbols:
        sym_lots = grouped[symbol]
        qty = sum(int(lot["qty_remaining"]) for lot in sym_lots)
        cost = ZERO
        sellable = 0
        for lot in sym_lots:
            remain = Decimal(int(lot["qty_remaining"]))
            original = Decimal(int(lot["qty_original"]))
            cost += (
                Decimal(str(lot["price"])) * remain
                + Decimal(str(lot["buy_fees"])) * remain / original
            )
            if lot["bought_on"] < clock.trade_date:
                sellable += int(lot["qty_remaining"])
        cost = _money(cost)
        avg_cost = _money(cost / Decimal(qty))
        quote = quotes.get(symbol)
        current = (
            Decimal(str(quote["price"])) if quote is not None else avg_cost
        )
        market_value = _money(current * qty)
        unrealized = _money(market_value - cost)
        return_pct = (
            (unrealized / cost).quantize(Decimal("0.000001"),
                                         rounding=ROUND_HALF_UP)
            if cost > 0
            else ZERO
        )
        decision = latest_buy.get(symbol, {})
        items.append(
            {
                "symbol": symbol,
                "name": decision.get("name"),
                "qty": qty,
                "sellable_qty": sellable,
                "avg_cost": _as_float(avg_cost),
                "cost": _as_float(cost),
                "current_price": _as_float(current),
                "price_time": quote["snapped_at"] if quote else None,
                "stale": quote is None
                or quote["snapped_at"].date() < clock.trade_date,
                "market_value": _as_float(market_value),
                "unrealized_pnl": _as_float(unrealized),
                "return_pct": float(return_pct),
                "chanlun_score": decision.get("chanlun_score"),
                "chanlun_confidence": decision.get("chanlun_confidence"),
                "chanlun_score_text": decision.get("chanlun_score_text"),
                "chanlun_analyzed_at": decision.get("chanlun_analyzed_at"),
            }
        )
    return {
        "items": items,
        "is_live": clock.is_live,
        "trade_date": clock.trade_date,
    }


def account(
    conn: Any,
    *,
    now: datetime | None = None,
    policy: FeePolicy | None = None,
) -> dict[str, Any]:
    policy = policy or FeePolicy.from_env()
    acc = get_or_create_account(conn, policy, now=now)
    pos = positions(conn, now=now, policy=policy)
    market_value = _money(
        sum((Decimal(str(i["market_value"])) for i in pos["items"]), ZERO)
    )
    cash = _money(Decimal(str(acc["cash_balance"])))
    total = _money(cash + market_value)
    initial = Decimal(str(acc["initial_capital"]))
    cum_pnl = _money(total - initial)
    cum_return = (
        (cum_pnl / initial).quantize(Decimal("0.000001"),
                                     rounding=ROUND_HALF_UP)
        if initial > 0
        else ZERO
    )
    day_start = datetime.combine(pos["trade_date"], datetime.min.time())
    prev = paper_db.last_nav_before(conn, day_start)
    day_pnl = (
        _money(total - Decimal(str(prev["total_asset"]))) if prev else None
    )
    return {
        "initial_capital": _as_float(initial),
        "cash": _as_float(cash),
        "market_value": _as_float(market_value),
        "total_asset": _as_float(total),
        "cumulative_pnl": _as_float(cum_pnl),
        "cumulative_return_pct": float(cum_return),
        "day_pnl": _as_float(day_pnl) if day_pnl is not None else None,
        "is_live": pos["is_live"],
        "trade_date": pos["trade_date"],
    }


def preview(
    conn: Any,
    symbol: str,
    qty: int | None,
    *,
    side: str = "buy",
    now: datetime | None = None,
    fetcher: Any = None,
    policy: FeePolicy | None = None,
) -> dict[str, Any]:
    """Price + fee trial + latest Chanlun score before confirming a trade."""
    policy = policy or FeePolicy.from_env()
    symbol = normalize_a_share_symbol(symbol)
    price = resolve_price(conn, symbol, now=now, fetcher=fetcher)
    amount = _money(price.price * qty) if qty else ZERO
    if qty:
        commission, stamp_tax, transfer_fee = calc_fees(policy, side, amount)
    else:
        commission = stamp_tax = transfer_fee = ZERO
    chan = paper_db.latest_chanlun(conn, symbol)
    watched = _default_membership().contains(symbol)
    return {
        "symbol": symbol,
        "price": _as_float(price.price),
        "price_session": price.session,
        "price_trade_date": price.trade_date,
        "source": price.source,
        "qty": qty,
        "amount": _as_float(amount),
        "commission": _as_float(commission),
        "stamp_tax": _as_float(stamp_tax),
        "transfer_fee": _as_float(transfer_fee),
        "total_cost": _as_float(amount + commission + transfer_fee),
        "net_proceeds": _as_float(amount - commission - stamp_tax
                                  - transfer_fee),
        "chanlun": chan,
        "watched": watched,
    }


def refresh_quotes(
    conn: Any,
    *,
    now: datetime | None = None,
    fetcher: Any = None,
    policy: FeePolicy | None = None,
) -> int:
    """Batch-refresh prices for every open position; append one NAV row.

    Returns the number of symbols refreshed. Missing symbols keep their last
    price (stale flag); the function never raises for partial quote failure.
    """
    policy = policy or FeePolicy.from_env()
    symbols = paper_db.open_position_symbols(conn)
    if not symbols:
        return 0
    ts = _naive(now)
    try:
        prices = resolve_prices(conn, symbols, now=now, fetcher=fetcher)
    except Exception as exc:  # noqa: BLE001 - partial/all failure: keep stale
        logger.warning("paper quote refresh failed, keeping stale prices: %s",
                       exc)
        return 0
    for symbol, price in prices.items():
        paper_db.upsert_quote(
            conn,
            symbol=symbol,
            price=_as_float(price.price),
            snapped_at=ts,
            source=price.source,
        )
    _snapshot_nav(conn, policy, now=ts)
    return len(prices)


def sync_position_klines(
    conn: Any,
    *,
    symbols: list[str] | None = None,
    intervals: Any = None,
    source: str | None = None,
    fetcher: Any = None,
    today: date | None = None,
) -> dict[str, list[str]]:
    """Refresh Chanlun K-line bars for every open position.

    Runs at the same 11:30 / 15:00 anchors as the quote refresh and covers
    all Chanlun levels (daily/weekly/monthly/quarterly/yearly plus 30m).
    Bars are upserted by ``(symbol, interval, bar_time)``, so the 15:00
    fetch replaces the 11:30 half-session daily bar in place with the
    full-session bar. One symbol's or level's failure never blocks others.
    """
    from src.watchlist import db as watch_db
    from src.watchlist import kline

    symbols = (
        symbols if symbols is not None else paper_db.open_position_symbols(conn)
    )
    if not symbols:
        return {}
    levels = tuple(intervals) if intervals is not None else kline.ALL_INTERVALS
    chosen_source = source or kline.DEFAULT_SOURCE
    watch_db.initialize_schema(conn)
    done: dict[str, list[str]] = {}
    for symbol in symbols:
        try:
            done[symbol] = kline.update_levels(
                symbol,
                levels,
                conn,
                source=chosen_source,
                fetcher=fetcher,
                today=today,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort background sync
            logger.warning("paper kline sync failed for %s: %s", symbol, exc)
    return done


def reset(
    conn: Any,
    *,
    now: datetime | None = None,
    policy: FeePolicy | None = None,
) -> dict[str, Any]:
    policy = policy or FeePolicy.from_env()
    ts = _naive(now)
    acc = paper_db.reset_account(conn, float(policy.initial_capital), now=ts)
    paper_db.insert_nav(
        conn,
        snapped_at=ts,
        cash=float(policy.initial_capital),
        market_value=0.0,
        total_asset=float(policy.initial_capital),
        initial_capital=float(policy.initial_capital),
    )
    return acc


def nav_series(
    conn: Any, range_key: str = "all", *, now: datetime | None = None
) -> list[dict[str, Any]]:
    today = (_naive(now)).date()
    days: int | None = None
    if range_key == "5d":
        days = 7  # calendar days to cover 5 trading days incl. weekend
    elif range_key == "20d":
        days = 28
    date_from = today - timedelta(days=days) if days else None
    return paper_db.list_nav(conn, date_from=date_from)
