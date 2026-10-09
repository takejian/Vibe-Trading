"""Pure parser for the Chanlun analyst's fixed 7-section report.

The ``technical_analysis_panel:chanlun_analyst`` prompt mandates exactly
seven numbered output sections (CN/EN bilingual in practice) ending with an
integer score in [-5, +5] and a structural confidence in 0-100%.

Parsing is deliberately strict: anything short of seven recognizable
sections, an out-of-range/missing score, or a missing/out-of-range
confidence returns ``None`` so the caller can archive the raw report with
``structured=false`` instead of fabricating dimensions.
"""

from __future__ import annotations

import re

#: Dimension key by section number (order is fixed, never reorder).
DIMENSION_KEYS: tuple[str, ...] = (
    "structure_read",       # 1 结构读取 / Structure read
    "active_pivots",        # 2 活跃支点 / Active pivots
    "divergence",           # 3 背驰 / Divergence
    "buy_sell_points",      # 4 买卖点 / Buy/sell points
    "multi_level_plan",     # 5 多级别计划 / Multi-level plan
    "elliott_corroboration",  # 6 艾略特验证 / Elliott corroboration
    "chanlun_score",        # 7 缠论打分 / Chanlun score
)

#: Title keywords (lowercase) accepted for each section, CN then EN.
_SECTION_KEYWORDS: tuple[tuple[str, ...], ...] = (
    ("结构", "structure"),
    ("支点", "中枢", "pivot", "zhongshu"),
    ("背驰", "divergence"),
    ("买卖", "buy", "sell"),
    ("多级别", "multi-level", "multi level", "multilevel", "plan"),
    ("艾略特", "elliott"),
    ("打分", "评分", "score"),
)

# A numbered heading line: optional quote/markdown prefix, the number
# (Arabic 1-7 or Chinese numeral 一..七), a separator, then title text.
_CN_NUMERALS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}
_HEADING_RE = re.compile(
    r"^[\s>#]{0,6}\**\s*([1-7]|[一二三四五六七])\s*[.、)）：:．]\s*(.*?)\s*$"
)

# Section 8 (the machine-readable Action Card) terminates the section-7
# body so the card's JSON numbers can never be mistaken for the score or
# confidence by the regexes below.
_SECTION8_STOP_RE = re.compile(
    r"^[\s>#]{0,6}\**\s*(8|八)\s*[.、)）：:．]\s*(.*?)\s*$"
)
_SECTION8_KEYWORDS = ("操作结论卡", "结论卡", "action", "卡片")

_SCORE_RE = re.compile(
    r"(?:缠论打分|缠论评分|打分|评分|chanlun\s*score|score)\s*[:：=]\s*"
    r"([+-−]?\d)(?:\s*/\s*5)?(?![\d.])",
    re.IGNORECASE,
)
_CONFIDENCE_PCT_RE = re.compile(
    r"(?:结构置信度|置信度|structural\s+confidence|confidence)"
    r"[^0-9%\n]{0,12}?(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
_CONFIDENCE_FRACTION_RE = re.compile(
    r"(?:结构置信度|置信度|structural\s+confidence|confidence)"
    r"\s*[:：=]\s*(0(?:\.\d+)?|1(?:\.0+)?)(?![\d.])",
    re.IGNORECASE,
)


def _clean_title(line: str) -> str:
    return line.replace("*", "").replace("#", "").strip().lower()


def _split_sections(text: str) -> list[str] | None:
    """Split report text into exactly 7 ordered section bodies, or None."""
    expected = 1
    starts: list[tuple[int, int, str]] = []  # (section_no, line_index, title)
    lines = text.splitlines()
    for idx, raw_line in enumerate(lines):
        match = _HEADING_RE.match(raw_line)
        if match is None:
            continue
        number = _CN_NUMERALS.get(match.group(1))
        if number is None:
            number = int(match.group(1))
        title = _clean_title(match.group(2))
        if number != expected:
            continue
        keywords = _SECTION_KEYWORDS[number - 1]
        if not any(keyword in title for keyword in keywords):
            continue
        starts.append((number, idx, title))
        expected += 1
        if expected > 7:
            break

    if expected <= 7:
        return None

    bodies: list[str] = []
    for pos, (number, line_idx, _title) in enumerate(starts):
        end = starts[pos + 1][1] if pos + 1 < len(starts) else len(lines)
        if pos + 1 == len(starts):
            # Stop section 7 at an optional section-8 Action Card heading.
            for tail_idx in range(line_idx + 1, end):
                stop_match = _SECTION8_STOP_RE.match(lines[tail_idx])
                if stop_match is not None and any(
                    keyword in _clean_title(stop_match.group(2))
                    for keyword in _SECTION8_KEYWORDS
                ):
                    end = tail_idx
                    break
        body = "\n".join(lines[line_idx + 1 : end]).strip()
        bodies.append(body)
    # Sections 1-6 must carry content; section 7 may be short but non-empty.
    if any(not body for body in bodies):
        return None
    return bodies


def _extract_score(section7: str) -> int | None:
    normalized = section7.replace("−", "-").replace("－", "-")
    matches = _SCORE_RE.findall(normalized)
    if not matches:
        return None
    raw = matches[-1].replace("+", "")
    try:
        score = int(raw)
    except ValueError:
        return None
    return score if -5 <= score <= 5 else None


def _extract_confidence(section7: str) -> float | None:
    pct_matches = _CONFIDENCE_PCT_RE.findall(section7)
    if pct_matches:
        try:
            value = float(pct_matches[-1])
        except ValueError:
            return None
        return value / 100.0 if 0 <= value <= 100 else None
    frac_matches = _CONFIDENCE_FRACTION_RE.findall(section7)
    if frac_matches:
        try:
            value = float(frac_matches[-1])
        except ValueError:
            return None
        return value if 0 <= value <= 1 else None
    return None


def parse_chanlun_report(text: str) -> dict | None:
    """Parse a finished Chanlun report into structured fields.

    Returns ``{"dims": {<7 keys>}, "score": int, "confidence": float}`` or
    ``None`` when the report is not a valid 7-section structure.
    """
    if not text or not text.strip():
        return None
    bodies = _split_sections(text)
    if bodies is None:
        return None

    score = _extract_score(bodies[6])
    confidence = _extract_confidence(bodies[6])
    if score is None or confidence is None:
        return None

    dims = {key: body for key, body in zip(DIMENSION_KEYS, bodies)}
    return {"dims": dims, "score": score, "confidence": confidence}
