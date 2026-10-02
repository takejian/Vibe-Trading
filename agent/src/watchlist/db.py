"""DuckDB persistence for watchlist-adjacent data.

Two concerns live here:

1. **Idempotent writes into the existing warehouse** — quote/profile refreshes
   upsert ``instrument_master`` / ``valuation_daily`` so a refresh never
   duplicates rows or nulls previously-known columns (COALESCE merge).
2. **M16-owned tables** — agent-fetched objective data
   (``watchlist_objective_data``) and parsed Chanlun reports
   (``chanlun_analysis``). Both survive unfollow/re-follow: they are keyed by
   symbol/run_id, never by watchlist membership.

Reads against legacy tables tolerate their absence (fresh DuckDB without the
market schema): a ``CatalogException`` on one category yields an empty list
for that category instead of failing the whole objective tab.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

import duckdb

from src.config.paths import get_market_db_path
from src.watchlist.market import normalize_a_share_symbol
from src.watchlist.models import CompanyProfile, QuoteSnapshot

#: Upper bound for raw-data lists so an endpoint can never dump the warehouse.
_DAILY_BAR_LIMIT = 250
_FINANCIAL_LIMIT = 80
_OBJECTIVE_LIMIT = 200
_CHANLUN_MAX_LIMIT = 100

_DDL = """
CREATE TABLE IF NOT EXISTS instrument_master (
    symbol       VARCHAR PRIMARY KEY,
    name         VARCHAR,
    name_en      VARCHAR,
    market       VARCHAR,
    currency     VARCHAR,
    exchange     VARCHAR,
    list_date    DATE,
    delist_date  DATE,
    lot_size     BIGINT,
    sector       VARCHAR,
    industry     VARCHAR,
    is_active    BOOLEAN DEFAULT true,
    source       VARCHAR,
    updated_at   TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS valuation_daily (
    symbol           VARCHAR,
    trade_date       DATE,
    pe_ttm           DOUBLE,
    pb               DOUBLE,
    total_market_cap DOUBLE,
    currency         VARCHAR,
    note             VARCHAR,
    source           VARCHAR,
    updated_at       TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, trade_date, source)
);

