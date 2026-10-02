"""HTTP contract tests for /watch/* routes (offline fakes, tmp DuckDB)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import watchlist_routes
from src.api.security import require_auth
from src.watchlist import market as watch_market
from src.watchlist.store import WatchlistStore

CHANLUN_REF = "technical_analysis_panel:chanlun_analyst"
CLASSIC_TA_REF = "technical_analysis_panel:classic_ta_analyst"
FETCH_REF = "equity_research_team:stock_picker"

ENTRIES = [
    {"ref": CHANLUN_REF, "name": "Chanlun (Chan Theory) Analyst",
     "purpose": "chan", "approved": True},
    {"ref": CLASSIC_TA_REF, "name": "Classic Technical Analyst",
     "purpose": "ta", "approved": True},
    {"ref": FETCH_REF, "name": "Stock Analyst",
     "purpose": "equity", "approved": True},
]


@dataclass
class FakeRun:
    id: str
    trial_role: str | None = None
    research_target: str = ""
    research_question: str = ""
    status: str = "pending"
    kind: str = "role_run"
    final_report: str = ""
    created_at: str = "2026-09-10T10:00:00+00:00"
    completed_at: str | None = None
    tasks: list = field(default_factory=list)


class FakeRuntime:
    def __init__(self) -> None:
        class _Store:
            def __init__(self) -> None:
                self.runs: list[FakeRun] = []

            def list_runs(self, limit: int = 50):
                return list(self.runs)

            def reconcile_run(self, run, *, write: bool = True):
                return run

        self._store = _Store()
        self.seq = 0

    def start_run(self, preset_name, user_vars, role_run=None, **kwargs):
        self.seq += 1
        run = FakeRun(
            id=f"run-{self.seq}",
            trial_role=role_run["role_ref"],
            research_target=role_run["target"],
            research_question=role_run["question"],
        )
        self._store.runs.append(run)
        return run


_STRUCTURED_REPORT = "\n".join(
    [
        "**1. Structure read 结构读取**", "s1",
        "**2. Active pivots 活跃支点**", "s2",
        "**3. Divergence 背驰**", "s3",
        "**4. Buy/sell points 买卖点**", "s4",
        "**5. Multi-level plan 多级别计划**", "s5",
        "**6. Elliott corroboration 艾略特验证**", "s6",
        "**7. Chanlun score 缠论打分**",
        "Score: +3", "Confidence: 78%",
    ]
)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = WatchlistStore(base_dir=tmp_path / "watchlist")
    runtime = FakeRuntime()
    monkeypatch.setattr(watchlist_routes, "_get_watch_store", lambda: store)
    monkeypatch.setattr(watchlist_routes, "_get_runtime", lambda: runtime)
    monkeypatch.setattr(watchlist_routes, "_get_catalog_entries", lambda: ENTRIES)

    primary = duckdb.connect(str(tmp_path / "market.duckdb"))
    monkeypatch.setattr(
        watchlist_routes.watch_db,
        "watchlist_connection",
        lambda: primary.cursor(),
    )

    def fake_snapshots(symbols, *, fetcher=None):
        return {
            sym: _snapshot()
            for sym in symbols
            if sym == "600519.SH"
        }

    monkeypatch.setattr(watch_market, "fetch_quote_snapshots", fake_snapshots)
    monkeypatch.setattr(
        watch_market,
        "search_a_shares",
        lambda q, **kw: [
            {"symbol": "600519.SH", "name": "贵州茅台", "industry": ""}
        ]
        if q == "茅台"
        else [],
    )

    app = FastAPI()
    watchlist_routes.register_watchlist_routes(app)
    with TestClient(app) as test_client:
        yield test_client, store, runtime


def _snapshot():
    from src.watchlist.models import QuoteSnapshot

    return QuoteSnapshot(
        price=1500.0, pe=25.6, pb=8.1,
        total_market_cap=1.88e12, industry="白酒",
    )


# ----------------------------------------------------------------------
def test_all_watch_routes_require_auth() -> None:
    app = FastAPI()
    watchlist_routes.register_watchlist_routes(app)
    watch_routes = [r for r in app.routes if r.path.startswith("/watch")]
    assert len(watch_routes) >= 12
    for route in watch_routes:
        calls = {dep.call for dep in route.dependant.dependencies}
        assert require_auth in calls, route.path


def test_list_add_duplicate_delete_flow(client) -> None:
    c, store, _runtime = client
    assert c.get("/watch/list").json() == {"items": [], "quote_error": None}

    resp = c.post("/watch", json={"symbol": "600519.SH", "name": "贵州茅台"})
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "600519.SH"

    dup = c.post("/watch", json={"symbol": "600519.sh", "name": "贵州茅台"})
    assert dup.status_code == 409

    listed = c.get("/watch/list").json()
    assert listed["quote_error"] is None
    item = listed["items"][0]
    assert item["quote"]["price"] == 1500.0
    assert item["quote"]["pe"] == 25.6
    assert item["quote"]["quote_updated_at"]

    bad = c.post("/watch", json={"symbol": "AAPL.US"})
    assert bad.status_code == 400

    deleted = c.delete("/watch/600519.SH")
    assert deleted.status_code == 200
    assert c.delete("/watch/600519.SH").status_code == 404
    assert c.get("/watch/list").json()["items"] == []


def test_search(client) -> None:
    c, _s, _r = client
    resp = c.get("/watch/search", params={"q": "茅台"})
    item = resp.json()["items"][0]
    assert item["symbol"] == "600519.SH"
    # FR-2: candidates carry industry, enriched with one batched quote call.
    assert item["industry"] == "白酒"
    assert c.get("/watch/search", params={"q": "  "}).json()["items"] == []


def test_search_data_error_502(client, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _s, _r = client

    def boom(query, **kw):
        raise watch_market.WatchlistDataError("搜索接口请求失败: timeout")

    monkeypatch.setattr(watch_market, "search_a_shares", boom)
    resp = c.get("/watch/search", params={"q": "茅台"})
    assert resp.status_code == 502


def test_refresh_buttons_direct_no_runtime(client, monkeypatch: pytest.MonkeyPatch) -> None:
    c, store, _runtime = client
    store.add_entry("600519.SH", name="贵州茅台")

    def _no_runtime():
        raise AssertionError("refresh must never touch the runtime/LLM")

    monkeypatch.setattr(watchlist_routes, "_get_runtime", _no_runtime)

    resp = c.post("/watch/600519.SH/refresh-quotes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["quote"]["price"] == 1500.0
    assert body["updated_at"]

    # Warehouse row persisted (valuation + instrument industry).
    profile = c.get("/watch/600519.SH/profile").json()
    assert profile["latest_valuation"]["pe_ttm"] == 25.6
    assert profile["instrument"]["industry"] == "白酒"


def test_refresh_quotes_failure_502(client, monkeypatch: pytest.MonkeyPatch) -> None:
    c, store, _runtime = client
    store.add_entry("600519.SH", name="贵州茅台")

    def boom(symbols, **kw):
        raise watch_market.WatchlistDataError("行情接口请求失败: 502")

    monkeypatch.setattr(watch_market, "fetch_quote_snapshots", boom)
    assert c.post("/watch/600519.SH/refresh-quotes").status_code == 502


def test_refresh_profile_success_and_failure(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, store, _runtime = client
    store.add_entry("600519.SH", name="贵州茅台")

    from src.watchlist.models import CompanyProfile

    def fake_profile(symbol, *, fetcher=None):
        return CompanyProfile(
            symbol="600519.SH", name="贵州茅台股份", industry="白酒制造",
            list_date="2001-08-27", total_shares=1.256e9,
        )

    monkeypatch.setattr(watch_market, "fetch_company_profile", fake_profile)
    resp = c.post("/watch/600519.SH/refresh-profile")
    assert resp.status_code == 200
    assert resp.json()["name"] == "贵州茅台股份"
    assert store.get_entry("600519.SH").industry == "白酒制造"

    def boom(symbol, *, fetcher=None):
        raise watch_market.WatchlistDataError("基本信息接口请求失败")

    monkeypatch.setattr(watch_market, "fetch_company_profile", boom)
    assert c.post("/watch/600519.SH/refresh-profile").status_code == 502


def test_objective_empty_then_fetch(client) -> None:
    c, store, runtime = client
    store.add_entry("600519.SH", name="贵州茅台")

    empty = c.get("/watch/600519.SH/objective").json()
    assert empty["raw"]["instrument"] == []
    assert empty["raw"]["daily_bar"] == []
    assert empty["raw"]["valuation"] == []
    assert empty["raw"]["financial"] == []
    assert empty["fetches"] == []

    assert c.post(
        "/watch/600519.SH/objective-fetch", json={"note": "   "}
    ).status_code == 400

    ok = c.post(
        "/watch/600519.SH/objective-fetch",
        json={"note": "抓取近三年分红"},
    )
    assert ok.status_code == 200 and ok.json()["id"] == "run-1"

    again = c.post(
        "/watch/600519.SH/objective-fetch",
        json={"note": "再抓一次"},
    )
    assert again.status_code == 409


def test_analyze_validation_and_success(client) -> None:
    c, store, runtime = client
    store.add_entry("600519.SH", name="贵州茅台")

    assert c.post(
        "/watch/600519.SH/analyze",
        json={"category": "technical", "role_ref": ""},
    ).status_code == 400
    assert c.post(
        "/watch/600519.SH/analyze",
        json={"category": "nope", "role_ref": CHANLUN_REF},
    ).status_code == 400
    assert c.post(
        "/watch/600519.SH/analyze",
        json={"category": "fundamental", "role_ref": CHANLUN_REF},
    ).status_code == 400
    assert c.post(
        "/watch/600519.SH/analyze",
        json={"category": "technical", "role_ref": "missing:role"},
    ).status_code == 400

    ok = c.post(
        "/watch/600519.SH/analyze",
        json={"category": "technical", "role_ref": CHANLUN_REF},
    )
    assert ok.status_code == 200
    assert ok.json()["id"] == "run-1"

    busy = c.post(
        "/watch/600519.SH/analyze",
        json={"category": "technical", "role_ref": CHANLUN_REF},
    )
    assert busy.status_code == 409


def test_agents_catalog(client) -> None:
    c, _s, _r = client
    resp = c.get("/watch/agents", params={"category": "technical"})
    refs = {item["ref"] for item in resp.json()["items"]}
    assert CHANLUN_REF in refs and FETCH_REF not in refs
    assert c.get("/watch/agents", params={"category": "bad"}).status_code == 422


def test_analyses_and_chanlun_history_after_completion(client) -> None:
    c, store, runtime = client
    store.add_entry("600519.SH", name="贵州茅台")
    runtime._store.runs.append(
        FakeRun(
            "run-9", CHANLUN_REF, "贵州茅台（600519.SH）", "q",
            status="completed", final_report=_STRUCTURED_REPORT,
            created_at="2026-09-10T10:00:00+00:00",
            completed_at="2026-09-10T11:00:00+00:00",
        )
    )

    analyses = c.get("/watch/600519.SH/analyses").json()["items"]
    assert len(analyses) == 1
    assert analyses[0]["id"] == "run-9"
    assert analyses[0]["is_chanlun"] is True
    assert analyses[0]["qualified"] is True
    # AC-11: full conclusion is available, not just the 280-char excerpt.
    assert analyses[0]["final_report"] == _STRUCTURED_REPORT
    assert analyses[0]["final_report_excerpt"] == _STRUCTURED_REPORT[:280]

    chanlun = c.get("/watch/600519.SH/chanlun").json()["items"]
    assert len(chanlun) == 1
    row = chanlun[0]
    assert row["structured"] is True
    assert row["score"] == 3
    assert abs(row["confidence"] - 0.78) < 1e-9
    assert row["dim2_active_pivots"] == "s2"

    # Date-window filter keeps the row; an unrelated window empties it.
    assert len(
        c.get(
            "/watch/600519.SH/chanlun",
            params={"from": "2026-09-10", "to": "2026-09-10"},
        ).json()["items"]
    ) == 1
    assert (
        c.get(
            "/watch/600519.SH/chanlun",
            params={"from": "2026-08-01", "to": "2026-08-31"},
        ).json()["items"]
        == []
    )

    # Bad date shape -> 400.
    assert c.get(
        "/watch/600519.SH/chanlun", params={"from": "10-09-2026"}
    ).status_code == 400


def test_not_watched_gating(client) -> None:
    c, _s, _r = client
    # Membership-required actions/views stay 404...
    assert c.get("/watch/000001.SZ/profile").status_code == 404
    assert c.post(
        "/watch/000001.SZ/objective-fetch", json={"note": "x"}
    ).status_code == 404
    # ...but history endpoints stay readable by symbol after unfollow (AC-3).
    assert c.get("/watch/000001.SZ/objective").status_code == 200
    assert c.get("/watch/000001.SZ/analyses").status_code == 200
    assert c.get("/watch/000001.SZ/chanlun").status_code == 200
    # Malformed symbols are still rejected at normalization (400).
    assert c.get("/watch/AAPL.US/objective").status_code == 400


def test_history_survives_unfollow(client) -> None:
    """AC-3: remove membership only — runs/archives stay queryable."""
    c, store, runtime = client
    store.add_entry("600519.SH", name="贵州茅台")
    runtime._store.runs.append(
        FakeRun(
            "run-keep", CHANLUN_REF, "贵州茅台（600519.SH）", "q",
            status="completed", final_report=_STRUCTURED_REPORT,
            created_at="2026-09-10T10:00:00+00:00",
            completed_at="2026-09-10T11:00:00+00:00",
        )
    )
    # First read archives the completed run into DuckDB.
    assert len(c.get("/watch/600519.SH/chanlun").json()["items"]) == 1
    assert len(c.get("/watch/600519.SH/analyses").json()["items"]) == 1

    # Unfollow; history remains available.
    assert c.delete("/watch/600519.SH").status_code == 200
    assert len(c.get("/watch/600519.SH/chanlun").json()["items"]) == 1
    analyses = c.get("/watch/600519.SH/analyses").json()["items"]
    assert [a["id"] for a in analyses] == ["run-keep"]

    # Re-follow and it is still there.
    assert c.post(
        "/watch", json={"symbol": "600519.SH", "name": "贵州茅台"}
    ).status_code == 200
    assert len(c.get("/watch/600519.SH/chanlun").json()["items"]) == 1
