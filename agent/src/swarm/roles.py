"""User-created custom roles backing the Role Square.

A custom role is a standalone role definition an investor creates from the
"智能体（角色）" page. Unlike a canvas one-off customization (which lives
only on the run snapshot), a custom role is a reusable JSON file under
``<runtime_root>/swarm/roles/`` and has a global approval state:

* newly created roles are *unapproved* and visible only to their creator;
* the operator approves a role manually in its detail page, and only after
  it has at least one qualified standalone run;
* once approved it is visible to every investor and appears in the team
  canvas "add role" catalog;
* editing an approved role keeps it approved; the operator may revoke the
  approval at any time.

Deletion / approval revocation never touches run snapshots or role-run
history: runs embed their own full agent/task graph.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from src.config.paths import get_roles_dir

_ROLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MAX_NAME_LEN = 80
_MAX_PURPOSE_LEN = 200
_MAX_PROMPT_LEN = 12000
_MIN_TIMEOUT_SECONDS = 1
_MAX_TIMEOUT_SECONDS = 1800
_MIN_ITERATIONS = 1
_MAX_ITERATIONS = 100


class CustomRole(BaseModel):
    """One user-created reusable role definition."""

    id: str
    name: str
    purpose: str = ""
    system_prompt: str
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    max_iterations: int = 25
    timeout_seconds: int = 300
    approved: bool = False
    approved_at: str | None = None
    derived_from: str | None = None
    created_at: str
    updated_at: str


def builtin_role_names() -> set[str]:
    """Display names of every built-in role (``role`` field across presets).

    Used for the global name-uniqueness gate on custom roles.
    """
    from src.swarm.presets import list_presets, load_preset

    names: set[str] = set()
    for summary in list_presets():
        try:
            data = load_preset(summary["name"])
        except Exception:
            continue
        for agent in data.get("agents", []) if isinstance(data, dict) else []:
            if isinstance(agent, dict):
                role = str(agent.get("role", "") or "").strip()
                if role:
                    names.add(role)
    return names


class RoleStore:
    """File-backed CRUD for custom roles."""

    def __init__(self, base_dir: str | os.PathLike[str] | None = None) -> None:
        self._dir = base_dir if base_dir is not None else get_roles_dir()

    # ------------------------------------------------------------------
    def _path_for(self, role_id: str) -> str:
        if not _ROLE_ID_RE.match(role_id or ""):
            raise ValueError(f"角色标识不合法: {role_id!r}")
        return os.path.join(self._dir, f"{role_id}.json")

    def _write(self, role: CustomRole) -> None:
        os.makedirs(self._dir, exist_ok=True)
        target = self._path_for(role.id)
        fd, tmp_name = tempfile.mkstemp(prefix=".role-", suffix=".json", dir=self._dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(role.model_dump(), handle, ensure_ascii=False, indent=2)
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    def list_roles(self) -> list[CustomRole]:
        if not os.path.isdir(self._dir):
            return []
        roles: list[CustomRole] = []
        for entry in os.listdir(self._dir):
            if not entry.endswith(".json") or entry.startswith("."):
                continue
            try:
                with open(os.path.join(self._dir, entry), encoding="utf-8") as handle:
                    roles.append(CustomRole.model_validate(json.load(handle)))
            except (OSError, json.JSONDecodeError, ValueError):
                # Skip corrupt rows rather than failing the whole gallery.
                continue
        roles.sort(key=lambda role: role.updated_at, reverse=True)
        return roles

    def get_role(self, role_id: str) -> CustomRole:
        path = self._path_for(role_id)
        try:
            with open(path, encoding="utf-8") as handle:
                return CustomRole.model_validate(json.load(handle))
        except FileNotFoundError:
            raise FileNotFoundError(f"自建角色不存在: {role_id}") from None

    def name_exists(self, name: str, exclude_id: str | None = None) -> bool:
        target = name.strip()
        return any(
            role.name == target and role.id != exclude_id for role in self.list_roles()
        )

    # ------------------------------------------------------------------
    def _allowed_tools(self) -> set[str]:
        # Union of tools whitelisted by bundled presets (operator-trusted).
        from src.swarm.skill_trials import preset_tool_union

        return set(preset_tool_union())

    def _allowed_skills(self) -> set[str]:
        # Custom roles may only use skills that are assembled AND approved —
        # either globally approved packages or operator-approved personal
        # custom skills (uniform approved catalog).
        from src.swarm.skill_catalog import list_approved_skill_names

        return set(list_approved_skill_names())

    def _validate_payload(
        self,
        name: str,
        purpose: str,
        system_prompt: str,
        tools: object,
        skills: object,
        max_iterations: object,
        timeout_seconds: object,
    ) -> dict:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("角色名称不能为空")
        if len(clean_name) > _MAX_NAME_LEN:
            raise ValueError(f"角色名称不能超过 {_MAX_NAME_LEN} 个字符")

        clean_purpose = (purpose or "").strip()
        if len(clean_purpose) > _MAX_PURPOSE_LEN:
            raise ValueError(f"业务用途不能超过 {_MAX_PURPOSE_LEN} 个字符")

        clean_prompt = (system_prompt or "").strip()
        if not clean_prompt:
            raise ValueError("职责提示词不能为空")
        if len(clean_prompt) > _MAX_PROMPT_LEN:
            raise ValueError(f"职责提示词不能超过 {_MAX_PROMPT_LEN} 个字符")

        if not isinstance(tools, list):
            raise ValueError("工具清单必须为列表")
        allowed_tools = self._allowed_tools()
        clean_tools: set[str] = set()
        for tool in tools:
            if not isinstance(tool, str) or not tool.strip():
                raise ValueError(f"工具名称不合法: {tool!r}")
            item = tool.strip()
            if item not in allowed_tools:
                raise ValueError(f"工具不在允许目录内: {item!r}")
            clean_tools.add(item)

        if not isinstance(skills, list):
            raise ValueError("技能清单必须为列表")
        allowed_skills = self._allowed_skills()
        clean_skills: set[str] = set()
        for skill in skills:
            if not isinstance(skill, str) or not skill.strip():
                raise ValueError(f"技能名称不合法: {skill!r}")
            item = skill.strip()
            if item not in allowed_skills:
                raise ValueError(
                    f"技能未装配或未通过试运行: {item!r}"
                )
            clean_skills.add(item)

        if isinstance(max_iterations, bool) or not isinstance(max_iterations, int):
            raise ValueError("最大迭代轮数必须为正整数")
        if not _MIN_ITERATIONS <= max_iterations <= _MAX_ITERATIONS:
            raise ValueError(
                f"最大迭代轮数必须在 {_MIN_ITERATIONS}–{_MAX_ITERATIONS} 之间"
            )

        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
            raise ValueError("执行时长必须为正整数（秒）")
        if not _MIN_TIMEOUT_SECONDS <= timeout_seconds <= _MAX_TIMEOUT_SECONDS:
            raise ValueError(
                f"执行时长必须在 {_MIN_TIMEOUT_SECONDS}–{_MAX_TIMEOUT_SECONDS} 秒之间"
            )

        return {
            "name": clean_name,
            "purpose": clean_purpose,
            "system_prompt": clean_prompt,
            "tools": sorted(clean_tools),
            "skills": sorted(clean_skills),
            "max_iterations": max_iterations,
            "timeout_seconds": timeout_seconds,
        }

    # ------------------------------------------------------------------
    def _resolve_template(self, template_ref: str | None) -> str | None:
        """Validate a derivation template; return the normalized ref.

        Only roles that still exist and are currently approved may serve
        as templates. Imported lazily: ``role_catalog`` imports this
        module at package import time.
        """
        ref = (template_ref or "").strip()
        if not ref:
            return None
        from src.swarm.role_catalog import resolve_role

        try:
            template = resolve_role(ref, self)
        except FileNotFoundError:
            raise ValueError(
                f"模板角色已删除，无法派生: {ref!r}，请重新选择模板"
            ) from None
        except ValueError:
            raise ValueError(
                f"模板角色不存在或引用不合法: {ref!r}，请重新选择模板"
            ) from None
        if not template.get("approved"):
            raise ValueError(
                "仅可派生自已通过角色；该模板未通过或已被取消通过，"
                "请重新选择模板"
            )
        return str(template["ref"])

    # ------------------------------------------------------------------
    def create_role(
        self,
        *,
        name: str,
        purpose: str,
        system_prompt: str,
        tools: list[str],
        skills: list[str],
        max_iterations: int,
        timeout_seconds: int,
        template_ref: str | None = None,
    ) -> CustomRole:
        """Create a new unapproved custom role.

        When ``template_ref`` is given it must point at a currently
        approved role; it is recorded as the lineage but never supplies
        the (mandatory, globally unique) name.
        """
        fields = self._validate_payload(
            name, purpose, system_prompt, tools, skills,
            max_iterations, timeout_seconds,
        )
        derived_from = self._resolve_template(template_ref)
        if fields["name"] in builtin_role_names():
            raise ValueError(
                f"角色名称与内置角色重名: {fields['name']!r}，请更换名称"
            )
        if self.name_exists(fields["name"]):
            raise ValueError(
                f"已存在同名自建角色: {fields['name']!r}，请更换名称"
            )
        now = datetime.now(timezone.utc).isoformat()
        role = CustomRole(
            id=f"role-{uuid.uuid4().hex[:12]}",
            approved=False,
            approved_at=None,
            derived_from=derived_from,
            created_at=now,
            updated_at=now,
            **fields,
        )
        self._write(role)
        return role

    def update_role(
        self,
        role_id: str,
        *,
        name: str,
        purpose: str,
        system_prompt: str,
        tools: list[str],
        skills: list[str],
        max_iterations: int,
        timeout_seconds: int,
    ) -> CustomRole:
        """Replace a role definition in place; approval state is preserved."""
        existing = self.get_role(role_id)
        fields = self._validate_payload(
            name, purpose, system_prompt, tools, skills,
            max_iterations, timeout_seconds,
        )
        if fields["name"] in builtin_role_names():
            raise ValueError(
                f"角色名称与内置角色重名: {fields['name']!r}，请更换名称"
            )
        if self.name_exists(fields["name"], exclude_id=role_id):
            raise ValueError(
                f"已存在同名自建角色: {fields['name']!r}，请更换名称"
            )
        updated = existing.model_copy(
            update={
                **fields,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._write(updated)
        return updated

    def delete_role(self, role_id: str) -> None:
        """Delete a role; run snapshots and role-run history are untouched."""
        path = self._path_for(role_id)
        try:
            os.unlink(path)
        except FileNotFoundError:
            raise FileNotFoundError(f"自建角色不存在: {role_id}") from None

    def approve(self, role_id: str) -> CustomRole:
        """Mark a role approved (operator action)."""
        existing = self.get_role(role_id)
        if existing.approved:
            return existing
        updated = existing.model_copy(
            update={
                "approved": True,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._write(updated)
        return updated

    def unapprove(self, role_id: str) -> CustomRole:
        """Revoke a role approval (operator action)."""
        existing = self.get_role(role_id)
        if not existing.approved:
            return existing
        updated = existing.model_copy(
            update={
                "approved": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._write(updated)
        return updated
