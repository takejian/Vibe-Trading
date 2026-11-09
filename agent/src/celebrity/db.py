"""MySQL persistence for the investment celebrity module.

Tables live in the local MySQL instance (default schema ``vibe``) and are
prefixed ``celebrity_``. All connections are short-lived (open per operation,
closed in ``finally``) and credentials come from the typed config layer
(``CELEBRITY_DB_*``) — never from ``os.getenv`` here.

SQL dialect notes vs. the original DuckDB implementation:
- placeholders are ``%s`` (not ``?``);
- UUID primary keys are generated in Python (``str(uuid.uuid4())``);
- ``BOOLEAN`` maps to ``TINYINT(1)``; Python ``bool`` values are coerced to int
  on write and back to bool on read;
- ``current_timestamp`` stays valid.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import pymysql

from src.celebrity.prompts import DEFAULT_PROMPTS, PREDEFINED_INVESTORS
from src.config.accessor import get_env_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DDL (executed for idempotent bootstrap; ALTER migrations handled separately)
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS celebrity_investor (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(256) NOT NULL,
    invest_style  TEXT NOT NULL,
    remark        TEXT NOT NULL,
    is_builtin    TINYINT(1) NOT NULL DEFAULT 0,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS celebrity_position (
    id            CHAR(36) NOT NULL PRIMARY KEY,
    investor_id   BIGINT UNSIGNED NOT NULL,
    target        VARCHAR(256) NOT NULL,
    percentage    VARCHAR(32) DEFAULT NULL,
    direction     VARCHAR(32) DEFAULT NULL,
    source        VARCHAR(256) DEFAULT NULL,
    update_time   VARCHAR(32) DEFAULT NULL,
    confidence    VARCHAR(16) DEFAULT NULL,
    first_added_price DECIMAL(14,4) DEFAULT NULL,
    latest_price      DECIMAL(14,4) DEFAULT NULL,
    return_rate       DECIMAL(10,6) DEFAULT NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_position_investor (investor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS celebrity_position_snapshot (
    id             CHAR(36) NOT NULL PRIMARY KEY,
    investor_id    BIGINT UNSIGNED NOT NULL,
    snapshot_date  VARCHAR(16) NOT NULL,
    target         VARCHAR(256) NOT NULL,
    percentage     VARCHAR(32) DEFAULT NULL,
    source         VARCHAR(256) DEFAULT NULL,
    confidence     VARCHAR(16) DEFAULT NULL,
    first_added_price DECIMAL(14,4) DEFAULT NULL,
    latest_price      DECIMAL(14,4) DEFAULT NULL,
    return_rate       DECIMAL(10,6) DEFAULT NULL,
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_snapshot_investor_date (investor_id, snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS celebrity_opinion (
    id             CHAR(36) NOT NULL PRIMARY KEY,
    investor_id    BIGINT UNSIGNED NOT NULL,
    publish_time   VARCHAR(32) DEFAULT NULL,
    content        TEXT,
    source         VARCHAR(256) DEFAULT NULL,
    confidence     VARCHAR(16) DEFAULT NULL,
    review_result  TEXT,
    is_latest      TINYINT(1) NOT NULL DEFAULT 0,
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_opinion_investor (investor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS celebrity_adjust (
    id             CHAR(36) NOT NULL PRIMARY KEY,
    investor_id    BIGINT UNSIGNED NOT NULL,
    time           VARCHAR(32) DEFAULT NULL,
    action         VARCHAR(32) DEFAULT NULL,
    target         VARCHAR(256) DEFAULT NULL,
    profit_desc    TEXT,
    source         VARCHAR(256) DEFAULT NULL,
    review_result  TEXT,
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_adjust_investor (investor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS celebrity_performance (
    id                  CHAR(36) NOT NULL PRIMARY KEY,
    investor_id         BIGINT UNSIGNED NOT NULL,
    recent_performance  TEXT,
    return_1y           VARCHAR(128) DEFAULT NULL,
    return_3y           VARCHAR(128) DEFAULT NULL,
    return_5y           VARCHAR(128) DEFAULT NULL,
    return_10y          VARCHAR(128) DEFAULT NULL,
    max_drawdown        VARCHAR(128) DEFAULT NULL,
    stability_tag       VARCHAR(64) DEFAULT NULL,
    stability_desc      TEXT,
    peer_compare        TEXT,
    risk_note           TEXT,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_performance_investor (investor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS celebrity_prompt (
    prompt_key     VARCHAR(64) NOT NULL PRIMARY KEY,
    content        TEXT NOT NULL,
    is_user_edited TINYINT(1) NOT NULL DEFAULT 0,
    updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def _connection_kwargs() -> dict[str, Any]:
    cfg = get_env_config()
    celeb = cfg.celebrity
    macro = cfg.macro
    # Default to the same local MySQL instance as the macro module so users
    # don't have to duplicate MACRO_DB_* into CELEBRITY_DB_* unless they want
    # a separate store.
    return {
        "host": celeb.celebrity_db_host or macro.macro_db_host,
        "port": celeb.celebrity_db_port or macro.macro_db_port,
        "user": celeb.celebrity_db_user or macro.macro_db_user,
        "password": celeb.celebrity_db_password or macro.macro_db_password,
        "database": celeb.celebrity_db_name or macro.macro_db_name,
        "charset": "utf8mb4",
        "connect_timeout": 5,
        "autocommit": False,
    }


@contextmanager
def celebrity_connection() -> Iterator[pymysql.connections.Connection]:
    """Yield a short-lived MySQL connection for the celebrity schema."""
    conn = pymysql.connect(**_connection_kwargs())
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # best-effort close
            logger.debug("celebrity MySQL connection close failed", exc_info=True)


def _exec(conn: pymysql.connections.Connection, sql: str, params: tuple = ()):
    """Execute a statement and return the cursor (for fetchone/fetchall/rowcount)."""
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def _row_to_dict(cur, row) -> dict[str, Any]:
    if row is None:
        return None  # type: ignore[return-value]
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _rows_to_dicts(cur, rows) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def _to_bool(v: Any) -> bool:
    """Coerce MySQL TINYINT(1) (0/1) back to Python bool."""
    if isinstance(v, bool):
        return v
    return bool(v)


def _column_exists(conn: pymysql.connections.Connection, table: str, column: str) -> bool:
    cur = _exec(conn, f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
    return cur.fetchone() is not None


def initialize_schema(conn: pymysql.connections.Connection) -> None:
    """Create celebrity_* tables and seed default data if absent."""
    for stmt in _DDL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.cursor().execute(stmt)
    # Migrations (idempotent, check column presence before ALTER).
    for table in ("celebrity_position", "celebrity_position_snapshot"):
        for col, ddl in [
            ("first_added_price", "ADD COLUMN first_added_price DECIMAL(14,4) DEFAULT NULL"),
            ("latest_price", "ADD COLUMN latest_price DECIMAL(14,4) DEFAULT NULL"),
            ("return_rate", "ADD COLUMN return_rate DECIMAL(10,6) DEFAULT NULL"),
        ]:
            if not _column_exists(conn, table, col):
                conn.cursor().execute(f"ALTER TABLE {table} {ddl}")
    if not _column_exists(conn, "celebrity_prompt", "is_user_edited"):
        conn.cursor().execute(
            "ALTER TABLE celebrity_prompt ADD COLUMN is_user_edited TINYINT(1) NOT NULL DEFAULT 0"
        )
    _seed_predefined_investors(conn)
    _seed_default_prompts(conn)


def _next_investor_id(conn: pymysql.connections.Connection) -> int:
    cur = _exec(conn, "SELECT coalesce(max(id), 0) + 1 FROM celebrity_investor")
    row = cur.fetchone()
    return int(row[0]) if row else 1


def _seed_predefined_investors(conn: pymysql.connections.Connection) -> None:
    for inv in PREDEFINED_INVESTORS:
        cur = _exec(conn, "SELECT id FROM celebrity_investor WHERE name = %s", (inv["name"],))
        if cur.fetchone() is None:
            nid = _next_investor_id(conn)
            _exec(
                conn,
                "INSERT INTO celebrity_investor (id, name, invest_style, remark, is_builtin) "
                "VALUES (%s, %s, %s, %s, 1)",
                (nid, inv["name"], inv["invest_style"], inv["remark"]),
            )


def _seed_default_prompts(conn: pymysql.connections.Connection) -> None:
    """Keep DB prompts in sync with code defaults.

    - missing key            → insert the default (not user-edited)
    - key present, not edited → overwrite DB content with the latest default
    - key present, edited    → leave the user's customization untouched
    """
    for key, content in DEFAULT_PROMPTS.items():
        cur = _exec(
            conn,
            "SELECT content, is_user_edited FROM celebrity_prompt WHERE prompt_key = %s",
            (key,),
        )
        row = cur.fetchone()
        if row is None:
            _exec(
                conn,
                "INSERT INTO celebrity_prompt (prompt_key, content, is_user_edited) "
                "VALUES (%s, %s, 0)",
                (key, content),
            )
            continue
        current_content, is_user_edited = row[0], row[1]
        if _to_bool(is_user_edited):
            continue
        if current_content != content:
            _exec(
                conn,
                "UPDATE celebrity_prompt SET content = %s, updated_at = CURRENT_TIMESTAMP "
                "WHERE prompt_key = %s",
                (content, key),
            )


# ---------------------------------------------------------------------------
# Investor CRUD
# ---------------------------------------------------------------------------

def list_investors(conn: pymysql.connections.Connection) -> list[dict[str, Any]]:
    cur = _exec(
        conn,
        "SELECT id, name, invest_style, remark, is_builtin, updated_at "
        "FROM celebrity_investor ORDER BY is_builtin DESC, id ASC",
    )
    rows = _rows_to_dicts(cur, cur.fetchall())
    for r in rows:
        r["is_builtin"] = _to_bool(r.get("is_builtin"))
    return rows


def get_investor(conn: pymysql.connections.Connection, investor_id: int) -> dict[str, Any] | None:
    cur = _exec(conn, "SELECT * FROM celebrity_investor WHERE id = %s", (investor_id,))
    row = _row_to_dict(cur, cur.fetchone())
    if row is not None:
        row["is_builtin"] = _to_bool(row.get("is_builtin"))
    return row


def add_investor(
    conn: pymysql.connections.Connection, name: str, invest_style: str, remark: str
) -> int:
    nid = _next_investor_id(conn)
    _exec(
        conn,
        "INSERT INTO celebrity_investor (id, name, invest_style, remark, is_builtin) "
        "VALUES (%s, %s, %s, %s, 0)",
        (nid, name, invest_style, remark),
    )
    return nid


def delete_investor(conn: pymysql.connections.Connection, investor_id: int) -> bool:
    """Delete a non-builtin investor and all its data. Returns True if deleted."""
    inv = get_investor(conn, investor_id)
    if inv is None:
        return False
    if inv.get("is_builtin"):
        return False
    _exec(conn, "DELETE FROM celebrity_position WHERE investor_id = %s", (investor_id,))
    _exec(conn, "DELETE FROM celebrity_position_snapshot WHERE investor_id = %s", (investor_id,))
    _exec(conn, "DELETE FROM celebrity_opinion WHERE investor_id = %s", (investor_id,))
    _exec(conn, "DELETE FROM celebrity_adjust WHERE investor_id = %s", (investor_id,))
    _exec(conn, "DELETE FROM celebrity_performance WHERE investor_id = %s", (investor_id,))
    _exec(conn, "DELETE FROM celebrity_investor WHERE id = %s", (investor_id,))
    return True


def update_invest_style(conn: pymysql.connections.Connection, investor_id: int, invest_style: str) -> None:
    _exec(
        conn,
        "UPDATE celebrity_investor SET invest_style = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
        (invest_style, investor_id),
    )


# ---------------------------------------------------------------------------
# Position / Opinion / Adjust
# ---------------------------------------------------------------------------

def append_positions(
    conn: pymysql.connections.Connection, investor_id: int, positions: list[dict[str, Any]]
) -> int:
    count = 0
    for p in positions:
        target = str(p.get("target", "")).strip()
        if not target:
            continue
        update_time = str(p.get("update_time", "") or "")
        cur = _exec(
            conn,
            "SELECT id FROM celebrity_position WHERE investor_id = %s AND update_time = %s AND target = %s",
            (investor_id, update_time, target),
        )
        if cur.fetchone():
            continue
        _exec(
            conn,
            "INSERT INTO celebrity_position "
            "(id, investor_id, target, percentage, direction, source, update_time, confidence) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                investor_id,
                target,
                str(p.get("percentage", "") or ""),
                str(p.get("direction", "") or ""),
                str(p.get("source", "") or ""),
                update_time,
                str(p.get("confidence", "") or ""),
            ),
        )
        count += 1
    return count


def overwrite_positions(
    conn: pymysql.connections.Connection,
    investor_id: int,
    positions: list[dict[str, Any]],
    snapshot_date: str,
) -> tuple[int, bool]:
    """Overwrite current positions with the new top-15 holdings.

    Preserves ``first_added_price`` from old positions when the target is
    still present in the new holdings (so it becomes the "first entry" price).
    Snapshots archive the old prices too so cleared targets keep their last
    known price trail.
    """
    old_positions = list_positions(conn, investor_id)
    old_by_target: dict[str, dict[str, Any]] = {
        str(p.get("target", "")): p for p in old_positions
    }

    cleaned: list[dict[str, Any]] = []
    for p in positions[:15]:
        target = str(p.get("target", "")).strip()
        if not target:
            continue
        old = old_by_target.get(target, {})
        old_first = old.get("first_added_price")
        old_latest = old.get("latest_price")
        # New position with no prior record: use any provided price as first_added_price
        # (LLM may embed first_added_price or latest_price in the incoming position dict).
        incoming_first = p.get("first_added_price")
        incoming_latest = p.get("latest_price")
        first_added_price = (
            old_first
            if old_first is not None
            else incoming_first
            if incoming_first is not None
            else incoming_latest
            if incoming_latest is not None
            else old_latest
            if old_latest is not None
            else None
        )
        latest_price = (
            incoming_latest
            if incoming_latest is not None
            else old_latest
            if old_latest is not None
            else None
        )
        cleaned.append({
            "target": target,
            "percentage": str(p.get("percentage", "") or ""),
            "source": str(p.get("source", "") or ""),
            "update_time": str(p.get("update_time", "") or ""),
            "confidence": str(p.get("confidence", "") or ""),
            "first_added_price": first_added_price,
            "latest_price": latest_price,
            "return_rate": old.get("return_rate"),  # keep from old if exists
        })

    def _fingerprint(items: list[dict[str, Any]]) -> set[tuple[str, str]]:
        return {(str(i.get("target", "")), str(i.get("percentage", "") or "")) for i in items}

    changed = _fingerprint(old_positions) != _fingerprint(cleaned)

    snapshot_saved = False
    if changed and old_positions:
        for old in old_positions:
            _exec(
                conn,
                "INSERT INTO celebrity_position_snapshot "
                "(id, investor_id, snapshot_date, target, percentage, source, confidence, "
                " first_added_price, latest_price, return_rate) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(uuid.uuid4()),
                    investor_id,
                    snapshot_date,
                    str(old.get("target", "")),
                    str(old.get("percentage", "") or ""),
                    str(old.get("source", "") or ""),
                    str(old.get("confidence", "") or ""),
                    old.get("first_added_price"),
                    old.get("latest_price"),
                    old.get("return_rate"),
                ),
            )
        snapshot_saved = True

    _exec(conn, "DELETE FROM celebrity_position WHERE investor_id = %s", (investor_id,))
    inserted = 0
    for p in cleaned:
        _exec(
            conn,
            "INSERT INTO celebrity_position "
            "(id, investor_id, target, percentage, source, update_time, confidence, "
            " first_added_price, latest_price, return_rate) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                investor_id,
                p["target"],
                p["percentage"],
                p["source"],
                p["update_time"],
                p["confidence"],
                p["first_added_price"],
                p["latest_price"],
                p["return_rate"],
            ),
        )
        inserted += 1
    return inserted, snapshot_saved


def append_position_snapshots(
    conn: pymysql.connections.Connection,
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
        cur = _exec(
            conn,
            "SELECT id FROM celebrity_position_snapshot "
            "WHERE investor_id = %s AND snapshot_date = %s AND target = %s",
            (investor_id, snapshot_date, target),
        )
        if cur.fetchone():
            continue
        _exec(
            conn,
            "INSERT INTO celebrity_position_snapshot "
            "(id, investor_id, snapshot_date, target, percentage, source, confidence) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                investor_id,
                snapshot_date,
                target,
                str(s.get("percentage", "") or ""),
                str(s.get("source", "") or ""),
                str(s.get("confidence", "") or ""),
            ),
        )
        count += 1
    return count


def append_opinions(
    conn: pymysql.connections.Connection, investor_id: int, opinions: list[dict[str, Any]],
    set_latest: bool = False,
) -> int:
    count = 0
    for o in opinions:
        content = str(o.get("content", "")).strip()
        publish_time = str(o.get("publish_time", "") or "")
        if not content and not publish_time:
            continue
        cur = _exec(
            conn,
            "SELECT id FROM celebrity_opinion WHERE investor_id = %s AND publish_time = %s AND content = %s",
            (investor_id, publish_time, content),
        )
        if cur.fetchone():
            continue
        _exec(
            conn,
            "INSERT INTO celebrity_opinion "
            "(id, investor_id, publish_time, content, source, confidence, review_result) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                investor_id,
                publish_time,
                content,
                str(o.get("source", "") or ""),
                str(o.get("confidence", "") or ""),
                str(o.get("review_result", "") or ""),
            ),
        )
        count += 1
    if set_latest and opinions:
        _exec(conn, "UPDATE celebrity_opinion SET is_latest = 0 WHERE investor_id = %s", (investor_id,))
        latest = max(opinions, key=lambda x: str(x.get("publish_time", "")), default=None)
        if latest:
            _exec(
                conn,
                "UPDATE celebrity_opinion SET is_latest = 1 "
                "WHERE investor_id = %s AND publish_time = %s AND content = %s",
                (investor_id, str(latest.get("publish_time", "")), str(latest.get("content", ""))),
            )
    return count


def append_adjusts(
    conn: pymysql.connections.Connection, investor_id: int, adjusts: list[dict[str, Any]]
) -> int:
    count = 0
    for a in adjusts:
        target = str(a.get("target", "")).strip()
        time_ = str(a.get("time", "") or "")
        action = str(a.get("action", "") or "")
        if not target and not time_:
            continue
        cur = _exec(
            conn,
            "SELECT id FROM celebrity_adjust WHERE investor_id = %s AND time = %s AND target = %s AND action = %s",
            (investor_id, time_, target, action),
        )
        if cur.fetchone():
            continue
        _exec(
            conn,
            "INSERT INTO celebrity_adjust "
            "(id, investor_id, time, action, target, profit_desc, source, review_result) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                investor_id,
                time_,
                action,
                target,
                str(a.get("profit_desc", "") or ""),
                str(a.get("source", "") or ""),
                str(a.get("review_result", "") or ""),
            ),
        )
        count += 1
    return count


def list_positions(conn: pymysql.connections.Connection, investor_id: int) -> list[dict[str, Any]]:
    cur = _exec(
        conn,
        "SELECT * FROM celebrity_position WHERE investor_id = %s ORDER BY update_time DESC, created_at DESC",
        (investor_id,),
    )
    return _rows_to_dicts(cur, cur.fetchall())


def list_position_snapshots(conn: pymysql.connections.Connection, investor_id: int) -> list[dict[str, Any]]:
    cur = _exec(
        conn,
        "SELECT * FROM celebrity_position_snapshot WHERE investor_id = %s "
        "ORDER BY snapshot_date DESC, created_at DESC",
        (investor_id,),
    )
    return _rows_to_dicts(cur, cur.fetchall())


def list_opinions(conn: pymysql.connections.Connection, investor_id: int) -> list[dict[str, Any]]:
    cur = _exec(
        conn,
        "SELECT * FROM celebrity_opinion WHERE investor_id = %s "
        "ORDER BY is_latest DESC, publish_time DESC, created_at DESC",
        (investor_id,),
    )
    rows = _rows_to_dicts(cur, cur.fetchall())
    for r in rows:
        r["is_latest"] = _to_bool(r.get("is_latest"))
    return rows


def list_adjusts(conn: pymysql.connections.Connection, investor_id: int) -> list[dict[str, Any]]:
    cur = _exec(
        conn,
        "SELECT * FROM celebrity_adjust WHERE investor_id = %s ORDER BY time DESC, created_at DESC",
        (investor_id,),
    )
    return _rows_to_dicts(cur, cur.fetchall())


def update_opinion_review(
    conn: pymysql.connections.Connection, opinion_id: str, confidence: str, review_result: str
) -> None:
    _exec(
        conn,
        "UPDATE celebrity_opinion SET confidence = %s, review_result = %s WHERE id = %s",
        (confidence, review_result, opinion_id),
    )


def update_adjust_review(
    conn: pymysql.connections.Connection, adjust_id: str, profit_desc: str, review_result: str
) -> None:
    _exec(
        conn,
        "UPDATE celebrity_adjust SET profit_desc = %s, review_result = %s WHERE id = %s",
        (profit_desc, review_result, adjust_id),
    )


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

def get_performance(conn: pymysql.connections.Connection, investor_id: int) -> dict[str, Any] | None:
    cur = _exec(
        conn,
        "SELECT * FROM celebrity_performance WHERE investor_id = %s ORDER BY created_at DESC LIMIT 1",
        (investor_id,),
    )
    return _row_to_dict(cur, cur.fetchone())


def save_performance(conn: pymysql.connections.Connection, investor_id: int, data: dict[str, Any]) -> None:
    _exec(conn, "DELETE FROM celebrity_performance WHERE investor_id = %s", (investor_id,))
    _exec(
        conn,
        """INSERT INTO celebrity_performance
            (id, investor_id, recent_performance, return_1y, return_3y, return_5y, return_10y,
             max_drawdown, stability_tag, stability_desc, peer_compare, risk_note)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            str(uuid.uuid4()),
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
        ),
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def get_prompt(conn: pymysql.connections.Connection, key: str) -> dict[str, Any] | None:
    cur = _exec(conn, "SELECT * FROM celebrity_prompt WHERE prompt_key = %s", (key,))
    row = _row_to_dict(cur, cur.fetchone())
    if row is not None:
        row["is_user_edited"] = _to_bool(row.get("is_user_edited"))
    return row


