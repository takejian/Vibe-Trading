"""二期服务编排测试：claims 判定 -> AI 复盘 -> 人工点评。"""

from __future__ import annotations

import json

import pytest

from src.macro_synthesis.db import MacroSynthesisRepository
from src.macro_synthesis.models import (
    CLAIM_STATUS_HIT,
    REVIEW_TYPE_AI,
    REVIEW_TYPE_MANUAL,
)
from src.macro_synthesis.service import (
    MacroSynthesisService,
    SynthesisServiceError,
)
from src.swarm.store import SwarmStore


class _Response:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, messages, tools=None, timeout=None):
        return _Response(self.content)


def _seed_market_tables(repo: MacroSynthesisRepository) -> None:
    conn = repo._conn
    conn.execute(
        "CREATE TABLE IF NOT EXISTS daily_bar "
        "(symbol VARCHAR, trade_date DATE, close DOUBLE)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fx_rate (base VARCHAR, quote VARCHAR, "
        "rate_date DATE, rate DOUBLE, rate_type VARCHAR)"
    )
    # 沪深300 9/25 收 3950 → hit；窗口前基准 3800
    conn.execute(
        "INSERT INTO daily_bar VALUES ('000300.SH', DATE '2026-09-25', 3950)"
    )
    conn.execute(
        "INSERT INTO daily_bar VALUES ('000300.SH', DATE '2026-08-28', 3800)"
    )
    # USDCNY 9/25 = 7.10 → <=7.12 hit
    conn.execute(
        "INSERT INTO fx_rate VALUES ('USD','CNY', DATE '2026-09-25', 7.10,'reference')"
    )
    conn.execute(
        "INSERT INTO fx_rate VALUES ('USD','CNY', DATE '2026-08-28', 7.18,'reference')"
    )


def _review_json() -> str:
    return json.dumps(
        {
            "comment": "总体看，原报告对权益与汇率的判断得到数据支持，节奏把握较好。",
            "attribution": "暂无明显偏差；需警惕模型在政策预期上的偏多倾向。",
            "lessons": "下期继续跟踪库存周期，并对政策力度假设保持审慎。",
        },
        ensure_ascii=False,
    )


def test_verify_then_ai_review(tmp_path, market_payload) -> None:
    db_file = tmp_path / "market.duckdb"
    repo = MacroSynthesisRepository(db_path=db_file)
    _seed_market_tables(repo)

    syn_llm = FakeLLM(json.dumps(market_payload(), ensure_ascii=False))
    review_llm = FakeLLM(_review_json())
    llms = iter([syn_llm, review_llm])

    service = MacroSynthesisService(
        repository=repo,
        llm_factory=lambda: next(llms),
        store=SwarmStore(tmp_path / "swarm"),
    )

    report, _ = service.synthesize("中国", "month", "2026-09")
    # 汇总刚生成，claims 仍 pending
    assert all(claim.status == "pending" for claim in report.claims)

    verified = service.verify_report(report.id)
    statuses = {claim.metric: claim.status for claim in verified.claims}
    assert statuses["CSI300"] == CLAIM_STATUS_HIT
    assert statuses["USDCNY"] == CLAIM_STATUS_HIT

    reviewed, stored_review = service.ai_review(report.id)
    assert stored_review.review_type == REVIEW_TYPE_AI
    assert stored_review.hit_rate is not None and stored_review.hit_rate > 0
    assert stored_review.brier_score is not None
    assert stored_review.attribution
    # 报告携带 review
    assert any(r.review_type == REVIEW_TYPE_AI for r in reviewed.reviews)


def test_ai_review_blocked_when_no_resolved(tmp_path, payload_llm, valid_payload) -> None:
    db_file = tmp_path / "market.duckdb"
    repo = MacroSynthesisRepository(db_path=db_file)
    factory, _ = payload_llm
    service = MacroSynthesisService(
        repository=repo,
        llm_factory=lambda: factory(valid_payload()),
        store=SwarmStore(tmp_path / "swarm"),
    )
    report, _ = service.synthesize("中国", "month", "2026-09")
    with pytest.raises(SynthesisServiceError):
        service.ai_review(report.id)


def test_add_manual_comment(tmp_path, payload_llm, valid_payload) -> None:
    db_file = tmp_path / "market.duckdb"
    repo = MacroSynthesisRepository(db_path=db_file)
    factory, _ = payload_llm
    service = MacroSynthesisService(
        repository=repo,
        llm_factory=lambda: factory(valid_payload()),
        store=SwarmStore(tmp_path / "swarm"),
    )
    report, _ = service.synthesize("中国", "month", "2026-09")

    updated = service.add_comment(report.id, "我的人工点评：结论偏乐观。", hit_rate=0.5)
    manual = [r for r in updated.reviews if r.review_type == REVIEW_TYPE_MANUAL]
    assert len(manual) == 1
    assert manual[0].comment == "我的人工点评：结论偏乐观。"
    assert manual[0].hit_rate == 0.5
    assert manual[0].reviewer == "user"

    # 空点评 / 非法评分
    with pytest.raises(SynthesisServiceError):
        service.add_comment(report.id, "  ")
    with pytest.raises(SynthesisServiceError):
        service.add_comment(report.id, "x", hit_rate=1.5)
