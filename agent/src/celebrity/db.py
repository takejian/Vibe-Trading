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
    # Migrate: add columns only when missing (idempotent, no aborted txn).
    if not _column_exists(conn, "celebrity_position", "percentage"):
        conn.cursor().execute("ALTER TABLE celebrity_position ADD COLUMN percentage VARCHAR(32)")
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
            _exec(
                conn,
                "INSERT INTO celebrity_position_snapshot "
                "(id, investor_id, snapshot_date, target, percentage, source, confidence) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    str(uuid.uuid4()),
                    investor_id,
                    snapshot_date,
                    str(old.get("target", "")),
                    str(old.get("percentage", "") or ""),
                    str(old.get("source", "") or ""),
                    str(old.get("confidence", "") or ""),
                ),
            )
        snapshot_saved = True

    _exec(conn, "DELETE FROM celebrity_position WHERE investor_id = %s", (investor_id,))
    inserted = 0
    for p in cleaned:
        _exec(
            conn,
            "INSERT INTO celebrity_position "
            "(id, investor_id, target, percentage, source, update_time, confidence) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                investor_id,
                p["target"],
                p["percentage"],
                p["source"],
                p["update_time"],
                p["confidence"],
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
