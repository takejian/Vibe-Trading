"""Tests for user-created custom skills (standalone Skill Plaza, M14)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from src.agent.skills import SkillsLoader
from src.swarm.custom_skills import CustomSkillStore, is_custom_skill_id
from src.swarm.skill_approvals import SkillApprovalStore
from src.swarm.skill_packages import SkillPackageError


@pytest.fixture
def store(tmp_path: Path) -> CustomSkillStore:
    return CustomSkillStore(
        base_dir=tmp_path / "custom-skills",
        user_skills_dir=tmp_path / "user-skills",
    )


def _payload(**overrides) -> dict:
    base = {
        "name": "自定义波动率曲面技能",
        "purpose": "曲面建模与历史分位提示",
        "methodology": "采集隐含波动率曲面，做历史分位与偏斜识别。",
        "inputs": "标的代码、期权链行情",
        "outputs": "分位结论与关注价位表",
    }
    base.update(overrides)
    return base


def _loader_for(store: CustomSkillStore) -> SkillsLoader:
    return SkillsLoader(user_skills_dir=store._user_skills_dir)


# ---------------------------------------------------------------------------
# CRUD + materialization
# ---------------------------------------------------------------------------


def test_create_skill_starts_unapproved_and_persists(store: CustomSkillStore) -> None:
    skill = store.create_skill(**_payload())

    assert skill.id.startswith("cskill-")
    assert skill.approved is False
    assert skill.approved_at is None
    assert skill.derived_from is None
    assert skill.created_at == skill.updated_at
    assert Path(store._path_for(skill.id)).is_file()

    reloaded = store.get_skill(skill.id)
    assert reloaded.name == skill.name
    assert reloaded.inputs and reloaded.outputs


def test_create_materializes_runnable_skill_package(store: CustomSkillStore) -> None:
    skill = store.create_skill(**_payload())

    skill_file = Path(store._materialized_dir(skill.id)) / "SKILL.md"
    assert skill_file.is_file()

    loaded = {item.name: item for item in _loader_for(store).skills}
    assert skill.name in loaded
    document = loaded[skill.name].body
    assert "历史分位与偏斜识别" in document
    assert "## 输入要求" in document and "期权链行情" in document
    assert "## 输出约定" in document and "关注价位表" in document


def test_list_skills_newest_updated_first(store: CustomSkillStore) -> None:
    first = store.create_skill(**_payload(name="自建技能甲"))
    second = store.create_skill(**_payload(name="自建技能乙"))
    updated = store.update_skill(first.id, **_payload(name="自建技能甲改"))

    assert [skill.id for skill in store.list_skills()] == [updated.id, second.id]


def test_update_refreshes_materialized_package(store: CustomSkillStore) -> None:
    skill = store.create_skill(**_payload())
    updated = store.update_skill(
        skill.id, **_payload(methodology="全新的方法论：先做宏观再做微观。")
    )

    document = (_loader_for(store).skills and _loader_for(store).get_content(skill.name))
    assert "全新的方法论" in document
    assert updated.approved is False


def test_delete_removes_record_and_package(store: CustomSkillStore) -> None:
    skill = store.create_skill(**_payload())
    materialized = Path(store._materialized_dir(skill.id))
    assert materialized.is_dir()

    store.delete_skill(skill.id)

    with pytest.raises(FileNotFoundError):
        store.get_skill(skill.id)
    assert not materialized.exists()
    with pytest.raises(FileNotFoundError):
        store.delete_skill(skill.id)


def test_bad_skill_id_rejected(store: CustomSkillStore) -> None:
    with pytest.raises(ValueError):
        store.get_skill("../escape")
    assert is_custom_skill_id("cskill-ab12cd34ef56")
    assert not is_custom_skill_id("assembled:chanlun")
    assert not is_custom_skill_id("")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "  "),
        ("name", "技" * 81),
        ("purpose", "简" * 201),
        ("methodology", "  "),
        ("methodology", "方" * 20001),
        ("inputs", "入" * 4001),
        ("outputs", "出" * 4001),
    ],
)
def test_payload_validation_rejects_bad_fields(
    store: CustomSkillStore, field: str, value: str
) -> None:
    with pytest.raises(ValueError):
        store.create_skill(**_payload(**{field: value}))


def test_duplicate_custom_name_rejected(store: CustomSkillStore) -> None:
    store.create_skill(**_payload())
    with pytest.raises(ValueError, match="同名"):
        store.create_skill(**_payload())


def test_duplicate_bundled_name_rejected(store: CustomSkillStore) -> None:
    bundled_name = SkillsLoader().skills[0].name
    with pytest.raises(ValueError, match="重名"):
        store.create_skill(**_payload(name=bundled_name))


def test_rename_into_existing_name_rejected(store: CustomSkillStore) -> None:
    first = store.create_skill(**_payload(name="独占名一"))
    store.create_skill(**_payload(name="独占名二"))
    with pytest.raises(ValueError, match="同名"):
        store.update_skill(first.id, **_payload(name="独占名二"))


# ---------------------------------------------------------------------------
# Approval lifecycle
# ---------------------------------------------------------------------------


def test_approve_and_unapprove_lifecycle(store: CustomSkillStore) -> None:
    skill = store.create_skill(**_payload())

    approved = store.approve(skill.id)
    assert approved.approved is True
    assert approved.approved_at
    assert store.approved_names() == {skill.name}
    # Idempotent.
    assert store.approve(skill.id).approved_at == approved.approved_at

    revoked = store.unapprove(skill.id)
    assert revoked.approved is False
    assert store.approved_names() == set()
    # Package stays on disk so the owner can keep trialing.
    assert (Path(store._materialized_dir(skill.id)) / "SKILL.md").is_file()


def test_editing_approved_skill_keeps_approval(store: CustomSkillStore) -> None:
    skill = store.create_skill(**_payload())
    store.approve(skill.id)

    updated = store.update_skill(skill.id, **_payload(purpose="更新后的用途"))
    assert updated.approved is True
    assert store.get_skill(skill.id).approved is True


# ---------------------------------------------------------------------------
# Derivation templates
# ---------------------------------------------------------------------------


def test_template_must_be_approved_custom_skill(store: CustomSkillStore) -> None:
    template = store.create_skill(**_payload(name="模板技能"))

    with pytest.raises(ValueError, match="已通过"):
        store.create_skill(
            **_payload(name="派生技能"), template_ref=template.id
        )

    store.approve(template.id)
    derived = store.create_skill(
        **_payload(name="派生技能"), template_ref=template.id
    )
    assert derived.derived_from == "模板技能"

    # Template disappears before another save → intercepted.
    store.delete_skill(template.id)
    with pytest.raises(ValueError, match="已删除"):
        store.create_skill(
            **_payload(name="派生技能二"), template_ref="cskill-xxxxxxxxxxxx"
        )


def test_derived_skill_is_independent_of_template(store: CustomSkillStore) -> None:
    template = store.create_skill(**_payload(name="独立模板"))
    store.approve(template.id)
    derived = store.create_skill(
        **_payload(name="独立派生"), template_ref=template.id
    )

    store.unapprove(template.id)
    # The derived skill's own state is untouched.
    assert store.get_skill(derived.id).derived_from == "独立模板"
    assert store.get_skill(derived.id).approved is False


def test_assembled_template_requires_global_approval(
    store: CustomSkillStore, tmp_path: Path
) -> None:
    bundled = SkillsLoader().skills[0]
    approvals = SkillApprovalStore()
    assert not approvals.is_approved(bundled.name)

    with pytest.raises(ValueError, match="已通过"):
        store.create_skill(
            **_payload(name="派生自已装配技能"),
            template_ref=f"assembled:{bundled.name}",
        )

    approvals.mark_approved(bundled.name, source_run_id="test")
    try:
        derived = store.create_skill(
            **_payload(name="派生自已装配技能"),
            template_ref=f"assembled:{bundled.name}",
        )
        assert derived.derived_from == bundled.name
    finally:
        # Restore the shared sandbox approval registry for other tests.
        data = approvals._read()
        data.pop(bundled.name, None)
        approvals._write(data)


def test_bad_template_ref_rejected(store: CustomSkillStore) -> None:
    with pytest.raises(ValueError, match="引用不合法"):
        store.create_skill(
            **_payload(name="坏模板派生"), template_ref="weird:ref"
        )


# ---------------------------------------------------------------------------
# Personal zip import
# ---------------------------------------------------------------------------


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, text in files.items():
            archive.writestr(path, text)
    return buffer.getvalue()


_FINANCE_SKILL = """---
name: personal-macro-timer
description: 个人导入的股票择时技能
category: strategy
---
# Macro Timer
基于利率与估值分位决定股票仓位。
"""


def test_personal_zip_import_creates_unapproved_custom_skills(
    store: CustomSkillStore,
) -> None:
    payload = _zip_bytes(
        {
            "personal-macro-timer/SKILL.md": _FINANCE_SKILL,
            "personal-macro-timer/references/notes.md": "# notes\n",
        }
    )

    created = store.import_zip_bytes(payload)
    assert len(created) == 1
    skill = created[0]
    assert skill.approved is False
    assert skill.derived_from is None
    assert skill.purpose == "个人导入的股票择时技能"

    materialized = Path(store._materialized_dir(skill.id))
    assert (materialized / "SKILL.md").is_file()
    assert (materialized / "references" / "notes.md").is_file()
    loaded = {item.name: item for item in _loader_for(store).skills}
    assert "personal-macro-timer" in loaded


def test_personal_zip_import_rejects_non_finance(store: CustomSkillStore) -> None:
    payload = _zip_bytes(
        {
            "cooking/SKILL.md": (
                "---\nname: cooking\ndescription: 做饭菜谱\n---\n# 红烧肉\n"
            )
        }
    )
    with pytest.raises(SkillPackageError):
        store.import_zip_bytes(payload)
    assert store.list_skills() == []


def test_personal_zip_import_rejects_bad_archive(store: CustomSkillStore) -> None:
    with pytest.raises(SkillPackageError):
        store.import_zip_bytes(b"not a zip")
    with pytest.raises(SkillPackageError):
        store.import_zip_bytes(b"")


def test_personal_zip_import_rejects_name_collision(store: CustomSkillStore) -> None:
    store.create_skill(
        name="personal-macro-timer",
        purpose="已占用",
        methodology="存量方法论",
        inputs="",
        outputs="",
    )
    payload = _zip_bytes({"personal-macro-timer/SKILL.md": _FINANCE_SKILL})
    with pytest.raises(SkillPackageError, match="同名"):
        store.import_zip_bytes(payload)


def test_personal_zip_import_rejects_oversized_archive(
    store: CustomSkillStore,
) -> None:
    # Stored (uncompressed) entry of 20MiB + 1 byte.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "huge-finance-skill/SKILL.md",
            b"name: huge-finance-skill\n\n" + b"0" * (20 * 1024 * 1024 + 1),
        )
    with pytest.raises(SkillPackageError, match="体积"):
        store.import_zip_bytes(buffer.getvalue())
    assert store.list_skills() == []


def test_personal_zip_import_rejects_missing_methodology_body(
    store: CustomSkillStore,
) -> None:
    payload = _zip_bytes(
        {
            "finance-mystery/SKILL.md": (
                "---\n"
                "name: finance-mystery\n"
                "description: 股票择时金融技能\n"
                "category: strategy\n"
                "---\n"
                "   \n"  # frontmatter only, no body
            )
        }
    )
    with pytest.raises(SkillPackageError, match="正文"):
        store.import_zip_bytes(payload)
    assert store.list_skills() == []


def test_personal_zip_import_rejects_overlong_methodology(
    store: CustomSkillStore,
) -> None:
    body = "# 股票分析\n" + "基本面与估值分析。" * 2500
    assert len(body) > 20_000
    markdown = (
        "---\n"
        "name: long-finance-writer\n"
        "description: 超长股票研究方法论\n"
        "category: strategy\n"
        "---\n" + body
    )
    payload = _zip_bytes({"long-finance-writer/SKILL.md": markdown})
    with pytest.raises(SkillPackageError, match="20000"):
        store.import_zip_bytes(payload)
    assert store.list_skills() == []
