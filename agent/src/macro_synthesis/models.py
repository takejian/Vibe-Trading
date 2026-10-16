"""宏观量化汇总的领域模型。

模型只描述结构与序列化，不包含 I/O；期次解析在 :mod:`periods`，
归集在 :mod:`coverage`，持久化在 :mod:`db`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# -- 期次 ------------------------------------------------------------------

PERIOD_MONTH = "month"
PERIOD_QUARTER = "quarter"
PERIOD_TYPES = (PERIOD_MONTH, PERIOD_QUARTER)

# -- 维度 / 周期 / 资产 -----------------------------------------------------

DIMENSIONS = ("growth", "inflation", "money", "external", "synthesis")

#: 五维固定权重，服务端赋予，不采信模型输出。
DIMENSION_WEIGHTS: dict[str, float] = {
    "growth": 0.30,
    "inflation": 0.20,
    "money": 0.20,
    "external": 0.15,
    "synthesis": 0.15,
}

#: 美林时钟四象限。
CYCLE_KEYS = ("recovery", "overheat", "stagflation", "recession")

#: 四类大类资产。
ASSET_KEYS = ("equity", "bond", "commodity", "cash")

#: 纳入覆盖检查的四支宏观智能体团队（swarm preset 名）。
MACRO_TEAMS = (
    "macro_strategy_forum",
    "macro_rates_fx_desk",
    "geopolitical_war_room",
    "sector_rotation_team",
)

#: 团队中文短标题（前端有完整 i18n，此为持久化/兜底用）。
TEAM_TITLES: dict[str, str] = {
    "macro_strategy_forum": "宏观策略",
    "macro_rates_fx_desk": "利率外汇",
    "geopolitical_war_room": "地缘分析",
    "sector_rotation_team": "资产轮转",
}

#: 维度与团队的对应关系，用于维度信号的来源 run 溯源。
DIMENSION_TEAMS: dict[str, tuple[str, ...]] = {
    "growth": ("macro_strategy_forum", "sector_rotation_team"),
    "inflation": ("macro_rates_fx_desk", "geopolitical_war_room"),
    "money": ("macro_rates_fx_desk", "macro_strategy_forum"),
    "external": ("macro_rates_fx_desk", "geopolitical_war_room"),
    "synthesis": (),
}

TRENDS = ("up", "down", "flat")
DIRECTIONS = ("up", "down", "flat")

#: Claim 验证状态。
CLAIM_STATUS_PENDING = "pending"  # 未到期 / 尚未判定
CLAIM_STATUS_HIT = "hit"  # 命中
CLAIM_STATUS_MISS = "miss"  # 未中
CLAIM_STATUS_PARTIAL = "partial"  # 接近阈值 / 部分正确
CLAIM_STATUS_DATA_MISSING = "data_missing"  # 窗口到期但本地库无实际数据

#: 已终态（verify 默认不再重判；data_missing 允许重试取数）。
CLAIM_TERMINAL_STATUSES = (
    CLAIM_STATUS_HIT,
    CLAIM_STATUS_MISS,
    CLAIM_STATUS_PARTIAL,
)
CLAIM_VERIFIED_STATUSES = CLAIM_TERMINAL_STATUSES + (CLAIM_STATUS_DATA_MISSING,)

REVIEW_TYPE_AI = "ai"
REVIEW_TYPE_MANUAL = "manual"


@dataclass(frozen=True)
class TeamCoverage:
    """一支团队在某一期次的结论覆盖情况。"""

    team: str
    title: str
    present: bool
    run_id: Optional[str] = None
    date: Optional[str] = None
    conclusion: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team,
            "title": self.title,
            "present": self.present,
            "run_id": self.run_id,
            "date": self.date,
            "conclusion": self.conclusion,
        }


@dataclass(frozen=True)
class DimensionSignal:
    """一个维度的量化信号。"""

    dimension: str
    signal: int  # -2 显著利空 … +2 显著利好
    confidence: float  # 0..1
    trend: str  # up/down/flat，相较上一期
    weight: float
    source_run_ids: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "signal": self.signal,
            "confidence": round(self.confidence, 2),
            "trend": self.trend,
            "weight": round(self.weight, 2),
            "source_run_ids": list(self.source_run_ids),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class SynthesisClaim:
    """一条可验证命题（结构化预测），闭环复盘的最小单元。"""

    dimension: str
    text: str
    metric: str
    direction: str  # up/down/flat
    predicted_value: str
    probability: float  # 0..1
    window_start: str  # YYYY-MM-DD
    window_end: str  # YYYY-MM-DD
    verify_source: str
    status: str = CLAIM_STATUS_PENDING
    actual_value: Optional[str] = None
    verified_at: Optional[str] = None
    ai_comment: Optional[str] = None
    id: Optional[int] = None
    report_id: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "report_id": self.report_id,
            "dimension": self.dimension,
            "text": self.text,
            "metric": self.metric,
            "direction": self.direction,
            "predicted_value": self.predicted_value,
            "probability": round(self.probability, 2),
            "window_start": self.window_start,
            "window_end": self.window_end,
            "verify_source": self.verify_source,
            "status": self.status,
            "actual_value": self.actual_value,
            "verified_at": self.verified_at,
            "ai_comment": self.ai_comment,
        }


@dataclass(frozen=True)
class SynthesisReview:
    """一期报告的一次复盘点评（AI 或人工）。"""

    report_id: int
    review_type: str  # ai / manual
    comment: str
    id: Optional[int] = None
    hit_rate: Optional[float] = None
    brier_score: Optional[float] = None
    counts: Optional[dict[str, int]] = None
    attribution: Optional[str] = None
    lessons: Optional[str] = None
    reviewer: Optional[str] = None
    create_time: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "report_id": self.report_id,
            "review_type": self.review_type,
            "hit_rate": round(self.hit_rate, 3) if self.hit_rate is not None else None,
            "brier_score": (
                round(self.brier_score, 3) if self.brier_score is not None else None
            ),
            "counts": dict(self.counts) if self.counts else None,
            "comment": self.comment,
            "attribution": self.attribution,
            "lessons": self.lessons,
            "reviewer": self.reviewer,
            "create_time": self.create_time,
        }


@dataclass(frozen=True)
class SynthesisReport:
    """一期宏观量化汇总报告（聚合根）。"""

    economy: str
    period_type: str
    period: str
    period_label: str
    mcs: float
    mcs_delta: Optional[float]
    cycle_probs: dict[str, float]
    allocation: dict[str, int]
    summary: str
    action_advice: str
    risk_triggers: list[str]
    teams: list[TeamCoverage]
    dimensions: list[DimensionSignal]
    claims: list[SynthesisClaim]
    reviews: list[SynthesisReview] = field(default_factory=list)
    allocation_details: list[Any] = field(default_factory=list)
    risk_budget: Optional[float] = None
    posture: str = ""
    status: str = "completed"
    id: Optional[int] = None
    create_time: Optional[str] = None

    @property
    def all_covered(self) -> bool:
        return all(team.present for team in self.teams)

    @property
    def claim_count(self) -> int:
        return len(self.claims)

    def to_dict(self, cached: bool = False) -> dict[str, Any]:
        return {
            "id": self.id,
            "economy": self.economy,
            "period_type": self.period_type,
            "period": self.period,
            "period_label": self.period_label,
            "mcs": self.mcs,
            "mcs_delta": self.mcs_delta,
            "cycle_probs": {key: round(self.cycle_probs[key], 2) for key in CYCLE_KEYS},
            "allocation": {key: self.allocation[key] for key in ASSET_KEYS},
            "summary": self.summary,
            "action_advice": self.action_advice,
            "risk_triggers": list(self.risk_triggers),
            "coverage": {
                "all_covered": self.all_covered,
                "teams": [team.to_dict() for team in self.teams],
            },
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
            "claims": [claim.to_dict() for claim in self.claims],
            "reviews": [review.to_dict() for review in self.reviews],
            "allocation_details": [detail.to_dict() for detail in self.allocation_details],
            "risk_budget": self.risk_budget,
            "posture": self.posture or None,
            "status": self.status,
            "claim_count": self.claim_count,
            "create_time": self.create_time,
            "cached": cached,
        }

    def summary_row(self) -> dict[str, Any]:
        """历史列表用精简结构。"""
        return {
            "id": self.id,
            "economy": self.economy,
            "period_type": self.period_type,
            "period": self.period,
            "period_label": self.period_label,
            "mcs": self.mcs,
            "mcs_delta": self.mcs_delta,
            "all_covered": self.all_covered,
            "status": self.status,
            "claim_count": self.claim_count,
            "create_time": self.create_time,
        }
