"""Multi-level K-line readiness for the Chanlun pre-run gate (M16).

Business contract (see BDD.md US-08A / rules 15-20):

* Five **required** levels for the Chanlun analyst: day / week / month /
  quarter / year (``1d`` / ``1w`` / ``1mo`` / ``1q`` / ``1y``).
* One **optional** level: 30-minute (``30m``) — public sources often fail to
  serve minute bars; it is never part of the run gate.
* A level is ``ready`` only when BOTH hold:
  - bar count at or above the minimum for the level
    (year 5 / quarter 12 / month 24 / week 60 / day 120);
  - the latest bar is no older than the 2nd-to-last trading day
    (weekends, holidays and suspensions are deferred by the threshold
    resolver in :mod:`src.watchlist.db`).
* Fetch failures never delete old bars; the row keeps its data-based status
  plus a ``fetch_failed`` marker so the UI can offer a per-level retry.

Like :mod:`src.watchlist.market`, every network entry point takes an
injectable fetcher and never goes through the LLM stack.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import duckdb

from src.watchlist import db as watch_db
from src.watchlist import kline_sources
from src.watchlist.market import (
    WatchlistDataError,
    normalize_a_share_symbol,
    to_eastmoney_secid,
)

logger = logging.getLogger(__name__)

#: Default source for the card — explicit Eastmoney, matching the chain's
#: historical behavior; investors can switch to any a_share chain source.
DEFAULT_SOURCE = "eastmoney"

#: Levels the Chanlun analyst requires before a run is allowed.
REQUIRED_INTERVALS: tuple[str, ...] = ("1d", "1w", "1mo", "1q", "1y")
#: Optional levels (shown with a standalone try-button; never gate a run).
OPTIONAL_INTERVALS: tuple[str, ...] = ("30m",)
ALL_INTERVALS: tuple[str, ...] = REQUIRED_INTERVALS + OPTIONAL_INTERVALS

#: Eastmoney push2his ``klt`` period codes.
_KLT: dict[str, int] = {
    "1d": 101,
    "1w": 102,
    "1mo": 103,
    "1q": 104,
    "1y": 105,
    "30m": 30,
}

#: Minimum bar counts (business rule 16).
_MIN_BARS: dict[str, int] = {
    "1y": 5,
    "1q": 12,
    "1mo": 24,
    "1w": 60,
    "1d": 120,
}
_MIN_BARS_OPTIONAL: dict[str, int] = {"30m": 24}

#: History window per level when fetching — comfortably beyond the minimum.
_LOOKBACK_YEARS: dict[str, int] = {
    "1y": 11,
    "1q": 6,
    "1mo": 5,
    "1w": 3,
    "1d": 2,
}
_30M_LOOKBACK_DAYS = 30

#: Status vocabulary.
READY = "ready"
INSUFFICIENT = "insufficient"
NOT_FETCHED = "not_fetched"
FAILED = "failed"

#: A kline fetcher: (secid, klt, beg_YYYYMMDD, end_YYYYMMDD) -> ascending rows.
KlineFetcher = Callable[[str, int, str, str], list[dict[str, Any]]]


@dataclass(frozen=True)
class LevelState:
    """Readiness state for one interval of one symbol."""

    interval: str
    required: bool
    status: str
    fetch_failed: bool
    bars_count: int
    earliest_bar_time: str | None
    latest_bar_time: str | None
    last_ok_at: datetime | None
    last_attempt_at: datetime | None
    last_error: str | None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "interval": self.interval,
            "required": self.required,
            "status": self.status,
            "fetch_failed": self.fetch_failed,
            "bars_count": self.bars_count,
            "earliest_bar_time": self.earliest_bar_time,
            "latest_bar_time": self.latest_bar_time,
            "last_ok_at": _iso(self.last_ok_at),
            "last_attempt_at": _iso(self.last_attempt_at),
            "last_error": self.last_error,
            "source": self.source,
        }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


def normalize_intervals(intervals: Sequence[str] | None) -> list[str]:
    """Validate an interval list; ``None`` means the required five."""
    if not intervals:
        return list(REQUIRED_INTERVALS)
    chosen: list[str] = []
    for raw in intervals:
        interval = str(raw or "").strip()
        if interval not in _KLT:
            raise ValueError(f"不支持的行情级别: {raw!r}")
        if interval not in chosen:
            chosen.append(interval)
    return chosen


def _bar_date(bar_time: str | None) -> date | None:
    """Parse a bar label — ``2026-09-30`` or ``2026-09-30 10:00:00``."""
    text = (bar_time or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def evaluate_level(
    interval: str,
    *,
    bars_count: int,
    latest_bar_time: str | None,
    ever_succeeded: bool,
    last_error: str | None,
    threshold_date: date | None,
) -> str:
    """Pure readiness decision for one level (business rules 16/20).

    ``threshold_date`` is the 2nd-to-last market trading day; it is applied
    to required levels only. The optional 30-minute level is never gated on
    freshness.
    """
    required = interval in REQUIRED_INTERVALS
    if bars_count <= 0:
        return FAILED if (last_error and not ever_succeeded) else NOT_FETCHED
    minimum = (
        _MIN_BARS.get(interval)
        if required
        else _MIN_BARS_OPTIONAL.get(interval, 1)
    )
    if bars_count < minimum:
        return INSUFFICIENT
    if required and threshold_date is not None:
        bar_day = _bar_date(latest_bar_time)
        if bar_day is None or bar_day < threshold_date:
            return INSUFFICIENT
    return READY


def _default_kline_fetcher(
    secid: str,
    klt: int,
    beg: str,
    end: str,
) -> list[dict[str, Any]]:
    # Lazy import keeps tests using injected fakes free of transport cost.
    from backtest.loaders.eastmoney_client import fetch_kline

    return fetch_kline(secid, klt=klt, fqt=1, beg=beg, end=end)


def list_sources() -> list[dict[str, Any]]:
    """Catalog of selectable sources (ordered like Settings' priority)."""
    return kline_sources.list_sources()


def normalize_source(source: str | None) -> str:
    """Validate a user-chosen source id (unknown/unavailable -> ValueError)."""
    source_id = (source or DEFAULT_SOURCE).strip()
    ok, reason = kline_sources.availability(source_id)
    if not ok:
        raise ValueError(f"数据源不可用: {source_id} ({reason})")
    return source_id


def fetch_level(
    symbol: str,
    interval: str,
    *,
    source: str = DEFAULT_SOURCE,
    fetcher: KlineFetcher | None = None,
    adapter: kline_sources.SourceAdapter | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Fetch one level of K-line bars straight from the data API (never AI).

    ``source`` selects the vendor (see :func:`list_sources`); Eastmoney keeps
    its native injectable ``fetcher`` (tests), other sources use the adapter
    registry in :mod:`src.watchlist.kline_sources`.

    Raises :class:`WatchlistDataError` on network failure or an empty
    payload; callers persist the failure per-level without touching other
    levels or existing bars.
    """
    normalized = normalize_a_share_symbol(symbol)
    if interval not in _KLT:
        raise ValueError(f"不支持的行情级别: {interval!r}")
    day = today or date.today()
    if interval == "30m":
        start = day - timedelta(days=_30M_LOOKBACK_DAYS)
    else:
        start = day - timedelta(days=365 * _LOOKBACK_YEARS[interval] + 30)
    end = day

    if source == "eastmoney":
        fetch = fetcher or _default_kline_fetcher
        try:
            rows = fetch(
                to_eastmoney_secid(normalized),
                _KLT[interval],
                start.strftime("%Y%m%d"),
                "20500101",
            )
        except WatchlistDataError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize to typed error
            raise WatchlistDataError(f"{interval} 行情接口请求失败: {exc}") from exc
        if not rows:
            raise WatchlistDataError(f"{interval} 行情接口未返回数据")
        return rows

    rows = kline_sources.fetch_source_level(
        source,
        normalized,
        interval,
        start,
        end,
        adapter=adapter,
    )
    return rows


def update_levels(
    symbol: str,
    intervals: Sequence[str] | None,
    conn: duckdb.DuckDBPyConnection,
    *,
    source: str = DEFAULT_SOURCE,
    fetcher: KlineFetcher | None = None,
    adapter: kline_sources.SourceAdapter | None = None,
    today: date | None = None,
) -> list[str]:
    """Fetch and persist the given levels; one level's failure never blocks
    another level. Returns the intervals actually attempted (in order).

    The chosen ``source`` is stamped on each successful level; a failed
    attempt keeps the level's previous source (and its old bars).
    """
    normalized = normalize_a_share_symbol(symbol)
    chosen = normalize_intervals(intervals)
    for interval in chosen:
        try:
            rows = fetch_level(
                normalized,
                interval,
                source=source,
                fetcher=fetcher,
                adapter=adapter,
                today=today,
            )
        except WatchlistDataError as exc:
            logger.warning(
                "kline fetch failed: %s %s via %s — %s",
                normalized,
                interval,
                source,
                exc,
            )
            watch_db.record_kline_fetch(
                normalized, interval, ok=False, error=str(exc), conn=conn
            )
            continue
        watch_db.upsert_kline_bars(
            normalized, interval, rows, source=source, conn=conn
        )
        watch_db.record_kline_fetch(
            normalized, interval, ok=True, error=None, source=source, conn=conn
        )
    return chosen


def list_level_states(
    symbol: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Return readiness states for every interval plus the market reference.

    Response shape::

        {"items": [LevelState...], "market_ref":
         {"last_trading_date": ..., "threshold_date": ..., "source": ...}}
    """
    normalized = normalize_a_share_symbol(symbol)
    day = today or date.today()
    last_open, threshold, ref_source = watch_db.resolve_market_dates(conn, today=day)
    rows = watch_db.list_kline_status_rows(normalized, conn)
    by_interval = {row["interval"]: row for row in rows}

    items: list[dict[str, Any]] = []
    for interval in ALL_INTERVALS:
        row = by_interval.get(interval)
        if row is None:
            state = LevelState(
                interval=interval,
                required=interval in REQUIRED_INTERVALS,
                status=NOT_FETCHED,
                fetch_failed=False,
                bars_count=0,
                earliest_bar_time=None,
                latest_bar_time=None,
                last_ok_at=None,
                last_attempt_at=None,
                last_error=None,
            )
        else:
            ever_ok = row.get("last_ok_at") is not None
            last_error = row.get("last_error")
            bars_count = int(row.get("bars_count") or 0)
            status = evaluate_level(
                interval,
                bars_count=bars_count,
                latest_bar_time=row.get("latest_bar_time"),
                ever_succeeded=ever_ok,
                last_error=last_error,
                threshold_date=threshold,
            )
            fetch_failed = bool(
                last_error
                and row.get("last_attempt_at") is not None
                and (
                    row.get("last_ok_at") is None
                    or row["last_attempt_at"] > row["last_ok_at"]
                )
            )
            state = LevelState(
                interval=interval,
                required=interval in REQUIRED_INTERVALS,
                status=status,
                fetch_failed=fetch_failed,
                bars_count=bars_count,
                earliest_bar_time=row.get("earliest_bar_time"),
                latest_bar_time=row.get("latest_bar_time"),
                last_ok_at=row.get("last_ok_at"),
                last_attempt_at=row.get("last_attempt_at"),
                last_error=last_error if fetch_failed else None,
                source=row.get("source"),
            )
        items.append(state.to_dict())

    return {
        "items": items,
        "market_ref": {
            "last_trading_date": last_open.isoformat() if last_open else None,
            "threshold_date": threshold.isoformat() if threshold else None,
            "source": ref_source,
        },
    }


def missing_required_levels(states: dict[str, Any]) -> list[dict[str, Any]]:
    """Required levels that are not ``ready`` (the Chanlun gate input)."""
    return [
        item
        for item in states.get("items", [])
        if item.get("required") and item.get("status") != READY
    ]
