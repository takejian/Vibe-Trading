"""Unit tests for the watchlist DuckDB persistence layer (tmp databases)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from src.watchlist import db
from src.watchlist.models import CompanyProfile, QuoteSnapshot


@pytest.fixture()
def conn(tmp_path: Path):
    connection = db.watchlist_connection(tmp_path / "sub" / "market.duckdb")
    yield connection
    connection.close()


def _create_legacy_tables(connection) -> None:
    connection.execute(
        """
        CREATE TABLE instrument_master (
            symbol VARCHAR PRIMARY KEY, name VARCHAR, name_en VARCHAR,
            market VARCHAR, currency VARCHAR, exchange VARCHAR,
            list_date DATE, delist_date DATE, lot_size BIGINT,
            sector VARCHAR, industry VARCHAR, is_active BOOLEAN DEFAULT true,
            source VARCHAR, updated_at TIMESTAMP DEFAULT current_timestamp)
        """
    )
    connection.execute(
        """
        CREATE TABLE daily_bar (
            symbol VARCHAR, trade_date DATE, open DOUBLE, high DOUBLE,
            low DOUBLE, close DOUBLE, volume DOUBLE, amount DOUBLE,
            volume_unit VARCHAR, price_caliber VARCHAR DEFAULT 'raw',
            source VARCHAR, updated_at TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (symbol, trade_date))
        """
    )
    connection.execute(
        """
        CREATE TABLE valuation_daily (
            symbol VARCHAR, trade_date DATE, pe_ttm DOUBLE, pb DOUBLE,
            total_market_cap DOUBLE, currency VARCHAR, note VARCHAR,
            source VARCHAR, updated_at TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (symbol, trade_date, source))
        """
    )
    connection.execute(
        """
        CREATE TABLE financial_statement (
            symbol VARCHAR, report_date DATE, ann_date DATE, statement VARCHAR,
            field VARCHAR, value DOUBLE, currency VARCHAR, period_type VARCHAR,
            source VARCHAR, updated_at TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (symbol, report_date, statement, field))
        """
    )


# ----------------------------------------------------------------------
def test_initialize_schema_is_idempotent(conn) -> None:
    db.initialize_schema(conn)
    db.initialize_schema(conn)  # second run must not error
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    assert {"watchlist_objective_data", "chanlun_analysis"} <= tables


def test_parent_dir_created(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "market.duckdb"
    connection = db.watchlist_connection(target)
    try:
        db.initialize_schema(connection)
        assert target.exists()
    finally:
        connection.close()


def test_list_raw_data_tolerates_missing_legacy_tables(conn) -> None:
    db.initialize_schema(conn)
    data = db.list_raw_data("600519.SH", conn)
    assert data == {"instrument": [], "daily_bar": [], "valuation": [], "financial": []}


def test_instrument_upsert_merge_preserves_known_fields(conn) -> None:
    _create_legacy_tables(conn)
    db.upsert_instrument(
        {"symbol": "600519.SH", "name": "贵州茅台", "industry": "白酒",
         "exchange": "SSE", "list_date": "2001-08-27"},
        conn,
    )
    # Sparse refresh (industry null, new name) must not null the industry.
    db.upsert_instrument(
        {"symbol": "600519.SH", "name": "贵州茅台股份", "industry": None},
        conn,
    )
    rows = conn.execute(
        "SELECT name, industry, market, currency FROM instrument_master WHERE symbol='600519.SH'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0] == ("贵州茅台股份", "白酒", "a_share", "CNY")


def test_profile_upsert_maps_exchange(conn) -> None:
    _create_legacy_tables(conn)
    db.apply_profile_to_instrument(
        CompanyProfile(
            symbol="430047.BJ",
            name="诺思兰德",
            industry="生物制药",
            list_date="2020-12-11",
        ),
        conn,
    )
    row = conn.execute(
        "SELECT exchange, list_date, source FROM instrument_master WHERE symbol='430047.BJ'"
    ).fetchone()
    assert row == ("BSE", datetime(2020, 12, 11).date(), "eastmoney")


def test_valuation_upsert_idempotent_and_coalesced(conn) -> None:
    _create_legacy_tables(conn)
    common = dict(symbol="600519.SH", trade_date="2026-09-30")
    db.upsert_valuation(**common, pe=25.0, pb=8.0, total_market_cap=1.8e12, conn=conn)
    db.upsert_valuation(**common, pe=26.0, pb=None, total_market_cap=None, conn=conn)
    rows = conn.execute(
        "SELECT pe_ttm, pb, total_market_cap FROM valuation_daily "
        "WHERE symbol='600519.SH'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0] == (26.0, 8.0, 1.8e12)  # new pe wins; nulls keep old


def test_persist_quote_snapshot_writes_valuation_and_industry(conn) -> None:
    _create_legacy_tables(conn)
    db.upsert_instrument({"symbol": "600519.SH", "name": "贵州茅台"}, conn)
    db.persist_quote_snapshot(
        "600519.SH",
        QuoteSnapshot(price=1500.0, pe=25.6, pb=8.1,
                      total_market_cap=1.88e12, industry="白酒"),
        "2026-09-30",
        conn,
    )
    val = conn.execute(
        "SELECT pe_ttm, pb, total_market_cap, source FROM valuation_daily"
    ).fetchone()
    assert val == (25.6, 8.1, 1.88e12, "eastmoney")
    ind = conn.execute(
        "SELECT industry FROM instrument_master WHERE symbol='600519.SH'"
    ).fetchone()
    assert ind == ("白酒",)


def test_list_raw_data_returns_rows_by_category(conn) -> None:
    _create_legacy_tables(conn)
    db.upsert_instrument({"symbol": "600519.SH", "name": "贵州茅台"}, conn)
    db.upsert_valuation(
        symbol="600519.SH", trade_date="2026-09-30",
        pe=25.0, pb=8.0, total_market_cap=1.8e12, conn=conn,
    )
    conn.execute(
        "INSERT INTO daily_bar VALUES ('600519.SH', '2026-09-29', 1,2,1,1.5,"
        " 100, 150, 'lots', 'raw', 'eastmoney', current_timestamp)"
    )
    conn.execute(
        "INSERT INTO financial_statement VALUES ('600519.SH', '2025-12-31',"
        " '2026-03-30', 'IS', 'revenue', 1.0, 'CNY', 'annual', 'akshare',"
        " current_timestamp)"
    )
    data = db.list_raw_data("600519.SH", conn)
    assert len(data["instrument"]) == 1
    assert len(data["valuation"]) == 1
    assert data["daily_bar"][0]["close"] == 1.5
    assert data["financial"][0]["field"] == "revenue"


# ----------------------------------------------------------------------
def test_objective_records_roundtrip(conn) -> None:
    db.initialize_schema(conn)
    rid = db.insert_objective_record(
        symbol="600519.SH",
        payload={"rows": [{"a": 1}]},  # non-string gets JSON-serialized
        source="equity_research_team:data_researcher",
        run_id="run-1",
        request_note="抓取近三年分红",
        created_at=datetime(2026, 6, 1),
        conn=conn,
    )
    assert rid
    assert db.objective_record_exists("run-1", conn) is True
    assert db.objective_record_exists("run-x", conn) is False

    db.insert_objective_record(
        symbol="600519.SH", payload="plain text", source="x",
        run_id="run-2", conn=conn,
        created_at=datetime(2026, 9, 1),
    )
    rows = db.list_objective_records("600519.SH", conn)
    assert [r["run_id"] for r in rows] == ["run-2", "run-1"]  # newest first
    assert rows[1]["category"] == "agent_fetch"
    assert rows[1]["request_note"] == "抓取近三年分红"


def test_chanlun_checks_and_query(conn) -> None:
    db.initialize_schema(conn)
    dims = {
        "structure_read": "s1", "active_pivots": "s2", "divergence": "s3",
        "buy_sell_points": "s4", "multi_level_plan": "s5",
        "elliott_corroboration": "s6", "chanlun_score": "s7",
    }
    db.insert_chanlun_record(
        run_id="r1", symbol="600519.SH", dims=dims,
        score=3, confidence=0.78, structured=True, raw_report="full",
        analyzed_at=datetime(2026, 9, 1, 10, 0), conn=conn,
    )
    # Boundary values are legal.
    db.insert_chanlun_record(
        run_id="r2", symbol="600519.SH", dims=dims,
        score=-5, confidence=0.0, structured=True, raw_report="low",
        analyzed_at=datetime(2026, 8, 1), conn=conn,
    )
    db.insert_chanlun_record(
        run_id="r3", symbol="600519.SH", dims={},
        score=None, confidence=None, structured=False, raw_report="raw text",
        analyzed_at=datetime(2026, 7, 1), conn=conn,
    )

    for bad_run, bad_score, bad_conf in [
        ("rx1", 6, 0.5), ("rx2", -6, 0.5), ("rx3", 3, 1.01), ("rx4", 3, -0.01)
    ]:
        with pytest.raises(duckdb.ConstraintException):
            db.insert_chanlun_record(
                run_id=bad_run, symbol="600519.SH", dims=dims,
                score=bad_score, confidence=bad_conf, structured=True,
                raw_report="x", conn=conn,
            )

    with pytest.raises(duckdb.ConstraintException):  # run_id UNIQUE
        db.insert_chanlun_record(
            run_id="r1", symbol="600519.SH", dims=dims, score=0,
            confidence=0.5, structured=True, raw_report="dup", conn=conn,
        )

    rows = db.list_chanlun_records("600519.SH", conn)
    assert [r["run_id"] for r in rows] == ["r1", "r2", "r3"]  # desc
    assert rows[0]["score"] == 3 and rows[0]["structured"] is True
    assert rows[2]["structured"] is False and rows[2]["raw_report"] == "raw text"

    august = db.list_chanlun_records(
        "600519.SH", conn, date_from="2026-08-01", date_to="2026-08-31"
    )
    assert [r["run_id"] for r in august] == ["r2"]

    limited = db.list_chanlun_records("600519.SH", conn, limit=1)
    assert len(limited) == 1
    assert db.chanlun_record_exists("r2", conn) is True
