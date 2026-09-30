"""Tests for standalone role-run construction and success rule."""

from __future__ import annotations

import pytest

from src.swarm.models import RunStatus, TaskStatus
from src.swarm.role_catalog import list_role_groups
from src.swarm.role_runs import build_role_run, role_run_succeeded
from src.swarm.roles import RoleStore


@pytest.fixture
def role_store(tmp_path) -> RoleStore:
    return RoleStore(base_dir=tmp_path / "roles")


def _first_builtin_ref() -> str:
    groups = list_role_groups()
    builtin = next(g for g in groups["groups"] if g["kind"] == "builtin")
    return builtin["roles"][0]["ref"]


def test_build_role_run_from_builtin(role_store: RoleStore) -> None:
    ref = _first_builtin_ref()
    run = build_role_run(ref, "COMEX黄金", "当前处于周期什么位置？")

    assert run.kind == "role_run"
    assert run.trial_role == ref
    assert run.preset_name == f"role:{ref}"
    assert run.customized is False
    assert run.research_target == "COMEX黄金"
    assert len(run.agents) == 1
    assert len(run.tasks) == 1
    task = run.tasks[0]
    assert task.agent_id == run.agents[0].id
    assert "{target}" in task.prompt_template
    assert "当前处于周期什么位置？" in task.prompt_template


def test_build_role_run_from_custom(role_store: RoleStore) -> None:
    role = role_store.create_role(
        name="可转债狙击手",
        purpose="埋伏下修博弈",
        system_prompt="You hunt convertible bonds for {target}.",
        tools=["get_market_data"],
        skills=[],
        max_iterations=15,
        timeout_seconds=180,
    )
    run = build_role_run(role.id, "113001.SH", "下修概率多大？", role_store)

    assert run.trial_role == role.id
    assert run.agents[0].id == "role_analyst"
    assert run.agents[0].role == "可转债狙击手"
    assert "113001.SH" in run.agents[0].system_prompt


def test_upstream_context_placeholder_is_preserved(role_store: RoleStore) -> None:
    role = role_store.create_role(
        name="上下游哨兵",
        purpose="读取上游结论",
        system_prompt=(
            "Target is {target}.\n"
            "Use upstream: {upstream_context}\n"
            "Unknown: {never_declared_field}"
        ),
        tools=[],
        skills=[],
        max_iterations=10,
        timeout_seconds=120,
    )
    run = build_role_run(role.id, "螺纹钢", "库存拐点？", role_store)
    prompt = run.agents[0].system_prompt

    assert "Target is 螺纹钢." in prompt
    assert "{upstream_context}" in prompt
    assert "{never_declared_field}" not in prompt


def test_unknown_builtin_role_ref_raises() -> None:
    with pytest.raises(ValueError, match="内置角色不存在"):
        build_role_run("investment_committee:ghost_agent", "600519.SH", "q")


def test_missing_custom_role_raises(role_store: RoleStore) -> None:
    with pytest.raises(FileNotFoundError):
        build_role_run("role-doesnotexist", "600519.SH", "q")


@pytest.mark.parametrize(
    "ref, target, question",
    [
        ("", "600519.SH", "q"),
        ("investment_committee:bull_advocate", "", "q"),
        ("investment_committee:bull_advocate", "600519.SH", ""),
    ],
)
def test_required_fields(ref: str, target: str, question: str) -> None:
    with pytest.raises(ValueError):
        build_role_run(ref, target, question)


def test_role_run_succeeded_rule() -> None:
    ref = _first_builtin_ref()
    run = build_role_run(ref, "COMEX黄金", "周期位置？")

    assert role_run_succeeded(run) is False

    running = run.model_copy(update={"status": RunStatus.running})
    assert role_run_succeeded(running) is False

    completed_empty = run.model_copy(update={"status": RunStatus.completed})
    assert role_run_succeeded(completed_empty) is False

    task = run.tasks[0].model_copy(
        update={"status": TaskStatus.completed, "summary": "合格结论正文"}
    )
    qualified = run.model_copy(
        update={"status": RunStatus.completed, "tasks": [task]}
    )
    assert role_run_succeeded(qualified) is True

    via_report = run.model_copy(
        update={"status": RunStatus.completed, "final_report": "# 结论\n..."}
    )
    assert role_run_succeeded(via_report) is True
