"""Domain models for the macro analysis module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class MacroJudgment:
    """One persisted cycle judgment (row of ``macro_cycle_judgment``)."""

    economy: str
    statistics_date: str  # YYYY-MM
    current_cycle: str
    judgment_result: str
    dimension_check: str
    meso_verify: str
    history_cycle_anchor: str
    judgment_confidence: str
    core_support: str
    core_risk: str
    extended_remark: str = ""
    id: Optional[int] = None
    create_time: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "economy": self.economy,
            "statistics_date": self.statistics_date,
            "current_cycle": self.current_cycle,
            "judgment_result": self.judgment_result,
            "dimension_check": self.dimension_check,
            "meso_verify": self.meso_verify,
            "history_cycle_anchor": self.history_cycle_anchor,
            "judgment_confidence": self.judgment_confidence,
            "core_support": self.core_support,
            "core_risk": self.core_risk,
            "extended_remark": self.extended_remark,
            "create_time": self.create_time,
        }


@dataclass(frozen=True)
class PromptDef:
    """A macro analysis prompt definition (row of ``macro_analysis_prompt``)."""

    code: str
    name: str
    prompt_text: str
    enabled: bool
    sort_order: int
    orchestration_config: Optional[str] = None
    id: Optional[int] = None
    create_time: Optional[str] = None
    update_time: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "prompt_text": self.prompt_text,
            "enabled": self.enabled,
            "sort_order": self.sort_order,
            "orchestration_config": self.orchestration_config,
            "update_time": self.update_time,
        }


@dataclass(frozen=True)
class DataReadiness:
    """Result of the pre-flight macro data availability assessment."""

    ready: bool
    latest_month: str
    reason: Optional[str] = None


@dataclass(frozen=True)
class JudgeResult:
    """Outcome of a judgment request: a stored judgment plus provenance."""

    judgment: MacroJudgment
    cached: bool = False
    data_insufficient: bool = False
    message: Optional[str] = None
    readiness: Optional[DataReadiness] = field(default=None)
