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
from src.swarm.store import SwarmStore, swarm_runs_root

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


def register_completed_role_run(
    *,
    role_ref: str,
    target: str,
    question: str,
    report: str,
    run_id: str,
    analyzed_at: datetime | None = None,
    store: SwarmStore | None = None,
    role_store: "RoleStore | None" = None,
) -> SwarmRun:
    """Register an already-finished standalone role run in the swarm store.

    Offline pipelines (e.g. the chanlun-bi-analysis skill) produce a qualified
    role report without going through the live swarm worker, but the Role
    Square reads only ``kind="role_run"`` files from the swarm store. This
    bridges that gap by persisting a terminal single-agent run whose
    ``final_report`` (and sole task summary) is the finished report.

    Idempotent: if ``run_id`` already exists on disk it is loaded and
    returned unchanged, so re-running an import never duplicates the record.

    Args:
        role_ref: Built-in role reference (``"preset:agent_id"``) or custom
            role id.
        target: Evaluation target, e.g. a stock symbol.
        question: Research question the report answers.
        report: Full finished report text (becomes final_report).
        run_id: Caller-chosen bare run-directory name, ideally the same id
            used for the analysis row in DuckDB.
        analyzed_at: Analysis completion time; naive values are interpreted as
            local time. Defaults to now (UTC).
        store: Override swarm store (tests).
        role_store: Override custom-role store (tests).

    Returns:
        The persisted completed :class:`SwarmRun`.

    Raises:
        ValueError: Empty report or an invalid/unknown role reference.
    """
    report = (report or "").strip()
    if not report:
        raise ValueError("角色运行报告不能为空")
    run_id = (run_id or "").strip()
    if not run_id:
        raise ValueError("run_id 不能为空")

    store = store or SwarmStore(swarm_runs_root())
    existing = store.load_run(run_id)
    if existing is not None:
        return existing

    if analyzed_at is None:
        finished = datetime.now(timezone.utc)
    elif analyzed_at.tzinfo is None:
        finished = analyzed_at.astimezone(timezone.utc)
    else:
        finished = analyzed_at.astimezone(timezone.utc)
    finished_iso = finished.isoformat()

    run = build_role_run(role_ref, target, question, role_store)
    task = run.tasks[0].model_copy(
        update={
            "status": TaskStatus.completed,
            "summary": report,
            "started_at": finished_iso,
            "completed_at": finished_iso,
        }
    )
    run = run.model_copy(
        update={
            "id": run_id,
            "status": RunStatus.completed,
            "tasks": [task],
            "completed_at": finished_iso,
            "final_report": report,
        }
    )
    store.create_run(run)
    return run


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
