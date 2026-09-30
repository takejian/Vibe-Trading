"""User-created custom skills backing the standalone Skill Plaza (M14).

A custom skill is a personal skill definition an investor creates on the
"技能广场" page — from scratch, by deriving ("另存为新建技能") from an
approved skill, or by importing a personal zip package. The authoritative
record is a JSON file under ``<runtime_root>/swarm/skills/``; for the skill
to actually run through the existing trial machinery every record is
*materialized* as a ``SKILL.md`` package under
``<runtime_root>/skills/user/custom-<id>/`` so that
:class:`src.agent.skills.SkillsLoader` picks it up immediately.

Admission (mirrors custom roles, deliberately unlike global packages):

* newly created/imported skills are *unapproved* and visible only to the
  local owner;
* a successful standalone trial is only a prerequisite — it never flips the
  approval bit automatically (see ``runtime._finalize``);
* the operator approves manually in the detail page, after at least one
  qualified trial; once approved the skill joins the role/canvas skill
  catalog for everyone;
* editing an approved skill keeps it approved; the operator may revoke.

Deletion removes both the record and the materialized package; approval
revocation keeps the package on disk so the owner can still trial it. Run
snapshots and trial history are never touched.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

from pydantic import BaseModel

from src.agent.skills import SkillsLoader
from src.config.paths import get_custom_skills_dir, get_user_skills_dir

_SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MAX_NAME_LEN = 80
_MAX_PURPOSE_LEN = 200
_MAX_METHODOLOGY_LEN = 20000
_MAX_IO_LEN = 4000

ASSEMBLED_TEMPLATE_PREFIX = "assembled:"
_MATERIALIZED_DIR_PREFIX = "custom-"


class CustomSkill(BaseModel):
    """One user-created reusable skill definition."""

    id: str
    name: str
    purpose: str = ""
    methodology: str
    inputs: str = ""
    outputs: str = ""
    approved: bool = False
    approved_at: str | None = None
    derived_from: str | None = None
    created_at: str
    updated_at: str


def is_custom_skill_id(ref: str) -> bool:
    """Whether a skill reference denotes a custom skill record."""
    return bool(ref) and ":" not in ref and _SKILL_ID_RE.match(ref) is not None


def _one_line(text: str) -> str:
    """Collapse a field to a single physical line for SKILL.md frontmatter."""
    return re.sub(r"\s+", " ", (text or "").strip())


class CustomSkillStore:
    """File-backed CRUD for custom skills plus SKILL.md materialization."""

    def __init__(
        self,
        base_dir: str | os.PathLike[str] | None = None,
        user_skills_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self._dir = base_dir if base_dir is not None else get_custom_skills_dir()
        self._user_skills_dir = (
            user_skills_dir if user_skills_dir is not None else get_user_skills_dir()
        )

    # ------------------------------------------------------------------
    # Record IO
    # ------------------------------------------------------------------
    def _path_for(self, skill_id: str) -> str:
        if not _SKILL_ID_RE.match(skill_id or ""):
            raise ValueError(f"自建技能标识不合法: {skill_id!r}")
        return os.path.join(self._dir, f"{skill_id}.json")

    def _materialized_dir(self, skill_id: str) -> str:
        return os.path.join(
            self._user_skills_dir, f"{_MATERIALIZED_DIR_PREFIX}{skill_id}"
        )

    def _write_record(self, skill: CustomSkill) -> None:
        os.makedirs(self._dir, exist_ok=True)
        target = self._path_for(skill.id)
        fd, tmp_name = tempfile.mkstemp(prefix=".custom-skill-", suffix=".json", dir=self._dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(skill.model_dump(), handle, ensure_ascii=False, indent=2)
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def list_skills(self) -> list[CustomSkill]:
        if not os.path.isdir(self._dir):
            return []
        skills: list[CustomSkill] = []
        for entry in os.listdir(self._dir):
            if not entry.endswith(".json") or entry.startswith("."):
                continue
            try:
                with open(os.path.join(self._dir, entry), encoding="utf-8") as handle:
                    skills.append(CustomSkill.model_validate(json.load(handle)))
            except (OSError, json.JSONDecodeError, ValueError):
                # Skip corrupt rows rather than failing the whole gallery.
                continue
        skills.sort(key=lambda skill: skill.updated_at, reverse=True)
        return skills

    def get_skill(self, skill_id: str) -> CustomSkill:
        path = self._path_for(skill_id)
        try:
            with open(path, encoding="utf-8") as handle:
                return CustomSkill.model_validate(json.load(handle))
        except FileNotFoundError:
            raise FileNotFoundError(f"自建技能不存在: {skill_id}") from None

    def name_exists(self, name: str, exclude_id: str | None = None) -> bool:
        target = name.strip()
        return any(
            skill.name == target and skill.id != exclude_id
            for skill in self.list_skills()
        )

    def get_by_name(self, name: str) -> CustomSkill | None:
        target = (name or "").strip()
        for skill in self.list_skills():
            if skill.name == target:
                return skill
        return None

    def approved_names(self) -> set[str]:
        return {skill.name for skill in self.list_skills() if skill.approved}

    # ------------------------------------------------------------------
    # Materialization
    # ------------------------------------------------------------------
    def render_skill_md(self, skill: CustomSkill) -> str:
        """Build the SKILL.md document the trial agent actually loads."""
        name = _one_line(skill.name)
        description = _one_line(skill.purpose)
        parts = [
            "---",
            f"name: {name}",
            f"description: {description}",
            "category: custom",
            "---",
            "",
            skill.methodology.strip(),
            "",
            "## 输入要求",
            "",
            skill.inputs.strip() or "（创建者未单独列出输入要求，按上述方法论执行。）",
            "",
            "## 输出约定",
            "",
            skill.outputs.strip() or "（创建者未单独约定输出结构，给出与方法论一致的结构化结论。）",
            "",
        ]
        return "\n".join(parts)

    def _materialize(self, skill: CustomSkill) -> None:
        target_dir = self._materialized_dir(skill.id)
        os.makedirs(target_dir, exist_ok=True)
        target_file = os.path.join(target_dir, "SKILL.md")
        fd, tmp_name = tempfile.mkstemp(prefix=".SKILL-", suffix=".md", dir=target_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self.render_skill_md(skill))
            os.replace(tmp_name, target_file)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _remove_materialized(self, skill_id: str) -> None:
        shutil.rmtree(self._materialized_dir(skill_id), ignore_errors=True)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate_payload(
        self,
        name: str,
        purpose: str,
        methodology: str,
        inputs: str,
        outputs: str,
    ) -> dict:
        clean_name = _one_line(name)
        if not clean_name:
            raise ValueError("技能名称不能为空")
        if len(clean_name) > _MAX_NAME_LEN:
            raise ValueError(f"技能名称不能超过 {_MAX_NAME_LEN} 个字符")

        clean_purpose = (purpose or "").strip()
        if len(clean_purpose) > _MAX_PURPOSE_LEN:
            raise ValueError(f"业务用途简介不能超过 {_MAX_PURPOSE_LEN} 个字符")

        clean_methodology = (methodology or "").strip()
        if not clean_methodology:
            raise ValueError("方法论与操作说明不能为空")
        if len(clean_methodology) > _MAX_METHODOLOGY_LEN:
            raise ValueError(
                f"方法论与操作说明不能超过 {_MAX_METHODOLOGY_LEN} 个字符"
            )

        clean_inputs = (inputs or "").strip()
        if len(clean_inputs) > _MAX_IO_LEN:
            raise ValueError(f"输入要求不能超过 {_MAX_IO_LEN} 个字符")
        clean_outputs = (outputs or "").strip()
        if len(clean_outputs) > _MAX_IO_LEN:
            raise ValueError(f"输出约定不能超过 {_MAX_IO_LEN} 个字符")

        return {
            "name": clean_name,
            "purpose": clean_purpose,
            "methodology": clean_methodology,
            "inputs": clean_inputs,
            "outputs": clean_outputs,
        }

    def _assembled_names(self) -> set[str]:
        from src.swarm.skill_catalog import assembled_skill_names

        return assembled_skill_names()

    def _resolve_template(self, template_ref: str | None) -> str | None:
        """Validate a derivation template; return its display name.

        Only skills that still exist and are currently approved may serve
        as templates — assembled skills (``assembled:<name>``) or custom
        skills (their record id).
        """
        ref = (template_ref or "").strip()
        if not ref:
            return None

        if ref.startswith(ASSEMBLED_TEMPLATE_PREFIX):
            name = ref[len(ASSEMBLED_TEMPLATE_PREFIX):].strip()
            if not name:
                raise ValueError("模板技能引用不合法，请重新选择模板")
            assembled = {skill.name for skill in SkillsLoader().skills}
            if name not in assembled:
                raise ValueError(
                    f"模板技能已删除或未装配: {name!r}，请重新选择模板"
                )
            from src.swarm.skill_approvals import SkillApprovalStore

            if not SkillApprovalStore().is_approved(name):
                raise ValueError(
                    "仅可派生自已通过技能；该模板未通过或已被取消通过，"
                    "请重新选择模板"
                )
            return name

        # Custom skill template.
        if not is_custom_skill_id(ref):
            raise ValueError("模板技能引用不合法，请重新选择模板")
        try:
            template = self.get_skill(ref)
        except FileNotFoundError:
            raise ValueError(
                f"模板技能已删除，无法派生: {ref!r}，请重新选择模板"
            ) from None
        if not template.approved:
            raise ValueError(
                "仅可派生自已通过技能；该模板未通过或已被取消通过，"
                "请重新选择模板"
            )
        return template.name

    def _assert_unique_name(self, name: str, exclude_id: str | None = None) -> None:
        if self.name_exists(name, exclude_id=exclude_id):
            raise ValueError(f"已存在同名自建技能: {name!r}，请更换名称")
        from src.swarm.skill_catalog import list_assembled_skills

        for item in list_assembled_skills():
            if item["name"] == name and item.get("kind") != "custom":
                raise ValueError(
                    f"技能名称与已装配技能重名: {name!r}，请更换名称"
                )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def create_skill(
        self,
        *,
        name: str,
        purpose: str,
        methodology: str,
        inputs: str,
        outputs: str,
        template_ref: str | None = None,
    ) -> CustomSkill:
        """Create a new unapproved custom skill and materialize its package."""
        fields = self._validate_payload(name, purpose, methodology, inputs, outputs)
        derived_from = self._resolve_template(template_ref)
        self._assert_unique_name(fields["name"])
        now = datetime.now(timezone.utc).isoformat()
        skill = CustomSkill(
            id=f"cskill-{uuid.uuid4().hex[:12]}",
            approved=False,
            approved_at=None,
            derived_from=derived_from,
            created_at=now,
            updated_at=now,
            **fields,
        )
        self._write_record(skill)
        self._materialize(skill)
        return skill

    def update_skill(
        self,
        skill_id: str,
        *,
        name: str,
        purpose: str,
        methodology: str,
        inputs: str,
        outputs: str,
    ) -> CustomSkill:
        """Replace a skill definition in place; approval state is preserved."""
        existing = self.get_skill(skill_id)
        fields = self._validate_payload(name, purpose, methodology, inputs, outputs)
        self._assert_unique_name(fields["name"], exclude_id=skill_id)
        updated = existing.model_copy(
            update={
                **fields,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._write_record(updated)
        self._materialize(updated)
        return updated

    def delete_skill(self, skill_id: str) -> None:
        """Delete record and materialized package; run history is untouched."""
        path = self._path_for(skill_id)
        try:
            os.unlink(path)
        except FileNotFoundError:
            raise FileNotFoundError(f"自建技能不存在: {skill_id}") from None
        self._remove_materialized(skill_id)

    def approve(self, skill_id: str) -> CustomSkill:
        """Mark a custom skill approved (operator action)."""
        existing = self.get_skill(skill_id)
        if existing.approved:
            return existing
        updated = existing.model_copy(
            update={
                "approved": True,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._write_record(updated)
        return updated

    def unapprove(self, skill_id: str) -> CustomSkill:
        """Revoke approval (operator action); materialized package stays."""
        existing = self.get_skill(skill_id)
        if not existing.approved:
            return existing
        updated = existing.model_copy(
            update={
                "approved": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._write_record(updated)
        return updated

    # ------------------------------------------------------------------
    # Personal zip import
    # ------------------------------------------------------------------
    def import_zip_bytes(self, payload: bytes) -> list[CustomSkill]:
        """Import a personal zip as one/many unapproved custom skills.

        Reuses the operator package gate (zip safety, SKILL.md presence,
        finance relevance). Every package becomes its own custom skill;
        the whole archive is rejected (nothing installed) on any failure
        or name collision. The operator sync manifest is never touched.
        """
        from src.swarm.skill_packages import (
            _MAX_ARCHIVE_BYTES,
            SkillPackageError,
            _package_dirs,
            _safe_extract_zip,
            _validate_package_dir,
        )
        from src.agent.frontmatter import parse_frontmatter

        if not payload:
            raise SkillPackageError("上传内容为空")
        if len(payload) > _MAX_ARCHIVE_BYTES:
            raise SkillPackageError(
                f"压缩包体积超过上限 {_MAX_ARCHIVE_BYTES // (1024 * 1024)}MB"
            )

        try:
            archive = zipfile.ZipFile(io.BytesIO(payload))
        except zipfile.BadZipFile:
            raise SkillPackageError("文件不是合法的 zip 压缩包") from None

        with tempfile.TemporaryDirectory(prefix="custom-skill-import-") as work:
            try:
                _safe_extract_zip(archive, work)
            finally:
                archive.close()
            package_dirs = _package_dirs(work)
            if not package_dirs:
                raise SkillPackageError("压缩包内未找到包含 SKILL.md 的技能目录")

            planned: list[tuple[str, str]] = []
            all_reasons: list[str] = []
            seen_names: set[str] = set()
            for directory in package_dirs:
                try:
                    pkg_name, _slug, _sha = _validate_package_dir(directory)
                    planned.append((directory, pkg_name))
                except SkillPackageError as exc:
                    all_reasons.extend(exc.reasons)
                    continue
                if pkg_name in seen_names:
                    all_reasons.append(f"[{pkg_name}] 压缩包内存在同名技能")
                seen_names.add(pkg_name)

            # Name collisions with existing custom/assembled skills.
            for _directory, pkg_name in planned:
                if self.name_exists(pkg_name):
                    all_reasons.append(
                        f"[{pkg_name}] 已存在同名技能，请改名后再导入"
                    )
                elif pkg_name in self._assembled_names():
                    all_reasons.append(
                        f"[{pkg_name}] 与已装配技能重名，请改名后再导入"
                    )

            # Length discipline: imported custom skills must obey the same
            # methodology limit as manually created ones, otherwise the
            # resulting record could never pass edit validation again. Empty
            # bodies are already rejected by the package validator above.
            parsed_packages: list[tuple[str, str, dict, str]] = []
            for directory, pkg_name in planned:
                with open(
                    os.path.join(directory, "SKILL.md"), encoding="utf-8"
                ) as handle:
                    meta, body = parse_frontmatter(handle.read())
                clean_body = body.strip()
                if len(clean_body) > _MAX_METHODOLOGY_LEN:
                    all_reasons.append(
                        f"[{pkg_name}] 方法论与操作说明超过 {_MAX_METHODOLOGY_LEN} 字符"
                    )
                parsed_packages.append((directory, pkg_name, meta, clean_body))

            if all_reasons:
                raise SkillPackageError(all_reasons)

            created: list[CustomSkill] = []
            now = datetime.now(timezone.utc).isoformat()
            for directory, pkg_name, meta, clean_body in parsed_packages:
                skill = CustomSkill(
                    id=f"cskill-{uuid.uuid4().hex[:12]}",
                    name=pkg_name,
                    purpose=str(meta.get("description", "") or "").strip()[
                        :_MAX_PURPOSE_LEN
                    ],
                    methodology=clean_body,
                    inputs="",
                    outputs="",
                    approved=False,
                    approved_at=None,
                    derived_from=None,
                    created_at=now,
                    updated_at=now,
                )
                self._write_record(skill)
                # Keep the package byte-for-byte (original SKILL.md plus any
                # supporting files); only the custom- directory prefix is ours.
                dest = self._materialized_dir(skill.id)
                shutil.rmtree(dest, ignore_errors=True)
                shutil.copytree(directory, dest)
                created.append(skill)
            return created
