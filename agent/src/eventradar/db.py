"""DuckDB persistence for the event radar (``radar_*`` / ``event_report``).

Mirrors the short-connection pattern of ``src/watchlist/db.py``: each caller
opens a connection against the market warehouse, initializes the schema
idempotently, and closes it in a ``finally``. Background scan threads always
use their own connection so they never share a write connection with API
requests.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any, Sequence

import duckdb

from src.config.paths import get_market_db_path

_DDL = """
CREATE TABLE IF NOT EXISTS radar_scan_run (
    id                VARCHAR PRIMARY KEY,
    scope             VARCHAR NOT NULL,
    trigger_type      VARCHAR NOT NULL,
    status            VARCHAR NOT NULL,
    source_status     VARCHAR,
    candidates        INTEGER DEFAULT 0,
    duplicates        INTEGER DEFAULT 0,
    new_events        INTEGER DEFAULT 0,
    escalated         INTEGER DEFAULT 0,
    to_review         INTEGER DEFAULT 0,
    error             VARCHAR,
    started_at        TIMESTAMP NOT NULL,
    finished_at       TIMESTAMP
);

CREATE TABLE IF NOT EXISTS radar_event (
    event_id          VARCHAR PRIMARY KEY,
    title             VARCHAR NOT NULL,
    event_type        VARCHAR NOT NULL,
    entities          VARCHAR,
    regions           VARCHAR,
    summary           VARCHAR,
    impact_direction  VARCHAR,
    affected_assets   VARCHAR,
    cluster_key       VARCHAR NOT NULL,
    simhash           VARCHAR,
    novelty_class     VARCHAR NOT NULL,
    paradigm_scores   VARCHAR,
    paradigm_total    INTEGER,
    long_term_themes  VARCHAR,
    impact_level      VARCHAR,
    verify_status     VARCHAR NOT NULL,
    confidence        DOUBLE,
    source_count      INTEGER DEFAULT 0,
    first_seen_at     TIMESTAMP NOT NULL,
    last_update_at    TIMESTAMP NOT NULL,
    locked_by_human   BOOLEAN DEFAULT false,
    related_event_ids VARCHAR,
    archived          BOOLEAN DEFAULT false,
    archived_at       TIMESTAMP,
    review_daily      VARCHAR,
    review_weekly     VARCHAR,
    review_monthly    VARCHAR
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_radar_event_cluster ON radar_event(cluster_key);
CREATE INDEX IF NOT EXISTS idx_radar_event_status ON radar_event(verify_status, last_update_at);
CREATE INDEX IF NOT EXISTS idx_radar_event_type ON radar_event(event_type, first_seen_at);
-- idx_radar_event_archived is created in initialize_schema() AFTER the
-- idempotent column migration (old warehouses lack ``archived``).

CREATE TABLE IF NOT EXISTS radar_evidence (
    id                VARCHAR PRIMARY KEY,
    event_id          VARCHAR NOT NULL,
    url               VARCHAR NOT NULL,
    source_name       VARCHAR,
    source_tier       INTEGER,
    title             VARCHAR,
    snippet           VARCHAR,
    published_at      TIMESTAMP,
    fetched_at        TIMESTAMP NOT NULL,
    is_independent    BOOLEAN DEFAULT true,
    fetch_scan_id     VARCHAR
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_radar_evidence_url ON radar_evidence(url);
CREATE INDEX IF NOT EXISTS idx_radar_evidence_event ON radar_evidence(event_id, source_tier);

CREATE TABLE IF NOT EXISTS radar_event_timeline (
    id                VARCHAR PRIMARY KEY,
    event_id          VARCHAR NOT NULL,
    change_type       VARCHAR NOT NULL,
    from_value        VARCHAR,
    to_value          VARCHAR,
    actor             VARCHAR,
    note              VARCHAR,
    created_at        TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_radar_timeline_event ON radar_event_timeline(event_id, created_at);

-- v1.2: daily Top-5 snapshots (the archive's on-leaderboard-day ledger)
CREATE TABLE IF NOT EXISTS radar_daily_pick (
    id                VARCHAR PRIMARY KEY,
    pick_date         DATE NOT NULL,
    rank_position     INTEGER NOT NULL,
    event_id          VARCHAR,
    title_snapshot    VARCHAR NOT NULL,
    source_channels   VARCHAR,
    scan_id           VARCHAR,
    created_at        TIMESTAMP NOT NULL,
    UNIQUE(pick_date, rank_position)
);
CREATE INDEX IF NOT EXISTS idx_daily_pick_event ON radar_daily_pick(event_id, pick_date);
CREATE INDEX IF NOT EXISTS idx_daily_pick_date ON radar_daily_pick(pick_date);

CREATE TABLE IF NOT EXISTS event_report (
    id                VARCHAR PRIMARY KEY,
    event_id          VARCHAR,
    run_id            VARCHAR NOT NULL,
    mode              VARCHAR NOT NULL,
    title             VARCHAR NOT NULL,
    market            VARCHAR,
    time_horizon      VARCHAR,
    status            VARCHAR NOT NULL,
    markdown          VARCHAR,
    sections_present  VARCHAR,
    data_sources      VARCHAR,
    expected_outcome  VARCHAR,
    guidance          VARCHAR,
    eval_rating       VARCHAR,
    eval_note         VARCHAR,
    eval_period_start DATE,
    eval_period_end   DATE,
    eval_related_report_id VARCHAR,
    evaluated_at      TIMESTAMP,
    created_at        TIMESTAMP NOT NULL,
    completed_at      TIMESTAMP,
    canceled_at       TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_event_report_event ON event_report(event_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_event_report_run ON event_report(run_id);

-- One-row-per-key migration ledger.
CREATE TABLE IF NOT EXISTS radar_schema_meta (
    key               VARCHAR PRIMARY KEY,
    value             VARCHAR
);
"""

#: Columns added after v1.0; applied idempotently to pre-v1.2 warehouses.
_EVENT_MIGRATION_COLUMNS = (
    ("archived", "BOOLEAN DEFAULT false"),
    ("archived_at", "TIMESTAMP"),
    ("review_daily", "VARCHAR"),
    ("review_weekly", "VARCHAR"),
    ("review_monthly", "VARCHAR"),
)
_REPORT_MIGRATION_COLUMNS = (
    ("expected_outcome", "VARCHAR"),
    ("guidance", "VARCHAR"),
    ("eval_rating", "VARCHAR"),
    ("eval_note", "VARCHAR"),
    ("eval_period_start", "DATE"),
    ("eval_period_end", "DATE"),
    ("eval_related_report_id", "VARCHAR"),
    ("evaluated_at", "TIMESTAMP"),
    ("canceled_at", "TIMESTAMP"),
)


class EventDBError(RuntimeError):
    """A DuckDB persistence failure surfaced to the service layer."""


def event_connection(
    db_path: str | os.PathLike[str] | None = None,
) -> duckdb.DuckDBPyConnection:
    """Open a short read-write connection, creating the parent directory."""
    path = str(db_path) if db_path is not None else str(get_market_db_path())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return duckdb.connect(path)


def _existing_columns(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        [table],
    ).fetchall()
    return {r[0] for r in rows}


def _migrate_columns(
    conn: duckdb.DuckDBPyConnection, table: str,
    columns: tuple[tuple[str, str], ...],
) -> None:
    existing = _existing_columns(conn, table)
    for name, ddl_type in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}")


def _meta_get(conn: duckdb.DuckDBPyConnection, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM radar_schema_meta WHERE key = ?", [key]
    ).fetchone()
    return row[0] if row else None


def _meta_set(conn: duckdb.DuckDBPyConnection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO radar_schema_meta (key, value) VALUES (?, ?)",
        [key, value],
    )


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Idempotently create/migrate radar tables/indexes."""
    ddl_text = "\n".join(
        line for line in _DDL.splitlines() if not line.strip().startswith("--")
    )
    for statement in ddl_text.strip().split(";"):
        ddl = statement.strip()
        if ddl:
            conn.execute(ddl)
    _migrate_columns(conn, "radar_event", _EVENT_MIGRATION_COLUMNS)
    _migrate_columns(conn, "event_report", _REPORT_MIGRATION_COLUMNS)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_radar_event_archived "
        "ON radar_event(archived, verify_status, last_update_at)"
    )
    # One-time v1.2 cleanup: pre-archive radar events are transient data.
    if _meta_get(conn, "v12_migrated") is None:
        conn.execute(
            "DELETE FROM radar_evidence WHERE event_id IN "
            "(SELECT event_id FROM radar_event WHERE COALESCE(archived, false) = false)"
        )
        conn.execute(
            "DELETE FROM radar_event_timeline WHERE event_id IN "
            "(SELECT event_id FROM radar_event WHERE COALESCE(archived, false) = false)"
        )
        conn.execute(
            "UPDATE radar_daily_pick SET event_id = NULL WHERE event_id IN "
            "(SELECT event_id FROM radar_event WHERE COALESCE(archived, false) = false)"
        )
        conn.execute("DELETE FROM radar_event WHERE COALESCE(archived, false) = false")
        _meta_set(conn, "v12_migrated", _now().isoformat())


def _now() -> datetime:
    return datetime.now()


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _loads(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Scan runs
# ---------------------------------------------------------------------------

def insert_scan_run(conn: duckdb.DuckDBPyConnection, *, scan_id: str, scope: str,
                    trigger_type: str) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO radar_scan_run (id, scope, trigger_type, status, started_at) "
        "VALUES (?, ?, ?, 'running', ?)",
        [scan_id, scope, trigger_type, now],
    )
    return {"id": scan_id, "scope": scope, "trigger_type": trigger_type,
            "status": "running", "started_at": now.isoformat()}


def update_scan_run(conn: duckdb.DuckDBPyConnection, scan_id: str, **fields: Any) -> None:
    if not fields:
        return
    columns = {
        "status", "source_status", "candidates", "duplicates", "new_events",
        "escalated", "to_review", "error",
    }
    sets: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in columns:
            continue
        sets.append(f"{key} = ?")
        values.append(_dumps(value) if key == "source_status" else value)
    sets.append("finished_at = ?")
    values.append(_now())
    values.append(scan_id)
    conn.execute(
        f"UPDATE radar_scan_run SET {', '.join(sets)} WHERE id = ?", values
    )


def _scan_run_row(row: Sequence[Any]) -> dict[str, Any]:
    return {
        "id": row[0], "scope": row[1], "trigger_type": row[2], "status": row[3],
        "source_status": _loads(row[4]), "candidates": row[5], "duplicates": row[6],
        "new_events": row[7], "escalated": row[8], "to_review": row[9],
        "error": row[10],
        "started_at": row[11].isoformat() if row[11] else None,
        "finished_at": row[12].isoformat() if row[12] else None,
    }


def get_scan_run(conn: duckdb.DuckDBPyConnection, scan_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, scope, trigger_type, status, source_status, candidates, "
        "duplicates, new_events, escalated, to_review, error, started_at, finished_at "
        "FROM radar_scan_run WHERE id = ?", [scan_id]
    ).fetchone()
    return _scan_run_row(row) if row else None


def get_running_scan(conn: duckdb.DuckDBPyConnection, scope: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, scope, trigger_type, status, source_status, candidates, "
        "duplicates, new_events, escalated, to_review, error, started_at, finished_at "
        "FROM radar_scan_run WHERE status = 'running' AND scope = ? "
        "ORDER BY started_at DESC LIMIT 1", [scope]
    ).fetchone()
    return _scan_run_row(row) if row else None


def list_scan_runs(conn: duckdb.DuckDBPyConnection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, scope, trigger_type, status, source_status, candidates, "
        "duplicates, new_events, escalated, to_review, error, started_at, finished_at "
        "FROM radar_scan_run ORDER BY started_at DESC LIMIT ?", [limit]
    ).fetchall()
    return [_scan_run_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

_EVENT_COLUMNS = (
    "event_id, title, event_type, entities, regions, summary, impact_direction, "
    "affected_assets, cluster_key, simhash, novelty_class, paradigm_scores, "
    "paradigm_total, long_term_themes, impact_level, verify_status, confidence, "
    "source_count, first_seen_at, last_update_at, locked_by_human, related_event_ids, "
    "archived, archived_at, review_daily, review_weekly, review_monthly"
)


def _event_row(row: Sequence[Any]) -> dict[str, Any]:
    return {
        "event_id": row[0], "title": row[1], "event_type": row[2],
        "entities": _loads(row[3]), "regions": _loads(row[4]), "summary": row[5],
        "impact_direction": row[6], "affected_assets": _loads(row[7]),
        "cluster_key": row[8], "simhash": row[9], "novelty_class": row[10],
        "paradigm_scores": _loads(row[11]), "paradigm_total": row[12],
        "long_term_themes": _loads(row[13]), "impact_level": row[14],
        "verify_status": row[15], "confidence": row[16], "source_count": row[17],
        "first_seen_at": row[18].isoformat() if row[18] else None,
        "last_update_at": row[19].isoformat() if row[19] else None,
        "locked_by_human": bool(row[20]), "related_event_ids": _loads(row[21]),
        "archived": bool(row[22]),
        "archived_at": row[23].isoformat() if row[23] else None,
        "review_daily": _loads(row[24]), "review_weekly": _loads(row[25]),
        "review_monthly": _loads(row[26]),
    }


def insert_event(conn: duckdb.DuckDBPyConnection, event: dict[str, Any]) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO radar_event (event_id, title, event_type, entities, regions, "
        "summary, impact_direction, affected_assets, cluster_key, simhash, "
        "novelty_class, paradigm_scores, paradigm_total, long_term_themes, "
        "impact_level, verify_status, confidence, source_count, first_seen_at, "
        "last_update_at, locked_by_human, related_event_ids) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, false, ?)",
        [
            event["event_id"], event["title"], event["event_type"],
            _dumps(event.get("entities")), _dumps(event.get("regions")),
            event.get("summary"), event.get("impact_direction"),
            _dumps(event.get("affected_assets")), event["cluster_key"],
            event.get("simhash"), event["novelty_class"],
            _dumps(event.get("paradigm_scores")), event.get("paradigm_total"),
            _dumps(event.get("long_term_themes")), event.get("impact_level"),
            event["verify_status"], event.get("confidence"),
            event.get("source_count", 0),
            event.get("first_seen_at") or now,
            event.get("last_update_at") or now,
            _dumps(event.get("related_event_ids")),
        ],
    )


def update_event_fields(
    conn: duckdb.DuckDBPyConnection, event_id: str, fields: dict[str, Any]
) -> None:
    """Update a whitelisted subset of event columns; always bumps last_update_at."""
    allowed = {
        "title", "summary", "impact_direction", "affected_assets", "simhash",
        "novelty_class", "paradigm_scores", "paradigm_total", "long_term_themes",
        "impact_level", "verify_status", "confidence", "source_count",
        "locked_by_human", "related_event_ids", "entities", "regions",
        "archived", "archived_at",
        "review_daily", "review_weekly", "review_monthly",
    }
    json_columns = {
        "affected_assets", "paradigm_scores", "long_term_themes",
        "related_event_ids", "entities", "regions",
        "review_daily", "review_weekly", "review_monthly",
    }
    #: Review/archive bookkeeping must not bump last_update_at (it drives the
    #: Task Force 7-day freshness window, which is about the news, not checks).
    no_bump = {"archived", "archived_at",
               "review_daily", "review_weekly", "review_monthly"}
    sets: list[str] = []
    values: list[Any] = []
    bumps_activity = False
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = ?")
        values.append(_dumps(value) if key in json_columns else value)
        if key not in no_bump:
            bumps_activity = True
    if not sets:
        return
    if bumps_activity:
        sets.append("last_update_at = ?")
        values.append(_now())
    values.append(event_id)
    conn.execute(
        f"UPDATE radar_event SET {', '.join(sets)} WHERE event_id = ?", values
    )


def get_event(conn: duckdb.DuckDBPyConnection, event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_EVENT_COLUMNS} FROM radar_event WHERE event_id = ?", [event_id]
    ).fetchone()
    return _event_row(row) if row else None


def get_event_by_cluster_key(
    conn: duckdb.DuckDBPyConnection, cluster_key: str
) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_EVENT_COLUMNS} FROM radar_event WHERE cluster_key = ?",
        [cluster_key],
    ).fetchone()
    return _event_row(row) if row else None


def get_event_by_title(
    conn: duckdb.DuckDBPyConnection, title: str
) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_EVENT_COLUMNS} FROM radar_event WHERE title = ?", [title]
    ).fetchone()
    return _event_row(row) if row else None


def list_events(
    conn: duckdb.DuckDBPyConnection,
    *,
    status: str | None = None,
    novelty: str | None = None,
    event_type: str | None = None,
    region: str | None = None,
    keyword: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    where: list[str] = []
    values: list[Any] = []
    if status and status != "all":
        where.append("verify_status = ?")
        values.append(status)
    if novelty and novelty != "all":
        where.append("novelty_class = ?")
        values.append(novelty)
    if event_type and event_type != "all":
        where.append("event_type = ?")
        values.append(event_type)
    if region:
        where.append("regions LIKE ?")
        values.append(f"%{region}%")
    if keyword:
        where.append("(title LIKE ? OR summary LIKE ?)")
        values.extend([f"%{keyword}%", f"%{keyword}%"])
    sql = f"SELECT {_EVENT_COLUMNS} FROM radar_event"
    if where:
        sql += " WHERE " + " AND ".join(where)
    # Importance order: verification verdict, then novelty (new paradigms
    # are the major opportunities), then confidence/source weight/recency.
    # This ranking feeds the radar's Top-5 default view.
    sql += (
        " ORDER BY CASE verify_status "
        "WHEN 'confirmed' THEN 0 WHEN 'verifying' THEN 1 "
        "WHEN 'disputed' THEN 2 WHEN 'unverified' THEN 3 "
        "WHEN 'rumor' THEN 4 ELSE 5 END, "
        "CASE novelty_class WHEN 'new_paradigm' THEN 0 "
        "WHEN 'known_escalation' THEN 1 ELSE 2 END, "
        "confidence DESC, source_count DESC, last_update_at DESC LIMIT ?"
    )
    values.append(limit)
    rows = conn.execute(sql, values).fetchall()
    return [_event_row(r) for r in rows]


def recent_events_for_lookup(
    conn: duckdb.DuckDBPyConnection, *, days: int = 14, limit: int = 500
) -> list[dict[str, Any]]:
    """Recent events for dedup lookups (cluster keys, entities, titles)."""
    rows = conn.execute(
        f"SELECT {_EVENT_COLUMNS} FROM radar_event "
        "WHERE first_seen_at >= current_timestamp - INTERVAL '"
        f"{int(days)} day' ORDER BY first_seen_at DESC LIMIT ?",
        [limit],
    ).fetchall()
    return [_event_row(r) for r in rows]


def search_events(
    conn: duckdb.DuckDBPyConnection,
    *,
    keyword: str = "",
    event_type: str | None = None,
    window_hours: int = 168,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Lookup used by the ``event_lookup`` LLM tool (read-only)."""
    where = ["first_seen_at >= current_timestamp - INTERVAL ?"]
    values: list[Any] = [f"{int(window_hours)} hours"]
    if keyword:
        where.append("(title LIKE ? OR summary LIKE ? OR entities LIKE ?)")
        like = f"%{keyword}%"
        values.extend([like, like, like])
    if event_type:
        where.append("event_type = ?")
        values.append(event_type)
    sql = f"SELECT {_EVENT_COLUMNS} FROM radar_event WHERE " + " AND ".join(where)
    sql += " ORDER BY last_update_at DESC LIMIT ?"
    values.append(limit)
    rows = conn.execute(sql, values).fetchall()
    return [_event_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Evidence + timeline
# ---------------------------------------------------------------------------

def evidence_url_exists(conn: duckdb.DuckDBPyConnection, url: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM radar_evidence WHERE url = ? LIMIT 1", [url]
    ).fetchone()
    return row is not None


def insert_evidence(
    conn: duckdb.DuckDBPyConnection,
    *,
    event_id: str,
    url: str,
    source_name: str | None,
    source_tier: int | None,
    title: str | None,
    snippet: str | None,
    published_at: datetime | None,
    is_independent: bool = True,
    scan_id: str | None = None,
) -> str:
    evidence_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO radar_evidence (id, event_id, url, source_name, source_tier, "
        "title, snippet, published_at, fetched_at, is_independent, fetch_scan_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [evidence_id, event_id, url, source_name, source_tier, title, snippet,
         published_at, _now(), is_independent, scan_id],
    )
    return evidence_id


def list_evidence(
    conn: duckdb.DuckDBPyConnection, event_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, url, source_name, source_tier, title, snippet, published_at, "
        "fetched_at, is_independent FROM radar_evidence WHERE event_id = ? "
        "ORDER BY source_tier ASC, fetched_at ASC", [event_id]
    ).fetchall()
    return [
        {
            "id": r[0], "url": r[1], "source_name": r[2], "source_tier": r[3],
            "title": r[4], "snippet": r[5],
            "published_at": r[6].isoformat() if r[6] else None,
            "fetched_at": r[7].isoformat() if r[7] else None,
            "is_independent": bool(r[8]),
        }
        for r in rows
    ]


def add_timeline(
    conn: duckdb.DuckDBPyConnection,
    *,
    event_id: str,
    change_type: str,
    from_value: str | None = None,
    to_value: str | None = None,
    actor: str = "system",
    note: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO radar_event_timeline (id, event_id, change_type, from_value, "
        "to_value, actor, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [str(uuid.uuid4()), event_id, change_type, from_value, to_value, actor,
         note, _now()],
    )


def list_timeline(conn: duckdb.DuckDBPyConnection, event_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT change_type, from_value, to_value, actor, note, created_at "
        "FROM radar_event_timeline WHERE event_id = ? ORDER BY created_at ASC",
        [event_id],
    ).fetchall()
    return [
        {"change_type": r[0], "from": r[1], "to": r[2], "actor": r[3],
         "note": r[4], "created_at": r[5].isoformat() if r[5] else None}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def insert_report(conn: duckdb.DuckDBPyConnection, report: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO event_report (id, event_id, run_id, mode, title, market, "
        "time_horizon, status, markdown, sections_present, data_sources, "
        "expected_outcome, guidance, eval_rating, eval_note, eval_period_start, "
        "eval_period_end, eval_related_report_id, evaluated_at, "
        "created_at, completed_at, canceled_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            report["id"], report.get("event_id"), report["run_id"], report["mode"],
            report["title"], report.get("market"), report.get("time_horizon"),
            report["status"], report.get("markdown"),
            _dumps(report.get("sections_present")),
            _dumps(report.get("data_sources")),
            report.get("expected_outcome"), report.get("guidance"),
            report.get("eval_rating"), report.get("eval_note"),
            report.get("eval_period_start"), report.get("eval_period_end"),
            report.get("eval_related_report_id"), report.get("evaluated_at"),
            report.get("created_at") or _now(), report.get("completed_at"),
            report.get("canceled_at"),
        ],
    )


def update_report_fields(
    conn: duckdb.DuckDBPyConnection, report_id: str, fields: dict[str, Any]
) -> None:
    allowed = {
        "status", "markdown", "sections_present", "data_sources", "completed_at",
        "expected_outcome", "guidance", "eval_rating", "eval_note",
        "eval_period_start", "eval_period_end", "eval_related_report_id",
        "evaluated_at", "canceled_at", "event_id", "title",
    }
    json_columns = {"sections_present", "data_sources"}
    sets: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = ?")
        values.append(_dumps(value) if key in json_columns else value)
    if not sets:
        return
    values.append(report_id)
    conn.execute(f"UPDATE event_report SET {', '.join(sets)} WHERE id = ?", values)


def _report_row(row: Sequence[Any]) -> dict[str, Any]:
    return {
        "id": row[0], "event_id": row[1], "run_id": row[2], "mode": row[3],
        "title": row[4], "market": row[5], "time_horizon": row[6], "status": row[7],
        "markdown": row[8], "sections_present": _loads(row[9]),
        "data_sources": _loads(row[10]),
        "expected_outcome": row[11], "guidance": row[12],
        "eval_rating": row[13], "eval_note": row[14],
        "eval_period_start": str(row[15]) if row[15] else None,
        "eval_period_end": str(row[16]) if row[16] else None,
        "eval_related_report_id": row[17],
        "evaluated_at": row[18].isoformat() if row[18] else None,
        "created_at": row[19].isoformat() if row[19] else None,
        "completed_at": row[20].isoformat() if row[20] else None,
        "canceled_at": row[21].isoformat() if row[21] else None,
    }


_REPORT_COLUMNS = (
    "id, event_id, run_id, mode, title, market, time_horizon, status, markdown, "
    "sections_present, data_sources, expected_outcome, guidance, eval_rating, "
    "eval_note, eval_period_start, eval_period_end, eval_related_report_id, "
    "evaluated_at, created_at, completed_at, canceled_at"
)


def get_report(conn: duckdb.DuckDBPyConnection, report_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_REPORT_COLUMNS} FROM event_report WHERE id = ?", [report_id]
    ).fetchone()
    return _report_row(row) if row else None


def get_report_by_run(conn: duckdb.DuckDBPyConnection, run_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_REPORT_COLUMNS} FROM event_report WHERE run_id = ?", [run_id]
    ).fetchone()
    return _report_row(row) if row else None


def list_reports(
    conn: duckdb.DuckDBPyConnection, *, mode: str | None = None,
    status: str | None = None, event_id: str | None = None, limit: int = 100,
) -> list[dict[str, Any]]:
    where: list[str] = []
    values: list[Any] = []
    if mode and mode != "all":
        where.append("mode = ?")
        values.append(mode)
    if status and status != "all":
        where.append("status = ?")
        values.append(status)
    if event_id:
        where.append("event_id = ?")
        values.append(event_id)
    sql = f"SELECT {_REPORT_COLUMNS} FROM event_report"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    values.append(limit)
    rows = conn.execute(sql, values).fetchall()
    return [_report_row(r) for r in rows]


def delete_report(conn: duckdb.DuckDBPyConnection, report_id: str) -> bool:
    cursor = conn.execute("DELETE FROM event_report WHERE id = ?", [report_id])
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Archive: keep/discard, transient purge, daily Top-N picks, leaderboard
# ---------------------------------------------------------------------------

def set_archived(
    conn: duckdb.DuckDBPyConnection, event_id: str, archived: bool
) -> None:
    update_event_fields(conn, event_id, {
        "archived": archived,
        "archived_at": _now() if archived else None,
    })


def delete_event_cascade(conn: duckdb.DuckDBPyConnection, event_id: str) -> None:
    """Physical discard: event + evidence + timeline gone; keep pick history
    (event_id nulled) and detach reports rather than deleting them."""
    conn.execute("DELETE FROM radar_evidence WHERE event_id = ?", [event_id])
    conn.execute("DELETE FROM radar_event_timeline WHERE event_id = ?", [event_id])
    conn.execute(
        "UPDATE radar_daily_pick SET event_id = NULL WHERE event_id = ?", [event_id]
    )
    conn.execute(
        "UPDATE event_report SET event_id = NULL WHERE event_id = ?", [event_id]
    )
    conn.execute("DELETE FROM radar_event WHERE event_id = ?", [event_id])


def purge_transient(
    conn: duckdb.DuckDBPyConnection, keep_event_ids: Sequence[str]
) -> int:
    """Delete non-archived events outside today's Top-N. Returns rows removed."""
    rows = conn.execute(
        "SELECT event_id FROM radar_event WHERE COALESCE(archived, false) = false"
    ).fetchall()
    keep = set(keep_event_ids)
    removed = 0
    for (event_id,) in rows:
        if event_id in keep:
            continue
        conn.execute("DELETE FROM radar_evidence WHERE event_id = ?", [event_id])
        conn.execute("DELETE FROM radar_event_timeline WHERE event_id = ?", [event_id])
        conn.execute("DELETE FROM radar_event WHERE event_id = ?", [event_id])
        removed += 1
    return removed


def list_events_by_ids(
    conn: duckdb.DuckDBPyConnection, event_ids: Sequence[str]
) -> list[dict[str, Any]]:
    if not event_ids:
        return []
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"SELECT {_EVENT_COLUMNS} FROM radar_event WHERE event_id IN ({placeholders})",
        list(event_ids),
    ).fetchall()
    return [_event_row(r) for r in rows]


def list_tf_candidates(
    conn: duckdb.DuckDBPyConnection, *, days: int = 7, limit: int = 50
) -> list[dict[str, Any]]:
    """Confirmed events fresh enough to start analysis from the Task Force tab."""
    rows = conn.execute(
        f"SELECT {_EVENT_COLUMNS} FROM radar_event "
        "WHERE verify_status = 'confirmed' AND last_update_at >= "
        f"current_timestamp - INTERVAL '{int(days)} days' "
        "ORDER BY last_update_at DESC LIMIT ?",
        [limit],
    ).fetchall()
    return [_event_row(r) for r in rows]


def upsert_daily_pick(
    conn: duckdb.DuckDBPyConnection,
    *,
    pick_date: Any,
    rank_position: int,
    event_id: str | None,
    title_snapshot: str,
    source_channels: Sequence[str],
    scan_id: str | None,
) -> None:
    conn.execute(
        "INSERT INTO radar_daily_pick (id, pick_date, rank_position, event_id, "
        "title_snapshot, source_channels, scan_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (pick_date, rank_position) DO UPDATE SET "
        "event_id = excluded.event_id, title_snapshot = excluded.title_snapshot, "
        "source_channels = excluded.source_channels, scan_id = excluded.scan_id",
        [str(uuid.uuid4()), pick_date, rank_position, event_id, title_snapshot,
         _dumps(list(source_channels)), scan_id, _now()],
    )


def _pick_row(row: Sequence[Any]) -> dict[str, Any]:
    return {
        "id": row[0],
        "pick_date": str(row[1]),
        "rank_position": row[2],
        "event_id": row[3],
        "title_snapshot": row[4],
        "source_channels": _loads(row[5]),
        "scan_id": row[6],
        "created_at": row[7].isoformat() if row[7] else None,
    }


_PICK_COLUMNS = (
    "id, pick_date, rank_position, event_id, title_snapshot, "
    "source_channels, scan_id, created_at"
)


def list_daily_picks(
    conn: duckdb.DuckDBPyConnection,
    *,
    date_from: Any = None,
    date_to: Any = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    where: list[str] = []
    values: list[Any] = []
    if date_from:
        where.append("pick_date >= ?")
        values.append(date_from)
    if date_to:
        where.append("pick_date <= ?")
        values.append(date_to)
    sql = f"SELECT {_PICK_COLUMNS} FROM radar_daily_pick"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY pick_date DESC, rank_position ASC LIMIT ?"
    values.append(limit)
    return [_pick_row(r) for r in conn.execute(sql, values).fetchall()]


def pick_stats_for_event(
    conn: duckdb.DuckDBPyConnection, event_id: str, window_days: int = 30
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT MIN(pick_date), MAX(pick_date), COUNT(DISTINCT pick_date) "
        "FROM radar_daily_pick WHERE event_id = ? AND pick_date >= "
        f"current_date - INTERVAL '{int(window_days)} days'",
        [event_id],
    ).fetchone()
    return {
        "first_pick_date": str(row[0]) if row and row[0] else None,
        "last_pick_date": str(row[1]) if row and row[1] else None,
        "pick_days": int(row[2]) if row and row[2] is not None else 0,
    }


def list_archive(
    conn: duckdb.DuckDBPyConnection,
    *,
    status: str | None = None,
    novelty: str | None = None,
    event_type: str | None = None,
    keyword: str | None = None,
    date_from: Any = None,
    date_to: Any = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Archived events enriched with pick-day stats and report counts."""
    where = ["COALESCE(e.archived, false) = true"]
    values: list[Any] = []
    if status and status != "all":
        where.append("e.verify_status = ?")
        values.append(status)
    if novelty and novelty != "all":
        where.append("e.novelty_class = ?")
        values.append(novelty)
    if event_type and event_type != "all":
        where.append("e.event_type = ?")
        values.append(event_type)
    if keyword:
        where.append("(e.title LIKE ? OR e.summary LIKE ?)")
        values.extend([f"%{keyword}%", f"%{keyword}%"])
    if date_from:
        where.append(
            "EXISTS (SELECT 1 FROM radar_daily_pick q WHERE q.event_id = e.event_id "
            "AND q.pick_date >= ?)"
        )
        values.append(date_from)
    if date_to:
        where.append(
            "EXISTS (SELECT 1 FROM radar_daily_pick q WHERE q.event_id = e.event_id "
            "AND q.pick_date <= ?)"
        )
        values.append(date_to)
    event_select = ", ".join(f"e.{c}" for c in _EVENT_COLUMNS.split(", "))
    sql = (
        f"SELECT {event_select}, s.first_pick, s.last_pick, s.pick_days, "
        "COALESCE(rc.report_count, 0) "
        "FROM radar_event e "
        "LEFT JOIN (SELECT event_id, MIN(pick_date) AS first_pick, "
        "MAX(pick_date) AS last_pick, COUNT(DISTINCT pick_date) AS pick_days "
        "FROM radar_daily_pick GROUP BY event_id) s ON s.event_id = e.event_id "
        "LEFT JOIN (SELECT event_id, COUNT(DISTINCT id) AS report_count "
        "FROM event_report GROUP BY event_id) rc ON rc.event_id = e.event_id "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY COALESCE(s.pick_days, 0) DESC, e.last_update_at DESC LIMIT ?"
    )
    values.append(limit)
    rows = conn.execute(sql, values).fetchall()
    n = len(_EVENT_COLUMNS.split(", "))
    out: list[dict[str, Any]] = []
    for row in rows:
        event = _event_row(row[:n])
        event["first_pick_date"] = str(row[n]) if row[n] else None
        event["last_pick_date"] = str(row[n + 1]) if row[n + 1] else None
        event["pick_days"] = int(row[n + 2] or 0)
        event["report_count"] = int(row[n + 3] or 0)
        out.append(event)
    return out


def pick_leaderboard(
    conn: duckdb.DuckDBPyConnection, *, window_days: int = 30, limit: int = 10
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT p.event_id, MAX(p.title_snapshot), COUNT(DISTINCT p.pick_date) AS d, "
        "MIN(p.pick_date), MAX(p.pick_date) "
        "FROM radar_daily_pick p "
        f"WHERE p.pick_date >= current_date - INTERVAL '{int(window_days)} days' "
        "AND p.event_id IS NOT NULL "
        "GROUP BY p.event_id ORDER BY d DESC, MAX(p.pick_date) DESC LIMIT ?",
        [limit],
    ).fetchall()
    return [
        {
            "event_id": r[0],
            "title": r[1],
            "pick_days": int(r[2]),
            "first_pick_date": str(r[3]),
            "last_pick_date": str(r[4]),
        }
        for r in rows
    ]
