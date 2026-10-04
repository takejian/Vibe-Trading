"""Objective-data K-line tool (local archive first, online fallback).

Industry-standard tool-callback replacement for injecting archived bars
into the role prompt (BDD rule 21): technical roles such as the Chanlun
analyst call ``objective_kline`` to read the multi-level OHLCV bars the
platform archives on the 「客观数据」 page. The tool never fabricates data:

1. Read the locally archived bars for the requested A-share symbol/level.
2. ``refresh="auto"`` (default): when the level is missing or stale, fetch
   from the online source chain once and archive the new bars, then read
   them back. Existing bars survive a failed refresh.
3. ``refresh="never"``: strictly local; ``refresh="always"``: force online.

The result always carries the level freshness, provenance and any refresh
error, so the agent can distinguish ready / stale / blind-spot levels.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.agent.tools import BaseTool
from src.watchlist import db as watch_db
from src.watchlist import kline as watch_kline
from src.watchlist.market import normalize_a_share_symbol
from src.watchlist.store import WatchlistError

logger = logging.getLogger(__name__)

#: Hard cap so a single call cannot flood the model context; callers can
#: page with start/end later if more history is ever needed.
_MAX_LIMIT = 2000
_DEFAULT_LIMIT = 500


def _payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


class ObjectiveKlineTool(BaseTool):
    """Read archived objective K-lines; fetch online only when stale."""

    name = "objective_kline"
    description = (
        "A-share multi-level OHLCV K-lines for technical analysis (Chanlun, "
        "Elliott Wave, indicators). Data policy: it reads the platform's "
        "archived objective data (the 「客观数据」 page) FIRST; only when the "
        "local archive for a level is missing or stale does refresh='auto' "
        "(the default) fetch the level once from the online source and "
        "archive it. Call this BEFORE get_market_data or writing raw "
        "eastmoney/baostock scripts for an A-share symbol. Levels: '1d' day, "
        "'1w' week, '1mo' month, '1q' quarter, '1y' year, '30m' 30-minute. "
        "Bars are returned in ascending time order as JSON. The payload "
        "reports level_status (ready/insufficient/not_fetched/failed), "
        "fresh, source and refresh_error — never invent prices for a level "
        "whose status is not ready; mark it as a data blind spot."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": (
                    "A-share code, e.g. '301606.SZ', '600519.SH', '830799.BJ'; "
                    "a bare 6-digit code ('600519') is accepted too."
                ),
            },
            "interval": {
                "type": "string",
                "enum": list(watch_kline.ALL_INTERVALS),
                "description": "K-line level. Default '1d'.",
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"Maximum number of most-recent bars to return "
                    f"(default {_DEFAULT_LIMIT}, max {_MAX_LIMIT})."
                ),
            },
            "refresh": {
                "type": "string",
                "enum": ["auto", "never", "always"],
                "description": (
                    "'auto' (default): use the local archive, fetch online "
                    "only when the level is missing/stale; 'never': local "
                    "archive only; 'always': force an online refresh even "
                    "when the archive is ready."
                ),
            },
        },
        "required": ["symbol"],
    }
    # Read-through market-data accessor; a successful refresh only upserts
    # bars into the local market warehouse, never places orders or mutates
    # research/portfolio state, so it stays a readonly tool like
    # get_market_data.
    repeatable = True

    def execute(
        self,
        symbol: str,
        interval: str = "1d",
        limit: int = _DEFAULT_LIMIT,
        refresh: str = "auto",
        **_: Any,
    ) -> str:
        raw_interval = str(interval or "1d").strip()
        if raw_interval not in watch_kline.ALL_INTERVALS:
            return _payload(
                {
                    "status": "error",
                    "error": (
                        f"unsupported interval {raw_interval!r}; expected one "
                        f"of {', '.join(watch_kline.ALL_INTERVALS)}"
                    ),
                }
            )
        if refresh not in ("auto", "never", "always"):
            return _payload(
                {
                    "status": "error",
                    "error": (
                        f"unsupported refresh {refresh!r}; expected "
                        "'auto', 'never' or 'always'"
                    ),
                }
            )
        try:
            cap = int(limit)
        except (TypeError, ValueError):
            cap = _DEFAULT_LIMIT
        cap = max(1, min(cap, _MAX_LIMIT))

        try:
            normalized = normalize_a_share_symbol(symbol)
        except WatchlistError as exc:
            return _payload({"status": "error", "error": str(exc)})

        conn = watch_db.watchlist_connection()
        try:
            watch_db.initialize_schema(conn)

            def _state() -> dict[str, Any]:
                states = watch_kline.list_level_states(normalized, conn)
                for item in states.get("items", []):
                    if item.get("interval") == raw_interval:
                        return item
                return {}

            before = _state()
            needs_refresh = refresh == "always" or (
                refresh == "auto" and before.get("status") != watch_kline.READY
            )

            refreshed = False
            refresh_error: str | None = None
            if needs_refresh:
                logger.info(
                    "objective_kline refresh: %s %s status=%s mode=%s",
                    normalized,
                    raw_interval,
                    before.get("status"),
                    refresh,
                )
                watch_kline.update_levels(
                    normalized,
                    [raw_interval],
                    conn,
                    source=watch_kline.DEFAULT_SOURCE,
                )
                refreshed = True
                after = _state()
                if after.get("fetch_failed"):
                    refresh_error = after.get("last_error") or (
                        "online refresh failed for this level"
                    )
                state = after
            else:
                state = before

            bars = watch_db.list_kline_bars(normalized, raw_interval, conn=conn)
        finally:
            conn.close()

        total = len(bars)
        page = bars[-cap:]
        level_status = str(state.get("status") or watch_kline.NOT_FETCHED)
        fresh = level_status == watch_kline.READY

        if total == 0:
            # Explicit failure contract: no archived bars and the online
            # refresh (if attempted) produced nothing — never return fake
            # bars. The role must treat this level as a blind spot.
            return _payload(
                {
                    "status": "error",
                    "error": (
                        f"no {raw_interval} bars available for {normalized}: "
                        f"level_status={level_status}"
                        + (f"; online refresh error: {refresh_error}" if refresh_error else "")
                    ),
                    "symbol": normalized,
                    "interval": raw_interval,
                    "level_status": level_status,
                    "refreshed": refreshed,
                    "refresh_error": refresh_error,
                    "bars": [],
                }
            )

        return _payload(
            {
                "status": "ok",
                "symbol": normalized,
                "interval": raw_interval,
                "level_status": level_status,
                "fresh": fresh,
                "refreshed": refreshed,
                "refresh_error": refresh_error,
                "source": state.get("source"),
                "bars_count": total,
                "returned_bars": len(page),
                "earliest_bar_time": str(page[0]["trade_date"]),
                "latest_bar_time": str(page[-1]["trade_date"]),
                "bars": page,
            }
        )
