"""Unit tests for deterministic approved-role classification.

The L2 filter never imports the L3 swarm package; tests pass catalog
entries as plain data (the real-catalog integration test fetches them
itself, which is allowed outside ``agent/src``).
"""

from __future__ import annotations

import pytest

from src.swarm.role_catalog import list_approved_role_refs
from src.watchlist import role_catalog_filter as rcf


def _entry(ref: str, name: str = "", purpose: str = "") -> dict:
    return {"ref": ref, "name": name, "purpose": purpose, "approved": True}


@pytest.fixture()
def entries() -> list[dict]:
    return [
        # Built-in technical panel
        _entry("technical_analysis_panel:chanlun_analyst",
               "Chanlun (Chan Theory) Analyst", "Chan theory reading"),
        _entry("technical_analysis_panel:classic_ta_analyst",
               "Classic Technical Analyst", "Moving averages / MACD"),
        _entry("technical_analysis_panel:ichimoku_analyst",
               "Ichimoku Analyst", "Cloud charts"),
        _entry("technical_analysis_panel:wave_analyst",
               "Elliott Wave Analyst", "Wave counting"),
        _entry("technical_analysis_panel:smc_analyst",
               "SMC Analyst", "Smart money concepts"),
        _entry("technical_analysis_panel:signal_aggregator",
               "Signal Aggregator", "Aggregate technical signals"),
        # Built-in fundamental presets
        _entry("fundamental_research_team:valuation_analyst",
               "Valuation Analyst", "DCF and multiples"),
        _entry("earnings_research_desk:earnings_analyst",
               "Earnings Analyst", "Quarterly results"),
        _entry("equity_research_team:stock_picker",
               "Stock Analyst", "Single-name equity research"),
        _entry("value_investing_committee:value_chair",
               "Value Chair", "Margin of safety"),
        # Built-in general presets
        _entry("macro_rates_fx_desk:macro_analyst",
               "Macro Analyst", "Rates and FX"),
        _entry("risk_committee:risk_officer",
               "Risk Officer", "Portfolio risk"),
        # Custom approved roles (keyword classification)
        _entry("my_ta_guy", "老张技术面分析", "专注 K线、均线 与缠论结构"),
        _entry("my_fin_girl", "财报深度研究员", "拆解财务报表与估值"),
        _entry("my_generalist", "行业观察员", "跟踪行业政策动态"),
        # Custom role whose NAME exactly matches the Chanlun role
        _entry("copy_chanlun", "  chanlun (chan theory) analyst  ", ""),
    ]


def test_builtin_roles_classify_by_preset(entries: list[dict]) -> None:
    cases = {
        "technical_analysis_panel:chanlun_analyst": ("technical", True),
        "technical_analysis_panel:classic_ta_analyst": ("technical", False),
        "technical_analysis_panel:ichimoku_analyst": ("technical", False),
        "technical_analysis_panel:wave_analyst": ("technical", False),
        "technical_analysis_panel:smc_analyst": ("technical", False),
        "technical_analysis_panel:signal_aggregator": ("technical", False),
        "fundamental_research_team:valuation_analyst": ("fundamental", False),
        "earnings_research_desk:earnings_analyst": ("fundamental", False),
        "equity_research_team:stock_picker": ("fundamental", False),
        "value_investing_committee:value_chair": ("fundamental", False),
        "macro_rates_fx_desk:macro_analyst": ("general", False),
        "risk_committee:risk_officer": ("general", False),
    }
    for entry in entries:
        if entry["ref"] in cases:
            assert rcf.classify_role(entry) == cases[entry["ref"]]


def test_custom_roles_use_keywords(entries: list[dict]) -> None:
    by_ref = {e["ref"]: e for e in entries}
    assert rcf.classify_role(by_ref["my_ta_guy"]) == ("technical", False)
    assert rcf.classify_role(by_ref["my_fin_girl"]) == ("fundamental", False)
    assert rcf.classify_role(by_ref["my_generalist"]) == ("general", False)
    # Exact Chanlun name (whitespace/case-insensitive) flags is_chanlun;
    # keyword "chanlun" in the name also classifies it technical.
    cat, chanlun = rcf.classify_role(by_ref["copy_chanlun"])
    assert (cat, chanlun) == ("technical", True)


