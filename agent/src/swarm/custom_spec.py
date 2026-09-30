"""Web-orchestrated, single-use swarm customizations.

The web "team orchestration" page lets a user pick a bundled preset and
temporarily adjust its roster (add/remove nodes, edit each node's duty /
allowed tools / timeout) and its collaboration edges before launching one
evaluation. The customization:

* never writes a YAML file (built-in presets stay byte-for-byte unchanged),
* is not saved as a reusable or shareable team plan,
* lives only on the resulting run — run.json's agents/tasks already carry
  the full edited graph, which is the long-lived "evaluation snapshot".

This module validates an inbound custom spec and builds a :class:`SwarmRun`
from it. Structural validation mirrors the frontend's real-time checks; the
backend is authoritative (HTTP 400 on any violation).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from src.swarm.models import RunStatus, SwarmAgentSpec, SwarmRun, SwarmTask, TaskStatus
from src.swarm.presets import load_preset
from src.swarm.task_store import validate_dag

#: Node ids double as agent ids (filesystem artifact segment), so they must
#: be short, URL/path-safe slugs.
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
#: Per-node worker timeout bounds for web-customized nodes (seconds).
_MIN_TIMEOUT_SECONDS = 1
_MAX_TIMEOUT_SECONDS = 1800
#: Default iteration budget for user-added nodes (matches SwarmAgentSpec).
_NEW_NODE_MAX_ITERATIONS = 25
_NEW_NODE_TEMPLATE = (
    "Fulfill your assigned role for {target} and address the research "
    "question. Use the upstream context when provided."
)


def _slug(value: str) -> str:
    """Collapse an identifier to a safe lowercase task/key fragment."""
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return f"n_{slug}" if slug[:1].isdigit() else slug


def _escape_template_text(text: str) -> str:
    """Escape braces in user text embedded into a format template.

    Task prompt templates are later rendered with ``str.format_map``; raw
    user content appended to a template must have its braces doubled or a
    question like ``"evaluate {x}"`` could raise during rendering.
    """
    return text.replace("{", "{{").replace("}", "}}")


def _preset_index(preset_data: dict) -> tuple[dict[str, dict], dict[str, dict], set[str]]:
    """Index the source preset's agents/tasks and build the tool catalog."""
    agents_by_id: dict[str, dict] = {}
    for agent_data in preset_data.get("agents", []):
        agent_id = agent_data.get("id")
        if isinstance(agent_id, str):
            agents_by_id[agent_id] = agent_data

    tasks_by_agent: dict[str, dict] = {}
    for task_data in preset_data.get("tasks", []):
        agent_id = task_data.get("agent_id")
        if isinstance(agent_id, str) and agent_id not in tasks_by_agent:
            tasks_by_agent[agent_id] = task_data

    catalog = {
        tool
        for agent_data in agents_by_id.values()
        for tool in agent_data.get("tools", [])
        if isinstance(tool, str)
    }
    return agents_by_id, tasks_by_agent, catalog


def validate_custom_spec_graph(preset_name: str, graph: dict) -> None:
    """Validate only the graph half of a custom spec (used when saving a team).

    "Save as my team" is legal exactly when the same graph would launch; the
    evaluation target/question are not part of a saved team, so non-empty
    placeholders stand in for them (they only feed prompt text).

    Raises:
        ValueError: Any structural/element/skill violation.
        FileNotFoundError: The source preset does not exist.
    """
    spec = {
        "nodes": graph.get("nodes", []),
        "edges": graph.get("edges", []),
        "target": "_",
        "question": "_",
    }
    build_run_from_custom_spec(preset_name, spec)


