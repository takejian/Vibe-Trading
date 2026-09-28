"""Public swarm REST and SSE contract regressions."""

from __future__ import annotations

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
