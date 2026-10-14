"""Price resolution for paper trades and periodic refreshes.

Two sessions:
* ``live``  — in-session (09:30–11:30, 13:00–15:00 trading day): Eastmoney
  ``ulist`` latest price via ``watchlist.market.fetch_quote_snapshots``.
* ``close`` — everything else: the close of the price-owning trading day,
  resolved offline-first from the warehouse (``daily_bar`` / 1d kline via
  ``watchlist.db.latest_close_on``) and falling back to the Eastmoney quote,
  whose ``f2`` field is the last close outside live trading.

All network goes through the injectable fetcher, keeping tests offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence

from src.paper import calendar as paper_calendar
from src.paper.errors import PaperDataError
from src.watchlist import db as watch_db
from src.watchlist import market as watch_market


@dataclass(frozen=True)
class Price:
    symbol: str
    price: Decimal
    session: str  # 'live' | 'close'
    trade_date: date
    source: str


def _live_prices(
    symbols: Sequence[str],
    trade_date: date,
    *,
    fetcher: Any,
) -> dict[str, Price]:
    snapshots = watch_market.fetch_quote_snapshots(list(symbols), fetcher=fetcher)
    out: dict[str, Price] = {}
    for symbol in symbols:
        snap = snapshots.get(symbol)
        if snap is None or snap.price is None:
            continue
        out[symbol] = Price(
            symbol=symbol,
            price=Decimal(str(snap.price)),
            session="live",
            trade_date=trade_date,
            source="eastmoney:ulist",
        )
    return out


def _close_prices(
    conn: Any,
    symbols: Sequence[str],
    trade_date: date,
    *,
    fetcher: Any,
) -> dict[str, Price]:
    out: dict[str, Price] = {}
    missing: list[str] = []
    for symbol in symbols:
        bar = None
        try:
            bar = watch_db.latest_close_on(symbol, trade_date, conn)
        except Exception:  # noqa: BLE001 - warehouse optional, fall through
            bar = None
        if bar and bar.get("close") is not None:
            out[symbol] = Price(
                symbol=symbol,
                price=Decimal(str(bar["close"])),
                session="close",
                trade_date=bar["trade_date"]
                if isinstance(bar.get("trade_date"), date)
                else trade_date,
                source="warehouse:daily_bar",
            )
        else:
            missing.append(symbol)

    if missing:
        snapshots = watch_market.fetch_quote_snapshots(missing, fetcher=fetcher)
        for symbol in missing:
            snap = snapshots.get(symbol)
            if snap is None or snap.price is None:
                continue
            out[symbol] = Price(
                symbol=symbol,
                price=Decimal(str(snap.price)),
                session="close",
                trade_date=trade_date,
                source="eastmoney:ulist:close",
            )
    return out


def resolve_prices(
    conn: Any,
    symbols: Sequence[str],
    *,
    now: datetime | None = None,
    fetcher: Any = None,
) -> dict[str, Price]:
    """Resolve executable prices (live or close) for many symbols.

    Raises :class:`PaperDataError` if any symbol cannot be priced at all.
    """
    normalized = [watch_market.normalize_a_share_symbol(s) for s in symbols]
    if not normalized:
        return {}
    unique = list(dict.fromkeys(normalized))
    clock = paper_calendar.market_clock(conn, now=now)
    if clock.is_live:
        prices = _live_prices(unique, clock.trade_date, fetcher=fetcher)
    else:
        prices = _close_prices(conn, unique, clock.trade_date, fetcher=fetcher)

    unresolved = [s for s in unique if s not in prices]
    if unresolved:
        raise PaperDataError(
            "以下标的暂时无法获取行情价格（实时价与收盘价均失败）: "
            + ", ".join(unresolved)
        )
    return prices


def resolve_price(
    conn: Any,
    symbol: str,
    *,
    now: datetime | None = None,
    fetcher: Any = None,
) -> Price:
    return resolve_prices(conn, [symbol], now=now, fetcher=fetcher)[
        watch_market.normalize_a_share_symbol(symbol)
    ]
