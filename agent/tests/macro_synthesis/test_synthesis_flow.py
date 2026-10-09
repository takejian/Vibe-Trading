"""端到端汇总编排测试（内存 DuckDB + 伪 LLM + 临时 swarm 目录）。"""

from __future__ import annotations

import duckdb
import pytest

from src.macro_synthesis.db import MacroSynthesisRepository
from src.macro_synthesis.service import (
    MacroSynthesisService,
    SynthesisFailedError,
)
from src.swarm.store import SwarmStore


def _service(tmp_path, repo, llm) -> MacroSynthesisService:
    return MacroSynthesisService(
        repository=repo,
        llm_factory=lambda: llm,
        store=SwarmStore(tmp_path),
    )


def test_synthesize_partial_coverage(
    tmp_path, payload_llm, valid_payload, run_writer
) -> None:
    factory, _holder = payload_llm
    llm = factory(valid_payload())

    store = SwarmStore(tmp_path)
    run_writer(store, "run-1", "macro_strategy_forum", "2026-10-08T10:00:00+00:00")
    run_writer(store, "run-4", "sector_rotation_team", "2026-10-07T10:00:00+00:00")
    # 9 月结论不应被归集到 10 月
    run_writer(store, "run-old", "macro_strategy_forum", "2026-09-08T10:00:00+00:00")

    repo = MacroSynthesisRepository(conn=duckdb.connect(":memory:"))
    service = _service(tmp_path, repo, llm)

    report, cached = service.synthesize("中国", "month", "2026-10")
    assert cached is False
    assert report.id is not None
    present = [team for team in report.teams if team.present]
    assert len(present) == 2
    assert report.all_covered is False
    assert report.claim_count == 5
    assert all(claim.status == "pending" for claim in report.claims)
    assert report.period_label == "2026年10月"
    assert "growth" in {d.dimension for d in report.dimensions}


def test_synthesize_cached(tmp_path, payload_llm, valid_payload) -> None:
    factory, _holder = payload_llm
    repo = MacroSynthesisRepository(conn=duckdb.connect(":memory:"))
    service = _service(tmp_path, repo, factory(valid_payload()))

    first, cached = service.synthesize("中国", "month", "2026-10")
    assert cached is False
    second, cached2 = service.synthesize("中国", "month", "2026-10")
    assert cached2 is True
    assert second.id == first.id


def test_synthesize_no_coverage(tmp_path, payload_llm, valid_payload) -> None:
    factory, _holder = payload_llm
    repo = MacroSynthesisRepository(conn=duckdb.connect(":memory:"))
    service = _service(tmp_path, repo, factory(valid_payload()))

    report, cached = service.synthesize("美国", "quarter", "2026-Q4")
    assert cached is False
    assert all(not team.present for team in report.teams)
    assert report.period_label == "2026年第四季度"


def test_synthesize_invalid_output_retries(tmp_path, payload_llm) -> None:
    factory, holder = payload_llm
    bad_llm = factory({"unexpected": 1})
    repo = MacroSynthesisRepository(conn=duckdb.connect(":memory:"))
    service = _service(tmp_path, repo, bad_llm)

    with pytest.raises(SynthesisFailedError):
        service.synthesize("中国", "month", "2026-10")
    # 初次 + 一次重试
    assert len(bad_llm.calls) == 2


def test_synthesize_mcs_delta(tmp_path, payload_llm, valid_payload) -> None:
    factory, _holder = payload_llm
    llm_strong = factory(valid_payload(signal=2))
    llm_neutral = factory(valid_payload(signal=0))
    llms = iter([llm_strong, llm_neutral])

    repo = MacroSynthesisRepository(conn=duckdb.connect(":memory:"))
    service = MacroSynthesisService(
        repository=repo,
        llm_factory=lambda: next(llms),
        store=SwarmStore(tmp_path),
    )

    first, _ = service.synthesize("中国", "month", "2026-09")
    assert first.mcs_delta is None  # 首期无环比
    second, _ = service.synthesize("中国", "month", "2026-10")
    assert second.mcs_delta is not None
    assert second.mcs_delta == round(second.mcs - first.mcs, 1)
    assert second.mcs_delta < 0
