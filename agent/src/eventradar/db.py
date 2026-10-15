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
    related_event_ids VARCHAR
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_radar_event_cluster ON radar_event(cluster_key);
CREATE INDEX IF NOT EXISTS idx_radar_event_status ON radar_event(verify_status, last_update_at);
CREATE INDEX IF NOT EXISTS idx_radar_event_type ON radar_event(event_type, first_seen_at);

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
    created_at        TIMESTAMP NOT NULL,
    completed_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_event_report_event ON event_report(event_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_event_report_run ON event_report(run_id);
"""


class EventDBError(RuntimeError):
    """A DuckDB persistence failure surfaced to the service layer."""


def event_connection(
    db_path: str | os.PathLike[str] | None = None,
) -> duckdb.DuckDBPyConnection:
    """Open a short read-write connection, creating the parent directory."""
    path = str(db_path) if db_path is not None else str(get_market_db_path())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return duckdb.connect(path)


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Idempotently create radar tables/indexes (safe to run repeatedly)."""
    ddl_text = "\n".join(
        line for line in _DDL.splitlines() if not line.strip().startswith("--")
    )
    for statement in ddl_text.strip().split(";"):
        ddl = statement.strip()
        if ddl:
            conn.execute(ddl)


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
    "source_count, first_seen_at, last_update_at, locked_by_human, related_event_ids"
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
    }
    json_columns = {
        "affected_assets", "paradigm_scores", "long_term_themes",
        "related_event_ids", "entities", "regions",
    }
    sets: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = ?")
        values.append(_dumps(value) if key in json_columns else value)
    if not sets:
        return
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
    # Paradigm events first, then impact level, then recency.
    sql += (
        " ORDER BY CASE WHEN novelty_class = 'new_paradigm' THEN 0 ELSE 1 END, "
        "last_update_at DESC LIMIT ?"
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
        "created_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            report["id"], report.get("event_id"), report["run_id"], report["mode"],
            report["title"], report.get("market"), report.get("time_horizon"),
            report["status"], report.get("markdown"),
            _dumps(report.get("sections_present")),
            _dumps(report.get("data_sources")),
            report.get("created_at") or _now(), report.get("completed_at"),
        ],
    )


def update_report_fields(
    conn: duckdb.DuckDBPyConnection, report_id: str, fields: dict[str, Any]
) -> None:
    allowed = {"status", "markdown", "sections_present", "data_sources", "completed_at"}
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
        "created_at": row[11].isoformat() if row[11] else None,
        "completed_at": row[12].isoformat() if row[12] else None,
    }


_REPORT_COLUMNS = (
    "id, event_id, run_id, mode, title, market, time_horizon, status, markdown, "
    "sections_present, data_sources, created_at, completed_at"
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
    status: str | None = None, limit: int = 100,
) -> list[dict[str, Any]]:
    where: list[str] = []
    values: list[Any] = []
    if mode and mode != "all":
        where.append("mode = ?")
        values.append(mode)
    if status and status != "all":
        where.append("status = ?")
        values.append(status)
    sql = f"SELECT {_REPORT_COLUMNS} FROM event_report"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    values.append(limit)
    rows = conn.execute(sql, values).fetchall()
    return [_report_row(r) for r in rows]
