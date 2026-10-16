"""细分品类配置与汇总服务的集成测试。"""

from __future__ import annotations

from src.macro_synthesis.db import MacroSynthesisRepository
from src.macro_synthesis.service import MacroSynthesisService
from src.swarm.store import SwarmStore


def test_synthesize_persists_allocation_details(
    tmp_path, payload_llm, valid_payload
) -> None:
    repo = MacroSynthesisRepository(db_path=tmp_path / "market.duckdb")
    factory, _ = payload_llm
    service = MacroSynthesisService(
        repository=repo,
        llm_factory=lambda: factory(valid_payload()),
        store=SwarmStore(tmp_path / "swarm"),
    )

    report, cached = service.synthesize("中国", "month", "2026-10")
    assert cached is False
    assert len(report.allocation_details) == 13
    assert report.posture in ("offensive", "balanced", "defensive")
    assert report.risk_budget is not None and 0.15 <= report.risk_budget <= 0.85

    # 权重合计 100%
    total = sum(d.weight_mid for d in report.allocation_details)
    assert abs(total - 1.0) < 1e-6

    # 四大类评级来自引擎，落库后 hydrate 仍一致
    reloaded = repo.get_report_by_id(report.id)
    assert reloaded is not None
    assert len(reloaded.allocation_details) == 13
    assert reloaded.posture == report.posture
    groups = {d.asset_group for d in reloaded.allocation_details}
    assert groups == {"equity", "bond", "commodity", "property", "cash"}

    payload = report.to_dict()
    assert len(payload["allocation_details"]) == 13
    assert payload["posture"]
    assert set(payload["allocation"]) == {"equity", "bond", "commodity", "cash"}


def test_backfill_for_legacy_report(tmp_path, payload_llm, valid_payload) -> None:
    """旧报告无明细行：hydrate 现算可用，backfill 后持久化。"""
    repo = MacroSynthesisRepository(db_path=tmp_path / "market.duckdb")
    factory, _ = payload_llm
    service = MacroSynthesisService(
        repository=repo,
        llm_factory=lambda: factory(valid_payload()),
        store=SwarmStore(tmp_path / "swarm"),
    )
    report, _ = service.synthesize("中国", "month", "2026-09")

    # 模拟旧报告：删明细 + 清形态列
    conn = repo._conn
    conn.execute(
        "DELETE FROM macro_synthesis_allocation_detail WHERE report_id = ?",
        [report.id],
    )
    conn.execute(
        "UPDATE macro_synthesis_report SET risk_budget = NULL, posture = NULL WHERE id = ?",
        [report.id],
    )

    # hydrate 现算：GET 不报错且有明细
    lazy = repo.get_report_by_id(report.id)
    assert lazy is not None
    assert len(lazy.allocation_details) == 13
    assert lazy.posture in ("offensive", "balanced", "defensive")

    # 持久化回填
    filled = service.backfill_allocation(report.id)
    assert len(filled.allocation_details) == 13
    assert filled.risk_budget is not None
    count = conn.execute(
        "SELECT COUNT(*) FROM macro_synthesis_allocation_detail WHERE report_id = ?",
        [report.id],
    ).fetchone()[0]
    assert count == 13
    assert filled.posture == conn.execute(
        "SELECT posture FROM macro_synthesis_report WHERE id = ?", [report.id]
    ).fetchone()[0]


def test_backfill_unknown_report(tmp_path) -> None:
    import pytest

    repo = MacroSynthesisRepository(db_path=tmp_path / "market.duckdb")
    service = MacroSynthesisService(repository=repo)
    with pytest.raises(Exception):
        service.backfill_allocation(99999)
