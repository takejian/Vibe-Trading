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


def test_cls_sign_matches_rsshub_scheme() -> None:
    import hashlib

    from src.eventradar.sources import _cls_signed_params

    params = _cls_signed_params()
    encoded = "appName=CailianpressWeb&os=web&sv=8.7.9"
    expected = hashlib.md5(hashlib.sha1(encoded.encode()).hexdigest().encode())
    assert params["sign"] == expected.hexdigest()
    assert list(params)[:3] == ["appName", "os", "sv"]


def test_cls_depth_normalizer_shape() -> None:
    payload = {
        "data": {
            "top_article": [
                {"id": 1, "title": "头条一", "brief": "摘要一", "ctime": 1792042178},
            ],
            "depth_list": [
                {"id": 2, "title": "", "brief": "仅摘要的深度稿",
                 "ctime": 1792040760, "source": "财联社"},
                {"id": 1, "title": "重复头条", "brief": "x", "ctime": 1792042178},
                {"id": 3, "title": "", "brief": "", "ctime": None},
            ],
        }
    }
    items = sources._normalize_cls_depth(payload, "财联社·头条")
    assert [i["url"] for i in items] == [
        "https://www.cls.cn/detail/1", "https://www.cls.cn/detail/2"
    ]
    assert items[0]["origin"] == "investment-news-collector"
    assert items[1]["title"] == "仅摘要的深度稿"
    assert items[1]["published_at"] is not None


def test_wallstreetcn_normalizers() -> None:
    lives = sources._normalize_wsc_lives({"data": {"items": [
        {"id": 10, "content_text": "<p>美联储宣布降息25个基点</p>",
         "highlight_title": "", "uri": "https://wallstreetcn.com/livenews/10",
         "display_time": 1792044225},
        {"id": 11, "content_text": "", "uri": "x", "display_time": None},
    ]}})
    assert len(lives) == 1
    assert lives[0]["title"] == "美联储宣布降息25个基点"
    assert lives[0]["origin"] == "wallstreetcn-news"

    articles = sources._normalize_wsc_articles({"data": {"items": [
        {"resource_type": "article", "resource": {
            "id": 20, "title": "能源停火破裂？", "content_short": "泽连斯基称…",
            "uri": "https://wallstreetcn.com/articles/20",
            "display_time": 1792042935}},
    ]}})
    assert articles[0]["snippet"] == "泽连斯基称…"
    assert articles[0]["url"] == "https://wallstreetcn.com/articles/20"


def test_collect_scope_routes_to_curated_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cls_only = ({"name": "cls", "status": "ok", "count": 1},
                [{"url": "https://www.cls.cn/detail/1", "title": "财联社稿",
                  "snippet": "", "source_name": "财联社"}])
    wsc_only = ({"name": "wsc", "status": "ok", "count": 1},
                [{"url": "https://wallstreetcn.com/articles/2", "title": "见闻稿",
                  "snippet": "", "source_name": "华尔街见闻"}])
    monkeypatch.setattr(sources, "_CHINA_CHANNELS",
                        (lambda: cls_only,))
    monkeypatch.setattr(sources, "_GLOBAL_CHANNELS",
                        (lambda: wsc_only,))

    china = sources.collect("china")
    assert {c["url"] for c in china["candidates"]} == {
        "https://www.cls.cn/detail/1"
    }
    glob = sources.collect("global")
    assert {c["url"] for c in glob["candidates"]} == {
        "https://wallstreetcn.com/articles/2"
    }
    both = sources.collect("all")
    assert len(both["candidates"]) == 2


def test_collect_isolates_failed_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources, "_CHINA_CHANNELS", (
        lambda: ({"name": "cls", "status": "error", "count": 0}, []),
    ))
    monkeypatch.setattr(sources, "_GLOBAL_CHANNELS", (
        lambda: (
            {"name": "wsc", "status": "ok", "count": 1},
            [{"url": "https://wallstreetcn.com/articles/2", "title": "见闻稿",
              "snippet": "", "source_name": "华尔街见闻"}],
        ),
    ))
    out = sources.collect("all")
    assert {s["status"] for s in out["sources"]} == {"error", "ok"}
    assert len(out["candidates"]) == 1


