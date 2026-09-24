"""Fakes shared by macro service tests (no sockets, no real MySQL)."""

from __future__ import annotations

import datetime as dt
from typing import Optional

import pytest

from src.macro.models import MacroJudgment, PromptDef
from src.macro.prompts import SEED_PROMPTS
from src.macro.readiness import CONFIRMED, INSUFFICIENT, UNKNOWN, ReadinessAssessor


def valid_payload(**overrides) -> str:
    import json

    payload = {
        "economy": "日本",
        "statistics_date": "2099-01",
        "current_cycle": "复苏期（向过热期过渡），内外需温和修复。",
        "judgment_result": "四维组合指向复苏期，库存与信用同步改善。",
        "dimension_check": "增长向上、通胀温和、货币宽松、信用扩张。",
        "meso_verify": "库存周期被动去库尾声，产能周期仍处底部，与复苏期共振。",
        "history_cycle_anchor": "与2016H2复苏区间匹配度较高，外需强度存在差异。",
        "judgment_confidence": "中（置信区间有限，部分高频指标尚未确认）",
        "core_support": "社融同比回升、PMI新订单站上荣枯线。",
        "core_risk": "外需回落与地产链拖累可能使复苏斜率不及预期。",
        "extended_remark": "部分月度数据口径待统一。",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def make_judgment(economy: str = "中国", month: str = "2026-08", **overrides) -> MacroJudgment:
    base = {
        "economy": economy,
        "statistics_date": month,
        "current_cycle": "复苏期",
        "judgment_result": "判定结果文本",
        "dimension_check": "维度校验文本",
        "meso_verify": "中观验证文本",
        "history_cycle_anchor": "历史锚定文本",
        "judgment_confidence": "中",
        "core_support": "核心支撑文本",
        "core_risk": "核心风险文本",
        "extended_remark": "备注",
    }
    base.update(overrides)
    return MacroJudgment(**base)


class FakeRepository:
    """In-memory MacroRepository for service tests."""

    def __init__(self, prompts: Optional[list[PromptDef]] = None) -> None:
        self.judgments: dict[tuple[str, str], list[MacroJudgment]] = {}
        self.insert_count = 0
        self.next_id = 1
        if prompts is None:
            prompts = [
                PromptDef(
                    code=row["code"],
                    name=row["name"],
                    prompt_text=row["prompt_text"],
                    enabled=row["enabled"],
                    sort_order=row["sort_order"],
                )
                for row in SEED_PROMPTS
            ]
        self.prompts = {p.code: p for p in prompts}

    # -- judgments -------------------------------------------------------
    def get_judgment(self, economy: str, statistics_date: str) -> Optional[MacroJudgment]:
        rows = self.judgments.get((economy, statistics_date))
        return rows[-1] if rows else None

    def insert_judgment(self, judgment: MacroJudgment) -> MacroJudgment:
        self.insert_count += 1
        stored = MacroJudgment(
            **{**judgment.__dict__, "id": self.next_id, "create_time": "2026-09-24 10:00:00"}
        )
        self.next_id += 1
        self.judgments.setdefault((judgment.economy, judgment.statistics_date), []).append(stored)
        return stored

    def list_judgments(self, economy: str, limit: int = 100) -> list[MacroJudgment]:
        rows = [
            judgment
            for (econ, _month), bucket in self.judgments.items()
            if econ == economy
            for judgment in bucket
        ]
        return sorted(rows, key=lambda j: j.statistics_date, reverse=True)[:limit]

    # -- prompts ---------------------------------------------------------
    def list_prompts(self) -> list[PromptDef]:
        return [self.prompts[code] for code in sorted(self.prompts, key=lambda c: self.prompts[c].sort_order)]

    def get_prompt(self, code: str) -> Optional[PromptDef]:
        return self.prompts.get(code)

    def update_prompt_text(self, code: str, prompt_text: str) -> Optional[PromptDef]:
        if code not in self.prompts:
            return None
        old = self.prompts[code]
        updated = PromptDef(
            code=old.code,
            name=old.name,
            prompt_text=prompt_text,
            enabled=old.enabled,
            sort_order=old.sort_order,
            orchestration_config=old.orchestration_config,
            id=old.id,
        )
        self.prompts[code] = updated
        return updated


class FakeLLM:
    """Scripted ChatLLM substitute: returns strings or raises, records calls."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools=None, timeout=None):
        self.calls.append(list(messages))
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return type("Response", (), {"content": item})()


class ScriptedProbe:
    """Probe returning a fixed status per canonical economy."""

    def __init__(self, status: str = CONFIRMED, statuses: Optional[dict] = None) -> None:
        self.default = status
        self.statuses = statuses or {}

    def probe(self, economy: str) -> str:
        return self.statuses.get(economy, self.default)


FIXED_TODAY = dt.date(2026, 9, 24)


def build_assessor(probe: Optional[ScriptedProbe] = None) -> ReadinessAssessor:
    return ReadinessAssessor(
        probe=probe or ScriptedProbe(CONFIRMED),
        today_provider=lambda: FIXED_TODAY,
    )


@pytest.fixture(autouse=True)
def _reset_judge_slots():
    """Ensure process-wide generation slots never leak between tests."""
    from src.macro import service as service_module

    with service_module._JUDGE_SLOTS_GUARD:
        service_module._JUDGE_SLOTS.clear()
    yield
    with service_module._JUDGE_SLOTS_GUARD:
        service_module._JUDGE_SLOTS.clear()


@pytest.fixture
def fake_repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def ready_assessor() -> ReadinessAssessor:
    return build_assessor()


@pytest.fixture
def insufficient_assessor() -> ReadinessAssessor:
    return build_assessor(ScriptedProbe(INSUFFICIENT))


@pytest.fixture
def unknown_assessor() -> ReadinessAssessor:
    return build_assessor(ScriptedProbe(UNKNOWN))
