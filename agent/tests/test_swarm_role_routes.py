"""HTTP contract tests for the Role Square endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
import src.api.swarm_routes as swarm_routes
from src.swarm.models import RunStatus, TaskStatus
from src.swarm.role_runs import build_role_run
from src.swarm.roles import RoleStore
from src.swarm.store import SwarmStore


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    roles_dir = tmp_path / "roles"
    runs_dir = tmp_path / "runs"
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    # Route RoleStore() default at the tmp dir.
    monkeypatch.setattr(
        "src.swarm.roles.get_roles_dir", lambda: roles_dir
    )

    store = SwarmStore(base_dir=runs_dir)

    class _FakeRuntime:
        def __init__(self) -> None:
            self._store = store
            self.captured: dict | None = None

        def start_run(self, preset_name, user_vars, *,
                      include_shell_tools=False, role_run=None, **kwargs):
            self.captured = role_run
            return build_role_run(
                role_run["role_ref"],
                role_run["target"],
                role_run["question"],
            )

    runtime = _FakeRuntime()
    monkeypatch.setattr(swarm_routes, "_swarm_runtime", runtime)

    return {
        "client": TestClient(api_server.app, client=("127.0.0.1", 50001)),
        "store": store,
        "roles": RoleStore(base_dir=roles_dir),
        "runtime": runtime,
    }


def _role_payload(**overrides) -> dict:
    base = {
        "name": "红利低波侦察兵",
        "purpose": "筛选高股息低波标的",
        "system_prompt": "You screen dividend low-volatility stocks.",
        "tools": ["get_market_data"],
        "skills": [],
        "max_iterations": 20,
        "timeout_seconds": 240,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Catalog & detail
# ---------------------------------------------------------------------------


def test_list_role_groups(ctx) -> None:
    groups = ctx["client"].get("/swarm/roles").json()["groups"]
    kinds = [g["kind"] for g in groups]
    assert "builtin" in kinds
    assert kinds[-1] == "custom"
    assert groups[-1]["roles"] == []

    ctx["roles"].create_role(**_role_payload())
    refreshed = ctx["client"].get("/swarm/roles").json()["groups"]
    custom = refreshed[-1]
    assert custom["kind"] == "custom"
    assert custom["roles"][0]["name"] == "红利低波侦察兵"
    assert custom["roles"][0]["approved"] is False


def test_list_role_groups_within_group_search(ctx) -> None:
    ctx["roles"].create_role(**_role_payload(name="红利低波侦察兵"))
    ctx["roles"].create_role(**_role_payload(name="题材龙头跟踪员"))

    hit = ctx["client"].get("/swarm/roles", params={"q": "红利"}).json()["groups"]
    assert len(hit) == 1
    assert [r["name"] for r in hit[0]["roles"]] == ["红利低波侦察兵"]

    miss = ctx["client"].get("/swarm/roles", params={"q": "不存在的角色"}).json()
    assert miss["groups"] == []


def test_role_detail_builtin(ctx) -> None:
    response = ctx["client"].get(
        "/swarm/roles/investment_committee:bull_advocate/detail"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "builtin"
    assert body["approved"] is True
    assert body["system_prompt"]


def test_role_detail_errors(ctx) -> None:
    client = ctx["client"]
    assert client.get("/swarm/roles/bad ref/detail").status_code == 400
    assert (
        client.get("/swarm/roles/investment_committee:ghost/detail").status_code
        == 400
    )
    assert client.get("/swarm/roles/role-missing/detail").status_code == 404


def test_role_detail_custom_has_timestamps(ctx) -> None:
    role = ctx["roles"].create_role(**_role_payload())
    body = ctx["client"].get(f"/swarm/roles/{role.id}/detail").json()
    assert body["kind"] == "custom"
    assert body["created_at"]
    assert body["updated_at"]


# ---------------------------------------------------------------------------
# Create / update / delete
# ---------------------------------------------------------------------------


def test_create_role_route(ctx) -> None:
    response = ctx["client"].post("/swarm/roles", json=_role_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"].startswith("role-")
    assert body["approved"] is False


def test_create_role_route_rejects_duplicate(ctx) -> None:
    ctx["client"].post("/swarm/roles", json=_role_payload())
    response = ctx["client"].post("/swarm/roles", json=_role_payload())
    assert response.status_code == 400


def test_update_role_route(ctx) -> None:
    role = ctx["roles"].create_role(**_role_payload())
    response = ctx["client"].put(
        f"/swarm/roles/{role.id}",
        json=_role_payload(purpose="更新用途"),
    )
    assert response.status_code == 200
    assert ctx["roles"].get_role(role.id).purpose == "更新用途"

    assert ctx["client"].put(
        "/swarm/roles/role-missing", json=_role_payload()
    ).status_code == 404

    # Built-in refs are not writable through custom-role endpoints.
    assert ctx["client"].put(
        "/swarm/roles/investment_committee:bull_advocate",
        json=_role_payload(),
    ).status_code == 400


def test_delete_role_route(ctx) -> None:
    role = ctx["roles"].create_role(**_role_payload())
    assert ctx["client"].delete(f"/swarm/roles/{role.id}").status_code == 200
    assert ctx["client"].delete(f"/swarm/roles/{role.id}").status_code == 404


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------


def test_approve_forbidden_when_admin_disabled(ctx) -> None:
    role = ctx["roles"].create_role(**_role_payload())
    response = ctx["client"].post(f"/swarm/roles/{role.id}/approve")
    assert response.status_code == 403


def test_approve_409_without_qualified_run(
    ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(swarm_routes, "_skill_admin_enabled", lambda: True)
    role = ctx["roles"].create_role(**_role_payload())

    response = ctx["client"].post(f"/swarm/roles/{role.id}/approve")
    assert response.status_code == 409


def test_approve_after_qualified_run(
    ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(swarm_routes, "_skill_admin_enabled", lambda: True)
    role = ctx["roles"].create_role(**_role_payload())

    # Inject a completed role_run for this role into the run store.
    run = build_role_run(role.id, "600519.SH", "适合做多吗", ctx["roles"])
    task = run.tasks[0].model_copy(
        update={"status": TaskStatus.completed, "summary": "合格：具备完整结论"}
    )
    qualified = run.model_copy(
        update={
            "status": RunStatus.completed,
            "tasks": [task],
        }
    )
    ctx["store"].create_run(qualified)

    response = ctx["client"].post(f"/swarm/roles/{role.id}/approve")
    assert response.status_code == 200, response.text
    assert response.json()["approved"] is True
    assert ctx["roles"].get_role(role.id).approved is True


def test_unapprove(
    ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    role = ctx["roles"].create_role(**_role_payload())
    # Disabled: forbidden even though unapproved.
    assert (
        ctx["client"].post(f"/swarm/roles/{role.id}/unapprove").status_code
        == 403
    )

    monkeypatch.setattr(swarm_routes, "_skill_admin_enabled", lambda: True)
    response = ctx["client"].post(f"/swarm/roles/{role.id}/unapprove")
    assert response.status_code == 200
    assert response.json()["approved"] is False


# ---------------------------------------------------------------------------
# Standalone runs
# ---------------------------------------------------------------------------


def test_create_role_run_route(ctx) -> None:
    response = ctx["client"].post(
        "/swarm/role-runs",
        json={
            "role_ref": "investment_committee:bull_advocate",
            "target": "600519.SH",
            "question": "多头逻辑是什么",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "role_run"
    assert body["trial_role"] == "investment_committee:bull_advocate"
    assert ctx["runtime"].captured["target"] == "600519.SH"


def test_create_role_run_route_rejects_bad_input(ctx) -> None:
    response = ctx["client"].post(
        "/swarm/role-runs",
        json={"role_ref": "investment_committee:ghost", "target": "x",
              "question": "q"},
    )
    assert response.status_code == 400


def test_list_role_runs_route(
    ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = build_role_run(
        "investment_committee:bull_advocate", "600519.SH", "多头逻辑"
    )
    ctx["store"].create_run(run)

    rows = ctx["client"].get("/swarm/role-runs").json()
    assert [row["id"] for row in rows] == [run.id]
    assert rows[0]["trial_role"] == "investment_committee:bull_advocate"

    filtered = ctx["client"].get(
        "/swarm/role-runs",
        params={"role_ref": "investment_committee:risk_officer"},
    ).json()
    assert filtered == []

    # scope=all requires admin.
    assert ctx["client"].get(
        "/swarm/role-runs", params={"scope": "all"}
    ).status_code == 403

    monkeypatch.setattr(swarm_routes, "_skill_admin_enabled", lambda: True)
    assert ctx["client"].get(
        "/swarm/role-runs", params={"scope": "all"}
    ).status_code == 200
