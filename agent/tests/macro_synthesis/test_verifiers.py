"""Claims 条件解析与判定测试。"""

from __future__ import annotations

import duckdb

from src.macro_synthesis.models import (
    CLAIM_STATUS_DATA_MISSING,
    CLAIM_STATUS_HIT,
    CLAIM_STATUS_MISS,
    CLAIM_STATUS_PARTIAL,
    SynthesisClaim,
)
from src.macro_synthesis.verifiers import (
    ActualObservation,
    judge,
    parse_predicate,
    verify_claim,
)


def test_parse_threshold() -> None:
    rule = parse_predicate(">=49.5")
    assert rule == {"kind": "threshold", "op": ">=", "value": 49.5}
    assert parse_predicate("≤ 50")["op"] == "<="
    assert parse_predicate("49.5")["kind"] == "threshold"


def test_parse_interval() -> None:
    rule = parse_predicate("49.0~50.0")
    assert rule["kind"] == "interval"
    assert rule["low"] == 49.0 and rule["high"] == 50.0
    rule2 = parse_predicate("50.0 - 49.0")
    assert rule2["low"] == 49.0  # 自动纠正颠倒


def test_parse_rel_change() -> None:
    rule = parse_predicate(">1%")
    assert rule == {"kind": "rel_change", "op": ">", "value": 1.0}


def test_parse_direction_fallback() -> None:
    assert parse_predicate("小幅回升")["kind"] == "direction"
    assert parse_predicate("")["kind"] == "direction"


def test_judge_threshold_hit_partial_miss() -> None:
    rule = {"kind": "threshold", "op": ">=", "value": 49.5}
    assert judge(rule, ActualObservation(50.0, "2026-11-30")) == CLAIM_STATUS_HIT
    # 49.4 距阈值 0.2% → partial
    assert judge(rule, ActualObservation(49.4, "2026-11-30")) == CLAIM_STATUS_PARTIAL
    assert judge(rule, ActualObservation(48.0, "2026-11-30")) == CLAIM_STATUS_MISS


def test_judge_interval() -> None:
    rule = {"kind": "interval", "low": 49.0, "high": 50.0}
    assert judge(rule, ActualObservation(49.5, "d")) == CLAIM_STATUS_HIT
    assert judge(rule, ActualObservation(48.9, "d")) == CLAIM_STATUS_PARTIAL
    assert judge(rule, ActualObservation(51.0, "d")) == CLAIM_STATUS_MISS


def test_judge_direction_with_baseline() -> None:
    assert judge(
        {"kind": "direction", "direction": "up"},
        ActualObservation(102.0, "d", baseline=100.0),
    ) == CLAIM_STATUS_HIT
    # 0.3% 涨幅落在 flat 带 → partial
    assert judge(
        {"kind": "direction", "direction": "up"},
        ActualObservation(100.3, "d", baseline=100.0),
    ) == CLAIM_STATUS_PARTIAL
    assert judge(
        {"kind": "direction", "direction": "up"},
        ActualObservation(99.0, "d", baseline=100.0),
    ) == CLAIM_STATUS_MISS
    # flat 判断
    assert judge(
        {"kind": "direction", "direction": "flat"},
        ActualObservation(100.2, "d", baseline=100.0),
    ) == CLAIM_STATUS_HIT


def test_judge_direction_without_baseline() -> None:
    assert judge(
        {"kind": "direction", "direction": "up"},
        ActualObservation(100.0, "d", baseline=None),
    ) == CLAIM_STATUS_DATA_MISSING


def _claim(**overrides) -> SynthesisClaim:
    base = dict(
        dimension="growth",
        text="沪深300 在窗口内收于 3900 以上",
        metric="CSI300",
        direction="up",
        predicted_value=">=3900",
        probability=0.6,
        window_start="2026-11-01",
        window_end="2026-11-30",
        verify_source="daily_bar",
        status="pending",
    )
    base.update(overrides)
    return SynthesisClaim(**base)


def test_verify_daily_bar_hit() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute(
        "CREATE TABLE daily_bar (symbol VARCHAR, trade_date DATE, close DOUBLE)"
    )
    conn.execute(
        "INSERT INTO daily_bar VALUES ('000300.SH', DATE '2026-11-25', 3950)"
    )
    conn.execute(
        "INSERT INTO daily_bar VALUES ('000300.SH', DATE '2026-10-30', 3800)"
    )
    status, actual, date_str = verify_claim(conn, _claim())
    assert status == CLAIM_STATUS_HIT
    assert actual == 3950
    assert date_str == "2026-11-25"


def test_verify_daily_bar_no_data() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute(
        "CREATE TABLE daily_bar (symbol VARCHAR, trade_date DATE, close DOUBLE)"
    )
    status, actual, _ = verify_claim(conn, _claim())
    assert status == CLAIM_STATUS_DATA_MISSING
    assert actual is None


def test_verify_fx_rate() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute(
        "CREATE TABLE fx_rate (base VARCHAR, quote VARCHAR, rate_date DATE, "
        "rate DOUBLE, rate_type VARCHAR)"
    )
    conn.execute(
        "INSERT INTO fx_rate VALUES ('USD','CNY', DATE '2026-11-20', 7.10,'reference')"
    )
    conn.execute(
        "INSERT INTO fx_rate VALUES ('USD','CNY', DATE '2026-10-30', 7.15,'reference')"
    )
    claim = _claim(
        metric="USDCNY",
        predicted_value="<=7.12",
        verify_source="fx_rate",
        text="美元兑人民币回落至 7.12 下方",
    )
    status, actual, _ = verify_claim(conn, claim)
    assert status == CLAIM_STATUS_HIT
    assert actual == 7.1


def test_verify_unknown_source() -> None:
    conn = duckdb.connect(":memory:")
    status, _, _ = verify_claim(conn, _claim(verify_source="cn_macro_monthly"))
    assert status == CLAIM_STATUS_DATA_MISSING