def test_daily_scheduler_anchor_math() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.eventradar.scheduler import next_run_after, parse_daily_at

    assert parse_daily_at("04:00") == (4, 0)
    assert parse_daily_at("23:59") == (23, 59)
    assert parse_daily_at("24:00") is None
    assert parse_daily_at("x") is None

    tz = ZoneInfo("Asia/Shanghai")
    before = datetime(2026, 10, 15, 3, 59, tzinfo=tz)
    due = datetime(2026, 10, 15, 4, 0, tzinfo=tz)
    assert next_run_after(before, 4, 0) == due
    assert next_run_after(due, 4, 0) == datetime(2026, 10, 16, 4, 0, tzinfo=tz)


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


def test_top5_ranking_puts_confirmed_paradigm_first(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sources, "collect", lambda scope="all": _fake_candidates())
    service.start_scan("all", llm_factory=None)
    _wait_scan()
    top = service.list_events(limit=1)
    assert len(top) == 1
    assert "厄尔尼诺" in top[0]["title"]
    assert top[0]["verify_status"] == "confirmed"
    assert len(service.list_events(limit=5)) <= 5


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


# ===========================================================================
# v1.2: head-N collection, chart filtering
# ===========================================================================

def test_collect_truncates_each_channel_to_head_n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _eight_channel(label_root: str, url_root: str):
        cands = [
            {"url": f"{url_root}/{i}", "title": f"{label_root}新闻{i}",
             "snippet": "", "source_name": label_root}
            for i in range(8)
        ]
        return lambda: (
            {"name": label_root, "status": "ok", "count": 8}, cands
        )

    monkeypatch.setattr(sources, "_CHINA_CHANNELS", (
        _eight_channel("财联社·头条", "https://www.cls.cn/1000"),
        _eight_channel("财联社·环球", "https://www.cls.cn/1007"),
    ))
    monkeypatch.setattr(sources, "_GLOBAL_CHANNELS", (
        _eight_channel("华尔街见闻·7x24",
                       "https://wallstreetcn.com/livenews"),
        _eight_channel("华尔街见闻·全球",
                       "https://wallstreetcn.com/articles"),
    ))
    # collect() is the single head-N cut: china = two CLS columns x head-5;
    # all = four channels x head-5.
    china = sources.collect("china", head_n=5)
    assert len(china["candidates"]) == 10
    both = sources.collect("all", head_n=5)
    assert len(both["candidates"]) == 20


def test_chart_pages_are_junk() -> None:
    assert sources.is_junk(
        "美元指数走势图", "", "https://wallstreetcn.com/charts/dxy"
    )
    assert not sources.is_junk(
        "美联储宣布加息25个基点", "", "https://wallstreetcn.com/articles/9"
    )


def _six_distinct_candidates() -> dict[str, Any]:
    titles = [
        "以色列与哈马斯达成临时停火协议 人道物资进入加沙",
        "欧盟正式通过新一轮人工智能监管法案 2027年实施",
        "智利北部发生7.1级地震 矿区运营暂停",
        "日本央行意外加息25个基点 日元汇率大幅波动",
        "阿根廷与国际货币基金达成债务重组新协议",
        "红海航运保险费率单周上涨四成 货船绕行好望角",
    ]
    candidates = [
        {"url": f"https://www.cls.cn/detail/{500 + i}",
         "title": title, "snippet": "", "source_name": "财联社·头条",
         "published_at": f"2026-10-15 0{i+1}:00:00"}
        for i, title in enumerate(titles)
    ]
    return {"sources": [{"name": "cls", "status": "ok", "count": 6}],
            "candidates": candidates}


# ===========================================================================
# v1.2: daily Top-N snapshot + transient purge + archive/discard
# ===========================================================================

def test_scan_writes_top5_picks_and_purges_remaining(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sources, "collect",
                        lambda scope="all": _six_distinct_candidates())
    service.start_scan("all", llm_factory=None)
    _wait_scan()
    events = service.list_events(limit=50)
    picks = service.daily_picks()
    assert len(events) == 5            # 6 events → Top 5 kept, 1 purged
    assert [p["rank_position"] for p in picks] == [1, 2, 3, 4, 5]
    assert all(p["event_id"] for p in picks)


