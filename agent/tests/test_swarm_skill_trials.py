"""Tests for standalone skill trial run construction and success rules.

No LLM calls: we validate the pending run graph produced by
:func:`src.swarm.skill_trials.build_skill_trial_run` and the
:func:`trial_succeeded` predicate used by the runtime approval hook.
"""

from __future__ import annotations

import pytest

from src.swarm.models import RunStatus, SwarmRun, TaskStatus
from src.swarm.runtime import SwarmRuntime
from src.swarm.skill_trials import build_skill_trial_run, trial_succeeded
from src.swarm.store import SwarmStore

SKILL = "behavioral-finance"


def test_trial_run_is_single_agent_with_skill_allowlist() -> None:
    run = build_skill_trial_run(SKILL, "600519.SH", "当前是否适合做多？")

    assert run.kind == "skill_trial"
    assert run.trial_skill == SKILL
    assert run.preset_name == f"skill:{SKILL}"
    assert run.research_target == "600519.SH"
    assert run.research_question == "当前是否适合做多？"
    assert run.status == RunStatus.pending
    assert len(run.agents) == 1
    assert len(run.tasks) == 1

    agent = run.agents[0]
    assert agent.skills == [SKILL]
    # The broad operator-trusted preset tool pool is attached.
    assert "get_market_data" in agent.tools
    assert agent.max_iterations == 25
    assert agent.timeout_seconds == 300

    task = run.tasks[0]
    assert task.agent_id == agent.id
    assert task.status == TaskStatus.pending
    assert "{target}" in task.prompt_template


def test_question_braces_are_template_safe() -> None:
    run = build_skill_trial_run(SKILL, "AAPL", "what about {target} and {weird")
    rendered = run.tasks[0].prompt_template.format_map(
        {"target": "AAPL", "question": "q"}
    )
    assert "AAPL" in rendered
    assert "{weird" in rendered


@pytest.mark.parametrize(
    "skill,target,question",
    [("", "AAPL", "q"), ("x", "", "q"), ("x", "AAPL", "  ")],
)
def test_trial_requires_skill_target_question(skill, target, question) -> None:
    with pytest.raises(ValueError):
        build_skill_trial_run(skill, target, question)


def test_trial_rejects_unassembled_skill() -> None:
    with pytest.raises(ValueError):
        build_skill_trial_run("not-installed-skill", "AAPL", "q?")


def _completed_run(summary: str = "", *, report: str = "") -> SwarmRun:
    run = build_skill_trial_run(SKILL, "AAPL", "q?")
    run.status = RunStatus.completed
    if summary:
        run.tasks[0].status = TaskStatus.completed
        run.tasks[0].summary = summary
    if report:
        run.final_report = report
    return run


def test_trial_success_rule() -> None:
    assert not trial_succeeded(_completed_run())
    assert trial_succeeded(_completed_run(summary="结论：偏多"))
    assert trial_succeeded(_completed_run(report="final answer"))

    failed = _completed_run(summary="x")
    failed.status = RunStatus.failed
    assert not trial_succeeded(failed)


def test_runtime_rejects_conflicting_launch_modes(tmp_path) -> None:
    runtime = SwarmRuntime(store=SwarmStore(base_dir=tmp_path / "runs"))
    with pytest.raises(ValueError):
        runtime.start_run(
            "investment_committee",
            {},
            custom_spec={"nodes": []},
            skill_trial={"skill_name": SKILL, "target": "AAPL", "question": "q?"},
        )
    with pytest.raises(ValueError):
        runtime.start_run(
            "investment_committee",
            {},
            resume_from=object(),
            skill_trial={"skill_name": SKILL, "target": "AAPL", "question": "q?"},
        )
