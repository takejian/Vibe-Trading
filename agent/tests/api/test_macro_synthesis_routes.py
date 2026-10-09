"""HTTP contract tests for /api/macro/synthesis/* routes (real service, fakes injected)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import duckdb
import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import macro_synthesis_routes
from src.macro_synthesis.db import MacroSynthesisRepository
from src.macro_synthesis.service import MacroSynthesisService
from src.swarm.store import SwarmStore
from tests.macro_synthesis.conftest import FakeLLM, write_team_run

_ORIGINAL_GET_SERVICE = macro_synthesis_routes.get_synthesis_service

_DIM_KEYS = ["growth", "inflation", "money", "external", "synthesis"]


def _payload_json() -> str:
    payload = {
        "summary": "总体宏观结论，描述现状、核心矛盾与短期展望。",
        "action_advice": "维持权益超配，关注下月数据与政策窗口。",
        "dimensions": [
            {"dimension": d, "signal": 1, "confidence": 0.7,
             "trend": "up", "rationale": "理由"}
            for d in _DIM_KEYS
        ],
        "cycle_probs": {"recovery": 0.4, "overheat": 0.3,
                        "stagflation": 0.1, "recession": 0.2},
        "allocation": {"equity": 1, "bond": 0, "commodity": -1, "cash": 0},
        "risk_triggers": ["风险条件一", "风险条件二"],
        "claims": [
            {"dimension": "growth",
             "text": f"11月官方制造业PMI回升至49.5以上（命题{i}）",
             "metric": "CN_PMI", "direction": "up", "predicted_value": ">=49.5",
             "probability": 0.6, "window_start": "2026-12-01",
             "window_end": "2026-12-10", "verify_source": "cn_macro_monthly"}
            for i in range(5)
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    repo = MacroSynthesisRepository(conn=duckdb.connect(":memory:"))
    store = SwarmStore(tmp_path)
    llm_holder: dict[str, FakeLLM] = {}

    def fresh_service() -> MacroSynthesisService:
        return MacroSynthesisService(
            repository=repo,
            store=store,
            llm_factory=(lambda: llm_holder["llm"]) if llm_holder else None,
        )

    api_server.app.dependency_overrides[_ORIGINAL_GET_SERVICE] = fresh_service
    client = TestClient(api_server.app, client=("127.0.0.1", 50002))
    try:
        yield SimpleNamespace(
            client=client,
            store=store,
            repo=repo,
            set_llm=lambda content: llm_holder.update(llm=FakeLLM(content)),
        )
    finally:
        api_server.app.dependency_overrides.pop(_ORIGINAL_GET_SERVICE, None)


def test_coverage_empty(harness) -> None:
    res = harness.client.get(
        "/api/macro/synthesis/coverage",
        params={"economy": "中国", "period_type": "month", "period": "2026-10"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["all_covered"] is False
    assert len(data["teams"]) == 4
    assert data["period_label"] == "2026年10月"


def test_coverage_with_run(harness) -> None:
    write_team_run(
        harness.store, "r1", "macro_strategy_forum",
        "2026-10-08T10:00:00+00:00",
    )
    res = harness.client.get(
        "/api/macro/synthesis/coverage",
        params={"economy": "中国", "period_type": "month", "period": "2026-10"},
    )
    teams = {item["team"]: item for item in res.json()["teams"]}
    assert teams["macro_strategy_forum"]["present"] is True
    assert teams["macro_rates_fx_desk"]["present"] is False


def test_create_and_fetch_report(harness) -> None:
    harness.set_llm(_payload_json())
    res = harness.client.post(
        "/api/macro/synthesis/reports",
        json={"economy": "中国", "period_type": "month", "period": "2026-10"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["cached"] is False
    report = body["report"]
    assert report["claim_count"] == 5
    assert len(report["dimensions"]) == 5

    report_id = report["id"]
    listing = harness.client.get(
        "/api/macro/synthesis/reports", params={"economy": "中国"}
    )
    assert listing.status_code == 200
    assert len(listing.json()["reports"]) == 1

    detail = harness.client.get(f"/api/macro/synthesis/reports/{report_id}")
    assert detail.status_code == 200
    assert detail.json()["report"]["id"] == report_id

    missing = harness.client.get("/api/macro/synthesis/reports/99999")
    assert missing.status_code == 404


def test_create_invalid_period(harness) -> None:
    harness.set_llm(_payload_json())
    res = harness.client.post(
        "/api/macro/synthesis/reports",
        json={"economy": "中国", "period_type": "month", "period": "bad"},
    )
    assert res.status_code == 400


def test_create_cached(harness) -> None:
    harness.set_llm(_payload_json())
    body = {"economy": "中国", "period_type": "quarter", "period": "2026-Q4"}
    first = harness.client.post("/api/macro/synthesis/reports", json=body)
    assert first.json()["cached"] is False
    second = harness.client.post("/api/macro/synthesis/reports", json=body)
    assert second.status_code == 200
    assert second.json()["cached"] is True

def _market_payload_json() -> str:
    payload = {
        "summary": "总体结论。",
        "action_advice": "操作建议。",
        "dimensions": [
            {"dimension": d, "signal": 1, "confidence": 0.7, "trend": "up",
             "rationale": "理由"}
            for d in _DIM_KEYS
        ],
        "cycle_probs": {"recovery": 0.4, "overheat": 0.3,
                        "stagflation": 0.1, "recession": 0.2},
        "allocation": {"equity": 1, "bond": 0, "commodity": -1, "cash": 0},
        "risk_triggers": ["条件一", "条件二"],
        "claims": [
            {"dimension": "synthesis", "text": "沪深300 9月收于3900以上",
             "metric": "CSI300", "direction": "up", "predicted_value": ">=3900",
             "probability": 0.6, "window_start": "2026-09-01",
             "window_end": "2026-09-30", "verify_source": "daily_bar"},
        ]
        + [
            {"dimension": "growth",
             "text": f"宏观指标命题（命题{i}），本地暂无数据",
             "metric": "CN_PMI", "direction": "up",
             "predicted_value": ">=49.5", "probability": 0.6,
             "window_start": "2026-09-01", "window_end": "2026-09-30",
             "verify_source": "cn_macro_monthly"}
            for i in range(4)
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _review_payload_json() -> str:
    return json.dumps(
        {"comment": "AI 复盘点评内容。",
         "attribution": "偏差归因说明。",
         "lessons": "下期改进建议。"},
        ensure_ascii=False,
    )


def test_verify_missing_then_hit_and_ai_review(harness) -> None:
    harness.set_llm(_market_payload_json())
    created = harness.client.post(
        "/api/macro/synthesis/reports",
        json={"economy": "中国", "period_type": "month", "period": "2026-09"},
    )
    report_id = created.json()["report"]["id"]

    # 首次 verify：无 daily_bar 表 -> data_missing（容错不 500）
    verified = harness.client.post(
        f"/api/macro/synthesis/reports/{report_id}/verify"
    )
    assert verified.status_code == 200
    claim0 = verified.json()["report"]["claims"][0]
    assert claim0["status"] == "data_missing"

    # 灌入行情数据后重新 verify
    conn = harness.repo._conn
    conn.execute(
        "CREATE TABLE daily_bar (symbol VARCHAR, trade_date DATE, close DOUBLE)"
    )
    conn.execute(
        "INSERT INTO daily_bar VALUES ('000300.SH', DATE '2026-09-25', 3950)"
    )
    verified2 = harness.client.post(
        f"/api/macro/synthesis/reports/{report_id}/verify"
    )
    statuses = [c["status"] for c in verified2.json()["report"]["claims"]]
    assert statuses[0] == "hit"

    # AI 复盘：先把 review payload 换上
    harness.set_llm(_review_payload_json())
    review_res = harness.client.post(
        f"/api/macro/synthesis/reports/{report_id}/review"
    )
    assert review_res.status_code == 200
    review = review_res.json()["review"]
    assert review["review_type"] == "ai"
    assert review["hit_rate"] == 1.0
    assert review["attribution"]

    # 人工点评
    comment_res = harness.client.post(
        f"/api/macro/synthesis/reports/{report_id}/comments",
        json={"comment": "我的点评", "hit_rate": 0.8},
    )
    assert comment_res.status_code == 200
    types = [r["review_type"] for r in comment_res.json()["report"]["reviews"]]
    assert "ai" in types and "manual" in types

    # 空点评被拒
    bad = harness.client.post(
        f"/api/macro/synthesis/reports/{report_id}/comments",
        json={"comment": ""},
    )
    assert bad.status_code == 422


def test_review_unknown_report(harness) -> None:
    res = harness.client.post("/api/macro/synthesis/reports/99999/review")
    assert res.status_code == 400