def update_prompt(conn: pymysql.connections.Connection, key: str, content: str) -> None:
    cur = _exec(conn, "SELECT prompt_key FROM celebrity_prompt WHERE prompt_key = %s", (key,))
    if cur.fetchone():
        _exec(
            conn,
            "UPDATE celebrity_prompt SET content = %s, is_user_edited = 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE prompt_key = %s",
            (content, key),
        )
    else:
        _exec(
            conn,
            "INSERT INTO celebrity_prompt (prompt_key, content, is_user_edited) VALUES (%s, %s, 1)",
            (key, content),
        )


def reset_prompt_to_default(conn: pymysql.connections.Connection, key: str) -> str:
    """Reset a prompt to its code default and clear the user-edit flag."""
    content = DEFAULT_PROMPTS.get(key, "")
    if not content:
        raise ValueError(f"未知的提示词键: {key}")
    cur = _exec(conn, "SELECT prompt_key FROM celebrity_prompt WHERE prompt_key = %s", (key,))
    if cur.fetchone():
        _exec(
            conn,
            "UPDATE celebrity_prompt SET content = %s, is_user_edited = 0, "
            "updated_at = CURRENT_TIMESTAMP WHERE prompt_key = %s",
            (content, key),
        )
    else:
        _exec(
            conn,
            "INSERT INTO celebrity_prompt (prompt_key, content, is_user_edited) VALUES (%s, %s, 0)",
            (key, content),
        )
    return content


