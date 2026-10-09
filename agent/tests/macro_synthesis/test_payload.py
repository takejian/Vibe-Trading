"""LLM payload 严格校验与量化计算测试。"""

from __future__ import annotations

import json

import pytest

from src.macro_synthesis.models import (
    CYCLE_KEYS,
    DIMENSION_TEAMS,
    TeamCoverage,
)
from src.macro_synthesis.service import (
    _build_dimensions,
    _compute_mcs,
    _normalize_cycle_probs,
    parse_synthesis_payload,
)


def test_parse_valid(valid_payload) -> None:
    raw = json.dumps(valid_payload(), ensure_ascii=False)
    payload, reason = parse_synthesis_payload(raw)
    assert payload is not None
    assert reason is None


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda p: p.pop("summary"), None),
        (lambda p: p.update(summary=""), None),
        (lambda p: p["dimensions"].pop(0), "五个维度"),
        (lambda p: p["dimensions"][0].update(signal=3), "-2..2"),
        (lambda p: p["dimensions"][0].update(confidence=1.5), "0..1"),
        (lambda p: p["dimensions"][0].update(trend="sideways"), "up/down/flat"),
        (lambda p: p["cycle_probs"].update(recovery=2), "0..1"),
        (lambda p: p["cycle_probs"].update(recovery=0.0), None),
        (lambda p: p["allocation"].update(equity=3), "-2..2"),
        (lambda p: p.update(risk_triggers=[]), "1~5"),
        (lambda p: p.update(claims=p["claims"][:3]), "5~10"),
        (lambda p: p["claims"][0].update(window_start="2027-01-01"), "窗口"),
        (lambda p: p["claims"][0].update(window_end="bad-date"), "YYYY-MM-DD"),
    ],
)
def test_parse_invalid(valid_payload, mutate, fragment) -> None:
    data = valid_payload()
    mutate(data)
    payload, reason = parse_synthesis_payload(json.dumps(data, ensure_ascii=False))
    assert payload is None
    assert reason
    if fragment:
        assert fragment in reason


def test_parse_non_json() -> None:
    assert parse_synthesis_payload("not json")[0] is None
    assert parse_synthesis_payload("")[0] is None
    assert parse_synthesis_payload(json.dumps([1, 2]))[0] is None


def test_compute_mcs_neutral(valid_payload) -> None:
    dims = _build_dimensions(valid_payload(signal=0), [])
    assert _compute_mcs(dims) == 50.0


def test_compute_mcs_extremes(valid_payload) -> None:
    strong = _build_dimensions(valid_payload(signal=2), [])
    # 将置信度统一为 1：confidence_factor=1，raw=2 -> 50+50=100
    dims_conf1 = [d.__class__(**{**d.__dict__, "confidence": 1.0}) for d in strong]
    assert _compute_mcs(dims_conf1) == 100.0

    weak_payload = valid_payload(signal=-2)
    weak = _build_dimensions(weak_payload, [])
    dims_conf1 = [d.__class__(**{**d.__dict__, "confidence": 1.0}) for d in weak]
    assert _compute_mcs(dims_conf1) == 0.0


def test_normalize_cycle_probs(valid_payload) -> None:
    data = valid_payload()
    data["cycle_probs"] = dict(zip(CYCLE_KEYS, (2, 2, 2, 2)))
    normalized = _normalize_cycle_probs(data)
    assert sum(normalized.values()) == pytest.approx(1.0, abs=0.01)


def test_build_dimensions_sources(valid_payload) -> None:
    teams = [
        TeamCoverage(
            team="macro_strategy_forum",
            title="宏观策略",
            present=True,
            run_id="run-a",
        ),
        TeamCoverage(team="macro_rates_fx_desk", title="利率外汇", present=False),
        TeamCoverage(team="geopolitical_war_room", title="地缘分析", present=False),
        TeamCoverage(team="sector_rotation_team", title="资产轮转", present=False),
    ]
    dims = _build_dimensions(valid_payload(), teams)
    by_key = {d.dimension: d for d in dims}
    # growth 关联 macro_strategy_forum 与 sector_rotation_team，仅前者有 run
    assert by_key["growth"].source_run_ids == ["run-a"]
    # money 关联 macro_rates_fx_desk（缺）与 macro_strategy_forum（有）
    assert by_key["money"].source_run_ids == ["run-a"]
    assert by_key["synthesis"].source_run_ids == []
    # 权重来自固定表
    for dim in dims:
        assert dim.weight  # 非零
    assert set(DIMENSION_TEAMS.keys()) == {d.dimension for d in dims}
