"""Tests for the multi-level K-line Chanlun readiness feature (BDD US-08A/US-11).

Covers the pure readiness rules, DuckDB persistence, the direct (never-LLM)
fetch orchestration and the HTTP contract incl. the 412 advisory
pre-run prompt (skippable) and the archived-bars data brief.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import watchlist_routes
from src.watchlist import db as watch_db
from src.watchlist import kline
from src.watchlist import kline_sources
from src.watchlist.market import WatchlistDataError
from src.watchlist.store import WatchlistStore

CHANLUN_REF = "technical_analysis_panel:chanlun_analyst"
CLASSIC_TA_REF = "technical_analysis_panel:classic_ta_analyst"

ENTRIES = [
    {"ref": CHANLUN_REF, "name": "Chanlun (Chan Theory) Analyst",
     "purpose": "chan", "approved": True},
    {"ref": CLASSIC_TA_REF, "name": "Classic Technical Analyst",
     "purpose": "ta", "approved": True},
]

TODAY = date(2026, 10, 2)


# ----------------------------------------------------------------------
# Pure readiness rules
# ----------------------------------------------------------------------
def test_evaluate_level_state_machine():
    # never attempted
    assert (
        kline.evaluate_level(
            "1d", bars_count=0, latest_bar_time=None,
            ever_succeeded=False, last_error=None, threshold_date=TODAY,
        )
        == kline.NOT_FETCHED
    )
    # failed with no usable bars
    assert (
        kline.evaluate_level(
            "1d", bars_count=0, latest_bar_time=None,
            ever_succeeded=False, last_error="boom", threshold_date=TODAY,
        )
        == kline.FAILED
    )
    # enough bars but stale
    assert (
        kline.evaluate_level(
            "1d", bars_count=200, latest_bar_time="2026-09-01",
            ever_succeeded=True, last_error=None, threshold_date=date(2026, 9, 29),
        )
        == kline.INSUFFICIENT
    )
    # too few bars
    assert (
        kline.evaluate_level(
            "1w", bars_count=10, latest_bar_time="2026-10-01",
            ever_succeeded=True, last_error=None, threshold_date=date(2026, 9, 29),
        )
        == kline.INSUFFICIENT
    )
    # ready
    assert (
        kline.evaluate_level(
            "1y", bars_count=5, latest_bar_time="2026-09-30",
            ever_succeeded=True, last_error=None, threshold_date=date(2026, 9, 29),
        )
        == kline.READY
    )
    # threshold is inclusive (on the 2nd-to-last trading day)
    assert (
        kline.evaluate_level(
            "1d", bars_count=120, latest_bar_time="2026-09-29",
            ever_succeeded=True, last_error=None, threshold_date=date(2026, 9, 29),
        )
        == kline.READY
    )


def test_optional_30m_is_never_freshness_gated():
    # Few bars → still insufficient by its own minimum.
    assert (
        kline.evaluate_level(
            "30m", bars_count=10, latest_bar_time="2026-01-02 10:00:00",
            ever_succeeded=True, last_error=None, threshold_date=TODAY,
        )
        == kline.INSUFFICIENT
    )
    # Enough bars → ready regardless of staleness.
    assert (
        kline.evaluate_level(
            "30m", bars_count=24, latest_bar_time="2026-01-02 10:00:00",
            ever_succeeded=True, last_error=None, threshold_date=TODAY,
        )
        == kline.READY
    )


def test_minimum_bar_constants_match_business_rules():
    assert kline._MIN_BARS == {"1y": 5, "1q": 12, "1mo": 24, "1w": 60, "1d": 120}
    assert set(kline.REQUIRED_INTERVALS) == {"1d", "1w", "1mo", "1q", "1y"}
    assert kline.OPTIONAL_INTERVALS == ("30m",)


def test_normalize_intervals_defaults_and_validates():
    assert kline.normalize_intervals(None) == list(kline.REQUIRED_INTERVALS)
    assert kline.normalize_intervals(["30m", "30m", "1d"]) == ["30m", "1d"]
    with pytest.raises(ValueError):
        kline.normalize_intervals(["2m"])


# ----------------------------------------------------------------------
# Fetch orchestration
# ----------------------------------------------------------------------
def test_fetch_level_uses_secid_period_and_window():
    calls = []

    def fake_fetch(secid, klt, beg, end):
        calls.append((secid, klt, beg, end))
        return [{"trade_date": "2026-09-30", "open": 1, "high": 1,
                 "low": 1, "close": 1, "volume": 1, "amount": 1}]

    rows = kline.fetch_level(
        "600519", "1w", fetcher=fake_fetch, today=TODAY
    )
    assert len(rows) == 1
    secid, klt, beg, end = calls[0]
    assert secid == "1.600519"
    assert klt == 102
    assert end == "20500101"
    assert beg < "20260000"  # YYYYMMDD window start


def test_fetch_level_normalizes_empty_and_errors():
    with pytest.raises(WatchlistDataError):
        kline.fetch_level("600519.SH", "1d", fetcher=lambda *a: [], today=TODAY)

    def boom(*_a):
        raise ConnectionError("RemoteDisconnected")

    with pytest.raises(WatchlistDataError):
        kline.fetch_level("600519.SH", "1d", fetcher=boom, today=TODAY)


# ----------------------------------------------------------------------
# DuckDB persistence
# ----------------------------------------------------------------------
@pytest.fixture()
def conn():
    connection = duckdb.connect(":memory:")
    watch_db.initialize_schema(connection)
    yield connection
    connection.close()


def _bars(interval: str, count: int, *, last: date = TODAY, minute: bool = False):
    rows = []
    for i in range(count):
        day = last - timedelta(days=i)
        label = f"{day.isoformat()} 10:00:00" if minute else day.isoformat()
        rows.append({"trade_date": label, "open": 1, "high": 1,
                     "low": 1, "close": 1, "volume": 1, "amount": 1})
    return rows


def test_upsert_kline_bars_is_idempotent(conn):
    rows = _bars("1d", 130)
    assert watch_db.upsert_kline_bars("600519.SH", "1d", rows, source="eastmoney", conn=conn) == 130
    watch_db.upsert_kline_bars("600519.SH", "1d", rows, source="eastmoney", conn=conn)
    total = conn.execute(
        "SELECT count(*) FROM watch_kline_bar WHERE symbol='600519.SH' AND interval='1d'"
    ).fetchone()[0]
    assert total == 130


def test_failed_fetch_keeps_old_bars_and_marks_error(conn):
    watch_db.upsert_kline_bars("600519.SH", "1w", _bars("1w", 61), source="eastmoney", conn=conn)
    watch_db.record_kline_fetch("600519.SH", "1w", ok=True, error=None, conn=conn)
    watch_db.record_kline_fetch("600519.SH", "1w", ok=False, error="RemoteDisconnected", conn=conn)

    row = conn.execute(
        "SELECT bars_count, last_ok_at, last_error FROM watch_kline_fetch_status "
        "WHERE symbol='600519.SH' AND interval='1w'"
    ).fetchone()
    assert row[0] == 61
    assert row[1] is not None
    assert "RemoteDisconnected" in row[2]

    states = kline.list_level_states("600519.SH", conn, today=TODAY)
    week = next(i for i in states["items"] if i["interval"] == "1w")
    # Old bars remain usable; the failed attempt is surfaced separately.
    assert week["status"] == kline.READY
    assert week["fetch_failed"] is True
    assert "RemoteDisconnected" in week["last_error"]


def test_update_levels_partial_failure_isolation(conn):
    def fake_fetch(_secid, klt, _beg, _end):
        if klt == 102:  # week fails
            raise ConnectionError("reset by peer")
        sizes = {101: 130, 103: 30, 104: 20, 105: 8, 30: 30}
        return _bars("1d", sizes[klt], minute=(klt == 30))

    attempted = kline.update_levels(
        "600519.SH", ["1d", "1w", "1mo", "1q", "1y"], conn,
        fetcher=fake_fetch, today=TODAY,
    )
    assert attempted == ["1d", "1w", "1mo", "1q", "1y"]

    states = kline.list_level_states("600519.SH", conn, today=TODAY)
    by = {i["interval"]: i for i in states["items"]}
    assert by["1d"]["status"] == kline.READY
    assert by["1mo"]["status"] == kline.READY
    assert by["1q"]["status"] == kline.READY
    assert by["1y"]["status"] == kline.READY
    assert by["1w"]["status"] == kline.FAILED  # no prior bars → hard failed
    assert by["1w"]["fetch_failed"] is True
    missing = [i["interval"] for i in kline.missing_required_levels(states)]
    assert missing == ["1w"]


def test_resolve_market_dates_calendar_tier(conn):
    conn.execute(
        "CREATE TABLE trading_calendar (market VARCHAR, cal_date DATE, is_open BOOLEAN)"
    )
    conn.execute(
        "INSERT INTO trading_calendar VALUES "
        "('a_share', DATE '2026-10-01', FALSE),"
        "('a_share', DATE '2026-09-30', TRUE),"
        "('a_share', DATE '2026-09-29', TRUE)"
    )
    last_open, threshold, source = watch_db.resolve_market_dates(conn, today=TODAY)
    assert source == "trading_calendar"
    assert last_open == date(2026, 9, 30)
    assert threshold == date(2026, 9, 29)


def test_resolve_market_dates_falls_back_to_daily_bar(conn):
    conn.execute("CREATE TABLE daily_bar (symbol VARCHAR, trade_date DATE)")
    conn.execute("INSERT INTO daily_bar VALUES ('600519.SH', DATE '2026-09-23')")
    last_open, threshold, source = watch_db.resolve_market_dates(conn, today=TODAY)
    assert source == "daily_bar"
    assert last_open == threshold == date(2026, 9, 23)


def test_list_level_states_seeds_all_intervals(conn):
    states = kline.list_level_states("600519.SH", conn, today=TODAY)
    intervals = [i["interval"] for i in states["items"]]
    assert intervals == ["1d", "1w", "1mo", "1q", "1y", "30m"]
    assert all(i["status"] == kline.NOT_FETCHED for i in states["items"])
    required = {i["interval"] for i in states["items"] if i["required"]}
    assert required == set(kline.REQUIRED_INTERVALS)


def test_build_chanlun_data_brief_was_replaced_by_objective_kline_tool():
    # BDD rule 21 (tool-callback design): bars are no longer rendered into
    # the prompt; the objective_kline tool serves them local-first with an
    # online fallback when stale.
    assert not hasattr(kline, "build_chanlun_data_brief")


# ----------------------------------------------------------------------
# HTTP contract + 412 advisory prompt
# ----------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = WatchlistStore(base_dir=tmp_path / "watchlist")
    store.add_entry("600519.SH", name="贵州茅台", industry="白酒")

    class _Runtime:
        def __init__(self):
            self.started = 0
            self.last_role_run = None
            self._store = self

        def list_runs(self, limit=10_000):
            return []

        def start_run(self, preset, user_vars, role_run=None, **kw):
            self.started += 1
            self.last_role_run = role_run

            class _Run:
                id = "run-x"
                status = "pending"
                kind = "role_run"
                trial_role = role_run["role_ref"]

            return _Run()

    runtime = _Runtime()
    monkeypatch.setattr(watchlist_routes, "_get_watch_store", lambda: store)
    monkeypatch.setattr(watchlist_routes, "_get_runtime", lambda: runtime)
    monkeypatch.setattr(watchlist_routes, "_get_catalog_entries", lambda: ENTRIES)

    primary = duckdb.connect(str(tmp_path / "market.duckdb"))
    monkeypatch.setattr(
        watchlist_routes.watch_db,
        "watchlist_connection",
        lambda: primary.cursor(),
    )

    sizes = {101: 130, 102: 70, 103: 30, 104: 20, 105: 8, 30: 30}

    def fake_fetch(_secid, klt, _beg, _end):
        if klt == 104:  # quarter always fails in this fixture
            raise ConnectionError("reset by peer")
        return _bars("1d", sizes[klt], minute=(klt == 30))

    monkeypatch.setattr(
        watchlist_routes.watch_kline, "_default_kline_fetcher", fake_fetch
    )

    app = FastAPI()
    watchlist_routes.register_watchlist_routes(app)
    with TestClient(app) as test_client:
        yield test_client, runtime


def test_status_endpoint_reports_not_fetched_initially(client):
    test_client, _ = client
    resp = test_client.get("/watch/600519.SH/kline/status")
    assert resp.status_code == 200
    body = resp.json()
    assert {i["interval"] for i in body["items"]} == {
        "1d", "1w", "1mo", "1q", "1y", "30m"
    }
    assert all(i["status"] == "not_fetched" for i in body["items"])
    assert body["market_ref"]["source"]


def test_bars_endpoint_returns_stored_bars(client):
    test_client, _ = client
    upd = test_client.post(
        "/watch/600519.SH/kline/update",
        json={"intervals": ["1d", "30m"]},
    )
    assert upd.status_code == 200

    resp = test_client.get(
        "/watch/600519.SH/kline/bars", params={"interval": "1d"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "600519.SH"
    assert body["interval"] == "1d"
    assert len(body["items"]) == 130
    assert set(body["items"][0]) == {
        "time", "open", "high", "low", "close", "volume", "amount"
    }
    # Ascending time order (oldest -> newest) like list_kline_bars.
    times = [item["time"] for item in body["items"]]
    assert times == sorted(times)

    resp30 = test_client.get(
        "/watch/600519.SH/kline/bars", params={"interval": "30m"}
    )
    assert resp30.status_code == 200
    assert resp30.json()["items"][0]["time"].endswith("10:00:00")


def test_bars_endpoint_level_without_rows_returns_empty(client):
    test_client, _ = client
    resp = test_client.get(
        "/watch/600519.SH/kline/bars", params={"interval": "1w"}
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_bars_endpoint_rejects_unknown_interval(client):
    test_client, _ = client
    resp = test_client.get(
        "/watch/600519.SH/kline/bars", params={"interval": "2m"}
    )
    assert resp.status_code == 400


def test_bars_endpoint_honors_limit(client):
    test_client, _ = client
    test_client.post(
        "/watch/600519.SH/kline/update", json={"intervals": ["1d"]}
    )
    resp = test_client.get(
        "/watch/600519.SH/kline/bars",
        params={"interval": "1d", "limit": 10},
    )
    assert len(resp.json()["items"]) == 10


def test_update_partial_failure_returns_per_level_results(client):
    test_client, _ = client
    resp = test_client.post(
        "/watch/600519.SH/kline/update", json={"intervals": ["1d", "1w", "1q"]}
    )
    assert resp.status_code == 200
    by = {i["interval"]: i for i in resp.json()["items"]}
    assert by["1d"]["status"] == "ready"
    assert by["1w"]["status"] == "ready"
    assert by["1q"]["status"] == "failed"


def test_update_rejects_unknown_interval(client):
    test_client, _ = client
    resp = test_client.post(
        "/watch/600519.SH/kline/update", json={"intervals": ["2m"]}
    )
    assert resp.status_code == 400


def test_chanlun_run_prompts_when_levels_missing_but_can_be_skipped(client):
    test_client, runtime = client
    resp = test_client.post(
        "/watch/600519.SH/analyze",
        json={"category": "technical", "role_ref": CHANLUN_REF},
    )
    # First attempt is an advisory prompt (412), no run created yet.
    assert resp.status_code == 412
    detail = resp.json()["detail"]
    assert detail["code"] == "kline_not_ready"
    assert len(detail["items"]) == 5
    assert runtime.started == 0

    # Fetch every required level (fixture's quarter endpoint fails, so
    # update once with a passing set): quarter succeeds on retry.
    resp = test_client.post(
        "/watch/600519.SH/kline/update",
        json={"intervals": ["1d", "1w", "1mo", "1y"]},
    )
    assert resp.status_code == 200

    # Quarter still missing → prompted again, now naming only that level.
    resp = test_client.post(
        "/watch/600519.SH/analyze",
        json={"category": "technical", "role_ref": CHANLUN_REF},
    )
    assert resp.status_code == 412
    assert [i["interval"] for i in resp.json()["detail"]["items"]] == ["1q"]

    # Investor skips the prompt (BDD rule 18): run starts. BDD rule 21 uses
    # a tool callback — archived bars are read through objective_kline at
    # runtime and are never injected into the research question.
    resp = test_client.post(
        "/watch/600519.SH/analyze",
        json={
            "category": "technical",
            "role_ref": CHANLUN_REF,
            "skip_kline_gate": True,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == "run-x"
    assert runtime.started == 1
    question = runtime.last_role_run["question"]
    assert "600519.SH" in question  # the target is still rendered
    assert "平台客观数据" not in question
    assert "时间,开盘,最高,最低,收盘,成交量" not in question
    assert "2026-10-02,1,1,1,1,1" not in question


def test_chanlun_run_allowed_when_required_levels_ready_30m_optional(client):
    test_client, runtime = client

    # Make quarter pass for this test by seeding bars directly.
    test_client.post(
        "/watch/600519.SH/kline/update",
        json={"intervals": ["1d", "1w", "1mo", "1y"]},
    )
    connection = watchlist_routes.watch_db.watchlist_connection()
    watch_db.upsert_kline_bars(
        "600519.SH", "1q", _bars("1q", 20), source="eastmoney", conn=connection
    )
    watch_db.record_kline_fetch("600519.SH", "1q", ok=True, error=None, conn=connection)
    connection.close()

    # 30m never fetched — gate must still pass.
    resp = test_client.post(
        "/watch/600519.SH/analyze",
        json={"category": "technical", "role_ref": CHANLUN_REF},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == "run-x"
    assert runtime.started == 1

    # The run reads archived bars via the objective_kline tool — no bars
    # are embedded into the research question.
    question = runtime.last_role_run["question"]
    assert "600519.SH" in question
    assert "平台客观数据" not in question
    assert "时间,开盘,最高,最低,收盘,成交量" not in question
    assert "2026-10-02,1,1,1,1,1" not in question


def test_non_chanlun_role_is_not_gated(client):
    test_client, runtime = client
    resp = test_client.post(
        "/watch/600519.SH/analyze",
        json={"category": "technical", "role_ref": CLASSIC_TA_REF},
    )
    assert resp.status_code == 200
    assert runtime.started == 1


# ----------------------------------------------------------------------
# Data-source selection: catalog, resampling, per-source dispatch
# ----------------------------------------------------------------------
def test_resample_monthly_bars_to_quarters_and_years():
    def _m(label: str, close: float, *, open_=None, high=None, low=None, vol=100):
        return {
            "trade_date": label,
            "open": close if open_ is None else open_,
            "high": close + 1 if high is None else high,
            "low": close - 1 if low is None else low,
            "close": close,
            "volume": vol,
            "amount": 1.0,
        }

    monthly = [
        _m("2026-01-30", 11, open_=10, high=12, low=9),
        _m("2026-02-27", 12, open_=11, high=13, low=10, vol=110),
        _m("2026-03-31", 13, open_=12, high=14, low=11, vol=120),
        _m("2026-04-30", 14, open_=13, high=15, low=12, vol=130),
        _m("2026-05-29", 15, open_=14, high=16, low=13, vol=140),
        _m("2026-06-30", 16, open_=15, high=17, low=14, vol=150),
    ]
    quarters = kline_sources.resample_bars(rows=monthly, rule="1q")
    assert [row["trade_date"] for row in quarters] == ["2026-03-31", "2026-06-30"]
    q1 = quarters[0]
    assert (q1["open"], q1["close"], q1["high"], q1["low"]) == (10, 13, 14, 9)
    assert q1["volume"] == 330
    assert quarters[1]["close"] == 16

    years = kline_sources.resample_bars(rows=monthly, rule="1y")
    assert len(years) == 1
    assert years[0]["trade_date"] == "2026-06-30"
    assert (years[0]["open"], years[0]["close"]) == (10, 16)
    assert (years[0]["high"], years[0]["low"]) == (17, 9)
    assert years[0]["volume"] == 750


def test_source_catalog_follows_a_share_chain_order():
    items = kline.list_sources()
    ids = [item["id"] for item in items]
    # Same vocabulary/order as Settings → MARKET_DATA_ORDER_A_SHARE.
    assert ids == [
        "tencent",
        "mootdx",
        "eastmoney",
        "baostock",
        "akshare",
        "tushare",
        "gildata",
        "local",
    ]
    by_id = {item["id"]: item for item in items}
    assert by_id["tencent"]["available"] is True
    assert set(by_id["tencent"]["intervals"]) == {
        "1d", "1w", "1mo", "1q", "1y", "30m"
    }
    assert by_id["eastmoney"]["available"] is True
    assert by_id["tushare"]["requires_auth"] is True
    # Vendors with adapters advertise all six levels; token-gated vendors
    # without credentials stay disabled with a machine-readable reason.
    assert by_id["baostock"]["available"] is True
    assert set(by_id["baostock"]["intervals"]) == {
        "1d", "1w", "1mo", "1q", "1y", "30m"
    }
    assert set(by_id["mootdx"]["intervals"]) == {
        "1d", "1w", "1mo", "1q", "1y", "30m"
    }
    # Local DuckDB warehouse needs neither install nor credentials.
    assert by_id["local"]["available"] is True
    assert set(by_id["local"]["intervals"]) == {
        "1d", "1w", "1mo", "1q", "1y", "30m"
    }
    assert by_id["gildata"]["available"] is False
    assert by_id["gildata"]["reason"] == kline_sources.REASON_NEEDS_AUTH


def test_normalize_source_defaults_eastmoney_and_rejects_bad_choices():
    assert kline.normalize_source(None) == "eastmoney"
    assert kline.normalize_source("tencent") == "tencent"
    with pytest.raises(ValueError):
        kline.normalize_source("not-a-vendor")
    with pytest.raises(ValueError):
        kline.normalize_source("gildata")  # catalog member, missing token


def test_update_levels_dispatches_to_selected_source_and_stamps_it(conn):
    seen: list[tuple[str, str]] = []

    def fake_adapter(symbol, interval, start, end):
        seen.append((symbol, interval))
        assert start < end
        count = 130 if interval == "1d" else 70
        return _bars(interval, count)

    attempted = kline.update_levels(
        "600519.SH",
        ["1d", "1w"],
        conn,
        source="tencent",
        adapter=fake_adapter,
        today=TODAY,
    )
    assert attempted == ["1d", "1w"]
    assert seen == [("600519.SH", "1d"), ("600519.SH", "1w")]

    states = kline.list_level_states("600519.SH", conn, today=TODAY)
    by = {item["interval"]: item for item in states["items"]}
    assert by["1d"]["status"] == kline.READY
    assert by["1d"]["source"] == "tencent"
    assert by["1w"]["source"] == "tencent"
    stamped = conn.execute(
        "SELECT DISTINCT source FROM watch_kline_bar "
        "WHERE symbol='600519.SH' AND interval='1d'"
    ).fetchone()
    assert stamped[0] == "tencent"


def test_failed_switch_of_source_keeps_previous_source_bars(conn):
    # Level first becomes ready via Eastmoney.
    kline.update_levels(
        "600519.SH", ["1d"], conn,
        fetcher=lambda *_a, **_k: _bars("1d", 130), today=TODAY,
    )

    # Switching to Tencent and failing must not overwrite bars or source.
    def _boom(_symbol, _interval, _start, _end):
        raise WatchlistDataError("tencent endpoint 500")

    kline.update_levels(
        "600519.SH", ["1d"], conn,
        source="tencent", adapter=_boom, today=TODAY,
    )
    states = kline.list_level_states("600519.SH", conn, today=TODAY)
    day = next(item for item in states["items"] if item["interval"] == "1d")
    assert day["status"] == kline.READY
    assert day["fetch_failed"] is True
    assert day["source"] == "eastmoney"
    assert "tencent endpoint 500" in day["last_error"]


def test_adapter_empty_payload_is_failure_not_success(conn):
    def _empty(_symbol, _interval, _start, _end):
        return []

    kline.update_levels(
        "600519.SH", ["1d"], conn,
        source="tencent", adapter=_empty, today=TODAY,
    )
    states = kline.list_level_states("600519.SH", conn, today=TODAY)
    day = next(item for item in states["items"] if item["interval"] == "1d")
    assert day["status"] == kline.FAILED
    assert day["source"] is None


def test_sources_endpoint_lists_catalog(client):
    test_client, _ = client
    resp = test_client.get("/watch/600519.SH/kline/sources")
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["items"]]
    assert ids[0] == "tencent"
    assert "eastmoney" in ids


def test_update_endpoint_honors_source_param(client, monkeypatch):
    test_client, _ = client

    def fake_tencent(symbol, interval, start, end):
        count = 130 if interval == "1d" else 70
        return _bars(interval, count)

    monkeypatch.setitem(
        watchlist_routes.watch_kline.kline_sources._ADAPTERS,
        "tencent",
        fake_tencent,
    )

    resp = test_client.post(
        "/watch/600519.SH/kline/update",
        json={"intervals": ["1d", "1w"], "source": "tencent"},
    )
    assert resp.status_code == 200
    by = {item["interval"]: item for item in resp.json()["items"]}
    assert by["1d"]["status"] == "ready"
    assert by["1d"]["source"] == "tencent"
    assert by["1w"]["source"] == "tencent"


def test_update_endpoint_rejects_unavailable_source(client):
    test_client, _ = client
    resp = test_client.post(
        "/watch/600519.SH/kline/update",
        json={"source": "gildata"},
    )
    assert resp.status_code == 400
    assert "gildata" in resp.json()["detail"]


def test_tencent_adapter_aggregates_quarter_and_year_from_monthly(monkeypatch):
    # Regression: quarter/year requests must fetch monthly and resample;
    # an earlier dispatch bug wrote raw monthly rows into the 1q/1y tables.
    months = [
        ["2026-01-30", 10, 11, 12, 9, 100],
        ["2026-02-27", 11, 12, 13, 10, 110],
        ["2026-03-31", 12, 13, 14, 11, 120],
        ["2026-04-30", 13, 14, 15, 12, 130],
        ["2026-05-29", 14, 15, 16, 13, 140],
        ["2026-06-30", 15, 16, 17, 14, 150],
    ]
    seen_urls: list[str] = []

    def fake_http_get_json(url: str, *, retries: int = 2):
        seen_urls.append(url)
        return {"code": 0, "data": {"sh600519": {"qfqmonth": months}}}

    monkeypatch.setattr(kline_sources, "_http_get_json", fake_http_get_json)

    quarters = kline_sources._fetch_tencent(
        "600519.SH", "1q", date(2026, 1, 1), date(2026, 7, 1)
    )
    assert len(quarters) == 2
    assert [row["trade_date"] for row in quarters] == ["2026-03-31", "2026-06-30"]
    assert (quarters[0]["open"], quarters[0]["close"]) == (10, 13)
    assert (quarters[0]["high"], quarters[0]["low"]) == (14, 9)
    assert quarters[0]["volume"] == 330
    # Underlying request really was the monthly period.
    assert ",month," in seen_urls[0]

    years = kline_sources._fetch_tencent(
        "600519.SH", "1y", date(2025, 1, 1), date(2027, 1, 1)
    )
    assert len(years) == 1
    assert years[0]["trade_date"] == "2026-06-30"
    assert (years[0]["open"], years[0]["close"]) == (10, 16)
    assert years[0]["volume"] == 750


# ----------------------------------------------------------------------
# BaoStock / mootdx / local DuckDB adapters
# ----------------------------------------------------------------------
import sys
import types

import pandas as pd


class _FakeBaostockRS:
    def __init__(self, fields, rows, error_code="0", error_msg="success"):
        self.fields = fields
        self._rows = rows
        self.error_code = error_code
        self.error_msg = error_msg
        self._idx = -1

    def next(self):
        self._idx += 1
        return self._idx < len(self._rows)

    def get_row_data(self):
        return self._rows[self._idx]


def _install_fake_baostock(monkeypatch, rows_by_freq):
    """rows_by_freq: {frequency: (fields, rows)}; records call kwargs."""
    calls = []

    fake = types.ModuleType("baostock")

    def _login():
        result = types.SimpleNamespace(error_code="0", error_msg="success")
        return result

    def _logout():
        return types.SimpleNamespace(error_code="0")

    def _query(code, fields, **kwargs):
        calls.append({"code": code, "fields": fields, **kwargs})
        freq = kwargs["frequency"]
        fieldnames, rows = rows_by_freq[freq]
        assert fields.split(",") == fieldnames
        return _FakeBaostockRS(fieldnames, rows)

    fake.login = _login
    fake.logout = _logout
    fake.query_history_k_data_plus = _query
    monkeypatch.setitem(sys.modules, "baostock", fake)
    monkeypatch.setattr(kline_sources, "_baostock_session_ok", False)
    return calls


def test_baostock_adapter_daily_30m_and_quarter(monkeypatch):
    daily_fields = ["date", "open", "high", "low", "close", "volume", "amount"]
    minute_fields = ["date", "time", "open", "high", "low", "close",
                     "volume", "amount"]
    rows_by_freq = {
        "d": (
            daily_fields,
            [
                ["2026-09-28", "10", "11", "9", "10.5", "100", "1000"],
                # suspended session -> empty OHLC, must be skipped
                ["2026-09-29", "", "", "", "", "", ""],
                ["2026-09-30", "10.5", "11.2", "10.2", "10.8", "120", "1200"],
            ],
        ),
        "30": (
            minute_fields,
            [
                ["2026-09-30", "20260930100000000", "10", "10.5", "9.9",
                 "10.2", "50", "500"],
                ["2026-09-30", "20260930103000000", "10.2", "10.6", "10.1",
                 "10.4", "60", "600"],
            ],
        ),
        "m": (
            daily_fields,
            [
                ["2026-01-30", "10", "12", "9", "11", "100", "1"],
                ["2026-02-27", "11", "13", "10", "12", "110", "1"],
                ["2026-03-31", "12", "14", "11", "13", "120", "1"],
            ],
        ),
    }
    calls = _install_fake_baostock(monkeypatch, rows_by_freq)

    daily = kline_sources._fetch_baostock(
        "600519.SH", "1d", date(2026, 9, 1), date(2026, 10, 1)
    )
    assert [row["trade_date"] for row in daily] == ["2026-09-28", "2026-09-30"]
    assert daily[1]["close"] == 10.8
    assert calls[0]["code"] == "sh.600519"
    assert calls[0]["frequency"] == "d"
    assert calls[0]["adjustflag"] == "2"
    assert "time" not in calls[0]["fields"]

    minute = kline_sources._fetch_baostock(
        "000001.SZ", "30m", date(2026, 9, 1), date(2026, 10, 1)
    )
    assert calls[-1]["code"] == "sz.000001"
    assert minute[0]["trade_date"] == "2026-09-30 10:00:00"
    assert minute[1]["trade_date"] == "2026-09-30 10:30:00"

    quarters = kline_sources._fetch_baostock(
        "600519.SH", "1q", date(2026, 1, 1), date(2026, 4, 1)
    )
    assert calls[-1]["frequency"] == "m"
    assert len(quarters) == 1
    assert quarters[0]["trade_date"] == "2026-03-31"
    assert (quarters[0]["open"], quarters[0]["close"]) == (10, 13)
    assert quarters[0]["volume"] == 330


def test_baostock_adapter_surfaces_query_error(monkeypatch):
    calls = []
    fake = types.ModuleType("baostock")
    fake.login = lambda: types.SimpleNamespace(error_code="0", error_msg="ok")
    fake.logout = lambda: types.SimpleNamespace(error_code="0")

    def _query(code, fields, **kwargs):
        calls.append(kwargs)
        return _FakeBaostockRS([], [], error_code="10004012",
                               error_msg="日线指标参数传入错误")
    fake.query_history_k_data_plus = _query
    monkeypatch.setitem(sys.modules, "baostock", fake)
    monkeypatch.setattr(kline_sources, "_baostock_session_ok", False)

    with pytest.raises(WatchlistDataError, match="日线指标参数传入错误"):
        kline_sources._fetch_baostock(
            "600519.SH", "1d", date(2026, 9, 1), date(2026, 10, 1)
        )


class _FakeMootdxClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def bars(self, symbol, frequency, start, offset):
        self.calls.append((symbol, frequency, start, offset))
        page = self.pages.get(start)
        if page is None:
            return pd.DataFrame()
        return pd.DataFrame(page)


def _mootdx_frame(day, *, minute=False):
    stamp = pd.Timestamp(f"{day} 10:00:00") if minute else pd.Timestamp(day)
    return {
        "datetime": stamp,
        "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
        "vol": 100, "amount": 1000.0,
    }


def _install_fake_mootdx(monkeypatch, client):
    fake_pkg = types.ModuleType("mootdx")
    fake_quotes = types.ModuleType("mootdx.quotes")
    fake_quotes.Quotes = types.SimpleNamespace(
        factory=lambda **kwargs: client
    )
    fake_pkg.quotes = fake_quotes
    monkeypatch.setitem(sys.modules, "mootdx", fake_pkg)
    monkeypatch.setitem(sys.modules, "mootdx.quotes", fake_quotes)
    monkeypatch.setattr(kline_sources, "_mootdx_client", None)


def test_mootdx_adapter_paginates_and_maps(monkeypatch):
    # First page ends inside the window (oldest > start) -> must page again;
    # second page is short -> pagination stops.
    page0 = [
        _mootdx_frame(f"2026-08-{d:02d}")
        for d in range(1, 31)
    ] + [_mootdx_frame("2026-09-30")]
    page0 = page0[-800:] if len(page0) > 800 else page0
    # Force "inside window" oldest by using 800 rows of August/September via
    # padding unique July days so oldest stays after 2026-01-01 anyway.
    page0 = [_mootdx_frame(f"2026-07-{((d % 28) + 1):02d}") for d in range(600)]
    page0 += [_mootdx_frame(f"2026-09-{((d % 28) + 1):02d}") for d in range(200)]
    page1 = [_mootdx_frame("2025-12-15"), _mootdx_frame("2025-11-03")]
    client = _FakeMootdxClient({0: page0, 800: page1})
    _install_fake_mootdx(monkeypatch, client)

    rows = kline_sources._fetch_mootdx(
        "600519.SH", "1d", date(2026, 1, 1), date(2026, 10, 2)
    )
    # Two pages requested with TDX category 9 (day), offsets 0 and 800.
    assert [call[1] for call in client.calls] == [9, 9]
    assert [call[2] for call in client.calls] == [0, 800]
    assert client.calls[0][0] == "600519"
    assert rows, "window rows expected"
    assert all(row["trade_date"] >= "2026-01-01" for row in rows)
    assert all(row["trade_date"] <= "2026-10-02" for row in rows)
    assert rows[0]["close"] == 10.5


def test_mootdx_adapter_30m_labels_and_quarter_resample(monkeypatch):
    client = _FakeMootdxClient({
        0: [_mootdx_frame("2026-09-30", minute=True)]
    })
    _install_fake_mootdx(monkeypatch, client)
    minute = kline_sources._fetch_mootdx(
        "600519.SH", "30m", date(2026, 9, 1), date(2026, 10, 1)
    )
    assert client.calls[0][1] == 2
    assert minute[0]["trade_date"] == "2026-09-30 10:00:00"

    monthly_client = _FakeMootdxClient({
        0: [
            _mootdx_frame("2026-01-30"),
            _mootdx_frame("2026-02-27"),
            _mootdx_frame("2026-03-31"),
        ]
    })
    _install_fake_mootdx(monkeypatch, monthly_client)
    quarters = kline_sources._fetch_mootdx(
        "600519.SH", "1q", date(2026, 1, 1), date(2026, 4, 1)
    )
    assert monthly_client.calls[0][1] == 6
    assert len(quarters) == 1
    assert quarters[0]["trade_date"] == "2026-03-31"


def test_mootdx_adapter_resets_client_on_transport_error(monkeypatch):
    class _BoomClient:
        def bars(self, **kwargs):
            raise ConnectionError("tdx reset")

    monkeypatch.setattr(kline_sources, "_mootdx_client", _BoomClient())
    with pytest.raises(WatchlistDataError, match="tdx reset"):
        kline_sources._fetch_mootdx(
            "600519.SH", "1d", date(2026, 9, 1), date(2026, 10, 1)
        )
    assert kline_sources._mootdx_client is None


def test_local_adapter_reads_incrementally_stored_duckdb_bars(conn, monkeypatch):
    watch_db.upsert_kline_bars(
        "600519.SH", "1d", _bars("1d", 130), source="tencent", conn=conn
    )
    watch_db.record_kline_fetch(
        "600519.SH", "1d", ok=True, error=None, source="tencent", conn=conn
    )
    minute_rows = [
        {
            "trade_date": "2026-09-30 10:00:00",
            "open": 10, "high": 11, "low": 9, "close": 10.5,
            "volume": 100, "amount": 1,
        },
        {
            "trade_date": "2026-09-30 10:30:00",
            "open": 10.5, "high": 11.2, "low": 10.2, "close": 11,
            "volume": 110, "amount": 1,
        },
    ]
    watch_db.upsert_kline_bars(
        "600519.SH", "30m", minute_rows, source="baostock", conn=conn
    )
    watch_db.record_kline_fetch(
        "600519.SH", "30m", ok=True, error=None, source="baostock", conn=conn
    )
    # The adapter opens its own connection; point it at the same in-memory DB
    # via a shared cursor (mirrors how the HTTP layer already opens cursors).
    monkeypatch.setattr(
        watch_db, "watchlist_connection", lambda *a, **k: conn.cursor()
    )

    daily = kline_sources.fetch_source_level(
        "local", "600519.SH", "1d",
        TODAY - timedelta(days=400), TODAY,
    )
    assert len(daily) == 130
    assert daily[0]["trade_date"] < daily[-1]["trade_date"]

    minute = kline_sources.fetch_source_level(
        "local", "600519.SH", "30m",
        TODAY - timedelta(days=10), TODAY,
    )
    assert [row["trade_date"] for row in minute] == [
        "2026-09-30 10:00:00",
        "2026-09-30 10:30:00",
    ]

    # No stored bars for a fresh symbol -> normalized empty-payload failure.
    with pytest.raises(WatchlistDataError, match="未返回"):
        kline_sources.fetch_source_level(
            "local", "000002.SZ", "1d",
            TODAY - timedelta(days=400), TODAY,
        )


def test_local_update_is_read_only_and_keeps_provenance(conn):
    watch_db.upsert_kline_bars(
        "600519.SH", "1d", _bars("1d", 130), source="baostock", conn=conn
    )
    watch_db.record_kline_fetch(
        "600519.SH", "1d", ok=True, error=None, source="baostock", conn=conn
    )

    attempted = kline.update_levels(
        "600519.SH", ["1d"], conn, source="local"
    )
    assert attempted == ["1d"]

    # Bars were not re-stamped with "local".
    sources = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT source FROM watch_kline_bar "
            "WHERE symbol='600519.SH' AND interval='1d'"
        ).fetchall()
    }
    assert sources == {"baostock"}
    # The status badge keeps advertising the bars' real origin.
    status = conn.execute(
        "SELECT source, last_error FROM watch_kline_fetch_status "
        "WHERE symbol='600519.SH' AND interval='1d'"
    ).fetchone()
    assert status[0] == "baostock"
    assert status[1] is None

    # Empty warehouse for the level -> per-level failure, no bars deleted.
    kline.update_levels("000002.SZ", ["1d"], conn, source="local")
    assert conn.execute(
        "SELECT count(*) FROM watch_kline_bar "
        "WHERE symbol='000002.SZ' AND interval='1d'"
    ).fetchone()[0] == 0
    assert "本地 DuckDB" in conn.execute(
        "SELECT last_error FROM watch_kline_fetch_status "
        "WHERE symbol='000002.SZ' AND interval='1d'"
    ).fetchone()[0]