# ---------------------------------------------------------------------------
# Weekly dynamics aggregation
# ---------------------------------------------------------------------------

def get_weekly_dynamics(conn: pymysql.connections.Connection) -> list[dict[str, Any]]:
    """Return one entry per investor with their latest opinion + latest adjust."""
    investors = list_investors(conn)
    result: list[dict[str, Any]] = []
    for inv in investors:
        inv_id = inv["id"]
        cur_o = _exec(
            conn,
            "SELECT publish_time, content, confidence, created_at FROM celebrity_opinion "
            "WHERE investor_id = %s ORDER BY is_latest DESC, publish_time DESC LIMIT 1",
            (inv_id,),
        )
        latest_opinion = cur_o.fetchone()
        cur_a = _exec(
            conn,
            "SELECT time, action, target, review_result, created_at FROM celebrity_adjust "
            "WHERE investor_id = %s ORDER BY time DESC LIMIT 1",
            (inv_id,),
        )
        latest_adjust = cur_a.fetchone()
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
    result.sort(key=lambda x: x["updated_at"] or "", reverse=True)
    return result


# ---------------------------------------------------------------------------
# Aggregated position view (for 公募持仓 Tab)
# ---------------------------------------------------------------------------

def list_all_positions_with_investors(
    conn: pymysql.connections.Connection,
) -> list[dict[str, Any]]:
    """Return every current position joined with investor name.

    Each row is one investor+target pair. Caller groups by normalized target.
    """
    cur = _exec(
        conn,
        """SELECT cp.id, cp.investor_id, cp.target, cp.percentage,
                  cp.first_added_price, cp.latest_price, cp.return_rate,
                  ci.name AS investor_name
             FROM celebrity_position cp
             JOIN celebrity_investor ci ON ci.id = cp.investor_id
             ORDER BY cp.target, cp.investor_id""",
    )
    return _rows_to_dicts(cur, cur.fetchall())


