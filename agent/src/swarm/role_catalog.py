"""Read-only role catalog for the Role Square / team canvas.

Aggregates two role sources behind one reference scheme:

* **built-in roles** — every agent defined in a bundled/user preset; reference
  is ``"{preset_name}:{agent_id}"``; always approved and read-only;
* **custom roles** — user-created :class:`~src.swarm.roles.CustomRole`
  records; reference is the role id (never contains ``:``); approval state
  comes from the role record.

A role *profile* is the full, uniform definition (name, purpose, system
prompt, tools, skills, iteration/timeout limits) used by both the detail
page and the standalone role-run builder.
"""

from __future__ import annotations

import re

from src.swarm.presets import list_presets, load_preset
from src.swarm.roles import RoleStore

SEPARATOR = ":"
_MAX_PURPOSE_LEN = 100
_MARKDOWN_PREFIX_RE = re.compile(r"^[#>*\-\s]+")
_WHITESPACE_RE = re.compile(r"\s+")


def is_builtin_ref(role_ref: str) -> bool:
    """Whether a role reference points at a preset agent."""
    return bool(role_ref) and SEPARATOR in role_ref


def parse_builtin_ref(role_ref: str) -> tuple[str, str]:
    """Split ``"preset:agent"`` into its parts (validated on resolution)."""
    preset_name, _, agent_id = role_ref.partition(SEPARATOR)
    return preset_name, agent_id


def derive_purpose(system_prompt: str, fallback: str = "") -> str:
    """Build a short business-purpose excerpt from the first prompt line.

    Preset YAMLs carry no separate role description; the first non-empty
    line of the system prompt is conventionally the role identity sentence.
    Markdown markers are stripped and the text is collapsed/truncated.
    """
    for raw_line in (system_prompt or "").splitlines():
        line = _WHITESPACE_RE.sub(" ", _MARKDOWN_PREFIX_RE.sub("", raw_line)).strip()
        if line:
            return line[:_MAX_PURPOSE_LEN]
    return fallback[:_MAX_PURPOSE_LEN]


def _builtin_role_item(preset_name: str, agent: dict) -> dict:
    role = str(agent.get("role", "") or "").strip()
    agent_id = str(agent.get("id", "") or "").strip()
    return {
        "ref": f"{preset_name}{SEPARATOR}{agent_id}",
        "name": role or agent_id,
        "purpose": derive_purpose(str(agent.get("system_prompt", "") or ""), role),
        "approved": True,
    }


def list_role_groups(store: RoleStore | None = None) -> dict:
    """Return the full grouped role catalog.

    Structure::

        {"groups": [
            {"kind": "builtin", "ref": "<preset>", "title", "description",
             "roles": [{ref, name, purpose, approved}]},
            ...,
            {"kind": "custom", "ref": "custom", "title": "自建角色",
             "roles": [{ref, name, purpose, approved}]},
        ]}
    """
    groups: list[dict] = []
    for summary in list_presets():
        preset_name = summary["name"]
        try:
            data = load_preset(preset_name)
        except Exception:
            continue
        roles = [
            _builtin_role_item(preset_name, agent)
            for agent in data.get("agents", [])
            if isinstance(agent, dict)
        ]
        groups.append(
            {
                "kind": "builtin",
                "ref": preset_name,
                "title": str(data.get("title", "") or summary.get("title", "")),
                "description": str(
                    data.get("description", "") or summary.get("description", "")
                ),
                "roles": roles,
            }
        )

    store = store or RoleStore()
    custom_roles = [
        {
            "ref": role.id,
            "name": role.name,
            "purpose": role.purpose or derive_purpose(role.system_prompt, role.name),
            "approved": role.approved,
        }
        for role in store.list_roles()
    ]
    groups.append(
        {
            "kind": "custom",
            "ref": "custom",
            "title": "自建角色",
            "description": "",
            "roles": custom_roles,
        }
    )
    return {"groups": groups}


def list_approved_role_refs(store: RoleStore | None = None) -> list[dict]:
    """Flat catalog of approved roles (canvas 'add role' picker)."""
    catalog = list_role_groups(store)
    items: list[dict] = []
    for group in catalog["groups"]:
        if group["kind"] == "builtin":
            items.extend(group["roles"])
        else:
            items.extend(role for role in group["roles"] if role["approved"])
    items.sort(key=lambda item: item["name"])
    return items


def _builtin_profile(role_ref: str) -> dict:
    preset_name, agent_id = parse_builtin_ref(role_ref)
    if not preset_name or not agent_id:
        raise ValueError(f"内置角色引用不合法: {role_ref!r}")
    data = load_preset(preset_name)
    for agent in data.get("agents", []):
        if isinstance(agent, dict) and str(agent.get("id", "")) == agent_id:
            role = str(agent.get("role", "") or "").strip()
            system_prompt = str(agent.get("system_prompt", "") or "")
            return {
                "kind": "builtin",
                "ref": role_ref,
                "name": role or agent_id,
                "purpose": derive_purpose(system_prompt, role),
                "system_prompt": system_prompt,
                "tools": [
                    str(tool)
                    for tool in agent.get("tools", [])
                    if isinstance(tool, str)
                ],
                "skills": [
                    str(skill)
                    for skill in agent.get("skills", [])
                    if isinstance(skill, str)
                ],
                "max_iterations": int(agent.get("max_iterations", 25)),
                "timeout_seconds": int(agent.get("timeout_seconds", 300)),
                "approved": True,
                "derived_from": None,
            }
    raise ValueError(f"内置角色不存在: {role_ref!r}")


def _custom_profile(role_ref: str, store: RoleStore) -> dict:
    role = store.get_role(role_ref)
    return {
        "kind": "custom",
        "ref": role.id,
        "name": role.name,
        "purpose": role.purpose or derive_purpose(role.system_prompt, role.name),
        "system_prompt": role.system_prompt,
        "tools": list(role.tools),
        "skills": list(role.skills),
        "max_iterations": role.max_iterations,
        "timeout_seconds": role.timeout_seconds,
        "approved": role.approved,
        "derived_from": role.derived_from,
    }


def resolve_role(role_ref: str, store: RoleStore | None = None) -> dict:
    """Return the full uniform profile of any role reference.

    Raises:
        ValueError: Malformed/unknown reference.
        FileNotFoundError: Custom role id no longer exists.
    """
    role_ref = (role_ref or "").strip()
    if not role_ref:
        raise ValueError("角色引用不能为空")
    if is_builtin_ref(role_ref):
        return _builtin_profile(role_ref)
    return _custom_profile(role_ref, store or RoleStore())


def is_role_approved(role_ref: str, store: RoleStore | None = None) -> bool:
    """Approval state of a role reference; unknown refs are not approved."""
    try:
        return bool(resolve_role(role_ref, store).get("approved"))
    except (ValueError, FileNotFoundError):
        return False