def test_archive_survives_purge_and_discard_cascades(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sources, "collect", lambda scope="all": _fake_candidates())
    service.start_scan("all", llm_factory=None)
    _wait_scan()
    elnino = [e for e in service.list_events() if "厄尔尼诺" in e["title"]][0]
    rumor = [e for e in service.list_events() if "未经证实" in e["title"]][0]

    archived = service.archive_event(elnino["event_id"], True)
    assert archived["archived"] is True
    service.discard_event(rumor["event_id"])
    with pytest.raises(service.EventNotFound):
        service.discard_event(rumor["event_id"])

    # Discard cascades: event gone, but its pick snapshot survives with a
    # nulled event_id (must check before the next scan rewrites today's picks).
    assert any(p["event_id"] is None for p in service.daily_picks())

    # A second scan purges transient events but keeps the archived one.
    service.start_scan("all", llm_factory=None)
    _wait_scan()
    assert service.event_detail(elnino["event_id"])["archived"] is True


def test_archive_list_leaderboard_and_pick_stats(
    isolated_db: Any,
) -> None:
    from src.eventradar import db as edb

    conn = edb.event_connection()
    edb.initialize_schema(conn)
    try:
        edb.insert_event(conn, {
            "event_id": "a1", "title": "长期事件甲", "event_type": "geopolitics",
            "cluster_key": "k-a1", "novelty_class": "new_paradigm",
            "verify_status": "verifying",
            "first_seen_at": "2026-10-10 00:00:00",
            "last_update_at": "2026-10-14 00:00:00",
        })
        edb.set_archived(conn, "a1", True)
        edb.insert_event(conn, {
            "event_id": "a2", "title": "长期事件乙", "event_type": "trade_tariff",
            "cluster_key": "k-a2", "novelty_class": "known_escalation",
            "verify_status": "confirmed",
            "first_seen_at": "2026-10-14 00:00:00",
            "last_update_at": "2026-10-14 00:00:00",
        })
        edb.set_archived(conn, "a2", True)
        for day in ("2026-10-12", "2026-10-13", "2026-10-14"):
            edb.upsert_daily_pick(
                conn, pick_date=day, rank_position=1, event_id="a1",
                title_snapshot="长期事件甲", source_channels=["财联社·头条"],
                scan_id=None,
            )
        edb.upsert_daily_pick(
            conn, pick_date="2026-10-14", rank_position=2, event_id="a2",
            title_snapshot="长期事件乙", source_channels=["华尔街见闻·7x24"],
            scan_id=None,
        )
    finally:
        conn.close()

    board = service.leaderboard(window_days=30)
    assert board[0]["event_id"] == "a1" and board[0]["pick_days"] == 3
    archive = service.list_archive()["items"]
    a1 = [a for a in archive if a["event_id"] == "a1"][0]
    assert a1["pick_days"] == 3
    assert a1["first_pick_date"] == "2026-10-12"
    by_date = service.list_archive(date_from="2026-10-14")["items"]
    assert {a["event_id"] for a in by_date} == {"a1", "a2"}


# ===========================================================================
# v1.2: tracking reviews
# ===========================================================================

def test_review_kinds_for_weekday_weekday_and_month_start() -> None:
    from datetime import datetime
    from src.eventradar import tracking

    wed = datetime(2026, 10, 14, 5, 0)   # Wednesday
    mon = datetime(2026, 10, 12, 5, 0)   # Monday
    first = datetime(2026, 11, 1, 5, 0)  # Sunday, day 1
    assert tracking.review_kinds_for(wed) == ["daily"]
    assert tracking.review_kinds_for(mon) == ["daily", "weekly"]
    assert tracking.review_kinds_for(first) == ["daily", "monthly"]