def test_english_keywords_for_custom_roles() -> None:
    assert rcf.classify_role(
        _entry("x1", "Momentum & Ichimoku Scout", "technical setups")
    ) == ("technical", False)
    assert rcf.classify_role(
        _entry("x2", "Financial Statement Reader", "earnings quality")
    ) == ("fundamental", False)
    assert rcf.classify_role(_entry("x3", "Policy Watcher", "news")) == (
        "general",
        False,
    )


def test_list_analyst_roles_filters_and_enriches(entries: list[dict]) -> None:
    technical = rcf.list_analyst_roles("technical", entries)
    assert {r["category"] for r in technical} == {"technical"}
    refs = {r["ref"] for r in technical}
    assert "technical_analysis_panel:chanlun_analyst" in refs
    assert "my_ta_guy" in refs
    chanlun = [r for r in technical if r["is_chanlun"]]
    builtin_chanlun = next(
        r for r in chanlun
        if r["ref"] == "technical_analysis_panel:chanlun_analyst"
    )
    assert builtin_chanlun["name"] == "Chanlun (Chan Theory) Analyst"

    fundamental = rcf.list_analyst_roles("fundamental", entries)
    assert len(fundamental) == 5  # 4 builtin + 1 keyword custom
    assert all("purpose" in r for r in fundamental)

    general = rcf.list_analyst_roles("general", entries)
    assert "risk_committee:risk_officer" in {r["ref"] for r in general}

    assert len(rcf.list_analyst_roles(None, entries)) == len(entries)
    with pytest.raises(ValueError):
        rcf.list_analyst_roles("bogus", entries)

    # Malformed rows are skipped, not crashed on.
    assert rcf.list_analyst_roles(None, [{"name": "no-ref"}, "x"]) == []


def test_get_analyst_role(entries: list[dict]) -> None:
    role = rcf.get_analyst_role("equity_research_team:stock_picker", entries)
    assert role is not None and role["category"] == "fundamental"
    assert rcf.get_analyst_role("not:real", entries) is None


def test_team_names_populate_source_team(entries: list[dict]) -> None:
    """The L4-supplied preset-title map drives the ``team`` source label."""
    team_names = {
        "technical_analysis_panel": "Technical Analysis Panel",
        "equity_research_team": "Equity Research Team",
        "custom": "自建角色",
    }
    roles = {
        role["ref"]: role
        for role in rcf.list_analyst_roles(None, entries, team_names=team_names)
    }
    assert (
        roles["technical_analysis_panel:chanlun_analyst"]["team"]
        == "Technical Analysis Panel"
    )
    assert roles["equity_research_team:stock_picker"]["team"] == "Equity Research Team"
    assert roles["my_fin_girl"]["team"] == "自建角色"


def test_team_names_default_without_map(entries: list[dict]) -> None:
    """Without a map, built-in roles fall back to the raw preset name and
    custom roles carry an empty team (L2 never imports swarm)."""
    roles = {
        role["ref"]: role for role in rcf.list_analyst_roles(None, entries)
    }
    assert (
        roles["technical_analysis_panel:chanlun_analyst"]["team"]
        == "technical_analysis_panel"
    )
    assert roles["my_generalist"]["team"] == ""


def test_real_shipped_catalog_flags_chanlun() -> None:
    """Integration against shipped preset YAMLs (no network)."""
    entries = list_approved_role_refs()
    technical = rcf.list_analyst_roles("technical", entries)
    chanlun = [r for r in technical if r["is_chanlun"]]
    assert len(chanlun) == 1
    assert chanlun[0]["ref"] == "technical_analysis_panel:chanlun_analyst"
    refs = {r["ref"] for r in technical}
    assert "technical_analysis_panel:classic_ta_analyst" in refs

    fundamental_refs = {
        r["ref"] for r in rcf.list_analyst_roles("fundamental", entries)
    }
    assert "equity_research_team:stock_picker" in fundamental_refs
