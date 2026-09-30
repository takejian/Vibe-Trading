"""Catalog integration for personal custom skills (M14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.skills import SkillsLoader
from src.swarm.custom_skills import CustomSkillStore
from src.swarm.skill_approvals import SkillApprovalStore
from src.swarm.skill_catalog import (
    is_custom_skill_name,
    list_assembled_skills,
    list_approved_skill_names,
    resolve_skill,
)


@pytest.fixture
def store(tmp_path: Path) -> CustomSkillStore:
    return CustomSkillStore(
        base_dir=tmp_path / "custom-skills",
        user_skills_dir=tmp_path / "user-skills",
    )


def _reload(store: CustomSkillStore) -> SkillsLoader:
    # SkillsLoader scans disk at construction time, so always build it
    # after the store has materialized packages.
    return SkillsLoader(user_skills_dir=store._user_skills_dir)


def _custom_by_name(items: list[dict], name: str) -> dict:
    return next(item for item in items if item["name"] == name)


def test_custom_skill_appears_as_custom_kind_unapproved(
    store: CustomSkillStore,
) -> None:
    skill = store.create_skill(
        name="目录自建技能",
        purpose="目录用途",
        methodology="目录方法论",
        inputs="输入",
        outputs="输出",
    )
    loader = _reload(store)

    items = list_assembled_skills(
        loader=loader, custom_store=store, approvals=SkillApprovalStore()
    )
    item = _custom_by_name(items, "目录自建技能")
    assert item["kind"] == "custom"
    assert item["source"] == "user"
    assert item["ref"] == skill.id
    assert item["approved"] is False
    assert "目录自建技能" not in list_approved_skill_names(
        loader=loader, custom_store=store, approvals=SkillApprovalStore()
    )


def test_approved_custom_skill_joins_unified_approved_catalog(
    store: CustomSkillStore,
) -> None:
    skill = store.create_skill(
        name="目录已通过技能",
        purpose="用途",
        methodology="方法论",
        inputs="",
        outputs="",
    )
    store.approve(skill.id)
    loader = _reload(store)

    item = _custom_by_name(
        list_assembled_skills(loader=loader, custom_store=store),
        "目录已通过技能",
    )
    assert item["approved"] is True
    assert "目录已通过技能" in list_approved_skill_names(
        loader=loader, custom_store=store
    )


def test_unapproved_custom_skill_ignores_global_registry(
    store: CustomSkillStore, tmp_path: Path
) -> None:
    skill = store.create_skill(
        name="审批双轨技能", purpose="", methodology="方法论", inputs="", outputs=""
    )
    approvals = SkillApprovalStore(path=tmp_path / "approvals.json")
    # Even a stray global-approval entry must not promote the custom skill;
    # its approval comes solely from its own record.
    approvals.mark_approved(skill.name)
    loader = _reload(store)

    item = _custom_by_name(
        list_assembled_skills(
            loader=loader, custom_store=store, approvals=approvals
        ),
        "审批双轨技能",
    )
    assert item["approved"] is False


def test_resolve_skill_custom_profile(store: CustomSkillStore) -> None:
    skill = store.create_skill(
        name="详情自建技能",
        purpose="详情用途",
        methodology="详情方法论全文",
        inputs="标的与区间",
        outputs="结论表格",
    )
    loader = _reload(store)

    profile = resolve_skill(skill.id, loader=loader, custom_store=store)
    assert profile["kind"] == "custom"
    assert profile["name"] == "详情自建技能"
    assert profile["methodology"] == "详情方法论全文"
    assert profile["inputs"] == "标的与区间"
    assert profile["outputs"] == "结论表格"
    assert profile["approved"] is False

    with pytest.raises(FileNotFoundError):
        resolve_skill("cskill-nonexistent", loader=loader, custom_store=store)
    with pytest.raises(ValueError):
        resolve_skill("bad ref", loader=loader, custom_store=store)


def test_resolve_skill_assembled_profile(store: CustomSkillStore) -> None:
    # Use a loader with the default bundled corpus (no custom packages yet).
    loader = SkillsLoader(user_skills_dir=store._user_skills_dir)
    bundled = loader.skills[0]
    profile = resolve_skill(
        f"assembled:{bundled.name}", loader=loader, custom_store=store
    )
    assert profile["kind"] == "assembled"
    assert profile["name"] == bundled.name
    assert profile["inputs"] == "" and profile["outputs"] == ""

    with pytest.raises(ValueError):
        resolve_skill("assembled:不存在的技能名", loader=loader, custom_store=store)


def test_is_custom_skill_name(store: CustomSkillStore) -> None:
    store.create_skill(
        name="归属判定技能", purpose="", methodology="方法论", inputs="", outputs=""
    )
    assert is_custom_skill_name("归属判定技能", custom_store=store)
    assert not is_custom_skill_name("其他技能", custom_store=store)
