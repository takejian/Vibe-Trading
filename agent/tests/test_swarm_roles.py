"""Tests for user-created custom roles (Role Square persistence)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.swarm.roles import CustomRole, RoleStore, builtin_role_names


@pytest.fixture
def store(tmp_path: Path) -> RoleStore:
    return RoleStore(base_dir=tmp_path / "roles")


def _payload(**overrides) -> dict:
    base = {
        "name": "港股小市值猎手",
        "purpose": "专门筛选港股低市值高成长标的",
        "system_prompt": "You hunt small-cap HK stocks.\nSecond line stays.",
        "tools": ["get_market_data"],
        "skills": [],
        "max_iterations": 20,
        "timeout_seconds": 240,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_create_role_starts_unapproved_and_persists(store: RoleStore) -> None:
    role = store.create_role(**_payload())

    assert role.id.startswith("role-")
    assert role.approved is False
    assert role.approved_at is None
    assert role.created_at == role.updated_at
    assert Path(store._path_for(role.id)).is_file()

    reloaded = store.get_role(role.id)
    assert reloaded.name == role.name
    assert reloaded.tools == ["get_market_data"]


def test_list_roles_newest_updated_first(store: RoleStore) -> None:
    first = store.create_role(**_payload(name="角色甲"))
    second = store.create_role(**_payload(name="角色乙"))
    updated = store.update_role(first.id, **_payload(name="角色甲改"))

    assert [role.id for role in store.list_roles()] == [updated.id, second.id]


def test_corrupt_role_file_is_skipped(store: RoleStore) -> None:
    good = store.create_role(**_payload())
    bad_path = Path(store._dir) / "role-broken.json"
    bad_path.write_text("{not json", encoding="utf-8")

    assert [role.id for role in store.list_roles()] == [good.id]


def test_delete_role_removes_file(store: RoleStore) -> None:
    role = store.create_role(**_payload())
    store.delete_role(role.id)

    with pytest.raises(FileNotFoundError):
        store.get_role(role.id)
    with pytest.raises(FileNotFoundError):
        store.delete_role(role.id)


def test_bad_role_id_rejected(store: RoleStore) -> None:
    with pytest.raises(ValueError):
        store.get_role("../escape")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, value",
    [
        ("name", "   "),
        ("name", "x" * 81),
        ("system_prompt", ""),
        ("system_prompt", "x" * 12001),
        ("purpose", "x" * 201),
        ("max_iterations", 0),
        ("max_iterations", 101),
        ("timeout_seconds", 0),
        ("timeout_seconds", 1801),
    ],
)
def test_scalar_validation_errors(store: RoleStore, field: str, value) -> None:
    with pytest.raises(ValueError):
        store.create_role(**_payload(**{field: value}))


def test_tools_must_be_list(store: RoleStore) -> None:
    with pytest.raises(ValueError):
        store.create_role(**_payload(tools="get_market_data"))


def test_tool_outside_preset_union_rejected(store: RoleStore) -> None:
    with pytest.raises(ValueError, match="不在允许目录内"):
        store.create_role(**_payload(tools=["rm_rf_everything"]))


def test_unapproved_or_unassembled_skill_rejected(store: RoleStore) -> None:
    with pytest.raises(ValueError, match="未装配或未通过"):
        store.create_role(**_payload(skills=["behavioral-finance-ghost"]))


def test_duplicate_custom_name_rejected(store: RoleStore) -> None:
    store.create_role(**_payload())
    with pytest.raises(ValueError, match="同名自建角色"):
        store.create_role(**_payload(purpose="另一个用途"))


def test_builtin_name_rejected(store: RoleStore) -> None:
    builtin = next(iter(builtin_role_names()))
    with pytest.raises(ValueError, match="内置角色重名"):
        store.create_role(**_payload(name=builtin))


def test_rename_into_existing_name_rejected(store: RoleStore) -> None:
    store.create_role(**_payload(name="角色甲"))
    target = store.create_role(**_payload(name="角色乙"))
    with pytest.raises(ValueError):
        store.update_role(target.id, **_payload(name="角色甲"))


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


def test_approve_then_unapprove(store: RoleStore) -> None:
    role = store.create_role(**_payload())

    approved = store.approve(role.id)
    assert approved.approved is True
    assert approved.approved_at

    revoked = store.unapprove(role.id)
    assert revoked.approved is False
    assert revoked.id == role.id

    assert store.approve(role.id).approved is True
    # Idempotent: re-approve keeps existing state.
    again = store.approve(role.id)
    assert again.approved_at == store.get_role(role.id).approved_at


def test_update_preserves_approval(store: RoleStore) -> None:
    role = store.create_role(**_payload())
    store.approve(role.id)

    updated = store.update_role(
        role.id, **_payload(purpose="更新后的用途")
    )
    assert updated.approved is True
    assert updated.approved_at == store.get_role(role.id).approved_at


def test_model_round_trip() -> None:
    role = CustomRole(
        id="role-x",
        name="X",
        system_prompt="p",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    dumped = json.loads(role.model_dump_json())
    assert dumped["approved"] is False
    assert dumped["tools"] == []