def test_manual_recheck_appends_evidence_and_confirms(
    isolated_db: Any,
) -> None:
    from src.eventradar import db as edb
    from src.eventradar import tracking

    conn = edb.event_connection()
    edb.initialize_schema(conn)
    try:
        edb.insert_event(conn, {
            "event_id": "t1", "title": "超强厄尔尼诺已形成 全球气候异常",
            "event_type": "climate_disaster", "entities": ["厄尔尼诺"],
            "cluster_key": "k-t1", "novelty_class": "new_paradigm",
            "verify_status": "verifying", "confidence": 0.4,
            "source_count": 1,
            "first_seen_at": "2026-10-13 00:00:00",
            "last_update_at": "2026-10-13 00:00:00",
        })
        edb.set_archived(conn, "t1", True)
        edb.insert_evidence(
            conn, event_id="t1",
            url="https://www.cls.cn/detail/old",
            source_name="财联社·头条", source_tier=2,
            title="厄尔尼诺形成", snippet="", published_at=None,
        )
    finally:
        conn.close()

    new_candidates = [
        {"url": "https://www.reuters.com/elnino-fresh",
         "title": "NOAA宣布超强厄尔尼诺形成 天气异常持续",
         "snippet": "reuters confirms el nino", "source_name": "reuters.com"},
        {"url": "https://www.cls.cn/detail/old",  # URL dedup: ignored
         "title": "厄尔尼诺形成", "snippet": "", "source_name": "财联社·头条"},
    ]
    review = tracking.recheck_event("t1", kind="manual", candidates=new_candidates)
    assert review["verdict"] == "true"
    assert review["status"] == "confirmed"
    assert review["actor"] == "manual"

    detail = service.event_detail("t1")
    assert detail["verify_status"] == "confirmed"
    assert detail["review_monthly"]["verdict"] == "true"
    assert len(detail["evidence"]) == 2


def test_manual_recheck_requires_archived_event(isolated_db: Any) -> None:
    from src.eventradar import db as edb
    from src.eventradar import tracking

    conn = edb.event_connection()
    edb.initialize_schema(conn)
    try:
        edb.insert_event(conn, {
            "event_id": "t2", "title": "未归档临时事件",
            "event_type": "politics", "cluster_key": "k-t2",
            "novelty_class": "known_continuation",
            "verify_status": "verifying",
            "first_seen_at": "2026-10-15 00:00:00",
            "last_update_at": "2026-10-15 00:00:00",
        })
    finally:
        conn.close()
    with pytest.raises(tracking.TrackingError):
        tracking.recheck_event("t2", kind="manual", candidates=[])


# ===========================================================================
# v1.2: TF candidates + report cancel/retry/evaluate
# ===========================================================================

def test_tf_candidates_only_fresh_confirmed(isolated_db: Any) -> None:
    from src.eventradar import db as edb

    conn = edb.event_connection()
    edb.initialize_schema(conn)
    try:
        edb.insert_event(conn, {
            "event_id": "old1", "title": "一个月前证实的事",
            "event_type": "politics", "cluster_key": "k-old",
            "novelty_class": "known_escalation",
            "verify_status": "confirmed",
            "first_seen_at": "2026-09-01 00:00:00",
            "last_update_at": "2026-09-02 00:00:00",
        })
        edb.insert_event(conn, {
            "event_id": "new1", "title": "昨天证实的事",
            "event_type": "politics", "cluster_key": "k-new",
            "novelty_class": "new_paradigm",
            "verify_status": "confirmed",
            "first_seen_at": "2026-10-14 00:00:00",
            "last_update_at": "2026-10-14 00:00:00",
        })
    finally:
        conn.close()
    ids = {e["event_id"] for e in service.tf_candidates(days=7)}
    assert ids == {"new1"}


_LIVE_MARKDOWN = """## 事件确认与定义
正文。
## 情景分析
正文。
## 传导链分析
正文。
## 跨资产与行业影响矩阵
正文。
## 受益与受损板块及标的线索
有色板块受益，关注铜与航运。
## 催化日历与跟踪指标
正文。
## 反方观点与证伪条件
正文。
<!-- EVENT-REPORT-META
expected_outcome: 通胀压力上行
guidance: 增持实物资产对冲
-->
"""


