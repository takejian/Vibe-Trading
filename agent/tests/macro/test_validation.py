"""Strict JSON / vocabulary validation for prompt-a outputs."""

from __future__ import annotations

import json

import pytest

from src.macro.service import parse_judgment_payload


def _payload_dict(**overrides):
    payload = {
        "economy": "中国",
        "statistics_date": "2026-08",
        "current_cycle": "复苏期，经济活动逐步修复。",
        "judgment_result": "复苏期。",
        "dimension_check": "四维校验。",
        "meso_verify": "中观验证。",
        "history_cycle_anchor": "历史锚定。",
        "judgment_confidence": "中",
        "core_support": "核心支撑。",
        "core_risk": "核心风险。",
        "extended_remark": "",
    }
    payload.update(overrides)
    return payload


def test_valid_payload_with_transition_description_passes():
    raw = json.dumps(_payload_dict(current_cycle="复苏期向过热期过渡"), ensure_ascii=False)
    payload, reason = parse_judgment_payload(raw)
    assert payload is not None and reason is None


def test_markdown_fenced_output_is_rejected():
    raw = "```json\n" + json.dumps(_payload_dict(), ensure_ascii=False) + "\n```"
    payload, reason = parse_judgment_payload(raw)
    assert payload is None
    assert "JSON" in reason


def test_output_with_extra_text_is_rejected():
    raw = "好的，分析结果如下：" + json.dumps(_payload_dict(), ensure_ascii=False)
    payload, reason = parse_judgment_payload(raw)
    assert payload is None


@pytest.mark.parametrize("stage", ["衰退期", "复苏期", "过热期", "滞胀期"])
def test_each_standard_stage_passes(stage):
    payload, reason = parse_judgment_payload(
        json.dumps(_payload_dict(current_cycle=stage), ensure_ascii=False)
    )
    assert payload is not None, reason


@pytest.mark.parametrize("bad_stage", ["扩张期", "萧条期", "reflation", ""])
def test_non_standard_stage_rejected(bad_stage):
    payload, reason = parse_judgment_payload(
        json.dumps(_payload_dict(current_cycle=bad_stage or "繁荣向上"), ensure_ascii=False)
    )
    assert payload is None
    assert "周期阶段" in reason


@pytest.mark.parametrize("level", ["高", "中", "低"])
def test_confidence_levels_pass(level):
    payload, _ = parse_judgment_payload(
        json.dumps(_payload_dict(judgment_confidence=level), ensure_ascii=False)
    )
    assert payload is not None


def test_non_standard_confidence_rejected():
    # Values containing none of 高/中/低 (and not English placeholders) fail.
    payload, reason = parse_judgment_payload(
        json.dumps(_payload_dict(judgment_confidence="不确定"), ensure_ascii=False)
    )
    assert payload is None
    assert "置信度" in reason


@pytest.mark.parametrize("missing_field", [
    "economy",
    "statistics_date",
    "current_cycle",
    "judgment_result",
    "dimension_check",
    "meso_verify",
    "history_cycle_anchor",
    "judgment_confidence",
    "core_support",
    "core_risk",
])
def test_missing_required_field_rejected(missing_field):
    data = _payload_dict()
    del data[missing_field]
    payload, reason = parse_judgment_payload(json.dumps(data, ensure_ascii=False))
    assert payload is None
    assert missing_field in reason


def test_empty_extended_remark_allowed_but_others_must_be_nonempty():
    assert parse_judgment_payload(json.dumps(_payload_dict(extended_remark=""), ensure_ascii=False))[0]
    payload, reason = parse_judgment_payload(
        json.dumps(_payload_dict(core_risk="   "), ensure_ascii=False)
    )
    assert payload is None and "core_risk" in reason


def test_empty_and_non_dict_outputs_rejected():
    assert parse_judgment_payload("")[0] is None
    assert parse_judgment_payload(None)[0] is None
    assert parse_judgment_payload(json.dumps(["not", "object"]), )[0] is None
