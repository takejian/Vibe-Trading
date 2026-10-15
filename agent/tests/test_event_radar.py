"""Tests for the event radar: dedup, verification gate, paradigm scoring,
extraction fallback, report contract, and the scan service/HTTP surface.

Fully network-free: news collection is monkeypatched, extraction uses the
heuristic fallback (``llm_factory=None``), and every test gets an isolated
DuckDB file.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api_server
from src.eventradar import db as event_db
from src.eventradar import dedup, extract, report as report_mod, scoring, service, sources


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------

def test_simhash_collapses_reworded_chinese_reposts() -> None:
    a = "超强厄尔尼诺已形成 未来数月全球气候异常"
    b = "NOAA宣布超强厄尔尼诺形成 未来几个月全球天气异常"
    c = "美联储意外降息50个基点 全球市场剧烈波动"
    assert dedup.is_near_duplicate(
        dedup.simhash64(a), dedup.simhash64(b), left_text=a, right_text=b
    )
    assert not dedup.is_near_duplicate(
        dedup.simhash64(a), dedup.simhash64(c), left_text=a, right_text=c
    )


def test_cluster_key_stable_for_same_entity_type_window() -> None:
    from datetime import datetime

    when = datetime(2026, 10, 14, 9, 0)
    k1 = dedup.cluster_key(["厄尔尼诺"], "climate_disaster", when, 72)
    k2 = dedup.cluster_key(["厄尔尼诺"], "climate_disaster",
                           datetime(2026, 10, 14, 20, 0), 72)
    k3 = dedup.cluster_key(["美联储"], "monetary_fiscal", when, 72)
    assert k1 == k2
    assert k1 != k3


def test_source_tiers_and_repost_detection() -> None:
    assert scoring.source_tier("新华社", "https://www.xinhuanet.com/x") == 2
    assert scoring.source_tier("NOAA", "https://www.noaa.gov/el-nino") == 1
    assert scoring.source_tier("某号", "https://weibo.example/x") == 4
    assert scoring.is_repost("转自路透社报道", "")
    assert not scoring.is_repost("独立采写的报道", "")


def test_single_source_never_confirmed() -> None:
    confidence = scoring.confidence_score(
        best_tier=2, independent_sources=1, fact_consistency=0.95
    )
    status = scoring.derive_status(
        best_tier=2, independent_sources=1, fact_consistency=0.95,
        confidence=confidence, min_sources=2, confirm_threshold=0.70,
    )
    assert status == "verifying"


def test_two_independent_t2_sources_confirm() -> None:
    confidence = scoring.confidence_score(
        best_tier=2, independent_sources=2, fact_consistency=0.8
    )
    status = scoring.derive_status(
        best_tier=2, independent_sources=2, fact_consistency=0.8,
        confidence=confidence, min_sources=2, confirm_threshold=0.70,
    )
    assert status == "confirmed"


def test_state_machine_blocks_illegal_transitions() -> None:
    assert scoring.can_transition("unverified", "verifying")
    assert not scoring.can_transition("dismissed", "confirmed")
    assert scoring.can_transition("rumor", "dismissed")


def test_paradigm_requires_all_four_dimensions_and_threshold() -> None:
    good = {"policy_duration": 4, "invest_cycle": 4,
            "chain_breadth": 4, "narrative_heat": 4}
    novelty, total, scores = scoring.validate_paradigm(
        "new_paradigm", good, threshold=15
    )
    assert novelty == "new_paradigm" and total == 16 and scores is not None

    low = {k: 3 for k in good}
    assert scoring.validate_paradigm("new_paradigm", low, threshold=15)[0] == \
        "known_escalation"
    missing = {"policy_duration": 5}
    assert scoring.validate_paradigm("new_paradigm", missing, threshold=15)[0] == \
        "known_escalation"


def test_theme_mapping() -> None:
    assert "气候与农业" in scoring.map_themes("超强厄尔尼诺形成，农产品供给承压")
    assert "AI 与算力" in scoring.map_themes("OpenAI 发布新大模型，算力需求激增")


def test_heuristic_extraction_shape() -> None:
    candidates = [
        {"title": "超强厄尔尼诺已形成 农产品承压", "url": "http://a/1",
         "snippet": "NOAA 宣布", "source_name": "x"},
    ]
    events, used_llm = extract.extract_events(candidates, [], llm_factory=None)
    assert used_llm is False
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "climate_disaster"
    assert event["action"] == "new"
    assert event["evidence_indexes"] == [0]


def test_llm_json_parse_tolerates_fence() -> None:
    raw = '```json\n[{"action":"new","title":"t","event_type":"trade",' \
          '"evidence_indexes":[0]}]\n```'
    parsed = extract.parse_extraction(raw, 1)
    assert len(parsed) == 1 and parsed[0]["event_type"] == "trade"


def test_llm_json_parse_rejects_unknown_type() -> None:
    raw = '[{"action":"new","title":"t","event_type":"not_a_type",' \
          '"evidence_indexes":[0]}]'
    assert extract.parse_extraction(raw, 1) == []


def test_junk_title_filter() -> None:
    from src.eventradar.sources import is_junk

    assert is_junk("【WTI原油期货】今日WTI原油期货实时行情,最新价格")
    assert is_junk("违约责任_百度百科")
    assert is_junk("原油 _ 期货频道 _ 东方财富网")
    assert not is_junk("超强厄尔尼诺已形成 未来数月全球气候异常")
    assert not is_junk("美联储意外降息50个基点 全球市场剧烈波动")


def test_report_section_contract() -> None:
    headings_live = [
        "## 事件确认与定义", "## 情景分析", "## 传导链分析",
        "## 跨资产与行业影响矩阵", "## 受益与受损板块及标的线索",
        "## 催化日历与跟踪指标", "## 反方观点与证伪条件",
    ]
    ok, present = report_mod.validate_report("\n".join(headings_live), "live")
    assert ok and len(present) == 7
    ok2, present2 = report_mod.validate_report("## 事件确认与定义\nx", "live")
    assert not ok2 and len(present2) == 1


# ---------------------------------------------------------------------------
# Service integration (isolated DuckDB, fake sources, heuristic extraction)
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    db_file = tmp_path / "event_radar.duckdb"
    monkeypatch.setattr(
        event_db, "get_market_db_path", lambda: str(db_file), raising=True
    )
    return db_file


def _fake_candidates() -> dict[str, Any]:
    return {
        "sources": [{"name": "fake", "status": "ok", "count": 3}],
        "candidates": [
            {"url": "http://xinhua/1",
             "title": "超强厄尔尼诺已形成 未来数月全球气候异常",
             "snippet": "NOAA 宣布厄尔尼诺", "source_name": "xinhuanet.com",
             "published_at": "2026-10-14 08:00:00"},
            {"url": "http://reuters/2",
             "title": "NOAA宣布超强厄尔尼诺形成 未来几个月全球天气异常",
             "snippet": "reuters el nino", "source_name": "reuters.com",
             "published_at": "2026-10-14 10:00:00"},
            {"url": "http://weibo/3",
             "title": "某自媒体传未经证实的消息 加群荐股",
             "snippet": "加群", "source_name": "weibo.example",
             "published_at": None},
        ],
    }


def _wait_scan() -> dict[str, Any]:
    for _ in range(100):
        runs = service.list_scan_runs(1)
        if runs and runs[0]["status"] in ("completed", "partial", "failed"):
            return runs[0]
        time.sleep(0.05)
    raise AssertionError("scan did not finish")


def test_scan_merges_reposts_into_one_event_with_evidence(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sources, "collect", lambda scope="all": _fake_candidates())
    service.start_scan("all", llm_factory=None)
    run = _wait_scan()
    assert run["status"] == "completed"
    assert run["candidates"] == 3
    assert run["duplicates"] == 1
    assert run["new_events"] == 2  # el nino cluster + rumor item

    events = service.list_events()
    elnino = [e for e in events if "厄尔尼诺" in e["title"]]
    assert len(elnino) == 1
    event = elnino[0]
    assert event["event_type"] == "climate_disaster"
    assert event["verify_status"] == "confirmed"  # 2 independent T2 sources
    assert event["novelty_class"] == "new_paradigm"
    assert event["source_count"] == 2
    detail = service.event_detail(event["event_id"])
    assert {e["source_tier"] for e in detail["evidence"]} == {2}
    assert len(detail["evidence"]) == 2


def test_second_scan_does_not_duplicate(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sources, "collect", lambda scope="all": _fake_candidates())
    service.start_scan("all", llm_factory=None)
    _wait_scan()
    service.start_scan("all", llm_factory=None)
    run2 = _wait_scan()
    assert run2["new_events"] == 0
    assert len([e for e in service.list_events() if "厄尔尼诺" in e["title"]]) == 1


def test_human_lock_blocks_analysis_and_requires_confirmation(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sources, "collect", lambda scope="all": _fake_candidates())
    service.start_scan("all", llm_factory=None)
    _wait_scan()
    rumor = [e for e in service.list_events() if "未经证实" in e["title"]][0]
    with pytest.raises(service.EventNotConfirmed):
        service.start_analysis(object(), event_id=rumor["event_id"])

    service.verify_event(rumor["event_id"], "mark_rumor", "已辟谣")
    locked = service.event_detail(rumor["event_id"])
    assert locked["verify_status"] == "rumor" and locked["locked_by_human"]
    with pytest.raises(service.EventRadarError):
        service.verify_event(rumor["event_id"], "confirm")


def test_custom_retrospective_requires_title(isolated_db: Any) -> None:
    with pytest.raises(service.EventRadarError):
        service.start_analysis(
            object(), event_id=None, mode="retrospective", event_title=" "
        )


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_http_scan_list_and_verify_flow(
    client: TestClient, isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sources, "collect", lambda scope="all": _fake_candidates())
    started = client.post("/events/scan", json={"scope": "all"})
    assert started.status_code == 200
    assert started.json()["status"] == "running"

    for _ in range(100):
        runs = client.get("/events/scan-runs").json()
        if runs and runs[0]["status"] in ("completed", "partial", "failed"):
            assert runs[0]["status"] == "completed"
            break
        time.sleep(0.05)

    items = client.get("/events/events").json()["items"]
    elnino = [e for e in items if "厄尔尼诺" in e["title"]][0]
    detail = client.get(f"/events/events/{elnino['event_id']}")
    assert detail.status_code == 200
    assert len(detail.json()["evidence"]) == 2


def test_http_analyze_unverified_conflict(
    client: TestClient, isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sources, "collect", lambda scope="all": _fake_candidates())
    client.post("/events/scan", json={"scope": "all"})
    for _ in range(100):
        runs = client.get("/events/scan-runs").json()
        if runs and runs[0]["status"] in ("completed", "partial", "failed"):
            break
        time.sleep(0.05)
    rumor = [
        e for e in client.get("/events/events").json()["items"]
        if "未经证实" in e["title"]
    ][0]
    resp = client.post(
        f"/events/events/{rumor['event_id']}/analyze", json={"mode": "live"}
    )
    assert resp.status_code == 409


def test_http_invalid_scope_rejected(client: TestClient, isolated_db: Any) -> None:
    resp = client.post("/events/scan", json={"scope": "moon"})
    assert resp.status_code == 422


def test_http_custom_retrospective_creates_report(
    client: TestClient, isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FakeRun:
        id = "run-fake-1"
        status = "running"

    class _FakeRuntime:
        def start_run(self, preset_name: str, user_vars: dict[str, Any]) -> Any:
            assert preset_name == service.PRESET_NAME
            assert user_vars["mode"] == "retrospective"
            return _FakeRun()

    monkeypatch.setattr(
        "src.api.event_routes._get_swarm_runtime", lambda: _FakeRuntime()
    )
    resp = client.post(
        "/events/analyze",
        json={"event_title": "新冠疫情", "event_period": "2020-01 至 2021-12"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "run-fake-1"
    reports = client.get("/events/reports").json()["items"]
    assert any(r["id"] == body["report_id"] and r["mode"] == "retrospective"
               for r in reports)


def test_preset_loads_with_four_role_chain() -> None:
    from src.swarm.presets import load_preset

    spec = load_preset(service.PRESET_NAME)
    assert [a["id"] for a in spec["agents"]] == [
        "event_scout", "impact_analyst", "historical_analyst", "strategist",
    ]
    assert [t["id"] for t in spec["tasks"]] == [
        "task-scout", "task-impact", "task-history", "task-strategy",
    ]