def list_latest_adjust_per_target(
    conn: pymysql.connections.Connection,
) -> dict[tuple[int, str], dict[str, Any]]:
    """Return the latest adjust per (investor_id, target) as a dict lookup."""
    cur = _exec(
        conn,
        """SELECT a.investor_id, a.target, a.action, a.time
             FROM celebrity_adjust a
             JOIN (
                 SELECT investor_id, target, MAX(time) AS max_time
                 FROM celebrity_adjust
                 GROUP BY investor_id, target
             ) t ON a.investor_id = t.investor_id
                 AND a.target = t.target
                 AND a.time = t.max_time""",
    )
    rows = _rows_to_dicts(cur, cur.fetchall())
    return {(int(r["investor_id"]), str(r["target"])): r for r in rows}


def get_latest_snapshot_date(
    conn: pymysql.connections.Connection, investor_id: int
) -> str | None:
    cur = _exec(
        conn,
        "SELECT snapshot_date FROM celebrity_position_snapshot "
        "WHERE investor_id = %s ORDER BY snapshot_date DESC LIMIT 1",
        (investor_id,),
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


def list_latest_batch_cleared(
    conn: pymysql.connections.Connection,
) -> list[dict[str, Any]]:
    """Return targets cleared in the most recent snapshot batch across all investors.

    A cleared target = present in the latest snapshot batch of that investor
    but absent from current celebrity_position.
    """
    # 1. Find latest snapshot_date per investor
    cur = _exec(
        conn,
        """SELECT investor_id, MAX(snapshot_date) AS latest_date
             FROM celebrity_position_snapshot
             GROUP BY investor_id""",
    )
    latest_dates = _rows_to_dicts(cur, cur.fetchall())
    results: list[dict[str, Any]] = []
    for row in latest_dates:
        inv_id = int(row["investor_id"])
        snap_date = str(row["latest_date"])
        cur2 = _exec(
            conn,
            """SELECT s.target, s.first_added_price, s.latest_price, s.return_rate,
                      ci.name AS investor_name
                 FROM celebrity_position_snapshot s
                 JOIN celebrity_investor ci ON ci.id = s.investor_id
                WHERE s.investor_id = %s AND s.snapshot_date = %s""",
            (inv_id, snap_date),
        )
        snap_rows = _rows_to_dicts(cur2, cur2.fetchall())
        snap_targets = {str(r["target"]): r for r in snap_rows}
        cur3 = _exec(
            conn,
            "SELECT target FROM celebrity_position WHERE investor_id = %s",
            (inv_id,),
        )
        current_targets = {str(r[0]) for r in cur3.fetchall()}
        for target, snap in snap_targets.items():
            if target not in current_targets:
                results.append({
                    "investor_id": inv_id,
                    "investor_name": snap["investor_name"],
                    "target": target,
                    "first_added_price": snap.get("first_added_price"),
                    "latest_price": snap.get("latest_price"),
                    "return_rate": snap.get("return_rate"),
                    "snapshot_date": snap_date,
                })
    results.sort(key=lambda x: str(x.get("snapshot_date", "")), reverse=True)
    return results


# ---------------------------------------------------------------------------
# Price updates
# ---------------------------------------------------------------------------

def batch_update_prices(
    conn: pymysql.connections.Connection,
    price_map: dict[str, float | None],
) -> int:
    """Update latest_price + compute return_rate for all current positions.

    price_map: {target: latest_price} (prices are numbers, NULL represented as None).
    Returns number of rows updated.
    """
    return _do_batch_price_update(conn, price_map)


def _do_batch_price_update(
    conn: pymysql.connections.Connection,
    price_map: dict[str, float | None],
) -> int:
    updated = 0
    for target, latest_price in price_map.items():
        if latest_price is None:
            continue
        cur = conn.cursor()
        cur.execute(
            "UPDATE celebrity_position "
            "SET latest_price = %s, "
            "    return_rate = CASE "
            "      WHEN first_added_price IS NULL OR first_added_price = 0 THEN NULL "
            "      ELSE ROUND((latest_price - first_added_price) / first_added_price, 6) "
            "    END "
            "WHERE target = %s",
            (latest_price, target),
        )
        updated += cur.rowcount or 0
    return updated


def sync_prices_to_latest_snapshot(
    conn: pymysql.connections.Connection,
    investor_id: int,
    target: str,
    first_added_price: float | None,
    latest_price: float | None,
    return_rate: float | None,
) -> None:
    """Backfill price fields onto the latest snapshot row for this (investor, target).

    Called when a position is cleared — the prices archived into snapshot by
    overwrite_positions may be stale (since we archive first and prices may
    update later). This ensures the latest snapshot row carries the final price.
    """
    cur = conn.cursor()
    cur.execute(
        """UPDATE celebrity_position_snapshot
              SET first_added_price = %s,
                  latest_price = %s,
                  return_rate = %s
            WHERE investor_id = %s AND target = %s
              AND snapshot_date = (
                  SELECT MAX(snapshot_date) FROM celebrity_position_snapshot
                  WHERE investor_id = %s AND target = %s
              )""",
        (first_added_price, latest_price, return_rate, investor_id, target, investor_id, target),
    )
