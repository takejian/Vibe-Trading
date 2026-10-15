"""Structural validation of archived Task Force reports.

Both report modes have a fixed section contract (see the PRD). Archiving
checks heading presence only — a cheap, deterministic guard that surfaces
"incomplete" runs instead of silently filing a truncated report. The
retrospective contract additionally requires the missed-opportunities
section and the reusable signal checklist.
"""

from __future__ import annotations

import re

#: section key -> accepted heading keywords (Chinese + English)
LIVE_SECTIONS: dict[str, tuple[str, ...]] = {
    "definition": ("事件确认", "事件定义", "event definition", "fact"),
    "scenarios": ("情景", "scenario"),
    "transmission": ("传导", "transmission", "second-order"),
    "impact_matrix": ("影响矩阵", "impact matrix", "跨资产"),
    "targets": ("受益", "受损", "板块", "target", "sector"),
    "catalyst_calendar": ("催化", "日历", "跟踪指标", "catalyst", "calendar",
                          "leading indicator"),
    "devils_advocate": ("反方", "证伪", "devil", "contrarian"),
}

RETRO_SECTIONS: dict[str, tuple[str, ...]] = {
    "timeline": ("时间线", "分期", "timeline", "phases"),
    "early_signals": ("早期信号", "关键信号", "early signal", "precursor"),
    "performance": ("真实表现", "资产表现", "走势", "performance", "actual return"),
    "transmission_review": ("传导链回顾", "传导回顾", "transmission"),
    "missed_opportunities": ("没抓住", "错过", "机会清单", "missed", "opportunit"),
    "signal_checklist": ("checklist", "信号清单", "观察清单", "early warning"),
    "replay_playbook": ("若重演", "应对预案", "replay", "playbook", "contingency"),
}

_HEADING_RE = re.compile(r"^#{1,4}\s+(.+)$", re.MULTILINE)


def present_sections(markdown: str, mode: str) -> list[str]:
    """Return the list of contract section keys present in the markdown."""
    contract = RETRO_SECTIONS if mode == "retrospective" else LIVE_SECTIONS
    headings = [
        match.group(1).strip().lower()
        for match in _HEADING_RE.finditer(markdown or "")
    ]
    present: list[str] = []
    for key, keywords in contract.items():
        if any(any(kw in heading for kw in keywords) for heading in headings):
            present.append(key)
    return present


def validate_report(markdown: str, mode: str) -> tuple[bool, list[str]]:
    """Return ``(complete, present_keys)`` against the mode's contract."""
    contract = RETRO_SECTIONS if mode == "retrospective" else LIVE_SECTIONS
    found = present_sections(markdown, mode)
    return len(found) == len(contract), found
