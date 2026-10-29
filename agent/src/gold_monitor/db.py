"""DuckDB persistence for the gold policy-cycle monitor module.

Three tables live under the shared market warehouse (``get_market_db_path()``):
    * ``gold_monthly``       — one row per YYYY-MM, key metrics
    * ``gold_policy_cycle``  — policy cycle boundaries and status
    * ``gold_refresh_log``   — audit trail of each refresh attempt

All connections are short-lived; this mirrors ``src.watchlist.db`` and
``src.paper.db`` patterns so multiple routes can interleave safely.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from src.config.paths import get_market_db_path

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS gold_monthly (
    month           VARCHAR(7) PRIMARY KEY,
    gold_price      DOUBLE,
    ffr             DOUBLE,
    yield_nominal   DOUBLE,
    bei             DOUBLE,
    tips_real       DOUBLE,
    gold_change_pct DOUBLE,
    ffr_change      DOUBLE,
    real_change     DOUBLE,
    updated_at      TIMESTAMP NOT NULL DEFAULT current_timestamp,
    source          VARCHAR(32) NOT NULL DEFAULT 'excel'
);

CREATE TABLE IF NOT EXISTS gold_policy_cycle (
    cycle_id        INTEGER PRIMARY KEY,
    cycle_name      VARCHAR(128) NOT NULL,
    start_month     VARCHAR(7) NOT NULL,
    end_month       VARCHAR(7),
    cycle_type      VARCHAR(16) NOT NULL,
    source          VARCHAR(16) NOT NULL DEFAULT 'excel',
    status          VARCHAR(16) NOT NULL DEFAULT 'active',
    gold_start      DOUBLE,
    gold_end        DOUBLE,
    gold_change_pct DOUBLE,
    created_at      TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at      TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS gold_refresh_log (
    log_id          INTEGER PRIMARY KEY,
    refreshed_month VARCHAR(7) NOT NULL,
    action          VARCHAR(16) NOT NULL,
    diff_summary    VARCHAR(512),
    success         BOOLEAN NOT NULL,
    error_msg       VARCHAR(512),
    source          VARCHAR(16) NOT NULL,
    refreshed_at    TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""


def gold_connection() -> duckdb.DuckDBPyConnection:
    """Open a short-lived DuckDB connection to the shared market warehouse."""
    db_path: Path = get_market_db_path()
    return duckdb.connect(str(db_path))


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create gold_* tables if they do not yet exist."""
    conn.execute(_DDL)


# ---------------------------------------------------------------------------
# gold_monthly CRUD
# ---------------------------------------------------------------------------

