"""DuckDB persistence for the investment celebrity module.

Tables live under the shared market warehouse (``get_market_db_path()``) and
are prefixed ``celebrity_`` to avoid collisions. All connections are short-lived.
"""

from __future__ import annotations

import logging
from typing import Any

import duckdb

from src.celebrity.prompts import DEFAULT_PROMPTS, PREDEFINED_INVESTORS
from src.config.paths import get_market_db_path

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS celebrity_investor (
    id            INTEGER PRIMARY KEY,
    name          VARCHAR(256) NOT NULL,
    invest_style  TEXT NOT NULL DEFAULT '',
    remark        TEXT NOT NULL DEFAULT '',
    is_builtin    BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at    TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS celebrity_position (
    id            UUID PRIMARY KEY DEFAULT uuid(),
    investor_id   INTEGER NOT NULL,
    target        VARCHAR(256) NOT NULL,
    percentage    VARCHAR(32),
    direction     VARCHAR(32),
    source        VARCHAR(256),
    update_time   VARCHAR(32),
    confidence    VARCHAR(16),
    created_at    TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS celebrity_position_snapshot (
    id             UUID PRIMARY KEY DEFAULT uuid(),
    investor_id    INTEGER NOT NULL,
    snapshot_date  VARCHAR(16) NOT NULL,
    target         VARCHAR(256) NOT NULL,
    percentage     VARCHAR(32),
    source         VARCHAR(256),
    confidence     VARCHAR(16),
    created_at     TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS celebrity_opinion (
    id             UUID PRIMARY KEY DEFAULT uuid(),
    investor_id    INTEGER NOT NULL,
    publish_time   VARCHAR(32),
    content        TEXT,
    source         VARCHAR(256),
    confidence     VARCHAR(16),
    review_result  TEXT,
    is_latest      BOOLEAN NOT NULL DEFAULT false,
    created_at     TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS celebrity_adjust (
    id             UUID PRIMARY KEY DEFAULT uuid(),
    investor_id    INTEGER NOT NULL,
    time           VARCHAR(32),
    action         VARCHAR(32),
    target         VARCHAR(256),
    profit_desc    TEXT,
    source         VARCHAR(256),
    review_result  TEXT,
    created_at     TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS celebrity_performance (
    id                  UUID PRIMARY KEY DEFAULT uuid(),
    investor_id         INTEGER NOT NULL,
    recent_performance  TEXT,
    return_1y           VARCHAR(128),
    return_3y           VARCHAR(128),
    return_5y           VARCHAR(128),
    return_10y          VARCHAR(128),
    max_drawdown        VARCHAR(128),
    stability_tag       VARCHAR(64),
    stability_desc      TEXT,
    peer_compare        TEXT,
    risk_note           TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS celebrity_prompt (
    prompt_key     VARCHAR(64) PRIMARY KEY,
    content        TEXT NOT NULL,
    is_user_edited BOOLEAN NOT NULL DEFAULT false,
    updated_at     TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""


def celebrity_connection() -> duckdb.DuckDBPyConnection:
    """Open a short-lived DuckDB connection to the shared market warehouse."""
    return duckdb.connect(str(get_market_db_path()))


def _column_exists(conn: duckdb.DuckDBPyConnection, table: str, column: str) -> bool:
    cols = [r[0] for r in conn.execute(f"DESCRIBE {table}").fetchall()]
    return column in cols


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create celebrity_* tables and seed default data if absent."""
    conn.execute(_DDL)
    # Migrate: add columns only when missing.
    # NOTE: We check existence first instead of try/except on ALTER TABLE,
    # because a failed ALTER TABLE aborts the DuckDB transaction and breaks
    # every subsequent statement in the same connection.
    if not _column_exists(conn, "celebrity_position", "percentage"):
        conn.execute("ALTER TABLE celebrity_position ADD COLUMN percentage VARCHAR")
    if not _column_exists(conn, "celebrity_prompt", "is_user_edited"):
        conn.execute("ALTER TABLE celebrity_prompt ADD COLUMN is_user_edited BOOLEAN DEFAULT false")
    _seed_predefined_investors(conn)
    _seed_default_prompts(conn)


def _next_investor_id(conn: duckdb.DuckDBPyConnection) -> int:
    row = conn.execute("SELECT coalesce(max(id), 0) + 1 FROM celebrity_investor").fetchone()
    return int(row[0]) if row else 1


def _seed_predefined_investors(conn: duckdb.DuckDBPyConnection) -> None:
    for inv in PREDEFINED_INVESTORS:
        existing = conn.execute(
            "SELECT id FROM celebrity_investor WHERE name = ?", [inv["name"]]
        ).fetchone()
        if existing is None:
            nid = _next_investor_id(conn)
            conn.execute(
                "INSERT INTO celebrity_investor (id, name, invest_style, remark, is_builtin) "
                "VALUES (?, ?, ?, ?, true)",
                [nid, inv["name"], inv["invest_style"], inv["remark"]],
            )


def _seed_default_prompts(conn: duckdb.DuckDBPyConnection) -> None:
    """Keep DB prompts in sync with code defaults.

    The database is the single source of truth at runtime. Code defaults
    (``DEFAULT_PROMPTS``) are only a factory reset value:
    - missing key            → insert the default (not user-edited)
    - key present, not edited → overwrite DB content with the latest default
                                (so code changes propagate to existing DBs)
    - key present, edited    → leave the user's customization untouched
    """
    for key, content in DEFAULT_PROMPTS.items():
        row = conn.execute(
            "SELECT content, is_user_edited FROM celebrity_prompt WHERE prompt_key = ?", [key]
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO celebrity_prompt (prompt_key, content, is_user_edited) "
                "VALUES (?, ?, false)",
                [key, content],
            )
            continue
        current_content, is_user_edited = row[0], row[1]
        if bool(is_user_edited):
            continue
        if current_content != content:
            conn.execute(
                "UPDATE celebrity_prompt SET content = ?, updated_at = current_timestamp "
                "WHERE prompt_key = ?",
                [content, key],
            )


# ---------------------------------------------------------------------------
# Investor CRUD
# ---------------------------------------------------------------------------

def list_investors(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, name, invest_style, remark, is_builtin, updated_at "
        "FROM celebrity_investor ORDER BY is_builtin DESC, id ASC"
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def get_investor(conn: duckdb.DuckDBPyConnection, investor_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM celebrity_investor WHERE id = ?", [investor_id]
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def add_investor(
    conn: duckdb.DuckDBPyConnection, name: str, invest_style: str, remark: str
) -> int:
    nid = _next_investor_id(conn)
    conn.execute(
        "INSERT INTO celebrity_investor (id, name, invest_style, remark, is_builtin) "
        "VALUES (?, ?, ?, ?, false)",
        [nid, name, invest_style, remark],
    )
    return nid


def delete_investor(conn: duckdb.DuckDBPyConnection, investor_id: int) -> bool:
    """Delete a non-builtin investor and all its data. Returns True if deleted."""
    inv = get_investor(conn, investor_id)
    if inv is None:
        return False
    if inv.get("is_builtin"):
        return False
    conn.execute("DELETE FROM celebrity_position WHERE investor_id = ?", [investor_id])
    conn.execute("DELETE FROM celebrity_position_snapshot WHERE investor_id = ?", [investor_id])
    conn.execute("DELETE FROM celebrity_opinion WHERE investor_id = ?", [investor_id])
    conn.execute("DELETE FROM celebrity_adjust WHERE investor_id = ?", [investor_id])
    conn.execute("DELETE FROM celebrity_performance WHERE investor_id = ?", [investor_id])
    conn.execute("DELETE FROM celebrity_investor WHERE id = ?", [investor_id])
    return True


def update_invest_style(conn: duckdb.DuckDBPyConnection, investor_id: int, invest_style: str) -> None:
    conn.execute(
        "UPDATE celebrity_investor SET invest_style = ?, updated_at = current_timestamp WHERE id = ?",
        [invest_style, investor_id],
    )


# ---------------------------------------------------------------------------
# Position / Opinion / Adjust — append with dedup
# ---------------------------------------------------------------------------

def append_positions(
    conn: duckdb.DuckDBPyConnection, investor_id: int, positions: list[dict[str, Any]]
) -> int:
    count = 0
    for p in positions:
        target = str(p.get("target", "")).strip()
        if not target:
            continue
        update_time = str(p.get("update_time", "") or "")
        # dedup key: (investor_id, update_time, target)
        existing = conn.execute(
            "SELECT id FROM celebrity_position WHERE investor_id = ? AND update_time = ? AND target = ?",
            [investor_id, update_time, target],
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO celebrity_position (investor_id, target, percentage, direction, source, update_time, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                investor_id,
                target,
                str(p.get("percentage", "") or ""),
                str(p.get("direction", "") or ""),
                str(p.get("source", "") or ""),
                update_time,
                str(p.get("confidence", "") or ""),
            ],
        )
        count += 1
    return count


def overwrite_positions(
    conn: duckdb.DuckDBPyConnection,
    investor_id: int,
    positions: list[dict[str, Any]],
    snapshot_date: str,
) -> tuple[int, bool]:
    """Overwrite current positions with the new top-15 holdings.

    If the new holdings differ from the old ones (by target + percentage set),
    the old holdings are archived into ``celebrity_position_snapshot`` tagged
    with ``snapshot_date``. Returns ``(inserted_count, snapshot_saved)``.
    """
    old_positions = list_positions(conn, investor_id)

    cleaned: list[dict[str, Any]] = []
    for p in positions[:15]:
        target = str(p.get("target", "")).strip()
        if not target:
            continue
        cleaned.append({
            "target": target,
            "percentage": str(p.get("percentage", "") or ""),
            "source": str(p.get("source", "") or ""),
            "update_time": str(p.get("update_time", "") or ""),
            "confidence": str(p.get("confidence", "") or ""),
        })

    def _fingerprint(items: list[dict[str, Any]]) -> set[tuple[str, str]]:
        return {(str(i.get("target", "")), str(i.get("percentage", "") or "")) for i in items}

    changed = _fingerprint(old_positions) != _fingerprint(cleaned)

    snapshot_saved = False
    if changed and old_positions:
        for old in old_positions:
            conn.execute(
                "INSERT INTO celebrity_position_snapshot "
                "(investor_id, snapshot_date, target, percentage, source, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    investor_id,
                    snapshot_date,
                    str(old.get("target", "")),
                    str(old.get("percentage", "") or ""),
                    str(old.get("source", "") or ""),
                    str(old.get("confidence", "") or ""),
                ],
            )
        snapshot_saved = True

    conn.execute("DELETE FROM celebrity_position WHERE investor_id = ?", [investor_id])
    inserted = 0
    for p in cleaned:
        conn.execute(
            "INSERT INTO celebrity_position "
            "(investor_id, target, percentage, source, update_time, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                investor_id,
                p["target"],
                p["percentage"],
                p["source"],
                p["update_time"],
                p["confidence"],
            ],
        )
        inserted += 1
    return inserted, snapshot_saved


def append_position_snapshots(
    conn: duckdb.DuckDBPyConnection,
    investor_id: int,
    snapshots: list[dict[str, Any]],
    default_snapshot_date: str,
) -> int:
    """Append historical positions into the snapshot table (no overwrite of current)."""
    count = 0
    for s in snapshots:
        target = str(s.get("target", "")).strip()
        if not target:
            continue
        snapshot_date = str(s.get("time", "") or default_snapshot_date)
        # dedup key: (investor_id, snapshot_date, target)
        existing = conn.execute(
            "SELECT id FROM celebrity_position_snapshot "
            "WHERE investor_id = ? AND snapshot_date = ? AND target = ?",
            [investor_id, snapshot_date, target],
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO celebrity_position_snapshot "
            "(investor_id, snapshot_date, target, percentage, source, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                investor_id,
                snapshot_date,
                target,
                str(s.get("percentage", "") or ""),
                str(s.get("source", "") or ""),
                str(s.get("confidence", "") or ""),
            ],
        )
        count += 1
    return count


def append_opinions(
    conn: duckdb.DuckDBPyConnection, investor_id: int, opinions: list[dict[str, Any]],
    set_latest: bool = False,
) -> int:
    count = 0
    for o in opinions:
        content = str(o.get("content", "")).strip()
        publish_time = str(o.get("publish_time", "") or "")
        if not content and not publish_time:
            continue
        # dedup key: (investor_id, publish_time, content)
        existing = conn.execute(
            "SELECT id FROM celebrity_opinion WHERE investor_id = ? AND publish_time = ? AND content = ?",
            [investor_id, publish_time, content],
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO celebrity_opinion (investor_id, publish_time, content, source, confidence, review_result) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                investor_id,
                publish_time,
                content,
                str(o.get("source", "") or ""),
                str(o.get("confidence", "") or ""),
                str(o.get("review_result", "") or ""),
            ],
        )
        count += 1
    if set_latest and opinions:
        # mark the most recent opinion as latest
        conn.execute(
            "UPDATE celebrity_opinion SET is_latest = false WHERE investor_id = ?", [investor_id]
        )
        latest = max(
            opinions,
            key=lambda x: str(x.get("publish_time", "")),
            default=None,
        )
        if latest:
            conn.execute(
                "UPDATE celebrity_opinion SET is_latest = true "
                "WHERE investor_id = ? AND publish_time = ? AND content = ?",
                [investor_id, str(latest.get("publish_time", "")), str(latest.get("content", ""))],
            )
    return count


def append_adjusts(
    conn: duckdb.DuckDBPyConnection, investor_id: int, adjusts: list[dict[str, Any]]
) -> int:
    count = 0
    for a in adjusts:
        target = str(a.get("target", "")).strip()
        time_ = str(a.get("time", "") or "")
        action = str(a.get("action", "") or "")
        if not target and not time_:
            continue
        existing = conn.execute(
            "SELECT id FROM celebrity_adjust WHERE investor_id = ? AND time = ? AND target = ? AND action = ?",
            [investor_id, time_, target, action],
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO celebrity_adjust (investor_id, time, action, target, profit_desc, source, review_result) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                investor_id,
                time_,
                action,
                target,
                str(a.get("profit_desc", "") or ""),
                str(a.get("source", "") or ""),
                str(a.get("review_result", "") or ""),
            ],
        )
        count += 1
    return count


def list_positions(conn: duckdb.DuckDBPyConnection, investor_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM celebrity_position WHERE investor_id = ? ORDER BY update_time DESC, created_at DESC",
        [investor_id],
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def list_position_snapshots(conn: duckdb.DuckDBPyConnection, investor_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM celebrity_position_snapshot WHERE investor_id = ? "
        "ORDER BY snapshot_date DESC, created_at DESC",
        [investor_id],
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def list_opinions(conn: duckdb.DuckDBPyConnection, investor_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM celebrity_opinion WHERE investor_id = ? ORDER BY is_latest DESC, publish_time DESC, created_at DESC",
        [investor_id],
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def list_adjusts(conn: duckdb.DuckDBPyConnection, investor_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM celebrity_adjust WHERE investor_id = ? ORDER BY time DESC, created_at DESC",
        [investor_id],
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def update_opinion_review(
    conn: duckdb.DuckDBPyConnection, opinion_id: str, confidence: str, review_result: str
) -> None:
    conn.execute(
        "UPDATE celebrity_opinion SET confidence = ?, review_result = ? WHERE id = ?",
        [confidence, review_result, opinion_id],
    )


def update_adjust_review(
    conn: duckdb.DuckDBPyConnection, adjust_id: str, profit_desc: str, review_result: str
) -> None:
    conn.execute(
        "UPDATE celebrity_adjust SET profit_desc = ?, review_result = ? WHERE id = ?",
        [profit_desc, review_result, adjust_id],
    )


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

def get_performance(conn: duckdb.DuckDBPyConnection, investor_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM celebrity_performance WHERE investor_id = ? ORDER BY created_at DESC LIMIT 1",
        [investor_id],
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def save_performance(conn: duckdb.DuckDBPyConnection, investor_id: int, data: dict[str, Any]) -> None:
    # Remove previous records for this investor (keep only latest)
    conn.execute("DELETE FROM celebrity_performance WHERE investor_id = ?", [investor_id])
    conn.execute(
        """INSERT INTO celebrity_performance
            (investor_id, recent_performance, return_1y, return_3y, return_5y, return_10y,
             max_drawdown, stability_tag, stability_desc, peer_compare, risk_note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            investor_id,
            str(data.get("recent_performance", "") or ""),
            str(data.get("return_1y", "") or ""),
            str(data.get("return_3y", "") or ""),
            str(data.get("return_5y", "") or ""),
            str(data.get("return_10y", "") or ""),
            str(data.get("max_drawdown", "") or ""),
            str(data.get("stability_tag", "") or ""),
            str(data.get("stability_desc", "") or ""),
            str(data.get("peer_compare", "") or ""),
            str(data.get("risk_note", "") or ""),
        ],
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def get_prompt(conn: duckdb.DuckDBPyConnection, key: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM celebrity_prompt WHERE prompt_key = ?", [key]
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def update_prompt(conn: duckdb.DuckDBPyConnection, key: str, content: str) -> None:
    existing = conn.execute(
        "SELECT prompt_key FROM celebrity_prompt WHERE prompt_key = ?", [key]
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE celebrity_prompt SET content = ?, is_user_edited = true, "
            "updated_at = current_timestamp WHERE prompt_key = ?",
            [content, key],
        )
    else:
        conn.execute(
            "INSERT INTO celebrity_prompt (prompt_key, content, is_user_edited) VALUES (?, ?, true)",
            [key, content],
        )


def reset_prompt_to_default(conn: duckdb.DuckDBPyConnection, key: str) -> str:
    """Reset a prompt to its code default and clear the user-edit flag."""
    content = DEFAULT_PROMPTS.get(key, "")
    if not content:
        raise ValueError(f"未知的提示词键: {key}")
    existing = conn.execute(
        "SELECT prompt_key FROM celebrity_prompt WHERE prompt_key = ?", [key]
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE celebrity_prompt SET content = ?, is_user_edited = false, "
            "updated_at = current_timestamp WHERE prompt_key = ?",
            [content, key],
        )
    else:
        conn.execute(
            "INSERT INTO celebrity_prompt (prompt_key, content, is_user_edited) VALUES (?, ?, false)",
            [key, content],
        )
    return content


# ---------------------------------------------------------------------------
# Weekly dynamics aggregation
# ---------------------------------------------------------------------------

def get_weekly_dynamics(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Return one entry per investor with their latest opinion + latest adjust."""
    investors = list_investors(conn)
    result: list[dict[str, Any]] = []
    for inv in investors:
        inv_id = inv["id"]
        latest_opinion = conn.execute(
            "SELECT publish_time, content, confidence, created_at FROM celebrity_opinion "
            "WHERE investor_id = ? ORDER BY is_latest DESC, publish_time DESC LIMIT 1",
            [inv_id],
        ).fetchone()
        latest_adjust = conn.execute(
            "SELECT time, action, target, review_result, created_at FROM celebrity_adjust "
            "WHERE investor_id = ? ORDER BY time DESC LIMIT 1",
            [inv_id],
        ).fetchone()
        updated_at = None
        if latest_opinion and latest_adjust:
            updated_at = max(str(latest_opinion[3]), str(latest_adjust[4]))
        elif latest_opinion:
            updated_at = str(latest_opinion[3])
        elif latest_adjust:
            updated_at = str(latest_adjust[4])
        result.append({
            "investor_id": inv_id,
            "name": inv["name"],
            "latest_opinion": {
                "publish_time": latest_opinion[0] if latest_opinion else None,
                "content": latest_opinion[1] if latest_opinion else None,
                "confidence": latest_opinion[2] if latest_opinion else None,
            } if latest_opinion else None,
            "latest_adjust": {
                "time": latest_adjust[0] if latest_adjust else None,
                "action": latest_adjust[1] if latest_adjust else None,
                "target": latest_adjust[2] if latest_adjust else None,
                "review_result": latest_adjust[3] if latest_adjust else None,
            } if latest_adjust else None,
            "updated_at": updated_at,
        })
    # Sort by updated_at desc (None last)
    result.sort(key=lambda x: x["updated_at"] or "", reverse=True)
    return result
