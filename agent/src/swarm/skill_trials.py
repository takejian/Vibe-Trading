"""Standalone single-skill trial runs for the Skill Square.

A trial reuses the whole swarm execution machinery (store, SSE, cancellation,
output-quality discipline, grounding, final report) but the graph is a single
agent/task whose ``skills`` allowlist contains exactly the one skill on
trial. The trial agent receives the broad research tool pool — the union of
tools pre-approved across bundled presets (operator-trusted); the tool
registry still drops anything not actually available at runtime.

Success discipline (mirrors team runs): a trial counts as successful only
when the run completes and the single task finishes with a non-empty summary
(empty / plan-only / simulated-data output is already judged by the worker).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from functools import lru_cache

from src.agent.skills import SkillsLoader
from src.swarm.custom_spec import _escape_template_text
from src.swarm.models import RunStatus, SwarmAgentSpec, SwarmRun, SwarmTask, TaskStatus
from src.swarm.presets import list_presets, load_preset

_TRIAL_AGENT_ID = "skill_analyst"
_TRIAL_TASK_ID = "task_run_skill"


def _trial_budget() -> tuple[int, int]:
    """Resolve the trial worker's ``(max_iterations, timeout_seconds)``.

    Defaults come from :class:`src.config.env_schema.SwarmConfig`
    (``SWARM_SKILL_TRIAL_MAX_ITER`` / ``SWARM_SKILL_TRIAL_TIMEOUT``, 40 /
    900s out of the box — aligned with built-in role budgets). Read lazily
    like the worker's own fallbacks so tests/operators can override via env.
    """
    from src.config.accessor import get_env_config

    cfg = get_env_config().swarm
    return int(cfg.swarm_skill_trial_max_iter), int(cfg.swarm_skill_trial_timeout)


@lru_cache(maxsize=1)
def preset_tool_union() -> tuple[str, ...]:
    """All tool names whitelisted by at least one available preset (cached)."""
    tools: set[str] = set()
    for summary in list_presets():
        try:
            data = load_preset(summary["name"])
        except Exception:
            continue
        for agent in data.get("agents", []) if isinstance(data, dict) else []:
            if isinstance(agent, dict):
                tools.update(
                    tool
                    for tool in agent.get("tools", [])
                    if isinstance(tool, str)
                )
    return tuple(sorted(tools))


def build_skill_trial_run(skill_name: str, target: str, question: str) -> SwarmRun:
    """Construct a pending single-agent :class:`SwarmRun` for one skill.

    Raises:
        ValueError: Empty target/question or unknown/unassembled skill name.
    """
    skill_name = (skill_name or "").strip()
    target = (target or "").strip()
    question = (question or "").strip()
    if not skill_name:
        raise ValueError("技能名称不能为空")
    if not target:
        raise ValueError("评估标的不能为空")
    if not question:
        raise ValueError("研究问题不能为空")

    known = {skill.name for skill in SkillsLoader().skills}
    if skill_name not in known:
        raise ValueError(f"技能不存在或未装配: {skill_name!r}")

    system_prompt = (
        f"You are running a standalone trial of the '{skill_name}' skill for "
        f"the evaluation target. First load the skill documentation via the "
        f"load_skill tool, then follow its workflow strictly to analyze the "
        f"target and answer the research question. Base every claim on "
        f"evidence actually obtained during this run; do not invent data."
    )
    prompt_template = (
        f"Trial skill: {skill_name}\n"
        "Evaluation target: {target}\n"
        f"Research question: {_escape_template_text(question)}\n"
        "Load the skill, perform the analysis within its scope, and finish "
        "with a structured conclusion."
    )

    max_iterations, timeout_seconds = _trial_budget()

    now = datetime.now(timezone.utc)
    run_id = f"swarm-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    agent = SwarmAgentSpec(
        id=_TRIAL_AGENT_ID,
        role=skill_name,
        system_prompt=system_prompt,
        tools=list(preset_tool_union()),
        skills=[skill_name],
        max_iterations=max_iterations,
        timeout_seconds=timeout_seconds,
    )
    task = SwarmTask(
        id=_TRIAL_TASK_ID,
        agent_id=_TRIAL_AGENT_ID,
        prompt_template=prompt_template,
        status=TaskStatus.pending,
    )
    return SwarmRun(
        id=run_id,
        preset_name=f"skill:{skill_name}",
        status=RunStatus.pending,
        user_vars={"target": target, "question": question},
        agents=[agent],
        tasks=[task],
        created_at=now.isoformat(),
        customized=False,
        research_target=target,
        research_question=question,
        kind="skill_trial",
        trial_skill=skill_name,
    )


def trial_succeeded(run: SwarmRun) -> bool:
    """Apply the trial success rule: completed run with a qualified output."""
    from src.swarm.models import RunStatus as _RunStatus

    if run.status != _RunStatus.completed:
        return False
    terminal = [
        task
        for task in run.tasks
        if task.status == TaskStatus.completed and (task.summary or "").strip()
    ]
    return bool(terminal) or bool((run.final_report or "").strip())


def trial_qualifies_for_global_approval(run: SwarmRun) -> bool:
    """Whether a successful trial flips the *global* package approval bit.

    Only assembled (built-in/operator-installed) skills auto-approve on a
    qualified trial. Personal custom skills follow the manual operator
    approval path; a deleted in-flight custom skill must not leave a stale
    global approval for its name either.
    """
    from src.swarm.skill_catalog import (
        assembled_skill_names,
        is_custom_skill_name,
    )

    name = getattr(run, "trial_skill", None)
    if not name or not trial_succeeded(run):
        return False
    return name in assembled_skill_names() and not is_custom_skill_name(name)
