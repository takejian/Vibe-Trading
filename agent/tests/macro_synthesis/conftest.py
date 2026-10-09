"""macro_synthesis 测试共享工厂。"""

from __future__ import annotations

import json

import pytest

from src.swarm.models import RunStatus, SwarmRun
from src.swarm.store import SwarmStore

DIM_KEYS = ["growth", "inflation", "money", "external", "synthesis"]


@pytest.fixture
def valid_payload():
    """返回一个通过严格校验的最小合法 payload。"""

    def _build(signal: int = 1) -> dict:
        return {
            "summary": "总体宏观结论，描述现状、核心矛盾与短期展望。",
            "action_advice": "维持权益超配，关注下月数据与政策窗口。",
            "dimensions": [
                {
                    "dimension": d,
                    "signal": signal,
                    "confidence": 0.7,
                    "trend": "up",
                    "rationale": "测试用理由",
                }
                for d in DIM_KEYS
            ],
            "cycle_probs": {
                "recovery": 0.4,
                "overheat": 0.3,
                "stagflation": 0.1,
                "recession": 0.2,
            },
            "allocation": {"equity": 1, "bond": 0, "commodity": -1, "cash": 0},
            "risk_triggers": ["风险条件一", "风险条件二"],
            "claims": [
                {
                    "dimension": "growth",
                    "text": f"11月官方制造业PMI较10月回升至49.5以上（命题{i}）",
                    "metric": "CN_PMI",
                    "direction": "up",
                    "predicted_value": ">=49.5",
                    "probability": 0.6,
                    "window_start": "2026-12-01",
                    "window_end": "2026-12-10",
                    "verify_source": "cn_macro_monthly",
                }
                for i in range(5)
            ],
        }

    return _build


class _Response:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeLLM:
    """记录消息、返回固定内容的伪 LLM。"""

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools=None, timeout=None):
        self.calls.append(messages)
        return _Response(self.content)


@pytest.fixture
def payload_llm(valid_payload):
    """返回 (llm holder, 取伪 LLM)；默认输出合法 JSON。"""

    holder: dict[str, FakeLLM] = {}

    def _factory(payload: dict | None = None) -> FakeLLM:
        data = payload if payload is not None else valid_payload()
        llm = FakeLLM(json.dumps(data, ensure_ascii=False))
        holder["llm"] = llm
        return llm

    return _factory, holder


def write_team_run(
    store: SwarmStore,
    run_id: str,
    preset: str,
    created_at: str,
    completed_at: str | None = None,
    final_report: str = "# 宏观分析报告\n\n这是一条足够长的核心结论行，用于摘要提取。\n",
    status: RunStatus = RunStatus.completed,
    kind: str = "team",
) -> SwarmRun:
    """在 swarm store 目录中写入一条 run。"""
    run = SwarmRun(
        id=run_id,
        preset_name=preset,
        status=status,
        created_at=created_at,
        completed_at=completed_at if completed_at is not None else created_at,
        final_report=final_report,
        kind=kind,
    )
    run_dir = store.run_dir(run_id)
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(run.model_dump_json(), encoding="utf-8")
    return run

@pytest.fixture
def run_writer():
    """以 fixture 形式暴露 write_team_run，避免测试显式相对导入。"""

    def _write(store, run_id, preset, created_at, **kwargs):
        return write_team_run(store, run_id, preset, created_at, **kwargs)

    return _write

