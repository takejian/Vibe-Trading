"""Standalone single-role runs for the Role Square.

A role run reuses the whole swarm execution machinery (store, SSE,
cancellation, output-quality discipline, grounding, final report) but the
graph is a single agent/task built from one resolved role profile. Both
built-in roles and unapproved custom roles may be run (the creator runs an
unapproved role to produce the qualified result required before the
operator can approve it).

Unlike skill trials, a successful role run does NOT flip any global state:
role approval stays a manual operator action.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.swarm.custom_spec import _escape_template_text
from src.swarm.models import RunStatus, SwarmAgentSpec, SwarmRun, SwarmTask, TaskStatus
from src.swarm.role_catalog import parse_builtin_ref, resolve_role
from src.swarm.roles import RoleStore

_UPSTREAM_SENTINEL = "\x00__UPSTREAM_CONTEXT__\x00"


class _SafeVars(dict):
    """Format mapping that renders missing fields as empty."""

    def __missing__(self, key: str) -> str:  # pragma: no cover - trivial
        return ""


def _normalize_system_prompt(prompt: str, target: str, question: str) -> str:
    """Render preset variables in the role prompt.

    ``{upstream_context}`` is preserved for worker injection (single-node
    runs get an empty upstream block); other placeholders are rendered from
    target/question, unknown ones blank out. If anything in the prompt
    cannot be formatted, the original text is kept verbatim.
    """
    protected = prompt.replace("{upstream_context}", _UPSTREAM_SENTINEL)
    variables = _SafeVars(target=target, question=question)
    try:
        rendered = protected.format_map(variables)
    except (ValueError, IndexError, AttributeError):
        return prompt
    return rendered.replace(_UPSTREAM_SENTINEL, "{upstream_context}")


def build_role_run(
    role_ref: str,
    target: str,
    question: str,
    store: "RoleStore | None" = None,
) -> SwarmRun:
    """Construct a pending single-agent :class:`SwarmRun` for one role.

    Raises:
        ValueError: Empty target/question or unknown role reference.
        FileNotFoundError: The custom role no longer exists.
    """
    role_ref = (role_ref or "").strip()
    target = (target or "").strip()
    question = (question or "").strip()
    if not role_ref:
        raise ValueError("角色引用不能为空")
    if not target:
        raise ValueError("评估标的不能为空")
    if not question:
        raise ValueError("研究问题不能为空")

    profile = resolve_role(role_ref, store)

    if ":" in role_ref:
        _, agent_id = parse_builtin_ref(role_ref)
    else:
        agent_id = "role_analyst"

    system_prompt = _normalize_system_prompt(
        profile["system_prompt"], target, question
    )
    prompt_template = (
        "Evaluation target: {target}\n"
        f"Research question: {_escape_template_text(question)}\n"
        "Fulfill your assigned role, base every claim on evidence actually "
        "obtained during this run, and finish with a structured conclusion."
    )

    now = datetime.now(timezone.utc)
    run_id = f"swarm-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    agent = SwarmAgentSpec(
        id=agent_id,
        role=profile["name"],
        system_prompt=system_prompt,
        tools=list(profile["tools"]),
        skills=list(profile["skills"]),
        max_iterations=int(profile["max_iterations"]),
        timeout_seconds=int(profile["timeout_seconds"]),
    )
    task = SwarmTask(
        id="task_run_role",
        agent_id=agent_id,
        prompt_template=prompt_template,
        status=TaskStatus.pending,
    )
    return SwarmRun(
        id=run_id,
        preset_name=f"role:{role_ref}",
        status=RunStatus.pending,
        user_vars={"target": target, "question": question},
        agents=[agent],
        tasks=[task],
        created_at=now.isoformat(),
        customized=False,
        research_target=target,
        research_question=question,
        kind="role_run",
        trial_role=role_ref,
    )


def role_run_succeeded(run: SwarmRun) -> bool:
    """Apply the run success rule: completed run with a qualified output."""
    if run.status != RunStatus.completed:
        return False
    terminal = [
        task
        for task in run.tasks
        if task.status == TaskStatus.completed and (task.summary or "").strip()
    ]
    return bool(terminal) or bool((run.final_report or "").strip())
