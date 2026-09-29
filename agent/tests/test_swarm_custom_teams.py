"""CRUD and validation tests for personal custom teams ("my teams").

Covers ``src.swarm.custom_teams.CustomTeamStore``: save/list/get/update/
delete, duplicate-name interception, graph validation on save, corrupt-row
tolerance, and the guarantee that deleting a team never touches run
snapshots. No LLM or network involved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.swarm.custom_teams import CustomTeamStore, DuplicateTeamNameError

PRESET = "investment_committee"


def _node(node_id: str, **overrides) -> dict:
    base = {
        "id": node_id,
        "role": node_id,
        "duty": f"Duty of {node_id}",
        "tools": ["load_skill", "get_market_data"],
        "timeout_seconds": 300,
        "source_task_id": {
            "bull_advocate": "task-bull",
            "bear_advocate": "task-bear",
            "risk_officer": "task-risk",
            "portfolio_manager": "task-decision",
        }.get(node_id),
        "is_new": False,
    }
    base.update(overrides)
    return base


def _team_payload(**overrides) -> dict:
    payload = {
        "name": "我的宏观团队",
        "description": "宏观驱动的多空评审",
        "source_preset": PRESET,
        "nodes": [
            _node("bull_advocate"),
            _node("bear_advocate"),
            _node("risk_officer"),
            _node("portfolio_manager"),
        ],
        "edges": [
            {"upstream": "bull_advocate", "downstream": "risk_officer"},
            {"upstream": "bear_advocate", "downstream": "risk_officer"},
            {"upstream": "risk_officer", "downstream": "portfolio_manager"},
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def store(tmp_path: Path) -> CustomTeamStore:
    return CustomTeamStore(base_dir=tmp_path / "custom_teams")


def test_save_and_get_round_trip(store: CustomTeamStore) -> None:
    team = store.save_team(**_team_payload())

    assert team.id.startswith("team-")
    loaded = store.get_team(team.id)
    assert loaded.name == "我的宏观团队"
    assert loaded.source_preset == PRESET
    assert len(loaded.nodes) == 4
    assert loaded.created_at == loaded.updated_at
    [listed] = store.list_teams()
    assert listed.id == team.id


def test_name_required_and_length_limits(store: CustomTeamStore) -> None:
    with pytest.raises(ValueError):
        store.save_team(**_team_payload(name="   "))
    with pytest.raises(ValueError):
        store.save_team(**_team_payload(name="x" * 81))
    with pytest.raises(ValueError):
        store.save_team(**_team_payload(description="x" * 401))


def test_missing_preset_rejected(store: CustomTeamStore) -> None:
    with pytest.raises(ValueError):
        store.save_team(**_team_payload(source_preset=""))


def test_invalid_graph_rejected_on_save(store: CustomTeamStore) -> None:
    payload = _team_payload()
    payload["edges"].append(
        {"upstream": "risk_officer", "downstream": "bull_advocate"}
    )  # cycle
    with pytest.raises(ValueError):
        store.save_team(**payload)


def test_duplicate_name_intercepted(store: CustomTeamStore) -> None:
    store.save_team(**_team_payload())
    with pytest.raises(DuplicateTeamNameError):
        store.save_team(**_team_payload())

    # A whitespace-different but equal name still collides.
    with pytest.raises(DuplicateTeamNameError):
        store.save_team(**_team_payload(name="  我的宏观团队 "))


def test_update_in_place_preserves_id_and_created_at(store: CustomTeamStore) -> None:
    team = store.save_team(**_team_payload())
    updated = store.update_team(
        team.id, **_team_payload(name="改名后的团队", description="新简介")
    )

    assert updated.id == team.id
    assert updated.created_at == team.created_at
    assert updated.updated_at >= team.updated_at
    assert store.get_team(team.id).name == "改名后的团队"


def test_update_rename_collision_is_409_class(store: CustomTeamStore) -> None:
    first = store.save_team(**_team_payload(name="团队甲"))
    store.save_team(**_team_payload(name="团队乙"))
    with pytest.raises(DuplicateTeamNameError):
        store.update_team(first.id, **_team_payload(name="团队乙"))


def test_update_missing_team_raises_filenotfound(store: CustomTeamStore) -> None:
    with pytest.raises(FileNotFoundError):
        store.update_team("team-missing", **_team_payload())


def test_delete_team_and_get_missing(store: CustomTeamStore) -> None:
    team = store.save_team(**_team_payload())
    store.delete_team(team.id)
    assert store.list_teams() == []
    with pytest.raises(FileNotFoundError):
        store.get_team(team.id)
    with pytest.raises(FileNotFoundError):
        store.delete_team(team.id)


def test_invalid_team_id_rejected(store: CustomTeamStore) -> None:
    with pytest.raises(ValueError):
        store.get_team("../escape")


def test_corrupt_rows_are_skipped(store: CustomTeamStore) -> None:
    good = store.save_team(**_team_payload())
    (Path(store._dir) / "team-broken.json").write_text("{not json", encoding="utf-8")

    listed = store.list_teams()
    assert [team.id for team in listed] == [good.id]


def test_deleting_team_does_not_touch_runs_dir(
    store: CustomTeamStore, tmp_path: Path
) -> None:
    snapshot_dir = tmp_path / "runs" / "swarm-historical"
    snapshot_dir.mkdir(parents=True)
    snapshot = snapshot_dir / "run.json"
    snapshot.write_text('{"id": "swarm-historical"}', encoding="utf-8")

    team = store.save_team(**_team_payload())
    store.delete_team(team.id)

    assert snapshot.exists()
    assert json.loads(snapshot.read_text(encoding="utf-8"))["id"] == "swarm-historical"
