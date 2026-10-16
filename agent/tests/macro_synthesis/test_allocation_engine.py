"""细分品类配置引擎的确定性测试。"""

from __future__ import annotations

import pytest

from src.macro_synthesis.allocation_engine import (
    ALLOCATION_CATEGORIES,
    BASE_EXPOSURE,
    CATEGORY_GROUP_OF,
    CATEGORY_VEHICLES,
    SENSITIVITY,
    build_allocation_plan,
    derive_asset_class_ratings,
)
from src.macro_synthesis.models import DIMENSION_WEIGHTS, DimensionSignal

CATEGORY_SET = set(ALLOCATION_CATEGORIES)


def _dimensions(signals: dict[str, int] | None = None, confidence: float = 0.7):
    signals = signals or {}
    return [
        DimensionSignal(
            dimension=key,
            signal=int(signals.get(key, 0)),
            confidence=confidence,
            trend="flat",
            weight=DIMENSION_WEIGHTS[key],
        )
        for key in ("growth", "inflation", "money", "external", "synthesis")
    ]


PROBS_EQUAL = {k: 0.25 for k in ("recovery", "overheat", "stagflation", "recession")}


def test_metadata_consistency() -> None:
    assert set(BASE_EXPOSURE) == CATEGORY_SET
    assert set(SENSITIVITY) == CATEGORY_SET
    assert set(CATEGORY_VEHICLES) == CATEGORY_SET
    assert set(CATEGORY_GROUP_OF) == CATEGORY_SET


def test_weights_sum_to_one_and_bounds() -> None:
    plan = build_allocation_plan(PROBS_EQUAL, _dimensions(), 50.0)
    assert len(plan.details) == 13
    assert sum(d.weight_mid for d in plan.details) == pytest.approx(1.0)
    assert sum(d.weight_low for d in plan.details) <= 1.0 + 1e-9
    for detail in plan.details:
        assert -2 <= detail.rating <= 2
        assert 0 <= detail.weight_low <= detail.weight_mid <= detail.weight_high
        assert detail.asset_group


def test_risk_categories_capped_at_15pct() -> None:
    probs = {"recovery": 0.8, "overheat": 0.2, "stagflation": 0.0, "recession": 0.0}
    plan = build_allocation_plan(
        probs, _dimensions({"growth": 2, "inflation": 1, "money": 2}), 85.0
    )
    assert plan.posture == "offensive"
    for detail in plan.details:
        if detail.category != "cash" and detail.asset_group != "bond":
            assert detail.weight_mid <= 0.15 + 1e-9
    assert sum(d.weight_mid for d in plan.details) == pytest.approx(1.0)


def test_recession_favors_bonds_cash_and_gold() -> None:
    probs = {"recovery": 0.0, "overheat": 0.0, "stagflation": 0.1, "recession": 0.9}
    plan = build_allocation_plan(
        probs, _dimensions({"growth": -2, "inflation": 1, "money": 1}), 30.0
    )
    assert plan.posture == "defensive"
    by_cat = {d.category: d for d in plan.details}
    assert by_cat["rate_bond"].rating >= 1
    assert by_cat["cn_growth"].rating <= -1
    assert by_cat["energy"].rating <= -1
    # 衰退象限黄金基准 +1
    assert by_cat["precious_metal"].raw_score > 0
    defensive = (
        by_cat["rate_bond"].weight_mid
        + by_cat["credit_bond"].weight_mid
        + by_cat["cash"].weight_mid
    )
    assert defensive > 0.6


def test_overheat_favors_commodities_and_underweights_long_bonds() -> None:
    probs = {"recovery": 0.2, "overheat": 0.7, "stagflation": 0.1, "recession": 0.0}
    plan = build_allocation_plan(
        probs, _dimensions({"growth": 1, "inflation": -1}), 60.0
    )
    by_cat = {d.category: d for d in plan.details}
    assert by_cat["industrial_metal"].rating >= 1
    assert by_cat["energy"].rating >= 1
    assert by_cat["rate_bond"].rating <= -1


def test_inflation_signal_sign_semantics() -> None:
    # 通胀加剧（inflation signal = -2）应推升黄金/原油评分
    probs = PROBS_EQUAL
    easing = build_allocation_plan(
        probs, _dimensions({"inflation": 2}), 50.0
    )
    rising = build_allocation_plan(
        probs, _dimensions({"inflation": -2}), 50.0
    )
    e = {d.category: d for d in easing.details}
    r = {d.category: d for d in rising.details}
    assert r["precious_metal"].raw_score > e["precious_metal"].raw_score
    assert r["energy"].raw_score > e["energy"].raw_score
    assert e["rate_bond"].raw_score > r["rate_bond"].raw_score


def test_posture_thresholds_align_with_mcs() -> None:
    base = build_allocation_plan(PROBS_EQUAL, _dimensions(), 50.0)
    hot = build_allocation_plan(PROBS_EQUAL, _dimensions(), 65.0)
    cold = build_allocation_plan(PROBS_EQUAL, _dimensions(), 35.0)
    assert base.posture == "balanced"
    assert hot.posture == "offensive"
    assert cold.posture == "defensive"


def test_deterministic() -> None:
    a = build_allocation_plan(PROBS_EQUAL, _dimensions(), 55.0)
    b = build_allocation_plan(PROBS_EQUAL, _dimensions(), 55.0)
    assert a.to_dict() == b.to_dict()


def test_notes_only_add_text() -> None:
    notes = {"gold": {"rationale": "x", "trigger": "y"}}  # 非法品类键，忽略
    plan = build_allocation_plan(
        PROBS_EQUAL,
        _dimensions(),
        50.0,
        notes={"precious_metal": {"rationale": "央行购金", "trigger": "实际利率转正"}},
    )
    gold = next(d for d in plan.details if d.category == "precious_metal")
    assert gold.rationale == "央行购金"
    assert gold.trigger == "实际利率转正"
    plan2 = build_allocation_plan(PROBS_EQUAL, _dimensions(), 50.0, notes=notes)
    # 非法 notes 不影响数字
    assert [d.rating for d in plan.details] == [d.rating for d in plan2.details]


def test_derived_asset_class_ratings_in_range() -> None:
    plan = build_allocation_plan(PROBS_EQUAL, _dimensions(), 50.0)
    ratings = derive_asset_class_ratings(plan)
    assert set(ratings) == {"equity", "bond", "commodity", "cash"}
    assert all(-2 <= value <= 2 for value in ratings.values())