def build_run_from_custom_spec(
    preset_name: str,
    spec: dict,
    user_vars: dict[str, str] | None = None,
) -> SwarmRun:
    """Validate a web-customized spec and build a pending :class:`SwarmRun`.

    Args:
        preset_name: Source preset name (the customization starts from a
            bundled/user preset; that preset itself is never modified).
        spec: ``{"nodes": [...], "edges": [...], "target": str,
            "question": str}``.
        user_vars: Optional extra template variables; canonical ``target``
            and ``question`` keys are always overwritten from ``spec``.

    Returns:
        A fully constructed pending ``SwarmRun`` with ``customized=True``.

    Raises:
        ValueError: Structural or field validation failure (mapped to
            HTTP 400 by the route layer).
        FileNotFoundError: The source preset does not exist.
    """
    if not isinstance(spec, dict):
        raise ValueError("custom spec must be an object")

    target = str(spec.get("target", "") or "").strip()
    question = str(spec.get("question", "") or "").strip()
    if not target:
        raise ValueError("评估标的不能为空")
    if not question:
        raise ValueError("研究问题不能为空")

    raw_nodes = spec.get("nodes")
    raw_edges = spec.get("edges", [])
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("至少需要一个角色节点")
    if not isinstance(raw_edges, list):
        raise ValueError("edges must be a list")

    preset_data = load_preset(preset_name)
    preset_agents, preset_tasks, tool_catalog = _preset_index(preset_data)

    # Skills allowed on nodes of THIS customization:
    #   preset skill union  ∪  globally approved skills (assembled packages
    #   and operator-approved personal custom skills, all physically present)
    # Unknown/delisted skills are a HARD error (unlike out-of-catalog tools,
    # which are silently stripped): the canvas highlights such references and
    # the launch must be blocked until the user removes/replaces them.
    from src.swarm.skill_catalog import list_approved_skill_names

    preset_skill_union = {
        skill
        for agent_data in preset_agents.values()
        for skill in agent_data.get("skills", [])
        if isinstance(skill, str)
    }
    allowed_skills = preset_skill_union | set(list_approved_skill_names())

    # --- Normalize + validate nodes -------------------------------------
    node_ids: set[str] = set()
    nodes: list[dict] = []
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index + 1} 个节点格式不合法")
        node_id = str(raw.get("id", "") or "").strip()
        if not _NODE_ID_RE.match(node_id):
            raise ValueError(
                f"节点标识不合法: {node_id!r}（仅允许字母、数字、下划线、短横线，且不超过 64 个字符）"
            )
        if node_id in node_ids:
            raise ValueError(f"节点标识重复: {node_id!r}")
        node_ids.add(node_id)

        role = str(raw.get("role", "") or "").strip()
        if not role:
            raise ValueError(f"节点 {node_id!r} 缺少角色名称")
        duty = str(raw.get("duty", "") or "").strip()
        if not duty:
            raise ValueError(f"节点 {node_id!r} 缺少职责说明")

        # When the node carries a role reference (canvas now introduces
        # roles exclusively from the Role Square), the referenced role must
        # still exist and be approved. Revoked/deleted role references are
        # a hard error on both launch and team save/update. Nodes without
        # role_ref (legacy snapshots) keep the legacy permissive behavior.
        role_ref = raw.get("role_ref")
        if role_ref is not None:
            role_ref = str(role_ref or "").strip()
        if role_ref:
            from src.swarm.role_catalog import is_role_approved, resolve_role

            try:
                resolve_role(role_ref)
            except (ValueError, FileNotFoundError):
                raise ValueError(
                    f"节点 {node_id!r} 引用的角色已不存在: {role_ref!r}，"
                    "请替换或移除该角色后再发起"
                ) from None
            if not is_role_approved(role_ref):
                raise ValueError(
                    f"节点 {node_id!r} 引用的角色未放开通过: {role_ref!r}，"
                    "请替换为已通过角色或请运维管理员放开后再发起"
                )

        timeout = raw.get("timeout_seconds")
        if isinstance(timeout, bool) or not isinstance(timeout, int):
            raise ValueError(f"节点 {node_id!r} 的执行时长必须为正整数（秒）")
        if not _MIN_TIMEOUT_SECONDS <= timeout <= _MAX_TIMEOUT_SECONDS:
            raise ValueError(
                f"节点 {node_id!r} 的执行时长必须在 "
                f"{_MIN_TIMEOUT_SECONDS}–{_MAX_TIMEOUT_SECONDS} 秒之间"
            )

        raw_tools = raw.get("tools", [])
        if not isinstance(raw_tools, list):
            raise ValueError(f"节点 {node_id!r} 的可用能力必须为列表")
        # Trust boundary: only tools the source preset pre-approved can be
        # used; anything outside the catalog is silently stripped (same
        # "assemble-time removal" discipline as preset loading).
        tools = sorted(
            {
                tool
                for tool in raw_tools
                if isinstance(tool, str) and tool in tool_catalog
            }
        )

        raw_skills = raw.get("skills")
        if raw_skills is None:
            skills_override: list[str] | None = None
        elif not isinstance(raw_skills, list):
            raise ValueError(f"节点 {node_id!r} 的使用技能必须为列表")
        else:
            skills_override = []
            seen_skills: set[str] = set()
            for skill in raw_skills:
                if not isinstance(skill, str) or not skill.strip():
                    raise ValueError(f"节点 {node_id!r} 的技能名称不合法: {skill!r}")
                name = skill.strip()
                if name not in allowed_skills:
                    raise ValueError(
                        f"节点 {node_id!r} 引用了不可用的技能 {name!r}"
                        "（不在本团队技能目录中，或该技能未通过试运行/已下架）"
                    )
                if name not in seen_skills:
                    seen_skills.add(name)
                    skills_override.append(name)

        is_new = bool(raw.get("is_new", node_id not in preset_agents))
        source_agent = preset_agents.get(node_id)
        source_task = preset_tasks.get(node_id)
        source_task_id = raw.get("source_task_id")
        if (
            not is_new
            and isinstance(source_task_id, str)
            and isinstance(preset_data.get("tasks"), list)
        ):
            for task_data in preset_data["tasks"]:
                if task_data.get("id") == source_task_id:
                    source_task = task_data
                    break

        nodes.append(
            {
                "id": node_id,
                "role": role,
                "duty": duty,
                "timeout": timeout,
                "tools": tools,
                "skills_override": skills_override,
                "is_new": is_new,
                "source_agent": source_agent,
                "source_task": source_task,
            }
        )

    # --- Normalize + validate edges -------------------------------------
    node_by_id = {node["id"]: node for node in nodes}
    has_incoming: set[str] = set()
    has_outgoing: set[str] = set()
    edge_set: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_edges):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index + 1} 条连线格式不合法")
        upstream = str(raw.get("upstream", "") or "").strip()
        downstream = str(raw.get("downstream", "") or "").strip()
        if upstream not in node_by_id:
            raise ValueError(f"第 {index + 1} 条连线引用了不存在的上游节点: {upstream!r}")
        if downstream not in node_by_id:
            raise ValueError(f"第 {index + 1} 条连线引用了不存在的下游节点: {downstream!r}")
        if upstream == downstream:
            raise ValueError(f"节点 {upstream!r} 不允许连接到自身")
        if (upstream, downstream) in edge_set:
            continue  # duplicate edges are harmless — dedupe silently
        edge_set.add((upstream, downstream))
        has_incoming.add(downstream)
        has_outgoing.add(upstream)

    starts = node_ids - has_incoming
    if not starts:
        raise ValueError("流程缺少起点角色（所有角色都设置了上游依赖）")
    if len(nodes) > 1:
        # An orphan participates in no edge at all. A node fed by or feeding
        # another independent chain is valid (multi-start DAGs are allowed).
        orphans = sorted(node_ids - has_incoming - has_outgoing)
        if orphans:
            raise ValueError(f"存在未纳入协作流程的孤立角色: {', '.join(orphans)}")

    # --- Build agents + tasks -------------------------------------------
    task_id_by_node: dict[str, str] = {}
    used_task_ids: set[str] = set()
    for node in nodes:
        base = _slug(node["id"])
        task_id = f"task_{base}"
        suffix = 2
        while task_id in used_task_ids:
            task_id = f"task_{base}_{suffix}"
            suffix += 1
        used_task_ids.add(task_id)
        task_id_by_node[node["id"]] = task_id

    depends_by_task: dict[str, list[str]] = {}
    input_from_by_task: dict[str, dict[str, str]] = {}
    for upstream, downstream in sorted(edge_set):
        downstream_task = task_id_by_node[downstream]
        depends_by_task.setdefault(downstream_task, []).append(
            task_id_by_node[upstream]
        )
        key = _slug(upstream)
        input_from_by_task.setdefault(downstream_task, {})[
            key
        ] = task_id_by_node[upstream]

    agents: list[SwarmAgentSpec] = []
    tasks: list[SwarmTask] = []
    escaped_question = _escape_template_text(question)
    for node in nodes:
        source_agent = node["source_agent"]
        source_task = node["source_task"]
        is_new = node["is_new"]

        system_prompt = node["duty"]
        incoming = input_from_by_task.get(task_id_by_node[node["id"]])
        if incoming and "{upstream_context}" not in system_prompt:
            # The worker injects upstream summaries ONLY through this
            # placeholder (worker.py); append one when the edited/new
            # duty text does not already provide it.
            system_prompt = f"{system_prompt}\n\n{{upstream_context}}"

        if is_new or source_task is None:
            prompt_template = _NEW_NODE_TEMPLATE
            max_iterations = _NEW_NODE_MAX_ITERATIONS
            model_name = None
            max_retries = 2
        else:
            prompt_template = str(source_task.get("prompt_template", "") or _NEW_NODE_TEMPLATE)
            max_iterations = int(
                (source_agent or {}).get("max_iterations", _NEW_NODE_MAX_ITERATIONS)
            )
            model_name = (source_agent or {}).get("model_name")
            max_retries = int((source_agent or {}).get("max_retries", 2))

        # Explicit per-node skills from the canvas win; otherwise keep the
        # source agent's preset skills (new nodes without an override get []).
        if node["skills_override"] is not None:
            skills = list(node["skills_override"])
        elif is_new or source_task is None:
            skills = []
        else:
            skills = list((source_agent or {}).get("skills", []))

        prompt_template = (
            f"{prompt_template}\n\nResearch question: {escaped_question}"
        )

        agents.append(
            SwarmAgentSpec(
                id=node["id"],
                role=node["role"],
                system_prompt=system_prompt,
                tools=node["tools"],
                skills=skills,
                max_iterations=max_iterations,
                timeout_seconds=node["timeout"],
                model_name=model_name,
                max_retries=max_retries,
            )
        )

        task_id = task_id_by_node[node["id"]]
        depends_on = sorted(depends_by_task.get(task_id, []))
        tasks.append(
            SwarmTask(
                id=task_id,
                agent_id=node["id"],
                prompt_template=prompt_template,
                depends_on=depends_on,
                blocked_by=list(depends_on),
                input_from=dict(sorted(input_from_by_task.get(task_id, {}).items())),
                status=TaskStatus.blocked if depends_on else TaskStatus.pending,
            )
        )

    # Authoritative DAG validation (unknown-dep + cycle detection).
    validate_dag(tasks)

    merged_vars: dict[str, str] = dict(user_vars or {})
    merged_vars["target"] = target
    merged_vars["question"] = question

    now = datetime.now(timezone.utc)
    run_id = f"swarm-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    return SwarmRun(
        id=run_id,
        preset_name=preset_name,
        status=RunStatus.pending,
        user_vars=merged_vars,
        agents=agents,
        tasks=tasks,
        created_at=now.isoformat(),
        customized=True,
        research_target=target,
        research_question=question,
    )