def insert_or_update_monthly(
    conn: duckdb.DuckDBPyConnection,
    month: str,
    gold_price: float | None,
    ffr: float | None,
    yield_nominal: float | None,
    bei: float | None,
    tips_real: float | None,
    gold_change_pct: float | None = None,
    ffr_change: float | None = None,
    real_change: float | None = None,
    source: str = "llm",
) -> bool:
    """Upsert one row into gold_monthly. Returns True if a new row was inserted."""
    existing = conn.execute(
        "SELECT month FROM gold_monthly WHERE month = ?", [month]
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE gold_monthly SET
                gold_price = ?, ffr = ?, yield_nominal = ?, bei = ?,
                tips_real = ?, gold_change_pct = ?, ffr_change = ?,
                real_change = ?, source = ?, updated_at = current_timestamp
            WHERE month = ?
            """,
            [gold_price, ffr, yield_nominal, bei, tips_real,
             gold_change_pct, ffr_change, real_change, source, month],
        )
        return False
    conn.execute(
        """
        INSERT INTO gold_monthly
            (month, gold_price, ffr, yield_nominal, bei, tips_real,
             gold_change_pct, ffr_change, real_change, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [month, gold_price, ffr, yield_nominal, bei, tips_real,
         gold_change_pct, ffr_change, real_change, source],
    )
    return True


def get_all_monthly(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM gold_monthly ORDER BY month ASC"
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def get_monthly_range(
    conn: duckdb.DuckDBPyConnection, start_month: str, end_month: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM gold_monthly WHERE month >= ? AND month <= ? ORDER BY month ASC",
        [start_month, end_month],
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def get_latest_monthly(conn: duckdb.DuckDBPyConnection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM gold_monthly ORDER BY month DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def get_recent_monthly(
    conn: duckdb.DuckDBPyConnection, limit: int = 12
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM gold_monthly ORDER BY month DESC LIMIT ?", [limit]
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return list(reversed([dict(zip(cols, r)) for r in rows]))


def get_monthly_by_month(
    conn: duckdb.DuckDBPyConnection, month: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM gold_monthly WHERE month = ?", [month]
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# gold_policy_cycle CRUD
# ---------------------------------------------------------------------------

def get_all_cycles(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM gold_policy_cycle ORDER BY start_month DESC"
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def get_active_cycle_for_month(
    conn: duckdb.DuckDBPyConnection, month: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM gold_policy_cycle
        WHERE start_month <= ?
          AND (end_month IS NULL OR end_month >= ?)
          AND status = 'active'
        ORDER BY start_month DESC
        LIMIT 1
        """,
        [month, month],
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def get_cycle_by_id(
    conn: duckdb.DuckDBPyConnection, cycle_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM gold_policy_cycle WHERE cycle_id = ?", [cycle_id]
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def get_last_cycle(conn: duckdb.DuckDBPyConnection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM gold_policy_cycle ORDER BY start_month DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def insert_cycle(
    conn: duckdb.DuckDBPyConnection,
    cycle_name: str,
    start_month: str,
    end_month: str | None,
    cycle_type: str,
    source: str = "auto",
    status: str = "pending_review",
    gold_start: float | None = None,
    gold_end: float | None = None,
    gold_change_pct: float | None = None,
) -> int:
    # DuckDB INTEGER PRIMARY KEY is not auto-incremented — compute next id manually
    row = conn.execute("SELECT coalesce(max(cycle_id), 0) + 1 FROM gold_policy_cycle").fetchone()
    next_id = int(row[0]) if row else 1
    conn.execute(
        """
        INSERT INTO gold_policy_cycle
            (cycle_id, cycle_name, start_month, end_month, cycle_type, source, status,
             gold_start, gold_end, gold_change_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [next_id, cycle_name, start_month, end_month, cycle_type, source, status,
         gold_start, gold_end, gold_change_pct],
    )
    return next_id


def approve_cycle(conn: duckdb.DuckDBPyConnection, cycle_id: int) -> None:
    conn.execute(
        "UPDATE gold_policy_cycle SET status = 'active', updated_at = current_timestamp WHERE cycle_id = ?",
        [cycle_id],
    )


def close_active_cycle(conn: duckdb.DuckDBPyConnection, end_month: str) -> None:
    """Close any active (end_month IS NULL) cycle by setting its end_month."""
    conn.execute(
        "UPDATE gold_policy_cycle SET end_month = ?, updated_at = current_timestamp WHERE end_month IS NULL AND status = 'active'",
        [end_month],
    )


# ---------------------------------------------------------------------------
# gold_refresh_log
# ---------------------------------------------------------------------------

def log_refresh(
    conn: duckdb.DuckDBPyConnection,
    refreshed_month: str,
    action: str,
    success: bool,
    source: str,
    diff_summary: str | None = None,
    error_msg: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO gold_refresh_log
            (refreshed_month, action, diff_summary, success, error_msg, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [refreshed_month, action, diff_summary, success, error_msg, source],
    )


def has_refreshed_today(
    conn: duckdb.DuckDBPyConnection, source: str = "scheduler"
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM gold_refresh_log
        WHERE refreshed_at >= current_date
          AND source = ?
          AND success = true
        LIMIT 1
        """,
        [source],
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Excel history import (一次性)
# ---------------------------------------------------------------------------

#: 列名映射（Excel 中文列 → 数据库字段）
_COLUMN_MAP = {
    "月份": "month",
    "国际金价(美元/盎司,月均)": "gold_price",
    "联邦基金有效利率(%)": "ffr",
    "10年期美债名义利率(%)": "yield_nominal",
    "10年期盈亏平衡通胀率BEI(%)": "bei",
    "10年期TIPS实际利率(%)": "tips_real",
    "金价环比涨跌(%)": "gold_change_pct",
    "政策利率月度变动(pct点)": "ffr_change",
    "实际利率月度变动(pct点)": "real_change",
}


def import_excel_history(
    conn: duckdb.DuckDBPyConnection, excel_path: str
) -> dict[str, Any]:
    """Import the two sheets from the historical Excel file.

    Returns a summary dict with row counts for each target table.
    """
    import pandas as pd

    # --- 月度数据 sheet ---
    df_monthly = pd.read_excel(excel_path, sheet_name="月度数据")
    # Rename to English column names
    rename_map = {k: v for k, v in _COLUMN_MAP.items() if k in df_monthly.columns}
    df_monthly = df_monthly.rename(columns=rename_map)

    rows_inserted = 0
    rows_updated = 0
    for _, row in df_monthly.iterrows():
        month = str(row.get("month", ""))
        if not month or month == "nan":
            continue
        # Normalize month format (Excel may give "1996-10", fine)
        gp = row.get("gold_price")
        ffr = row.get("ffr")
        yn = row.get("yield_nominal")
        bei_val = row.get("bei")
        tips = row.get("tips_real")
        # Compute tips_real if bei is present but tips_real is NaN
        if (pd.isna(tips) or tips is None) and not (pd.isna(yn) or pd.isna(bei_val)):
            tips = float(yn) - float(bei_val)

        inserted = insert_or_update_monthly(
            conn,
            month=month,
            gold_price=_to_float_or_none(gp),
            ffr=_to_float_or_none(ffr),
            yield_nominal=_to_float_or_none(yn),
            bei=_to_float_or_none(bei_val),
            tips_real=_to_float_or_none(tips),
            gold_change_pct=_to_float_or_none(row.get("gold_change_pct")),
            ffr_change=_to_float_or_none(row.get("ffr_change")),
            real_change=_to_float_or_none(row.get("real_change")),
            source="excel",
        )
        if inserted:
            rows_inserted += 1
        else:
            rows_updated += 1

    # --- 政策周期对比 sheet ---
    df_cycles = pd.read_excel(excel_path, sheet_name="政策周期对比", header=None)
    # Data starts at row index 2 (rows 0-1 are title + header)
    data = df_cycles.iloc[2:].dropna(subset=[0])
    rows_cycles = 0
    for _, row in data.iterrows():
        name_raw = str(row[0]).strip()
        start = str(row[1]).strip()
        end = str(row[2]).strip()
        if not name_raw or not start or start == "nan":
            continue
        # Determine cycle_type from the name
        cycle_type = _classify_cycle_name(name_raw)
        gp_start = _to_float_or_none(row[7])
        gp_end = _to_float_or_none(row[8])
        gp_chg = _to_float_or_none(row[9])

        insert_cycle(
            conn,
            cycle_name=name_raw,
            start_month=start,
            end_month=None if end == "至今" or end == "nan" else end,
            cycle_type=cycle_type,
            source="excel",
            status="active",
            gold_start=gp_start,
            gold_end=gp_end,
            gold_change_pct=gp_chg,
        )
        rows_cycles += 1

    logger.info(
        "Excel import complete: monthly inserted=%d updated=%d, cycles=%d",
        rows_inserted, rows_updated, rows_cycles,
    )
    return {
        "monthly_inserted": rows_inserted,
        "monthly_updated": rows_updated,
        "cycles_inserted": rows_cycles,
    }


def _to_float_or_none(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _classify_cycle_name(name: str) -> str:
    if "加息" in name or "hiking" in name.lower():
        return "hiking"
    if "降息" in name or "cutting" in name.lower() or "LTCM" in name:
        return "cutting"
    if "平台" in name or "stable" in name.lower():
        return "plateau"
    # LTCM 预防式降息
    if "LTCM" in name:
        return "cutting"
    return "plateau"
