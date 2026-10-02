"""Deterministic 3-way classification of approved roles for analysis tabs.

The role catalog itself carries no category field, so the watchlist decides
"fundamental / technical / general" purely by fixed rules (no LLM, no
heuristic drift):

1. Built-in roles (``preset:agent`` refs) classify by their preset group.
2. Approved custom roles classify by CN/EN keywords in name + purpose.
3. Anything unmatched is ``general``.

The Chanlun analyst is additionally flagged so its finished reports can be
parsed into the fixed 7-dimension structure.

Layering: this module is L2 and must NOT import the L3 swarm package. The
approved catalog (``list_approved_role_refs()``) is fetched by the L4 route
layer and passed in as plain data.
"""

from __future__ import annotations

from typing import Any, Literal

Category = Literal["fundamental", "technical", "general"]
CATEGORIES: tuple[str, ...] = ("fundamental", "technical", "general")

#: Preset groups whose agents are deterministic technical/fundamental roles.
TECHNICAL_PRESETS = frozenset({"technical_analysis_panel"})
# ``earnings_research_team`` is an alias kept in case the preset is renamed
# back; the shipped preset is ``earnings_research_desk``.
FUNDAMENTAL_PRESETS = frozenset(
    {
        "fundamental_research_team",
        "earnings_research_team",
        "earnings_research_desk",
        "equity_research_team",
        "value_investing_committee",
    }
)

_TECHNICAL_KEYWORDS = (
    "技术", "缠论", "chanlun", "chan theory", "elliott", "波浪",
    "ichimoku", "smc", "k线", "k 线", "均线", "macd", "动量", "形态",
    "technical",
)
_FUNDAMENTAL_KEYWORDS = (
    "基本面", "财务", "财报", "盈利", "估值", "价值",
    "fundamental", "financial", "earnings", "value",
)

#: The single built-in Chanlun role (ref + exact normalized display name).
CHANLUN_ROLE_REF = "technical_analysis_panel:chanlun_analyst"
CHANLUN_ROLE_NAME = "chanlun (chan theory) analyst"


def _normalize_name(name: str) -> str:
    return " ".join(str(name or "").lower().split())


def is_chanlun_role(entry: dict[str, Any]) -> bool:
    """Whether a catalog entry is THE Chanlun analyst role."""
    ref = str(entry.get("ref") or "").strip()
    if ref == CHANLUN_ROLE_REF:
        return True
    return _normalize_name(str(entry.get("name") or "")) == CHANLUN_ROLE_NAME


def _classify_custom(entry: dict[str, Any]) -> str:
    haystack = _normalize_name(
        f"{entry.get('name', '')} {entry.get('purpose', '')}"
    )
    if any(keyword in haystack for keyword in _TECHNICAL_KEYWORDS):
        return "technical"
    if any(keyword in haystack for keyword in _FUNDAMENTAL_KEYWORDS):
        return "fundamental"
    return "general"


def classify_role(entry: dict[str, Any]) -> tuple[str, bool]:
    """Classify one catalog entry.

    Returns ``(category, is_chanlun)``. Category is one of
    fundamental/technical/general; built-in classification is by preset,
    custom roles fall back to keyword matching.
    """
    ref = str(entry.get("ref") or "").strip()
    chanlun = is_chanlun_role(entry)

    preset = ref.split(":", 1)[0] if ":" in ref else ""
    if preset:
        if preset in TECHNICAL_PRESETS:
            category = "technical"
        elif preset in FUNDAMENTAL_PRESETS:
            category = "fundamental"
        else:
            category = "general"
    else:
        category = _classify_custom(entry)
    return category, chanlun


def list_analyst_roles(
    category: str | None,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach ``category``/``is_chanlun`` to approved catalog entries.

    Args:
        category: Optional filter; must be one of the three categories.
        entries: The approved-role catalog as returned by
            ``src.swarm.role_catalog.list_approved_role_refs`` (fetched by
            the L4 caller). Only approved roles should be passed in.

    Returns:
        Sorted ``[{ref, name, purpose, category, is_chanlun}]`` list.
    """
    if category is not None and category not in CATEGORIES:
        raise ValueError(
            f"不支持的角色分类: {category!r}（可选 fundamental/technical/general）"
        )
    roles: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("ref"):
            continue
        resolved_category, is_chanlun = classify_role(entry)
        if category is not None and resolved_category != category:
            continue
        roles.append(
            {
                "ref": entry["ref"],
                "name": entry.get("name") or entry["ref"],
                "purpose": entry.get("purpose") or "",
                "category": resolved_category,
                "is_chanlun": is_chanlun,
            }
        )
    roles.sort(key=lambda role: role["name"])
    return roles


def get_analyst_role(
    role_ref: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find one approved role with classification, or ``None``."""
    for role in list_analyst_roles(None, entries):
        if role["ref"] == role_ref:
            return role
    return None
