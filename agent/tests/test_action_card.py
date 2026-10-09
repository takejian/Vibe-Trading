"""Tests for the Chanlun section-8 action-card strict parser."""

from __future__ import annotations

import json

from src.watchlist.action_card import (
    PARSE_CONTRACT_VIOLATION,
    PARSE_NO_CARD,
    PARSE_OK,
    parse_action_card,
)

_BULLISH = {
    "schema_version": 1,
    "base_price": 23.76,
    "base_date": "2026-10-08",
    "direction": "bullish",
    "action": "buy",
    "confidence_pct": 62,
    "setup_class": "3买",
    "horizon_days": 20,
    "trigger_price": 24.10,
    "stop_price": 23.20,
    "target_prices": [25.60, 27.20],
    "rr_at_t1": 1.67,
    "invalidation": "收盘跌回23.20下方",
    "key_risks": "大盘回调",
    "one_liner": "三买待确认",
}


def _card_report(
    payload: dict, heading: str = "8. 操作结论卡 / Action Card"
) -> str:
    return (
        f"## {heading}\n\n```json\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n```\n"
    )


def test_bullish_card_ok() -> None:
    result = parse_action_card(_card_report(_BULLISH))
    assert result["parse"] == PARSE_OK
    card = result["card"]
    assert card is not None
    assert card["direction"] == "bullish"
    assert card["target_prices"] == [25.60, 27.20]
    assert card["base_price"] == 23.76
    assert card["confidence_pct"] == 62.0


def test_bearish_card_requires_stop_above_trigger() -> None:
    payload = {
        **_BULLISH,
        "direction": "bearish",
        "action": "sell",
        "setup_class": "1卖",
        "trigger_price": 22.0,
        "stop_price": 23.5,
        "target_prices": [20.5, 19.0],
    }
    result = parse_action_card(_card_report(payload))
    assert result["parse"] == PARSE_OK
    assert result["card"]["stop_price"] == 23.5


def test_neutral_card_requires_all_prices_null() -> None:
    payload = {
        **_BULLISH,
        "direction": "neutral",
        "action": "wait",
        "setup_class": "none",
        "trigger_price": None,
        "stop_price": None,
        "target_prices": None,
        "rr_at_t1": None,
    }
    result = parse_action_card(_card_report(payload))
    assert result["parse"] == PARSE_OK
    assert result["card"]["trigger_price"] is None


def test_heading_variants_cn_numeral_and_bold() -> None:
    result = parse_action_card(
        _card_report(_BULLISH, heading="**八、操作结论卡 Action Card**")
    )
    assert result["parse"] == PARSE_OK


def test_no_card_for_legacy_report() -> None:
    legacy = "\n".join(
        [
            "### 1、结构读取",
            "内容",
            "### 7、缠论打分",
            "打分：+2",
            "置信度：65%",
        ]
    )
    assert parse_action_card(legacy)["parse"] == PARSE_NO_CARD
    assert parse_action_card("")["parse"] == PARSE_NO_CARD


def test_section_with_prose_is_violation() -> None:
    report = "## 8. Action Card\n\n模型没有给JSON，只有一句话。\n"
    result = parse_action_card(report)
    assert result["parse"] == PARSE_CONTRACT_VIOLATION
    assert "fenced json" in result["error"]


def test_malformed_json_is_violation() -> None:
    report = "## 8. Action Card\n\n```json\n{not json\n```\n"
    result = parse_action_card(report)
    assert result["parse"] == PARSE_CONTRACT_VIOLATION
    assert result["card"] is None


def test_missing_base_price_is_violation() -> None:
    payload = {k: v for k, v in _BULLISH.items() if k != "base_price"}
    result = parse_action_card(_card_report(payload))
    assert result["parse"] == PARSE_CONTRACT_VIOLATION
    assert "base_price" in result["error"]


def test_long_stop_must_be_below_trigger() -> None:
    payload = {**_BULLISH, "stop_price": 25.0}
    result = parse_action_card(_card_report(payload))
    assert result["parse"] == PARSE_CONTRACT_VIOLATION
    assert "stop" in result["error"]


def test_targets_must_be_ascending() -> None:
    payload = {**_BULLISH, "target_prices": [27.2, 25.6]}
    result = parse_action_card(_card_report(payload))
    assert result["parse"] == PARSE_CONTRACT_VIOLATION


def test_neutral_with_prices_is_violation() -> None:
    payload = {
        **_BULLISH,
        "direction": "neutral",
        "action": "wait",
        "setup_class": "none",
    }
    result = parse_action_card(_card_report(payload))
    assert result["parse"] == PARSE_CONTRACT_VIOLATION


def test_direction_action_mismatch_is_violation() -> None:
    payload = {
        **_BULLISH,
        "direction": "bearish",
        "action": "buy",
        "setup_class": "1卖",
    }
    result = parse_action_card(_card_report(payload))
    assert result["parse"] == PARSE_CONTRACT_VIOLATION


def test_bullish_with_sell_setup_is_violation() -> None:
    payload = {**_BULLISH, "setup_class": "2卖"}
    result = parse_action_card(_card_report(payload))
    assert result["parse"] == PARSE_CONTRACT_VIOLATION


def test_bad_date_and_horizon_are_violations() -> None:
    payload = {**_BULLISH, "base_date": "2026-13-40"}
    assert (
        parse_action_card(_card_report(payload))["parse"]
        == PARSE_CONTRACT_VIOLATION
    )
    payload = {**_BULLISH, "horizon_days": 999}
    assert (
        parse_action_card(_card_report(payload))["parse"]
        == PARSE_CONTRACT_VIOLATION
    )


def test_hold_without_plan_is_ok() -> None:
    payload = {
        **_BULLISH,
        "action": "hold",
        "trigger_price": None,
        "stop_price": None,
        "target_prices": None,
        "rr_at_t1": None,
    }
    result = parse_action_card(_card_report(payload))
    assert result["parse"] == PARSE_OK