CREATE TABLE IF NOT EXISTS watchlist_objective_data (
    id            UUID PRIMARY KEY,
    symbol        VARCHAR NOT NULL,
    category      VARCHAR,
    request_note  VARCHAR,
    payload       VARCHAR,
    source        VARCHAR,
    run_id        VARCHAR,
    created_by    VARCHAR,
    created_at    TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_watchlist_objective_symbol
    ON watchlist_objective_data(symbol, created_at);

CREATE TABLE IF NOT EXISTS chanlun_analysis (
    id                       UUID PRIMARY KEY,
    run_id                   VARCHAR UNIQUE,
    symbol                   VARCHAR NOT NULL,
    analyzed_at              TIMESTAMP,
    dim1_structure_read      VARCHAR,
    dim2_active_pivots       VARCHAR,
    dim3_divergence          VARCHAR,
    dim4_buy_sell_points     VARCHAR,
    dim5_multi_level_plan    VARCHAR,
    dim6_elliott_corroboration VARCHAR,
    dim7_chanlun_score       VARCHAR,
    score                    INTEGER CHECK (score BETWEEN -5 AND 5),
    confidence               DOUBLE CHECK (confidence >= 0 AND confidence <= 1),
    structured               BOOLEAN,
    raw_report               VARCHAR,
    created_at               TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chanlun_analysis_symbol
    ON chanlun_analysis(symbol, analyzed_at);

-- Multi-level K-line bars fetched for the Chanlun pre-run gate (M16).
-- One row per symbol/interval/bar across intervals 30m,1d,1w,1mo,1q,1y.
-- Bars are append/merge only — failed refreshes never delete old rows.
CREATE TABLE IF NOT EXISTS watch_kline_bar (
    symbol      VARCHAR NOT NULL,
    interval    VARCHAR NOT NULL,
    bar_time    VARCHAR NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      DOUBLE,
    amount      DOUBLE,
    source      VARCHAR,
    updated_at  TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (symbol, interval, bar_time)
);

-- Last fetch outcome per (symbol, interval); the readiness decision itself
-- is derived by src.watchlist.kline from bars + this row.
CREATE TABLE IF NOT EXISTS watch_kline_fetch_status (
    symbol           VARCHAR NOT NULL,
    interval         VARCHAR NOT NULL,
    last_attempt_at  TIMESTAMP,
    last_ok_at       TIMESTAMP,
    last_error       VARCHAR,
    bars_count       BIGINT DEFAULT 0,
    earliest_bar_time VARCHAR,
    latest_bar_time  VARCHAR,
    source           VARCHAR,
    PRIMARY KEY (symbol, interval)
)
"""


class WatchlistDBError(RuntimeError):
    """A DuckDB persistence failure surfaced to the service layer."""


# ----------------------------------------------------------------------
# Connection / schema
# ----------------------------------------------------------------------
def watchlist_connection(
    db_path: str | os.PathLike[str] | None = None,
) -> duckdb.DuckDBPyConnection:
    """Open a short read-write connection, creating the parent directory."""
    path = str(db_path) if db_path is not None else str(get_market_db_path())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return duckdb.connect(path)


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Idempotently create M16 tables/indexes (safe to run repeatedly)."""
    # Strip full-line SQL comments first — their prose may contain ";" which
    # would otherwise split a statement mid-comment.
    ddl_text = "\n".join(
        line for line in _DDL.splitlines() if not line.strip().startswith("--")
    )
    for statement in ddl_text.strip().split(";"):
        ddl = statement.strip()
        if ddl:
            conn.execute(ddl)
    _migrate_kline_status_source(conn)


def _migrate_kline_status_source(conn: duckdb.DuckDBPyConnection) -> None:
    """Add the ``source`` column to pre-existing M16 status tables."""
    exists = conn.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name = 'watch_kline_fetch_status' AND column_name = 'source'"
    ).fetchone()
    if exists is not None and int(exists[0]) == 0:
        conn.execute(
            "ALTER TABLE watch_kline_fetch_status ADD COLUMN source VARCHAR"
        )


# ----------------------------------------------------------------------
# Existing-warehouse upserts
# ----------------------------------------------------------------------
def upsert_instrument(
    master: dict[str, Any],
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """Upsert one ``instrument_master`` row, preserving known non-null fields.

    Accepts a sparse dict; columns omitted/None keep their previous value.
    """
    symbol = normalize_a_share_symbol(str(master.get("symbol") or ""))
    now = datetime.now()
    values: list[Any] = [
        symbol,
        master.get("name"),
        master.get("name_en"),
        master.get("market", "a_share"),
        master.get("currency", "CNY"),
        master.get("exchange"),
        master.get("list_date"),
        master.get("delist_date"),
        master.get("lot_size"),
        master.get("sector"),
        master.get("industry"),
        master.get("is_active", True),
        master.get("source", "eastmoney"),
        now,
    ]
    columns = (
        "symbol, name, name_en, market, currency, exchange, list_date, "
        "delist_date, lot_size, sector, industry, is_active, source, updated_at"
    )
    merge_cols = [c.strip() for c in columns.split(",") if c.strip() != "symbol"]
    set_clause = ", ".join(
        f"{col} = COALESCE(excluded.{col}, instrument_master.{col})"
        for col in merge_cols
    )
    conn.execute(
        f"INSERT INTO instrument_master ({columns}) VALUES ({', '.join(['?'] * len(values))}) "
        f"ON CONFLICT (symbol) DO UPDATE SET {set_clause}",
        values,
    )


def apply_profile_to_instrument(
    profile: CompanyProfile,
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """Persist F10 profile fields onto ``instrument_master``."""
    exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[profile.symbol.split(".")[1]]
    upsert_instrument(
        {
            "symbol": profile.symbol,
            "name": profile.name,
            "industry": profile.industry,
            "list_date": profile.list_date,
            "exchange": exchange,
            "source": "eastmoney",
        },
        conn,
    )


def upsert_valuation(
    symbol: str,
    trade_date: str,
    *,
    pe: float | None,
    pb: float | None,
    total_market_cap: float | None,
    source: str = "eastmoney",
    currency: str = "CNY",
    note: str | None = None,
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """Idempotently upsert one ``valuation_daily`` snapshot row."""
    normalized = normalize_a_share_symbol(symbol)
    conn.execute(
        """
        INSERT INTO valuation_daily
            (symbol, trade_date, pe_ttm, pb, total_market_cap, currency, note, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (symbol, trade_date, source) DO UPDATE SET
            pe_ttm = COALESCE(excluded.pe_ttm, valuation_daily.pe_ttm),
            pb = COALESCE(excluded.pb, valuation_daily.pb),
            total_market_cap = COALESCE(excluded.total_market_cap, valuation_daily.total_market_cap),
            currency = COALESCE(excluded.currency, valuation_daily.currency),
            note = COALESCE(excluded.note, valuation_daily.note),
            updated_at = excluded.updated_at
        """,
        [
            normalized,
            trade_date,
            pe,
            pb,
            total_market_cap,
            currency,
            note,
            source,
            datetime.now(),
        ],
    )


def persist_quote_snapshot(
    symbol: str,
    snapshot: QuoteSnapshot,
    trade_date: str,
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """Write a refreshed snapshot into valuation_daily (+ industry on master)."""
    upsert_valuation(
        symbol,
        trade_date,
        pe=snapshot.pe,
        pb=snapshot.pb,
        total_market_cap=snapshot.total_market_cap,
        conn=conn,
    )
    if snapshot.industry:
        upsert_instrument(
            {"symbol": symbol, "industry": snapshot.industry},
            conn,
        )


# ----------------------------------------------------------------------
# Raw-data reads (tolerate legacy tables not existing)
# ----------------------------------------------------------------------
def _query_dicts(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params or [])
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _table_exists(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    rows = conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
        [table],
    ).fetchone()
    return bool(rows and rows[0] > 0)


def list_raw_data(
    symbol: str,
    conn: duckdb.DuckDBPyConnection,
) -> dict[str, list[dict[str, Any]]]:
    """Return existing raw data in four categories; missing tables → empty.

    Categories: ``instrument`` (master), ``daily_bar``, ``valuation``,
    ``financial``.
    """
    normalized = normalize_a_share_symbol(symbol)
    result: dict[str, list[dict[str, Any]]] = {
        "instrument": [],
        "daily_bar": [],
        "valuation": [],
        "financial": [],
    }

    def _safe(table: str, sql: str, params: Sequence[Any]) -> None:
        if not _table_exists(conn, table):
            return
        try:
            key = {
                "instrument_master": "instrument",
                "daily_bar": "daily_bar",
                "valuation_daily": "valuation",
                "financial_statement": "financial",
            }[table]
            result[key] = _query_dicts(conn, sql, params)
        except duckdb.CatalogException:
            return

    _safe(
        "instrument_master",
        "SELECT * FROM instrument_master WHERE symbol = ?",
        [normalized],
    )
    _safe(
        "daily_bar",
        """
        SELECT * FROM (
            SELECT * FROM daily_bar
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT ?
        ) ORDER BY trade_date ASC
        """,
        [normalized, _DAILY_BAR_LIMIT],
    )
    _safe(
        "valuation_daily",
        """
        SELECT * FROM (
            SELECT * FROM valuation_daily
            WHERE symbol = ?
            ORDER BY trade_date DESC, source
            LIMIT ?
        ) ORDER BY trade_date DESC
        """,
        [normalized, _DAILY_BAR_LIMIT],
    )
    _safe(
        "financial_statement",
        """
        SELECT * FROM (
            SELECT * FROM financial_statement
            WHERE symbol = ?
            ORDER BY report_date DESC, statement, field
            LIMIT ?
        )
        """,
        [normalized, _FINANCIAL_LIMIT],
    )
    return result


# ----------------------------------------------------------------------
# Objective data CRUD
# ----------------------------------------------------------------------
def insert_objective_record(
    *,
    symbol: str,
    payload: str,
    source: str,
    conn: duckdb.DuckDBPyConnection,
    category: str = "agent_fetch",
    request_note: str | None = None,
    run_id: str | None = None,
    created_by: str = "system",
    created_at: datetime | None = None,
) -> str:
    """Archive one agent-fetched objective-data record; returns its id."""
    normalized = normalize_a_share_symbol(symbol)
    record_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO watchlist_objective_data
            (id, symbol, category, request_note, payload, source, run_id,
             created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            record_id,
            normalized,
            category,
            request_note,
            payload
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False),
            source,
            run_id,
            created_by,
            created_at or datetime.now(),
        ],
    )
    return record_id


def objective_record_exists(run_id: str, conn: duckdb.DuckDBPyConnection) -> bool:
    """Whether a fetch run was already archived (idempotency guard)."""
    row = conn.execute(
        "SELECT count(*) FROM watchlist_objective_data WHERE run_id = ?",
        [run_id],
    ).fetchone()
    return bool(row and row[0] > 0)


def list_objective_records(
    symbol: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    limit: int = _OBJECTIVE_LIMIT,
) -> list[dict[str, Any]]:
    """List archived objective records for one symbol, newest first."""
    normalized = normalize_a_share_symbol(symbol)
    return _query_dicts(
        conn,
        """
        SELECT id, symbol, category, request_note, payload, source, run_id,
               created_by, created_at
        FROM watchlist_objective_data
        WHERE symbol = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        [normalized, max(1, min(int(limit), _OBJECTIVE_LIMIT))],
    )


# ----------------------------------------------------------------------
# Chanlun CRUD
# ----------------------------------------------------------------------
def insert_chanlun_record(
    *,
    run_id: str,
    symbol: str,
    conn: duckdb.DuckDBPyConnection,
    dims: dict[str, str | None],
    score: int | None,
    confidence: float | None,
    structured: bool,
    raw_report: str,
    analyzed_at: datetime | None = None,
) -> str:
    """Insert one parsed Chanlun analysis row.

    CHECK constraints reject out-of-range score/confidence; callers parse
    defensively and pass ``structured=False`` with raw text when parsing
    could not produce all seven dimensions.
    """
    normalized = normalize_a_share_symbol(symbol)
    record_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO chanlun_analysis
            (id, run_id, symbol, analyzed_at,
             dim1_structure_read, dim2_active_pivots, dim3_divergence,
             dim4_buy_sell_points, dim5_multi_level_plan,
             dim6_elliott_corroboration, dim7_chanlun_score,
             score, confidence, structured, raw_report, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            record_id,
            run_id,
            normalized,
            analyzed_at or datetime.now(),
            dims.get("structure_read"),
            dims.get("active_pivots"),
            dims.get("divergence"),
            dims.get("buy_sell_points"),
            dims.get("multi_level_plan"),
            dims.get("elliott_corroboration"),
            dims.get("chanlun_score"),
            score,
            confidence,
            structured,
            raw_report,
            datetime.now(),
        ],
    )
    return record_id


def chanlun_record_exists(run_id: str, conn: duckdb.DuckDBPyConnection) -> bool:
    row = conn.execute(
        "SELECT count(*) FROM chanlun_analysis WHERE run_id = ?",
        [run_id],
    ).fetchone()
    return bool(row and row[0] > 0)


def list_chanlun_records(
    symbol: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List Chanlun rows for one symbol (newest first, optional date range).

    Date bounds are inclusive day-prefix comparisons: ``date_to`` covers the
    whole day (``< date_to + 1 day``).
    """
    normalized = normalize_a_share_symbol(symbol)
    clauses = ["symbol = ?"]
    params: list[Any] = [normalized]
    if date_from:
        clauses.append("analyzed_at >= CAST(? AS TIMESTAMP)")
        params.append(f"{date_from}T00:00:00" if "T" not in date_from else date_from)
    if date_to:
        clauses.append("analyzed_at < CAST(? AS TIMESTAMP) + INTERVAL 1 DAY")
        params.append(date_to)
    params.extend(
        [
            max(1, min(int(limit), _CHANLUN_MAX_LIMIT)),
            max(0, int(offset)),
        ]
    )
    return _query_dicts(
        conn,
        f"""
        SELECT id, run_id, symbol, analyzed_at,
               dim1_structure_read, dim2_active_pivots, dim3_divergence,
               dim4_buy_sell_points, dim5_multi_level_plan,
               dim6_elliott_corroboration, dim7_chanlun_score,
               score, confidence, structured, raw_report, created_at
        FROM chanlun_analysis
        WHERE {' AND '.join(clauses)}
        ORDER BY analyzed_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        params,
    )


# ----------------------------------------------------------------------
# Multi-level K-line (Chanlun readiness, BDD rules 15-20)
# ----------------------------------------------------------------------
def upsert_kline_bars(
    symbol: str,
    interval: str,
    rows: Sequence[dict[str, Any]],
    *,
    source: str,
    conn: duckdb.DuckDBPyConnection,
) -> int:
    """Merge one level's bars (``INSERT OR REPLACE``); never deletes rows."""
    normalized = normalize_a_share_symbol(symbol)
    stamped = datetime.now()
    records = [
        (
            normalized,
            interval,
            str(row["trade_date"]),
            row.get("open"),
            row.get("high"),
            row.get("low"),
            row.get("close"),
            row.get("volume"),
            row.get("amount"),
            source,
            stamped,
        )
        for row in rows
        if row.get("trade_date")
    ]
    if records:
        conn.executemany(
            """
            INSERT OR REPLACE INTO watch_kline_bar
                (symbol, interval, bar_time, open, high, low, close,
                 volume, amount, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
    return len(records)


def list_kline_bars(
    symbol: str,
    interval: str,
    start: date | None = None,
    end: date | None = None,
    *,
    conn: duckdb.DuckDBPyConnection,
) -> list[dict[str, Any]]:
    """Read previously stored bars for one level in ascending time order.

    Backs the ``local`` data source (every online source incrementally
    upserts its bars into the same table). Bounds compare lexically on
    ISO labels, so minute bars (``YYYY-MM-DD HH:MM:SS``) are fully covered
    by an inclusive upper bound of ``end 23:59:59``.
    """
    normalized = normalize_a_share_symbol(symbol)
    clauses = ["symbol = ?", "interval = ?"]
    params: list[Any] = [normalized, interval]
    if start is not None:
        clauses.append("bar_time >= ?")
        params.append(start.isoformat())
    if end is not None:
        clauses.append("bar_time <= ?")
        params.append(f"{end.isoformat()} 23:59:59")
    result = conn.execute(
        f"""
        SELECT bar_time, open, high, low, close, volume, amount
        FROM watch_kline_bar
        WHERE {' AND '.join(clauses)}
        ORDER BY bar_time
        """,
        params,
    ).fetchall()
    return [
        {
            "trade_date": bar_time,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
        }
        for bar_time, open_, high, low, close, volume, amount in result
    ]


def record_kline_fetch(
    symbol: str,
    interval: str,
    *,
    ok: bool,
    error: str | None,
    source: str | None = None,
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """Persist one fetch attempt; on success refresh the bar summary.

    On success the status row adopts the serving ``source``; a failure keeps
    the previous source (the old bars were served by it and stay in place).
    """
    normalized = normalize_a_share_symbol(symbol)
    now = datetime.now()
    existing = conn.execute(
        "SELECT last_ok_at, source FROM watch_kline_fetch_status "
        "WHERE symbol = ? AND interval = ?",
        [normalized, interval],
    ).fetchone()

    summary = conn.execute(
        "SELECT count(*), min(bar_time), max(bar_time) FROM watch_kline_bar "
        "WHERE symbol = ? AND interval = ?",
        [normalized, interval],
    ).fetchone()
    bars_count = int(summary[0]) if summary else 0
    earliest = summary[1] if summary else None
    latest = summary[2] if summary else None
    last_ok = now if ok else (existing[0] if existing else None)
    last_error = None if ok else (error or "获取失败")
    # Successful attempt stamps the new source; failed attempts keep the
    # source that last served the level (None when it has never succeeded).
    effective_source = source if ok else (existing[1] if existing else None)

    if existing is not None:
        conn.execute(
            """
            UPDATE watch_kline_fetch_status
            SET last_attempt_at = ?, last_ok_at = ?, last_error = ?,
                bars_count = ?, earliest_bar_time = ?, latest_bar_time = ?,
                source = ?
            WHERE symbol = ? AND interval = ?
            """,
            [
                now,
                last_ok,
                last_error,
                bars_count,
                earliest,
                latest,
                effective_source,
                normalized,
                interval,
            ],
        )
    else:
        conn.execute(
            """
            INSERT INTO watch_kline_fetch_status
                (symbol, interval, last_attempt_at, last_ok_at, last_error,
                 bars_count, earliest_bar_time, latest_bar_time, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                normalized,
                interval,
                now,
                last_ok,
                last_error,
                bars_count,
                earliest,
                latest,
                effective_source,
            ],
        )


def list_kline_status_rows(
    symbol: str,
    conn: duckdb.DuckDBPyConnection,
) -> list[dict[str, Any]]:
    """Raw fetch-status rows for every interval ever attempted for a symbol."""
    normalized = normalize_a_share_symbol(symbol)
    return _query_dicts(
        conn,
        """
        SELECT symbol, interval, last_attempt_at, last_ok_at, last_error,
               bars_count, earliest_bar_time, latest_bar_time, source
        FROM watch_kline_fetch_status
        WHERE symbol = ?
        ORDER BY interval
        """,
        [normalized],
    )


def resolve_market_dates(
    conn: duckdb.DuckDBPyConnection,
    *,
    today: date,
) -> tuple[date | None, date | None, str]:
    """Resolve ``(last_trading_day, threshold_day, source)`` for freshness.

    Tiers, in order:
      1. ``trading_calendar`` (a_share) when its newest open day is within
         12 days (covers Spring Festival / National Day breaks);
      2. newest ``trade_date`` across the warehouse ``daily_bar`` table;
      3. weekday rollback heuristic (skips Saturdays/Sundays only).

    ``threshold_day`` is the 2nd-to-last trading day — a level's latest bar
    must be on or after it (business rule 16: weekends/holidays deferred).
    """
    if _table_exists(conn, "trading_calendar"):
        try:
            row = conn.execute(
                "SELECT max(cal_date) FROM trading_calendar "
                "WHERE market = 'a_share' AND is_open"
            ).fetchone()
            newest = row[0] if row else None
            if isinstance(newest, date) and newest >= today - timedelta(days=12):
                open_days = [
                    r[0]
                    for r in conn.execute(
                        """
                        SELECT cal_date FROM trading_calendar
                        WHERE market = 'a_share' AND is_open AND cal_date <= ?
                        ORDER BY cal_date DESC
                        LIMIT 2
                        """,
                        [today],
                    ).fetchall()
                ]
                if open_days:
                    threshold = open_days[1] if len(open_days) > 1 else open_days[0]
                    return open_days[0], threshold, "trading_calendar"
        except duckdb.CatalogException:
            pass

    if _table_exists(conn, "daily_bar"):
        try:
            row = conn.execute("SELECT max(trade_date) FROM daily_bar").fetchone()
            if row and isinstance(row[0], date):
                return row[0], row[0], "daily_bar"
        except duckdb.CatalogException:
            pass

    if _table_exists(conn, "watch_kline_bar"):
        try:
            row = conn.execute(
                "SELECT max(CAST(substr(bar_time, 1, 10) AS DATE)) "
                "FROM watch_kline_bar WHERE interval = '1d'"
            ).fetchone()
            if row and isinstance(row[0], date):
                return row[0], row[0], "watch_kline_bar"
        except duckdb.CatalogException:
            pass

    found: list[date] = []
    cursor = today
    while len(found) < 2:
        if cursor.weekday() < 5:
            found.append(cursor)
        cursor -= timedelta(days=1)
    return found[0], found[1], "weekday"
