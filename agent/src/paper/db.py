"""DuckDB persistence for the simulated paper portfolio.

Tables live in the same local market warehouse as the watchlist
(``get_market_db_path``) but are all prefixed ``paper_`` and are fully
independent of the live ``/api/portfolio`` tables. Connections are short and
short-lived (same pattern as ``src.watchlist.db``).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import duckdb

from src.config.paths import get_market_db_path

_DDL = """
CREATE TABLE IF NOT EXISTS paper_account (
    id               INTEGER PRIMARY KEY DEFAULT 1,
    initial_capital  DOUBLE NOT NULL,
    cash_balance     DOUBLE NOT NULL,
    created_at       TIMESTAMP,
    updated_at       TIMESTAMP,
    CONSTRAINT paper_account_singleton CHECK (id = 1)
);

CREATE TABLE IF NOT EXISTS paper_order (
    id                   VARCHAR PRIMARY KEY,
    side                 VARCHAR NOT NULL,
    symbol               VARCHAR NOT NULL,
    name                 VARCHAR,
    qty                  BIGINT NOT NULL,
    price                DOUBLE NOT NULL,
    amount               DOUBLE NOT NULL,
    commission           DOUBLE NOT NULL,
    stamp_tax            DOUBLE NOT NULL,
    transfer_fee         DOUBLE NOT NULL,
    price_session        VARCHAR NOT NULL,
    price_trade_date     DATE NOT NULL,
    chanlun_run_id       VARCHAR,
    chanlun_score        INTEGER,
    chanlun_confidence   DOUBLE,
    chanlun_score_text   VARCHAR,
    chanlun_analyzed_at  TIMESTAMP,
    traded_at            TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_lot (
    id               VARCHAR PRIMARY KEY,
    buy_order_id     VARCHAR NOT NULL,
    symbol           VARCHAR NOT NULL,
    qty_original     BIGINT NOT NULL,
    qty_remaining    BIGINT NOT NULL,
    price            DOUBLE NOT NULL,
    buy_fees         DOUBLE NOT NULL,
    bought_on        DATE NOT NULL,
    created_at       TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_close (
    id               VARCHAR PRIMARY KEY,
    sell_order_id    VARCHAR NOT NULL,
    buy_order_id     VARCHAR NOT NULL,
    symbol           VARCHAR NOT NULL,
    qty              BIGINT NOT NULL,
    buy_cost         DOUBLE NOT NULL,
    sell_proceeds    DOUBLE NOT NULL,
    realized_pnl     DOUBLE NOT NULL,
    return_pct       DOUBLE NOT NULL,
    holding_days     INTEGER NOT NULL,
    chanlun_score    INTEGER,
    created_at       TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_quote_snapshot (
    symbol     VARCHAR NOT NULL,
    price      DOUBLE NOT NULL,
    snapped_at TIMESTAMP NOT NULL,
    source     VARCHAR,
    PRIMARY KEY (symbol, snapped_at)
);

CREATE TABLE IF NOT EXISTS paper_nav_snapshot (
    snapped_at    TIMESTAMP PRIMARY KEY,
    cash          DOUBLE NOT NULL,
    market_value  DOUBLE NOT NULL,
    total_asset   DOUBLE NOT NULL,
    nav           DOUBLE NOT NULL
);
"""

#: Tables wiped by an account reset (order matters only for readability).
_TABLES: tuple[str, ...] = (
    "paper_close",
    "paper_lot",
    "paper_order",
    "paper_quote_snapshot",
    "paper_nav_snapshot",
    "paper_account",
)


class PaperDBError(RuntimeError):
    """A DuckDB persistence failure in the paper module."""


def paper_connection(
    db_path: str | os.PathLike[str] | None = None,
) -> duckdb.DuckDBPyConnection:
    """Open a short read-write connection, creating the parent directory."""
    path = str(db_path) if db_path is not None else str(get_market_db_path())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return duckdb.connect(path)


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Idempotently create every paper_* table."""
    for statement in _DDL.strip().split(";"):
        ddl = statement.strip()
        if ddl:
            conn.execute(ddl)


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


def new_id() -> str:
    return str(uuid.uuid4())


# ----------------------------------------------------------------------
# Account
# ----------------------------------------------------------------------
def get_account(conn: duckdb.DuckDBPyConnection) -> dict[str, Any] | None:
    rows = _query_dicts(conn, "SELECT * FROM paper_account WHERE id = 1")
    return rows[0] if rows else None


def create_account(
    conn: duckdb.DuckDBPyConnection,
    initial_capital: float,
    *,
    now: datetime,
) -> dict[str, Any]:
    conn.execute(
        """
        INSERT INTO paper_account
            (id, initial_capital, cash_balance, created_at, updated_at)
        VALUES (1, ?, ?, ?, ?)
        """,
        [float(initial_capital), float(initial_capital), now, now],
    )
    account = get_account(conn)
    assert account is not None
    return account


def update_cash(
    conn: duckdb.DuckDBPyConnection, cash: float, *, now: datetime
) -> None:
    conn.execute(
        "UPDATE paper_account SET cash_balance = ?, updated_at = ? WHERE id = 1",
        [float(cash), now],
    )


def reset_account(
    conn: duckdb.DuckDBPyConnection, initial_capital: float, *, now: datetime
) -> dict[str, Any]:
    """Delete every paper row and recreate a fresh single account."""
    for table in _TABLES:
        conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed internal names
    return create_account(conn, initial_capital, now=now)


# ----------------------------------------------------------------------
# Orders
# ----------------------------------------------------------------------
_ORDER_COLUMNS = (
    "id", "side", "symbol", "name", "qty", "price", "amount",
    "commission", "stamp_tax", "transfer_fee",
    "price_session", "price_trade_date",
    "chanlun_run_id", "chanlun_score", "chanlun_confidence",
    "chanlun_score_text", "chanlun_analyzed_at", "traded_at",
)


def insert_order(
    conn: duckdb.DuckDBPyConnection, order: dict[str, Any]
) -> dict[str, Any]:
    order = dict(order)
    order.setdefault("id", new_id())
    placeholders = ", ".join("?" for _ in _ORDER_COLUMNS)
    conn.execute(
        f"INSERT INTO paper_order ({', '.join(_ORDER_COLUMNS)}) "
        f"VALUES ({placeholders})",
        [order.get(col) for col in _ORDER_COLUMNS],
    )
    return order


def list_orders(
    conn: duckdb.DuckDBPyConnection,
    *,
    symbol: str | None = None,
    side: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    if side:
        clauses.append("side = ?")
        params.append(side)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
    return _query_dicts(
        conn,
        f"""
        SELECT * FROM paper_order
        {where}
        ORDER BY traded_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        params,
    )


def get_order_by_id(
    conn: duckdb.DuckDBPyConnection, order_id: str
) -> dict[str, Any] | None:
    rows = _query_dicts(
        conn, "SELECT * FROM paper_order WHERE id = ?", [order_id]
    )
    return rows[0] if rows else None


def total_fees(conn: duckdb.DuckDBPyConnection) -> float:
    row = conn.execute(
        "SELECT coalesce(sum(commission + stamp_tax + transfer_fee), 0) "
        "FROM paper_order"
    ).fetchone()
    return float(row[0]) if row else 0.0


# ----------------------------------------------------------------------
# Buy lots (FIFO / T+1 units)
# ----------------------------------------------------------------------
def insert_lot(conn: duckdb.DuckDBPyConnection, lot: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO paper_lot
            (id, buy_order_id, symbol, qty_original, qty_remaining,
             price, buy_fees, bought_on, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            lot.get("id") or new_id(),
            lot["buy_order_id"],
            lot["symbol"],
            int(lot["qty_original"]),
            int(lot["qty_remaining"]),
            float(lot["price"]),
            float(lot["buy_fees"]),
            lot["bought_on"],
            lot["created_at"],
        ],
    )


def list_open_lots(
    conn: duckdb.DuckDBPyConnection, symbol: str | None = None
) -> list[dict[str, Any]]:
    """Open buy lots in FIFO order (oldest first)."""
    if symbol:
        return _query_dicts(
            conn,
            "SELECT * FROM paper_lot WHERE qty_remaining > 0 AND symbol = ? "
            "ORDER BY created_at ASC, id ASC",
            [symbol],
        )
    return _query_dicts(
        conn,
        "SELECT * FROM paper_lot WHERE qty_remaining > 0 "
        "ORDER BY created_at ASC, id ASC",
    )


def set_lot_remaining(
    conn: duckdb.DuckDBPyConnection, lot_id: str, qty_remaining: int
) -> None:
    conn.execute(
        "UPDATE paper_lot SET qty_remaining = ? WHERE id = ?",
        [int(qty_remaining), lot_id],
    )


def open_position_symbols(conn: duckdb.DuckDBPyConnection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT symbol FROM paper_lot WHERE qty_remaining > 0 "
        "ORDER BY symbol"
    ).fetchall()
    return [str(r[0]) for r in rows]


# ----------------------------------------------------------------------
# Closed trades
# ----------------------------------------------------------------------
def insert_close(conn: duckdb.DuckDBPyConnection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO paper_close
            (id, sell_order_id, buy_order_id, symbol, qty, buy_cost,
             sell_proceeds, realized_pnl, return_pct, holding_days,
             chanlun_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            row.get("id") or new_id(),
            row["sell_order_id"],
            row["buy_order_id"],
            row["symbol"],
            int(row["qty"]),
            float(row["buy_cost"]),
            float(row["sell_proceeds"]),
            float(row["realized_pnl"]),
            float(row["return_pct"]),
            int(row["holding_days"]),
            row.get("chanlun_score"),
            row["created_at"],
        ],
    )


def list_closes(
    conn: duckdb.DuckDBPyConnection,
    *,
    symbol: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if symbol:
        sql = (
            "SELECT * FROM paper_close WHERE symbol = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        )
        params: Sequence[Any] = [symbol, max(1, min(int(limit), 500)),
                                 max(0, int(offset))]
    else:
        sql = (
            "SELECT * FROM paper_close ORDER BY created_at DESC, id DESC "
            "LIMIT ? OFFSET ?"
        )
        params = [max(1, min(int(limit), 500)), max(0, int(offset))]
    return _query_dicts(conn, sql, params)


def close_stats(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT count(*)            AS closes,
               coalesce(sum(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END), 0) AS wins,
               coalesce(avg(realized_pnl), 0)   AS avg_pnl,
               coalesce(avg(return_pct), 0)     AS avg_return_pct,
               coalesce(avg(holding_days), 0)   AS avg_holding_days,
               coalesce(sum(realized_pnl), 0)   AS total_realized_pnl
        FROM paper_close
        """
    ).fetchone()
    return {
        "closes": int(row[0]),
        "wins": int(row[1]),
        "win_rate": float(row[1] / row[0]) if row[0] else 0.0,
        "avg_pnl": float(row[2]),
        "avg_return_pct": float(row[3]),
        "avg_holding_days": float(row[4]),
        "total_realized_pnl": float(row[5]),
    }


# ----------------------------------------------------------------------
# Quotes / NAV snapshots
# ----------------------------------------------------------------------
def upsert_quote(
    conn: duckdb.DuckDBPyConnection,
    *,
    symbol: str,
    price: float,
    snapped_at: datetime,
    source: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO paper_quote_snapshot
            (symbol, price, snapped_at, source)
        VALUES (?, ?, ?, ?)
        """,
        [symbol, float(price), snapped_at, source],
    )


def latest_quotes(
    conn: duckdb.DuckDBPyConnection,
    symbols: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    if symbols:
        placeholders = ", ".join("?" for _ in symbols)
        rows = _query_dicts(
            conn,
            f"""
            SELECT q.symbol, q.price, q.snapped_at, q.source
            FROM paper_quote_snapshot q
            WHERE q.symbol IN ({placeholders})
              AND q.snapped_at = (
                  SELECT max(snapped_at) FROM paper_quote_snapshot
                  WHERE symbol = q.symbol
              )
            """,
            list(symbols),
        )
    else:
        rows = _query_dicts(
            conn,
            """
            SELECT q.symbol, q.price, q.snapped_at, q.source
            FROM paper_quote_snapshot q
            WHERE q.snapped_at = (
                SELECT max(snapped_at) FROM paper_quote_snapshot
                WHERE symbol = q.symbol
            )
            """,
        )
    return {str(r["symbol"]): r for r in rows}


def insert_nav(
    conn: duckdb.DuckDBPyConnection,
    *,
    snapped_at: datetime,
    cash: float,
    market_value: float,
    total_asset: float,
    initial_capital: float,
) -> None:
    nav = total_asset / initial_capital if initial_capital else 1.0
    conn.execute(
        """
        INSERT OR REPLACE INTO paper_nav_snapshot
            (snapped_at, cash, market_value, total_asset, nav)
        VALUES (?, ?, ?, ?, ?)
        """,
        [snapped_at, float(cash), float(market_value), float(total_asset),
         float(nav)],
    )


def list_nav(
    conn: duckdb.DuckDBPyConnection, *, date_from: date | None = None
) -> list[dict[str, Any]]:
    if date_from is not None:
        return _query_dicts(
            conn,
            "SELECT * FROM paper_nav_snapshot WHERE snapped_at >= ? "
            "ORDER BY snapped_at ASC",
            [datetime.combine(date_from, datetime.min.time())],
        )
    return _query_dicts(
        conn, "SELECT * FROM paper_nav_snapshot ORDER BY snapped_at ASC"
    )


def last_nav_before(
    conn: duckdb.DuckDBPyConnection, when: datetime
) -> dict[str, Any] | None:
    rows = _query_dicts(
        conn,
        "SELECT * FROM paper_nav_snapshot WHERE snapped_at < ? "
        "ORDER BY snapped_at DESC LIMIT 1",
        [when],
    )
    return rows[0] if rows else None


# ----------------------------------------------------------------------
# Chanlun snapshot (read-only consumer of the watchlist schema)
# ----------------------------------------------------------------------
def latest_chanlun(
    conn: duckdb.DuckDBPyConnection, symbol: str
) -> dict[str, Any] | None:
    """Newest archived Chanlun analysis for ``symbol`` (None if unavailable)."""
    if not _table_exists(conn, "chanlun_analysis"):
        return None
    try:
        rows = _query_dicts(
            conn,
            """
            SELECT run_id, score, confidence, dim7_chanlun_score, analyzed_at
            FROM chanlun_analysis
            WHERE symbol = ?
            ORDER BY analyzed_at DESC, id DESC
            LIMIT 1
            """,
            [symbol],
        )
    except duckdb.Error:
        return None
    return rows[0] if rows else None


def list_close_view(
    conn: duckdb.DuckDBPyConnection,
    *,
    symbol: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Closed-trade rows enriched with buy/sell order dates, prices and name."""
    where = "WHERE c.symbol = ?" if symbol else ""
    bound_limit = max(1, min(int(limit), 500))
    params: Sequence[Any] = (
        [symbol, bound_limit, max(0, int(offset))]
        if symbol
        else [bound_limit, max(0, int(offset))]
    )
    return _query_dicts(
        conn,
        f"""
        SELECT c.id, c.symbol, COALESCE(so.name, bo.name) AS name,
               c.qty, c.buy_cost, c.sell_proceeds, c.realized_pnl,
               c.return_pct, c.holding_days, c.chanlun_score,
               bo.price AS buy_price, so.price AS sell_price,
               bo.traded_at AS bought_at, so.traded_at AS sold_at,
               bo.price_session AS buy_session, so.price_session AS sell_session,
               c.created_at
        FROM paper_close c
        JOIN paper_order bo ON bo.id = c.buy_order_id
        JOIN paper_order so ON so.id = c.sell_order_id
        {where}
        ORDER BY so.traded_at DESC, c.id DESC
        LIMIT ? OFFSET ?
        """,
        params,
    )
