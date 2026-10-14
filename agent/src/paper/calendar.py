"""A-share trading calendar and session clock for the paper portfolio.

Time zone is fixed to ``Asia/Shanghai``. Trading day status prefers the local
DuckDB ``trading_calendar`` (market='a_share') maintained by the market-data
pipeline; when the table is missing or stale it falls back to a Mon–Fri
weekday heuristic (mirroring ``watchlist.db.resolve_market_dates``).

Session windows: 09:30–11:30 and 13:00–15:00. The refresh anchors are the
ends of the two 2-hour blocks starting at each open: **11:30** and **15:00**.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")

MORNING_START = time(9, 30)
MORNING_END = time(11, 30)
AFTERNOON_START = time(13, 0)
AFTERNOON_END = time(15, 0)

#: 2-hour anchors measured from each session open (9:30+2h, 13:00+2h).
ANCHORS: tuple[time, ...] = (MORNING_END, AFTERNOON_END)

#: Grace window after an anchor during which a late server start still runs it.
ANCHOR_GRACE = timedelta(minutes=5)


@dataclass(frozen=True)
class MarketClock:
    """Current market state at :attr:`now`."""

    now: datetime
    is_trading_day: bool
    is_live: bool
    #: Trading day the executable price belongs to (today in-session / after
    #: close; the previous open day before open or on weekends/holidays).
    trade_date: date


def now_cn() -> datetime:
    """Current tz-aware timestamp in the China zone."""
    return datetime.now(CN_TZ)


def _calendar_is_open(conn: Any, day: date) -> bool | None:
    """Return is_open for ``day`` from trading_calendar, or None if no data."""
    try:
        row = conn.execute(
            "SELECT is_open FROM trading_calendar "
            "WHERE market = 'a_share' AND cal_date = ?",
            [day],
        ).fetchone()
    except Exception:  # noqa: BLE001 - missing table / uninitialized warehouse
        return None
    if row is None:
        return None
    return bool(row[0])


def _calendar_latest_open_le(conn: Any, day: date) -> date | None:
    try:
        row = conn.execute(
            "SELECT max(cal_date) FROM trading_calendar "
            "WHERE market = 'a_share' AND is_open AND cal_date <= ?",
            [day],
        ).fetchone()
    except Exception:  # noqa: BLE001
        return None
    return row[0] if row and isinstance(row[0], date) else None


def is_trading_day(conn: Any, day: date | None = None) -> bool:
    """Whether ``day`` (default: today CN) is an A-share open day."""
    day = day or now_cn().date()
    flagged = _calendar_is_open(conn, day)
    if flagged is not None:
        return flagged
    return day.weekday() < 5


def previous_open_day(conn: Any, day: date) -> date:
    """Latest open day strictly before ``day`` (calendar then weekday walk)."""
    cached = _calendar_latest_open_le(conn, day - timedelta(days=1))
    if cached is not None:
        return cached
    cursor = day - timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def latest_open_day_le(conn: Any, day: date) -> date:
    """Latest open day on or before ``day`` (calendar then weekday walk)."""
    cached = _calendar_latest_open_le(conn, day)
    if cached is not None:
        return cached
    cursor = day
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def _in_live_window(t: time) -> bool:
    if MORNING_START <= t < MORNING_END:
        return True
    if AFTERNOON_START <= t < AFTERNOON_END:
        return True
    return False


def market_clock(conn: Any, *, now: datetime | None = None) -> MarketClock:
    """Resolve the market state used for price/session/T+1 decisions."""
    moment = now or now_cn()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=CN_TZ)
    today = moment.date()
    open_today = is_trading_day(conn, today)
    t = moment.timetz().replace(tzinfo=None)

    if open_today and _in_live_window(t):
        return MarketClock(now=moment, is_trading_day=True, is_live=True,
                           trade_date=today)
    if open_today and t < MORNING_START:
        return MarketClock(now=moment, is_trading_day=True, is_live=False,
                           trade_date=previous_open_day(conn, today))
    if open_today:
        # Lunch break (11:30–13:00) and after close (>=15:00): the day's
        # latest traded/close price belongs to today.
        return MarketClock(now=moment, is_trading_day=True, is_live=False,
                           trade_date=today)
    # Weekend / holiday: last trading day's close.
    return MarketClock(now=moment, is_trading_day=False, is_live=False,
                       trade_date=latest_open_day_le(conn, today))


def due_anchors(
    conn: Any,
    *,
    now: datetime | None = None,
    executed: set[tuple[date, time]] | None = None,
) -> list[time]:
    """Anchors due at ``now`` and not yet executed (today only).

    An anchor more than :data:`ANCHOR_GRACE` in the past is treated as
    already executed so a server started mid-day never backfills prices.
    """
    moment = now or now_cn()
    if not is_trading_day(conn, moment.date()):
        return []
    executed = executed or set()
    t = moment.timetz().replace(tzinfo=None)
    due: list[time] = []
    for anchor in ANCHORS:
        key = (moment.date(), anchor)
        if key in executed:
            continue
        if t < anchor:
            continue
        if (datetime.combine(moment.date(), t)
              - datetime.combine(moment.date(), anchor) > ANCHOR_GRACE):
            executed.add(key)  # server was down at this anchor; do not backfill
            continue
        due.append(anchor)
    return due
