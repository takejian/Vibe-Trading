"""Public swarm REST and SSE contract regressions."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api_server
import src.api.swarm_routes as swarm_routes
from src.swarm.models import RunStatus, SwarmEvent, SwarmRun, SwarmTask
from src.swarm.store import SwarmStore


@pytest.fixture
def swarm_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SwarmStore:
    """Route the process-wide swarm endpoint at an isolated on-disk store."""
    store = SwarmStore(base_dir=tmp_path / "runs")
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    monkeypatch.setattr(swarm_routes, "_swarm_runtime", SimpleNamespace(_store=store))
    return store


def _client() -> TestClient:
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _create_run(
    store: SwarmStore,
    *,
    run_id: str = "run-contract",
    status: RunStatus = RunStatus.pending,
    tasks: list[SwarmTask] | None = None,
) -> SwarmRun:
    run = SwarmRun(
        id=run_id,
        preset_name="contract-test",
        status=status,
        created_at="2026-07-16T00:00:00+00:00",
        completed_at=(
            "2026-07-16T00:00:01+00:00" if status == RunStatus.completed else None
        ),
        tasks=tasks or [],
    )
    store.create_run(run)
    return run


def test_swarm_events_returns_404_before_streaming_missing_run(
    swarm_store: SwarmStore,
) -> None:
    response = _client().get("/swarm/runs/missing-run/events")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run missing-run not found"


def test_swarm_events_resumes_from_last_event_id_header(
    swarm_store: SwarmStore,
) -> None:
    run = _create_run(swarm_store, status=RunStatus.completed)
    for index in range(1, 4):
        swarm_store.append_event(
            run.id,
            SwarmEvent(
                type=f"step_{index}",
                data={"index": index},
                timestamp=f"2026-07-16T00:00:0{index}+00:00",
            ),
        )

    response = _client().get(
        f"/swarm/runs/{run.id}/events?last_index=1",
        headers={"Last-Event-ID": "2"},
    )

    assert response.status_code == 200
    assert "event: step_1" not in response.text
    assert "event: step_2" not in response.text
    assert "id: 3\nevent: step_3" in response.text
    assert 'event: done\ndata: {"status": "completed"}' in response.text


def test_swarm_events_keeps_last_index_query_compatibility(
    swarm_store: SwarmStore,
) -> None:
    run = _create_run(swarm_store, status=RunStatus.completed)
    for index in range(1, 3):
        swarm_store.append_event(
            run.id,
            SwarmEvent(
                type=f"query_step_{index}",
                timestamp=f"2026-07-16T00:00:0{index}+00:00",
            ),
        )

    response = _client().get(f"/swarm/runs/{run.id}/events?last_index=1")

    assert response.status_code == 200
    assert "event: query_step_1" not in response.text
    assert "id: 2\nevent: query_step_2" in response.text


def test_swarm_detail_uses_redacted_public_task_projection(
    swarm_store: SwarmStore,
) -> None:
    internal_path = str(
        Path.cwd() / "agent" / ".swarm" / "runs" / "secret" / "task.log"
    )
    _create_run(
        swarm_store,
        tasks=[
            SwarmTask(
                id="task-1",
                agent_id="analyst",
                prompt_template="internal prompt",
                summary="Public summary",
                artifacts=[internal_path],
                error=f"failed while reading {internal_path}",
                worker_iterations=3,
            )
        ],
    )

    response = _client().get("/swarm/runs/run-contract")

    assert response.status_code == 200
    task = response.json()["tasks"][0]
    assert task["summary"] == "Public summary"
    assert "<redacted>" in task["error"]
    assert internal_path not in response.text
    assert "artifacts" not in task
    assert "prompt_template" not in task
    assert task["worker_iterations"] == 3
    assert task["iterations"] == 3


def test_swarm_preset_detail_returns_full_editor_payload(
    swarm_store: SwarmStore,
) -> None:
    response = _client().get("/swarm/presets/investment_committee/detail")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "investment_committee"
    assert {a["id"] for a in payload["agents"]} == {
        "bull_advocate",
        "bear_advocate",
        "risk_officer",
        "portfolio_manager",
    }
    pm = next(a for a in payload["agents"] if a["id"] == "portfolio_manager")
    assert pm["system_prompt"]
    assert pm["timeout_seconds"] == 1800
    assert len(payload["tasks"]) == 4
    assert "get_market_data" in payload["tool_catalog"]
    assert payload["layers"]  # topological layout present


def test_swarm_preset_detail_404_for_unknown(swarm_store: SwarmStore) -> None:
    response = _client().get("/swarm/presets/no_such_preset/detail")
    assert response.status_code == 404


class _FakeValidatingRuntime:
    """Route-level fake: delegates custom specs to the real validator/build
    without starting any thread or LLM call."""

    def __init__(self, store: SwarmStore) -> None:
        self._store = store
        self.last_kwargs: dict | None = None

    def start_run(self, preset_name, user_vars, *, include_shell_tools=False,
                  custom_spec=None, **kwargs):
        self.last_kwargs = {
            "preset_name": preset_name,
            "user_vars": user_vars,
            "include_shell_tools": include_shell_tools,
            "custom_spec": custom_spec,
        }
        if custom_spec is not None:
            from src.swarm.custom_spec import build_run_from_custom_spec

            return build_run_from_custom_spec(preset_name, custom_spec, user_vars)
        raise FileNotFoundError("plain preset launch is not supported by fake")


def _ic_custom_spec() -> dict:
    def node(node_id: str) -> dict:
        return {
            "id": node_id,
            "role": node_id,
            "duty": f"duty {node_id}",
            "tools": ["load_skill"],
            "timeout_seconds": 300,
            "is_new": False,
        }

    return {
        "target": "600519.SH",
        "question": "做多还是做空",
        "nodes": [
            node("bull_advocate"),
            node("bear_advocate"),
            node("risk_officer"),
            node("portfolio_manager"),
        ],
        "edges": [
            {"upstream": "bull_advocate", "downstream": "risk_officer"},
            {"upstream": "bear_advocate", "downstream": "risk_officer"},
            {"upstream": "risk_officer", "downstream": "portfolio_manager"},
        ],
    }


def test_create_custom_swarm_run_passes_spec_and_returns_id(
    swarm_store: SwarmStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeValidatingRuntime(swarm_store)
    monkeypatch.setattr(swarm_routes, "_swarm_runtime", fake)

    response = _client().post(
        "/swarm/runs",
        json={
            "preset_name": "investment_committee",
            "user_vars": {},
            "custom": _ic_custom_spec(),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["preset_name"] == "investment_committee"
    assert body["status"] == "pending"
    assert body["id"].startswith("swarm-")
    assert fake.last_kwargs["custom_spec"]["target"] == "600519.SH"


def test_create_custom_swarm_run_rejects_cycle_with_400(
    swarm_store: SwarmStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        swarm_routes, "_swarm_runtime", _FakeValidatingRuntime(swarm_store)
    )
    spec = _ic_custom_spec()
    spec["edges"].append(
        {"upstream": "risk_officer", "downstream": "bull_advocate"}
    )

    response = _client().post(
        "/swarm/runs",
        json={"preset_name": "investment_committee", "user_vars": {}, "custom": spec},
    )

    assert response.status_code == 400


def test_create_custom_swarm_run_rejects_non_object_custom(
    swarm_store: SwarmStore,
) -> None:
    response = _client().post(
        "/swarm/runs",
        json={
            "preset_name": "investment_committee",
            "user_vars": {},
            "custom": "not-an-object",
        },
    )
    assert response.status_code == 400


def test_swarm_run_list_and_detail_carry_customization_fields(
    swarm_store: SwarmStore,
) -> None:
    run = _create_run(swarm_store, status=RunStatus.completed)
    run.customized = True
    run.research_target = "600519.SH"
    run.research_question = "做多还是做空"
    run.final_report = "倾向做多，理由是……"
    swarm_store.update_run(run)

    listing = _client().get("/swarm/runs").json()
    row = next(item for item in listing if item["id"] == run.id)
    assert row["customized"] is True
    assert row["research_target"] == "600519.SH"
    assert row["research_question"] == "做多还是做空"
    assert row["final_report_excerpt"] == "倾向做多，理由是……"

    detail = _client().get(f"/swarm/runs/{run.id}").json()
    assert detail["customized"] is True
    assert detail["research_target"] == "600519.SH"
    assert detail["research_question"] == "做多还是做空"


# ---------------------------------------------------------------------------
# Run list filtering: kind / target / created-date window
# ---------------------------------------------------------------------------


def _stored_run(
    store: SwarmStore,
    run_id: str,
    *,
    kind: str = "team",
    trial_skill: str | None = None,
    target: str = "600519.SH 贵州茅台",
    created_at: str = "2026-07-15T08:00:00+00:00",
) -> SwarmRun:
    run = SwarmRun(
        id=run_id,
        preset_name=f"skill:{trial_skill}" if trial_skill else "investment_committee",
        status=RunStatus.completed,
        created_at=created_at,
        completed_at=created_at,
        research_target=target,
        kind=kind,
        trial_skill=trial_skill,
    )
    store.create_run(run)
    return run


def test_run_list_defaults_to_team_kind(swarm_store: SwarmStore) -> None:
    _stored_run(swarm_store, "team-1")
    _stored_run(
        swarm_store,
        "trial-1",
        kind="skill_trial",
        trial_skill="behavioral-finance",
    )

    rows = _client().get("/swarm/runs").json()
    ids = {row["id"] for row in rows}
    assert ids == {"team-1"}
    assert rows[0]["kind"] == "team"
    assert rows[0]["trial_skill"] is None


def test_run_list_filters_trial_kind_and_skill(swarm_store: SwarmStore) -> None:
    _stored_run(swarm_store, "team-1")
    _stored_run(
        swarm_store,
        "trial-1",
        kind="skill_trial",
        trial_skill="behavioral-finance",
    )
    _stored_run(
        swarm_store,
        "trial-2",
        kind="skill_trial",
        trial_skill="commodity-analysis",
        target="GCX 黄金",
        created_at="2026-07-16T08:00:00+00:00",
    )

    rows = _client().get("/swarm/runs?kind=skill_trial").json()
    assert {row["id"] for row in rows} == {"trial-1", "trial-2"}

    all_rows = _client().get("/swarm/runs?kind=all").json()
    assert {row["id"] for row in all_rows} == {"team-1", "trial-1", "trial-2"}

    trials = _client().get("/swarm/skill-trials?skill_name=commodity-analysis").json()
    assert [row["id"] for row in trials] == ["trial-2"]


def test_run_list_filters_target_fuzzy(swarm_store: SwarmStore) -> None:
    _stored_run(swarm_store, "team-1", target="600519.SH 贵州茅台")
    _stored_run(
        swarm_store,
        "team-2",
        target="000001.SZ 平安银行",
        created_at="2026-07-16T08:00:00+00:00",
    )

    rows = _client().get("/swarm/runs?target=茅台").json()
    assert [row["id"] for row in rows] == ["team-1"]
    rows = _client().get("/swarm/runs?target=000001").json()
    assert [row["id"] for row in rows] == ["team-2"]
    assert _client().get("/swarm/runs?target=nonexistent").json() == []


def test_run_list_filters_created_date_window(swarm_store: SwarmStore) -> None:
    _stored_run(swarm_store, "old", created_at="2026-07-10T08:00:00+00:00")
    _stored_run(
        swarm_store, "mid", created_at="2026-07-16T08:00:00+00:00"
    )
    _stored_run(
        swarm_store, "edge", created_at="2026-07-20T08:00:00+00:00"
    )

    rows = _client().get("/swarm/runs?from=2026-07-16&to=2026-07-20").json()
    assert {row["id"] for row in rows} == {"mid", "edge"}


def test_run_list_rejects_unknown_kind(swarm_store: SwarmStore) -> None:
    assert _client().get("/swarm/runs?kind=bogus").status_code == 422


def test_run_detail_carries_kind_and_trial_skill(swarm_store: SwarmStore) -> None:
    _stored_run(
        swarm_store,
        "trial-9",
        kind="skill_trial",
        trial_skill="behavioral-finance",
    )
    detail = _client().get("/swarm/runs/trial-9").json()
    assert detail["kind"] == "skill_trial"
    assert detail["trial_skill"] == "behavioral-finance"


# ---------------------------------------------------------------------------
# Custom teams
# ---------------------------------------------------------------------------


def _team_body() -> dict:
    return {
        "name": "路由测试团队",
        "description": "契约测试",
        "source_preset": "investment_committee",
        "nodes": [node for node in (
            {
                "id": node_id,
                "role": node_id,
                "duty": f"duty {node_id}",
                "tools": ["load_skill"],
                "timeout_seconds": 300,
                "is_new": False,
            }
            for node_id in (
                "bull_advocate",
                "bear_advocate",
                "risk_officer",
                "portfolio_manager",
            )
        )],
        "edges": [
            {"upstream": "bull_advocate", "downstream": "risk_officer"},
            {"upstream": "bear_advocate", "downstream": "risk_officer"},
            {"upstream": "risk_officer", "downstream": "portfolio_manager"},
        ],
    }


def test_custom_team_crud_lifecycle(swarm_store: SwarmStore) -> None:
    client = _client()

    created = client.post("/swarm/custom-teams", json=_team_body())
    assert created.status_code == 200, created.text
    team_id = created.json()["id"]

    listing = client.get("/swarm/custom-teams").json()
    assert any(team["id"] == team_id and team["role_count"] == 4 for team in listing)

    detail = client.get(f"/swarm/custom-teams/{team_id}").json()
    assert detail["name"] == "路由测试团队"
    assert len(detail["nodes"]) == 4

    body = _team_body()
    body["name"] = "路由测试团队-改"
    updated = client.put(f"/swarm/custom-teams/{team_id}", json=body)
    assert updated.status_code == 200
    assert client.get(f"/swarm/custom-teams/{team_id}").json()["name"] == "路由测试团队-改"

    assert client.delete(f"/swarm/custom-teams/{team_id}").status_code == 200
    assert client.get(f"/swarm/custom-teams/{team_id}").status_code == 404


def test_custom_team_duplicate_name_is_409(swarm_store: SwarmStore) -> None:
    client = _client()
    assert client.post("/swarm/custom-teams", json=_team_body()).status_code == 200
    assert client.post("/swarm/custom-teams", json=_team_body()).status_code == 409


def test_custom_team_invalid_payload_is_400_and_missing_is_404(
    swarm_store: SwarmStore,
) -> None:
    client = _client()
    bad = _team_body()
    bad["name"] = "  "
    assert client.post("/swarm/custom-teams", json=bad).status_code == 400
    assert client.get("/swarm/custom-teams/team-nope").status_code == 404
    assert client.delete("/swarm/custom-teams/team-nope").status_code == 404


# ---------------------------------------------------------------------------
# Skill Square catalog / capabilities / trials
# ---------------------------------------------------------------------------


def test_skill_catalog_and_capabilities(swarm_store: SwarmStore) -> None:
    client = _client()
    catalog = client.get("/swarm/skills/catalog").json()["skills"]
    entry = next(item for item in catalog if item["name"] == "behavioral-finance")
    assert entry["source"] == "bundled"
    assert entry["approved"] is False

    caps = client.get("/swarm/skills/capabilities").json()
    assert caps["admin_enabled"] is False


class _FakeTrialRuntime:
    def __init__(self, store: SwarmStore) -> None:
        self._store = store
        self.captured: dict | None = None

    def start_run(self, preset_name, user_vars, *, include_shell_tools=False,
                  skill_trial=None, **kwargs):
        self.captured = skill_trial
        from src.swarm.skill_trials import build_skill_trial_run

        return build_skill_trial_run(
            skill_trial["skill_name"],
            skill_trial["target"],
            skill_trial["question"],
        )


def test_skill_trial_launch_route(
    swarm_store: SwarmStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeTrialRuntime(swarm_store)
    monkeypatch.setattr(swarm_routes, "_swarm_runtime", fake)

    response = _client().post(
        "/swarm/skill-trials",
        json={
            "skill_name": "behavioral-finance",
            "target": "600519.SH",
            "question": "适合做多吗",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "skill_trial"
    assert body["trial_skill"] == "behavioral-finance"
    assert fake.captured["target"] == "600519.SH"


def test_skill_trial_launch_route_rejects_unknown_skill(
    swarm_store: SwarmStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(swarm_routes, "_swarm_runtime", _FakeTrialRuntime(swarm_store))
    response = _client().post(
        "/swarm/skill-trials",
        json={"skill_name": "ghost-skill", "target": "AAPL", "question": "q"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Operator-only package administration
# ---------------------------------------------------------------------------


def _skill_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "macro-radar/SKILL.md",
            "---\n"
            "name: macro-radar\n"
            "description: 股票宏观流动性分析\n"
            "---\n\n"
            "# 宏观雷达\n\n跟踪利率变化辅助股票择时。\n",
        )
    return buffer.getvalue()


def test_skill_admin_routes_forbidden_when_disabled(swarm_store: SwarmStore) -> None:
    client = _client()
    response = client.post(
        "/swarm/skills/import",
        files={"file": ("p.zip", _skill_zip(), "application/zip")},
    )
    assert response.status_code == 403
    assert client.post("/swarm/skills/sync").status_code == 403


def test_skill_import_when_enabled(
    swarm_store: SwarmStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(swarm_routes, "_skill_admin_enabled", lambda: True)
    response = _client().post(
        "/swarm/skills/import",
        files={"file": ("p.zip", _skill_zip(), "application/zip")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["installed"][0]["name"] == "macro-radar"

    # A non-finance / broken package is refused with 400.
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr(
            "cookbook/SKILL.md",
            "---\nname: cookbook\ndescription: recipes\n---\n\nbake cake\n",
        )
    refused = _client().post(
        "/swarm/skills/import",
        files={"file": ("bad.zip", bad.getvalue(), "application/zip")},
    )
    assert refused.status_code == 400


def test_skill_sync_without_source_is_409(
    swarm_store: SwarmStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(swarm_routes, "_skill_admin_enabled", lambda: True)
    response = _client().post("/swarm/skills/sync")
    assert response.status_code == 409
