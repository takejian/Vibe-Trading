"""Tests for the skill catalog, finance gate and global approval registry.

Also covers the custom-spec skills trust boundary: preset skills and
globally-approved assembled skills are selectable for canvas nodes, while
unknown/delisted skills are a hard error (unlike out-of-catalog tools).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.skills import SkillsLoader
from src.swarm.custom_spec import build_run_from_custom_spec
from src.swarm.skill_approvals import SkillApprovalStore
from src.swarm.skill_catalog import (
    is_finance_related,
    list_assembled_skills,
    list_approved_skill_names,
)

SKILL_MARKDOWN = """---
name: user-macro-radar
description: 宏观流动性与利率雷达，用于股票市场择时
category: macro
---

# 宏观雷达

跟踪利率、通胀与流动性变化，辅助股票做多/做空决策。
"""


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    user_dir = tmp_path / "skills" / "user"
    approvals_file = tmp_path / "skills" / "approvals.json"
    user_dir.mkdir(parents=True)
    # The catalog/custom_spec build default SkillsLoader()/stores through
    # these config-path accessors.
    monkeypatch.setattr("src.config.paths.get_user_skills_dir", lambda: user_dir)
    monkeypatch.setattr(
        "src.config.paths.get_skill_approvals_file", lambda: approvals_file
    )
    # custom_spec imports SkillApprovalStore, which captured the accessor at
    # import time — patch the bound name too.
    monkeypatch.setattr(
        "src.swarm.skill_approvals.get_skill_approvals_file",
        lambda: approvals_file,
    )
    return user_dir, approvals_file


def _install_user_skill(user_dir: Path, slug: str = "user-macro-radar") -> Path:
    target = user_dir / slug
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(SKILL_MARKDOWN, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Finance gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,description,body",
    [
        ("Macro Radar", "rates and inflation", ""),
        ("我的技能", "股票多空分析", ""),
        ("x", "", "track futures and option order flow"),
    ],
)
def test_finance_keywords_hit(name: str, description: str, body: str) -> None:
    assert is_finance_related(name, description, body=body)


def test_finance_explicit_frontmatter_flag() -> None:
    assert is_finance_related("weather", "rain forecast", body="", metadata={"finance": True})
    assert is_finance_related("weather", body="", metadata={"finance": "true"})


def test_non_finance_package_rejected() -> None:
    assert not is_finance_related("weather-radar", "daily rain forecast", body="pack an umbrella")


# ---------------------------------------------------------------------------
# Approval registry
# ---------------------------------------------------------------------------


def test_approval_mark_is_idempotent_and_keeps_first_provenance(paths) -> None:
    _user_dir, approvals_file = paths
    store = SkillApprovalStore(path=approvals_file)

    first = store.mark_approved("user-macro-radar", source_run_id="swarm-run-1")
    assert first.approved is True
    assert first.source_run_id == "swarm-run-1"

    second = store.mark_approved("user-macro-radar", source_run_id="swarm-run-2")
    assert second.source_run_id == "swarm-run-1"  # first success wins

    reloaded = SkillApprovalStore(path=approvals_file)
    assert reloaded.is_approved("user-macro-radar")
    assert reloaded.approved_names() == {"user-macro-radar"}
    assert not reloaded.is_approved("never-tried")


def test_corrupt_approval_file_starts_empty(paths) -> None:
    _user_dir, approvals_file = paths
    approvals_file.write_text("{broken", encoding="utf-8")
    store = SkillApprovalStore(path=approvals_file)
    assert store.approved_names() == set()
    store.mark_approved("chanlun-analysis", source_run_id="run-x")
    assert SkillApprovalStore(path=approvals_file).is_approved("chanlun-analysis")


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def test_catalog_marks_user_source_and_approval(paths) -> None:
    user_dir, approvals_file = paths
    _install_user_skill(user_dir)
    loader = SkillsLoader(user_skills_dir=user_dir)
    approvals = SkillApprovalStore(path=approvals_file)

    items = list_assembled_skills(loader=loader, approvals=approvals)
    by_name = {item["name"]: item for item in items}
    assert by_name["user-macro-radar"]["source"] == "user"
    assert by_name["user-macro-radar"]["approved"] is False
    assert by_name["behavioral-finance"]["source"] == "bundled"

    approvals.mark_approved("user-macro-radar", source_run_id="r1")
    by_name2 = {
        item["name"]: item
        for item in list_assembled_skills(loader=loader, approvals=approvals)
    }
    assert by_name2["user-macro-radar"]["approved"] is True
    assert "user-macro-radar" in list_approved_skill_names(loader=loader, approvals=approvals)


# ---------------------------------------------------------------------------
# Custom spec skills boundary
# ---------------------------------------------------------------------------


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


def _spec() -> dict:
    return {
        "target": "600519.SH",
        "question": "做多还是做空？",
        "nodes": [
            _ic_node("bull_advocate"),
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


def test_unknown_skill_on_node_is_hard_error(paths) -> None:
    spec = _spec()
    spec["nodes"][0]["skills"] = ["delisted-mystery-skill"]
    with pytest.raises(ValueError):
        build_run_from_custom_spec("investment_committee", spec)


def test_non_string_skill_entry_is_hard_error(paths) -> None:
    spec = _spec()
    spec["nodes"][0]["skills"] = ["behavioral-finance", 123]
    with pytest.raises(ValueError):
        build_run_from_custom_spec("investment_committee", spec)


def test_approved_user_skill_is_allowed_and_deduped(paths) -> None:
    user_dir, approvals_file = paths
    _install_user_skill(user_dir)
    SkillApprovalStore(path=approvals_file).mark_approved("user-macro-radar", source_run_id="r1")

    spec = _spec()
    spec["nodes"][0]["skills"] = ["user-macro-radar", "user-macro-radar"]
    run = build_run_from_custom_spec("investment_committee", spec)

    bull = next(a for a in run.agents if a.id == "bull_advocate")
    assert bull.skills == ["user-macro-radar"]


def test_unapproved_assembled_skill_not_selectable(paths) -> None:
    user_dir, _approvals_file = paths
    _install_user_skill(user_dir)  # assembled but no successful trial yet
    spec = _spec()
    spec["nodes"][0]["skills"] = ["user-macro-radar"]
    with pytest.raises(ValueError):
        build_run_from_custom_spec("investment_committee", spec)


def test_node_without_skills_key_keeps_preset_skills(paths) -> None:
    run = build_run_from_custom_spec("investment_committee", _spec())
    pm = next(a for a in run.agents if a.id == "portfolio_manager")
    assert pm.skills == ["strategy-generate", "asset-allocation"]
