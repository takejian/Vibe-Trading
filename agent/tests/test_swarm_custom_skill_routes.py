"""HTTP contract tests for the standalone Skill Plaza endpoints (M14)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
import src.api.swarm_routes as swarm_routes
import src.config.paths as config_paths
import src.swarm.custom_skills as custom_skills_mod
from src.agent.skills import SkillsLoader
from src.swarm.custom_skills import CustomSkillStore
from src.swarm.models import RunStatus, TaskStatus
from src.swarm.skill_trials import build_skill_trial_run
from src.swarm.store import SwarmStore


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    custom_dir = tmp_path / "custom-skills"
    user_skills_dir = tmp_path / "user-skills"
    runs_dir = tmp_path / "runs"

    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    monkeypatch.setattr(
        config_paths, "get_user_skills_dir", lambda: user_skills_dir
    )
    monkeypatch.setattr(
        custom_skills_mod, "get_user_skills_dir", lambda: user_skills_dir
    )
    monkeypatch.setattr(
        custom_skills_mod, "get_custom_skills_dir", lambda: custom_dir
    )

    store = SwarmStore(base_dir=runs_dir)

    class _FakeRuntime:
        def __init__(self) -> None:
            self._store = store

    monkeypatch.setattr(swarm_routes, "_swarm_runtime", _FakeRuntime())

    return {
        "client": TestClient(api_server.app, client=("127.0.0.1", 50002)),
        "store": store,
        "skills": CustomSkillStore(
            base_dir=custom_dir, user_skills_dir=user_skills_dir
        ),
    }


def _payload(**overrides) -> dict:
    base = {
        "name": "北向资金异动跟踪",
        "purpose": "识别北向资金集中流入的行业",
        "methodology": "按交易日汇总北向资金净流入并排序。",
        "inputs": "观察区间",
        "outputs": "行业资金流入榜单",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Catalog & detail
# ---------------------------------------------------------------------------


def test_catalog_includes_custom_skill(ctx) -> None:
    ctx["skills"].create_skill(**_payload())
    items = ctx["client"].get("/swarm/skills/catalog").json()["skills"]
    item = next(row for row in items if row["name"] == "北向资金异动跟踪")
    assert item["kind"] == "custom"
    assert item["approved"] is False
    assert item["ref"].startswith("cskill-")


def test_custom_skill_detail_route(ctx) -> None:
    skill = ctx["skills"].create_skill(**_payload())
    body = ctx["client"].get(f"/swarm/skills/{skill.id}/detail").json()
    assert body["kind"] == "custom"
    assert body["name"] == "北向资金异动跟踪"
    assert body["methodology"] == "按交易日汇总北向资金净流入并排序。"
    assert body["inputs"] == "观察区间"
    assert body["outputs"] == "行业资金流入榜单"
    assert body["approved"] is False


def test_assembled_skill_detail_route(ctx) -> None:
    bundled = SkillsLoader(user_skills_dir=None).skills[0]
    body = ctx["client"].get(
        f"/swarm/skills/assembled:{bundled.name}/detail"
    )
    assert body.status_code == 200, body.text
    assert body.json()["kind"] == "assembled"
    assert body.json()["name"] == bundled.name


def test_skill_detail_errors(ctx) -> None:
    client = ctx["client"]
    assert client.get("/swarm/skills/bad ref/detail").status_code == 400
    assert client.get("/swarm/skills/cskill-ghost1234567/detail").status_code == 404
    assert client.get(
        "/swarm/skills/assembled:不存在的技能名/detail"
    ).status_code == 400


# ---------------------------------------------------------------------------
# Create / update / delete
# ---------------------------------------------------------------------------


def test_create_custom_skill_route(ctx) -> None:
    response = ctx["client"].post("/swarm/skills/custom", json=_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"].startswith("cskill-")
    assert body["approved"] is False
    assert body["derived_from"] is None


def test_create_custom_skill_route_validation(ctx) -> None:
    response = ctx["client"].post(
        "/swarm/skills/custom", json=_payload(methodology="")
    )
    assert response.status_code == 400


def test_create_custom_skill_duplicate(ctx) -> None:
    assert ctx["client"].post("/swarm/skills/custom", json=_payload()).status_code == 200
    assert ctx["client"].post("/swarm/skills/custom", json=_payload()).status_code == 400


def test_update_custom_skill_keeps_approval(ctx) -> None:
    skill = ctx["skills"].create_skill(**_payload())
    ctx["skills"].approve(skill.id)

    response = ctx["client"].put(
        f"/swarm/skills/custom/{skill.id}",
        json=_payload(purpose="更新后的用途"),
    )
    assert response.status_code == 200, response.text
    refreshed = ctx["skills"].get_skill(skill.id)
    assert refreshed.purpose == "更新后的用途"
    assert refreshed.approved is True
    assert refreshed.approved_at is not None


def test_update_custom_skill_errors(ctx) -> None:
    assert ctx["client"].put(
        "/swarm/skills/custom/cskill-missing000000", json=_payload()
    ).status_code == 404
    assert ctx["client"].put(
        "/swarm/skills/custom/BadID", json=_payload()
    ).status_code == 400


def test_delete_custom_skill_route(ctx) -> None:
    skill = ctx["skills"].create_skill(**_payload())
    assert (
        ctx["client"].delete(f"/swarm/skills/custom/{skill.id}").status_code == 200
    )
    assert (
        ctx["client"].delete(f"/swarm/skills/custom/{skill.id}").status_code == 404
    )


# ---------------------------------------------------------------------------
# Manual approval gate
# ---------------------------------------------------------------------------


def _qualified_trial(ctx, skill_name: str) -> None:
    run = build_skill_trial_run(skill_name, "600519.SH", "资金流向如何")
    task = run.tasks[0].model_copy(
        update={"status": TaskStatus.completed, "summary": "合格：结论完整"}
    )
    qualified = run.model_copy(
        update={"status": RunStatus.completed, "tasks": [task]}
    )
    ctx["store"].create_run(qualified)


def test_approve_custom_skill_forbidden_when_disabled(ctx) -> None:
    skill = ctx["skills"].create_skill(**_payload())
    assert (
        ctx["client"].post(f"/swarm/skills/custom/{skill.id}/approve").status_code
        == 403
    )


def test_approve_custom_skill_409_without_trial(
    ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(swarm_routes, "_skill_admin_enabled", lambda: True)
    skill = ctx["skills"].create_skill(**_payload())
    response = ctx["client"].post(f"/swarm/skills/custom/{skill.id}/approve")
    assert response.status_code == 409
    assert "试运行" in response.json()["detail"]


def test_approve_custom_skill_after_qualified_trial(
    ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(swarm_routes, "_skill_admin_enabled", lambda: True)
    skill = ctx["skills"].create_skill(**_payload())
    _qualified_trial(ctx, skill.name)

    response = ctx["client"].post(f"/swarm/skills/custom/{skill.id}/approve")
    assert response.status_code == 200, response.text
    assert response.json()["approved"] is True
    assert ctx["skills"].get_skill(skill.id).approved is True


def test_unapprove_custom_skill(
    ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = ctx["skills"].create_skill(**_payload())
    assert (
        ctx["client"].post(
            f"/swarm/skills/custom/{skill.id}/unapprove"
        ).status_code
        == 403
    )
    monkeypatch.setattr(swarm_routes, "_skill_admin_enabled", lambda: True)
    response = ctx["client"].post(
        f"/swarm/skills/custom/{skill.id}/unapprove"
    )
    assert response.status_code == 200
    assert response.json()["approved"] is False


# ---------------------------------------------------------------------------
# Personal zip import
# ---------------------------------------------------------------------------


def _skill_zip(name: str = "龙虎榜游资跟踪") -> bytes:
    content = (
        "---\n"
        f"name: {name}\n"
        "description: 跟踪股票龙虎榜席位与营业部资金动向\n"
        "---\n"
        "# 龙虎榜游资跟踪\n"
        "分析股票每日龙虎榜买入席位，结合资金净流入给出短线研判。\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{name}/SKILL.md", content)
    return buffer.getvalue()


def test_import_personal_skill_package(ctx) -> None:
    response = ctx["client"].post(
        "/swarm/skills/import-personal",
        files={"file": ("skill.zip", _skill_zip(), "application/zip")},
    )
    assert response.status_code == 200, response.text
    installed = response.json()["installed"]
    assert len(installed) == 1
    assert installed[0]["name"] == "龙虎榜游资跟踪"

    # Imported skill starts unapproved and is usable in trials immediately.
    skill = ctx["skills"].get_by_name("龙虎榜游资跟踪")
    assert skill is not None and skill.approved is False


def test_import_personal_skill_package_bad_zip(ctx) -> None:
    response = ctx["client"].post(
        "/swarm/skills/import-personal",
        files={"file": ("skill.zip", b"not-a-zip", "application/zip")},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Trial history scope
# ---------------------------------------------------------------------------


def test_list_skill_trials_scope_guard(
    ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundled = SkillsLoader(user_skills_dir=None).skills[0].name
    run = build_skill_trial_run(bundled, "600519.SH", "问题")
    ctx["store"].create_run(run)

    assert (
        ctx["client"].get("/swarm/skill-trials").status_code == 200
    )
    assert (
        ctx["client"].get(
            "/swarm/skill-trials", params={"scope": "all"}
        ).status_code
        == 403
    )

    monkeypatch.setattr(swarm_routes, "_skill_admin_enabled", lambda: True)
    assert (
        ctx["client"].get(
            "/swarm/skill-trials", params={"scope": "all"}
        ).status_code
        == 200
    )
