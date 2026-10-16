"""细分品类战术资产配置量化引擎（纯函数，无 I/O）。

行业实践：美林时钟象限基准暴露 + 五维信号敏感度修正（卖方金工 TAA），
再以 MCS 决定风险预算（risk budget），把总仓位拆到 13 个可交易品类，
输出评级（-2..+2）、权重中枢与区间、组合形态。评级与仓位全部由本模块
确定性算出，LLM 只能补 rationale / trigger 文字，不能改数字。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .models import CYCLE_KEYS, DimensionSignal

# -- 品类元数据 ------------------------------------------------------------

CATEGORY_GROUPS = ("equity", "bond", "commodity", "property", "cash")

#: 风险品类（参与风险预算分配）；债券/现金为防御品类。
RISK_CATEGORIES = (
    "cn_large",
    "cn_growth",
    "cn_dividend",
    "hk_equity",
    "global_equity",
    "precious_metal",
    "industrial_metal",
    "energy",
    "agriculture",
    "property_chain",
)
DEFENSIVE_CATEGORIES = ("rate_bond", "credit_bond", "cash")

#: 象限基准暴露（recovery/overheat/stagflation/recession），美林时钟行业标定。
BASE_EXPOSURE: dict[str, tuple[int, int, int, int]] = {
    "cn_large": (2, 1, -1, -1),
    "cn_growth": (2, 0, -2, -1),
    "cn_dividend": (0, 0, 1, 1),
    "hk_equity": (2, 1, -1, -1),
    "global_equity": (1, 1, -1, -1),
    "rate_bond": (-1, -2, -1, 2),
    "credit_bond": (0, -1, -1, 1),
    "precious_metal": (0, 1, 2, 1),
    "industrial_metal": (1, 2, 0, -1),
    "energy": (1, 2, 1, -2),
    "agriculture": (0, 1, 1, 0),
    "property_chain": (1, -1, -1, 0),
    "cash": (-1, -1, 1, 1),
}

#: 五维信号敏感度（growth/inflation/money/external）。
#: 注意 inflation 维度语义：通胀缓解为正、加剧为负；抗通胀资产该系数为负。
SENSITIVITY: dict[str, tuple[float, float, float, float]] = {
    "cn_large": (1.0, 0.5, 1.0, 0.5),
    "cn_growth": (1.0, 0.5, 1.5, 0.5),
    "cn_dividend": (0.0, 0.5, 0.5, 0.0),
    "hk_equity": (0.5, 0.5, 1.0, 1.5),
    "global_equity": (1.0, 0.5, 1.0, 0.5),
    "rate_bond": (-1.0, 1.0, 1.5, 0.0),
    "credit_bond": (-0.5, 0.5, 1.0, 0.5),
    "precious_metal": (-0.5, -1.0, 1.0, -0.5),
    "industrial_metal": (1.5, -0.5, 0.5, 0.5),
    "energy": (1.0, -1.0, 0.0, -0.5),
    "agriculture": (0.0, -1.0, 0.5, 0.0),
    "property_chain": (1.0, 0.5, 1.5, 0.0),
    "cash": (-0.5, 0.5, -1.0, 0.0),
}

#: 境内可交易工具默认映射（LLM 可补文字但不改代码）。
CATEGORY_VEHICLES: dict[str, str] = {
    "cn_large": "510300 沪深300ETF",
    "cn_growth": "159915 创业板ETF",
    "cn_dividend": "510880 红利ETF",
    "hk_equity": "159920 恒生ETF",
    "global_equity": "513500 标普500ETF",
    "rate_bond": "511010 国债ETF",
    "credit_bond": "511220 城投债ETF",
    "precious_metal": "518880 黄金ETF",
    "industrial_metal": "159980 有色ETF",
    "energy": "162411 原油基金",
    "agriculture": "159985 豆粕ETF",
    "property_chain": "512200 房地产ETF",
    "cash": "511880 银华日利",
}

#: 引擎输出品类顺序（展示用）。
ALLOCATION_CATEGORIES = (
    "cn_large",
    "cn_growth",
    "cn_dividend",
    "hk_equity",
    "global_equity",
    "rate_bond",
    "credit_bond",
    "precious_metal",
    "industrial_metal",
    "energy",
    "agriculture",
    "property_chain",
    "cash",
)

CATEGORY_GROUP_OF: dict[str, str] = {
    "cn_large": "equity",
    "cn_growth": "equity",
    "cn_dividend": "equity",
    "hk_equity": "equity",
    "global_equity": "equity",
    "rate_bond": "bond",
    "credit_bond": "bond",
    "precious_metal": "commodity",
    "industrial_metal": "commodity",
    "energy": "commodity",
    "agriculture": "commodity",
    "property_chain": "property",
    "cash": "cash",
}

#: 战术修正强度。
SIGNAL_ADJUST_WEIGHT = 0.35
#: 单品类权重上限。
MAX_CATEGORY_WEIGHT = 0.15
#: 风险预算区间。
RISK_BUDGET_MIN = 0.15
RISK_BUDGET_MAX = 0.85


@dataclass(frozen=True)
class AllocationDetail:
    """一个细分品类的量化配置结论。"""

    category: str
    asset_group: str
    rating: int  # -2 强低配 … +2 强超配
    raw_score: float
    weight_mid: float
    weight_low: float
    weight_high: float
    vehicle: str
    rationale: str = ""
    trigger: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "asset_group": self.asset_group,
            "rating": self.rating,
            "raw_score": round(self.raw_score, 2),
            "weight_mid": round(self.weight_mid, 4),
            "weight_low": round(self.weight_low, 4),
            "weight_high": round(self.weight_high, 4),
            "vehicle": self.vehicle,
            "rationale": self.rationale,
            "trigger": self.trigger,
        }


@dataclass(frozen=True)
class AllocationPlan:
    """整份组合方案。"""

    details: list[AllocationDetail]
    risk_budget: float
    posture: str  # offensive / balanced / defensive
    group_weights: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "risk_budget": round(self.risk_budget, 3),
            "posture": self.posture,
            "group_weights": {
                group: round(weight, 4)
                for group, weight in self.group_weights.items()
            },
            "details": [detail.to_dict() for detail in self.details],
        }


# -- 评分 ------------------------------------------------------------------


def _round_half_away(value: float) -> int:
    return int(math.copysign(math.floor(abs(value) + 0.5), value))


def _quadrant_expected(
    cycle_probs: dict[str, float], exposures: tuple[int, int, int, int]
) -> float:
    return sum(cycle_probs[key] * exposures[i] for i, key in enumerate(CYCLE_KEYS))


def _dimension_adjustment(
    dimensions: list[DimensionSignal],
    sensitivity: tuple[float, float, float],
) -> float:
    by_dim = {item.dimension: item for item in dimensions}
    terms = (
        by_dim["growth"].signal * sensitivity[0] * by_dim["growth"].confidence,
        by_dim["inflation"].signal * sensitivity[1] * by_dim["inflation"].confidence,
        by_dim["money"].signal * sensitivity[2] * by_dim["money"].confidence,
        by_dim["external"].signal * sensitivity[3] * by_dim["external"].confidence,
    )
    return SIGNAL_ADJUST_WEIGHT * sum(terms)


def _risk_budget(mcs: float) -> float:
    budget = 0.5 + (mcs - 50) / 100 * 0.7
    return min(RISK_BUDGET_MAX, max(RISK_BUDGET_MIN, budget))


def _posture(budget: float) -> str:
    # 与 MCS 语义对齐：MCS>=60 -> 进攻，MCS<=40 -> 防御。
    if budget >= 0.57:
        return "offensive"
    if budget <= 0.43:
        return "defensive"
    return "balanced"


def _band(mid: float) -> tuple[float, float]:
    half = max(0.015, 0.3 * mid)
    low = math.floor((mid - half) * 200) / 200  # 0.5% 网格向下
    high = math.ceil((mid + half) * 200) / 200
    return max(0.0, low), high


def _round_grid(value: float) -> float:
    return round(value * 200) / 200


def build_allocation_plan(
    cycle_probs: dict[str, float],
    dimensions: list[DimensionSignal],
    mcs: float,
    notes: Optional[dict[str, dict[str, str]]] = None,
) -> AllocationPlan:
    """根据周期概率、五维信号、MCS 计算 13 品类配置方案。

    notes：可选的 LLM 补充文字 ``{category: {"rationale": ..., "trigger": ...}}``，
    非法或越界内容忽略。
    """
    notes = notes or {}

    raw_scores: dict[str, float] = {}
    for category in ALLOCATION_CATEGORIES:
        expected = _quadrant_expected(cycle_probs, BASE_EXPOSURE[category])
        adjusted = expected + _dimension_adjustment(
            dimensions, SENSITIVITY[category]
        )
        raw_scores[category] = min(2.0, max(-2.0, adjusted))

    risk_budget = _risk_budget(mcs)
    weights: dict[str, float] = {category: 0.0 for category in ALLOCATION_CATEGORIES}

    # 风险品类：按正向评分比例分配风险预算，单品类 15% 封顶并再分配。
    positive = {c: max(raw_scores[c], 0.0) for c in RISK_CATEGORIES}
    total_positive = sum(positive.values())
    if total_positive > 0:
        capped: set[str] = set()
        remaining_budget = risk_budget
        scores = dict(positive)
        while True:
            active_sum = sum(s for c, s in scores.items() if c not in capped)
            progressed = False
            for category in RISK_CATEGORIES:
                if category in capped or scores[category] <= 0:
                    continue
                share = remaining_budget * scores[category] / active_sum
                if share > MAX_CATEGORY_WEIGHT:
                    weights[category] = MAX_CATEGORY_WEIGHT
                    capped.add(category)
                    remaining_budget -= MAX_CATEGORY_WEIGHT
                    progressed = True
                    break
            if not progressed:
                for category in RISK_CATEGORIES:
                    if category not in capped and scores[category] > 0:
                        weights[category] = (
                            remaining_budget
                            * scores[category]
                            / active_sum
                        )
                break

    # 防御品类：债券占防御预算的比例随利率债/信用债评分变化，现金为残差。
    defensive_budget = 1.0 - sum(weights[c] for c in RISK_CATEGORIES)
    bond_appetite = min(
        1.0, max(0.0, 0.4 + 0.1 * (raw_scores["rate_bond"] + raw_scores["credit_bond"]))
    )
    bond_total = defensive_budget * (0.3 + 0.55 * bond_appetite)
    rate_score = max(raw_scores["rate_bond"], 0.0)
    credit_score = max(raw_scores["credit_bond"], 0.0)
    if rate_score + credit_score > 0:
        weights["rate_bond"] = bond_total * rate_score / (rate_score + credit_score)
        weights["credit_bond"] = bond_total * credit_score / (
            rate_score + credit_score
        )
    else:
        weights["rate_bond"] = bond_total * 0.65
        weights["credit_bond"] = bond_total * 0.35

    # 网格取整，残差全部给现金，保证合计恒为 100%。
    rounded = {
        category: _round_grid(weights[category])
        for category in ALLOCATION_CATEGORIES
        if category != "cash"
    }
    weights["cash"] = max(0.0, round(1.0 - sum(rounded.values()), 3))
    weights.update(rounded)

    details: list[AllocationDetail] = []
    for category in ALLOCATION_CATEGORIES:
        low, high = _band(weights[category])
        note = notes.get(category) if isinstance(notes, dict) else None
        rationale = ""
        trigger = ""
        if isinstance(note, dict):
            raw_rationale = note.get("rationale", "")
            raw_trigger = note.get("trigger", "")
            if isinstance(raw_rationale, str):
                rationale = raw_rationale.strip()[:120]
            if isinstance(raw_trigger, str):
                trigger = raw_trigger.strip()[:120]
        details.append(
            AllocationDetail(
                category=category,
                asset_group=CATEGORY_GROUP_OF[category],
                rating=_round_half_away(raw_scores[category]),
                raw_score=raw_scores[category],
                weight_mid=weights[category],
                weight_low=low,
                weight_high=high,
                vehicle=CATEGORY_VEHICLES[category],
                rationale=rationale,
                trigger=trigger,
            )
        )

    group_weights = {group: 0.0 for group in CATEGORY_GROUPS}
    for detail in details:
        group_weights[detail.asset_group] += detail.weight_mid

    return AllocationPlan(
        details=details,
        risk_budget=risk_budget,
        posture=_posture(risk_budget),
        group_weights=group_weights,
    )


def derive_asset_class_ratings(plan: AllocationPlan) -> dict[str, int]:
    """把 13 品类评分汇总为四大类评级（替代 LLM 直给，保证口径一致）。"""
    aggregates: dict[str, list[float]] = {
        "equity": [],
        "bond": [],
        "commodity": [],
        "cash": [],
    }
    for detail in plan.details:
        group = detail.asset_group
        if group == "property":
            aggregates["equity"].append(detail.raw_score)
            continue
        aggregates[group].append(detail.raw_score)
    return {
        key: _round_half_away(sum(values) / len(values))
        for key, values in aggregates.items()
    }