def test_report_cancel_retry_and_evaluate(
    isolated_db: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.eventradar import db as edb

    monkeypatch.setattr(sources, "collect", lambda scope="all": _fake_candidates())
    service.start_scan("all", llm_factory=None)
    _wait_scan()
    event_id = [
        e for e in service.list_events() if "厄尔尼诺" in e["title"]
    ][0]["event_id"]

    class _FakeRun:
        def __init__(self, run_id: str, status: str = "running") -> None:
            self.id = run_id
            self.status = status

    class _FakeRuntime:
        def __init__(self) -> None:
            self.cancelled: list[str] = []

        def start_run(self, preset_name: str, user_vars: dict[str, Any]) -> Any:
            return _FakeRun(f"run-{len(self.cancelled)}-{id(self)}")

        def cancel_run(self, run_id: str) -> bool:
            self.cancelled.append(run_id)
            return True

    runtime = _FakeRuntime()
    started = service.start_analysis(runtime, event_id=event_id)
    report_id = started["report_id"]
    canceled = service.cancel_report(runtime, report_id)
    assert canceled["status"] == "canceled" and canceled["canceled_at"]
    with pytest.raises(service.EventRadarError):
        service.cancel_report(runtime, report_id)

    # A failed report can be retried into a brand-new run/report.
    conn = edb.event_connection()
    edb.initialize_schema(conn)
    try:
        edb.insert_report(conn, {
            "id": "rep-failed", "event_id": event_id, "run_id": "run-dead",
            "mode": "live", "title": "失败报告", "market": "A股+全球",
            "time_horizon": "未来3-6个月", "status": "failed",
        })
        edb.insert_report(conn, {
            "id": "rep-done", "event_id": event_id, "run_id": "run-ok",
            "mode": "live", "title": "完成报告", "market": "A股+全球",
            "time_horizon": "未来3-6个月", "status": "completed",
            "markdown": _LIVE_MARKDOWN,
            "expected_outcome": "通胀压力上行",
            "guidance": "增持实物资产对冲",
            "completed_at": "2026-10-14 10:00:00",
        })
    finally:
        conn.close()
    retried = service.retry_report(runtime, "rep-failed")
    assert retried["report_id"] != "rep-failed"
    assert service.get_report(runtime, "rep-failed")["status"] == "failed"

    evaluated = service.evaluate_report("rep-done", {
        "rating": "accurate", "note": "方向正确",
        "period_start": "2026-10-15", "period_end": "2027-01-15",
    })
    assert evaluated["eval_rating"] == "accurate" and evaluated["evaluated_at"]
    assert evaluated["expected_outcome"] == "通胀压力上行"
    assert evaluated["guidance"] == "增持实物资产对冲"
    with pytest.raises(service.EventRadarError):
        service.evaluate_report("rep-done", {"rating": "bogus"})


# ===========================================================================
# v1.2: HTTP surface for archive / reviews / TF candidates
# ===========================================================================

def test_http_archive_recheck_and_tf_candidates(
    client: TestClient, isolated_db: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sources, "collect", lambda scope="all": _fake_candidates())
    client.post("/events/scan", json={"scope": "all"})
    for _ in range(100):
        runs = client.get("/events/scan-runs").json()
        if runs and runs[0]["status"] in ("completed", "partial", "failed"):
            break
        time.sleep(0.05)

    event_id = client.get(
        "/events/events?status=confirmed&limit=1"
    ).json()["items"][0]["event_id"]

    arch = client.post(f"/events/events/{event_id}/archive", json={"archived": True})
    assert arch.status_code == 200 and arch.json()["archived"] is True
    archive = client.get("/events/archive").json()["items"]
    assert any(a["event_id"] == event_id for a in archive)

    board = client.get("/events/archive/leaderboard").json()["items"]
    assert isinstance(board, list)
    picks = client.get("/events/daily-picks").json()["items"]
    assert len(picks) >= 1

    recheck = client.post(f"/events/events/{event_id}/recheck")
    assert recheck.status_code == 200
    assert recheck.json()["verdict"] in {
        "true", "false", "unverified", "error"
    }

    tf = client.get("/events/tf-candidates").json()["items"]
    assert any(e["event_id"] == event_id for e in tf)
