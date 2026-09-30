"""End-to-end admission for operator-approved personal custom skills (M14).

Covers the chain that turns a manual approval into a globally selectable
skill:

* approved custom skills pass canvas/custom-team graph validation and the
  custom-role skill allowlist;
* unapproved, revoked or deleted custom skills are hard errors at both
  consumption points (canvas highlight blocks launch; role save rejected);
* the trial auto-approval hook is dual-track: qualified assembled skills
  flip the global registry, personal custom skills never do — not even when
  the custom record is deleted while a trial is in flight.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.swarm.custom_skills import CustomSkillStore
from src.swarm.custom_spec import build_run_from_custom_spec
from src.swarm.models import RunStatus, TaskStatus
from src.swarm.roles import RoleStore
from src.swarm.skill_trials import (
    build_skill_trial_run,
    trial_qualifies_for_global_approval,
)

CUSTOM_NAME = "期权波动率曲面"
BUNDLED_NAME = "behavioral-finance"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    user_dir = tmp_path / "skills" / "user"
    custom_dir = tmp_path / "swarm" / "skills"
    approvals_file = tmp_path / "skills" / "approvals.json"
    user_dir.mkdir(parents=True)
    custom_dir.mkdir(parents=True)

    # Default-constructed stores/loaders resolve through these accessors.
    monkeypatch.setattr("src.config.paths.get_user_skills_dir", lambda: user_dir)
    monkeypatch.setattr("src.config.paths.get_custom_skills_dir", lambda: custom_dir)
    monkeypatch.setattr(
        "src.swarm.custom_skills.get_user_skills_dir", lambda: user_dir
    )
    monkeypatch.setattr(
        "src.swarm.custom_skills.get_custom_skills_dir", lambda: custom_dir
    )
    monkeypatch.setattr(
        "src.config.paths.get_skill_approvals_file", lambda: approvals_file
    )
    monkeypatch.setattr(
        "src.swarm.skill_approvals.get_skill_approvals_file",
        lambda: approvals_file,
    )
    return SimpleNamespace(
        user_dir=user_dir,
        custom_dir=custom_dir,
        approvals_file=approvals_file,
        custom_store=CustomSkillStore(),
        role_store=RoleStore(base_dir=tmp_path / "roles"),
    )


def _custom_skill(env: SimpleNamespace, *, approved: bool):
    skill = env.custom_store.create_skill(
        name=CUSTOM_NAME,
        purpose="期权波动率分析",
        methodology="拟合隐含波动率曲面并识别偏度与期限结构异常。",
        inputs="标的、到期链、报价",
        outputs="曲面图表与套利提示",
    )
    if approved:
        env.custom_store.approve(skill.id)
    return skill


def _ic_node(node_id: str, **overrides) -> dict:
    base = {
        "id": node_id,
        "role": node_id,
        "duty": f"Duty of {node_id}",
        "tools": ["get_market_data"],
        "timeout_seconds": 300,
        "is_new": False,
    }
    base.update(overrides)
    return base


def _spec_with_skill(skill_name: str) -> dict:
    return {
        "target": "510050.SH",
        "question": "期权贵不贵？",
        "nodes": [
            _ic_node("bull_advocate", skills=[skill_name]),
            _ic_node("bear_advocate"),
            _ic_node("risk_officer"),
            _ic_node("portfolio_manager"),
        ],
        "edges": [
            {"upstream": "bull_advocate", "downstream": "risk_officer"},
            {"upstream": "bear_advocate", "downstream": "risk_officer"},
            {"upstream": "risk_officer", "downstream": "portfolio_manager"},
        ],
    }


def _role_payload(**overrides) -> dict:
    base = {
        "name": "期权策略师",
        "purpose": "基于波动率曲面制定期权策略",
        "system_prompt": "You analyze options surfaces and propose trades.",
        "tools": ["get_market_data"],
        "skills": [],
        "max_iterations": 20,
        "timeout_seconds": 240,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Canvas / custom-team graph validation
# ---------------------------------------------------------------------------


def test_approved_custom_skill_allowed_on_canvas_node(env: SimpleNamespace) -> None:
    _custom_skill(env, approved=True)

    run = build_run_from_custom_spec(
        "investment_committee", _spec_with_skill(CUSTOM_NAME)
    )
    bull = next(a for a in run.agents if a.id == "bull_advocate")
    assert bull.skills == [CUSTOM_NAME]


def test_unapproved_custom_skill_blocked_on_canvas(env: SimpleNamespace) -> None:
    _custom_skill(env, approved=False)
    with pytest.raises(ValueError):
        build_run_from_custom_spec(
            "investment_committee", _spec_with_skill(CUSTOM_NAME)
        )


def test_revoked_custom_skill_blocked_on_canvas(env: SimpleNamespace) -> None:
    skill = _custom_skill(env, approved=True)
    # Was selectable right after approval.
    build_run_from_custom_spec(
        "investment_committee", _spec_with_skill(CUSTOM_NAME)
    )

    env.custom_store.unapprove(skill.id)
    with pytest.raises(ValueError):
        build_run_from_custom_spec(
            "investment_committee", _spec_with_skill(CUSTOM_NAME)
        )


def test_deleted_custom_skill_blocked_on_canvas(env: SimpleNamespace) -> None:
    skill = _custom_skill(env, approved=True)
    env.custom_store.delete_skill(skill.id)
    with pytest.raises(ValueError):
        build_run_from_custom_spec(
            "investment_committee", _spec_with_skill(CUSTOM_NAME)
        )


# ---------------------------------------------------------------------------
# Custom role allowlist
# ---------------------------------------------------------------------------


def test_role_save_accepts_approved_custom_skill(env: SimpleNamespace) -> None:
    _custom_skill(env, approved=True)
    role = env.role_store.create_role(
        **_role_payload(skills=[CUSTOM_NAME])
    )
    assert role.skills == [CUSTOM_NAME]


def test_role_save_rejects_unapproved_custom_skill(env: SimpleNamespace) -> None:
    _custom_skill(env, approved=False)
    with pytest.raises(ValueError):
        env.role_store.create_role(**_role_payload(skills=[CUSTOM_NAME]))


def test_role_update_blocked_after_skill_revoked(env: SimpleNamespace) -> None:
    skill = _custom_skill(env, approved=True)
    role = env.role_store.create_role(**_role_payload(skills=[CUSTOM_NAME]))

    env.custom_store.unapprove(skill.id)
    with pytest.raises(ValueError):
        env.role_store.update_role(
            role.id, **_role_payload(skills=[CUSTOM_NAME])
        )


# ---------------------------------------------------------------------------
# Dual-track trial auto-approval predicate
# ---------------------------------------------------------------------------


def _completed_trial(skill_name: str, *, summary: str = "结论明确"):
    run = build_skill_trial_run(skill_name, "510050.SH", "期权贵不贵？")
    run.status = RunStatus.completed
    if summary:
        run.tasks[0].status = TaskStatus.completed
        run.tasks[0].summary = summary
    return run


def test_qualified_assembled_trial_still_auto_approves(
    env: SimpleNamespace,
) -> None:
    run = _completed_trial(BUNDLED_NAME)
    assert trial_qualifies_for_global_approval(run) is True


def test_qualified_custom_trial_never_auto_approves(env: SimpleNamespace) -> None:
    _custom_skill(env, approved=False)
    run = _completed_trial(CUSTOM_NAME)
    assert trial_qualifies_for_global_approval(run) is False


def test_deleted_inflight_custom_trial_leaves_no_global_approval(
    env: SimpleNamespace,
) -> None:
    skill = _custom_skill(env, approved=False)
    run = _completed_trial(CUSTOM_NAME)
    # Record and its materialized directory disappear before finalization.
    env.custom_store.delete_skill(skill.id)
    assert trial_qualifies_for_global_approval(run) is False


def test_failed_trial_does_not_auto_approve(env: SimpleNamespace) -> None:
    run = _completed_trial(BUNDLED_NAME)
    run.status = RunStatus.failed
    assert trial_qualifies_for_global_approval(run) is False

    empty = _completed_trial(BUNDLED_NAME, summary="")
    assert trial_qualifies_for_global_approval(empty) is False
