"""Strict parser for the Chanlun analyst's section-8 machine-readable card.

The ``technical_analysis_panel:chanlun_analyst`` prompt mandates an eighth
output section: ``8. 操作结论卡 / Action Card`` whose body is exactly one
fenced ``json`` code block -- the investor-facing "what to do now" summary
(direction, action, trigger/stop/target prices, horizon, invalidation).

Parsing mirrors :mod:`src.scheduled_research.verdict` philosophy: strict on
purpose, with three explicit states:

* ``ok`` -- a structurally and semantically valid card;
* ``no_card`` -- the report carries no section 8 / no JSON block (older
  reports or a skipped card); callers archive the raw report without a
  card instead of guessing;
* ``contract_violation`` -- section 8 exists but the JSON is malformed or
  breaks a declared consistency rule. Surfaced as a quality signal, never
  "repaired" with fabricated numbers.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from typing import Any

#: Parse states persisted alongside the archived report.
PARSE_OK = "ok"
PARSE_NO_CARD = "no_card"
PARSE_CONTRACT_VIOLATION = "contract_violation"

DIRECTIONS = ("bullish", "bearish", "neutral")
ACTIONS = ("buy", "add", "hold", "reduce", "sell", "wait")
BUY_SETUPS = ("1买", "2买", "3买")
SELL_SETUPS = ("1卖", "2卖", "3卖")
SETUPS = BUY_SETUPS + SELL_SETUPS + ("none",)

BULLISH_ACTIONS = ("buy", "add", "hold", "wait")
BEARISH_ACTIONS = ("sell", "reduce", "hold", "wait")

#: Numbered section-8 heading, Arabic (8) or Chinese numeral (八), with an
#: optional markdown/quote prefix; title must mention the card.
_HEADING_RE = re.compile(
    r"^[\s>#]{0,6}\**\s*(8|八)\s*[.、)）：:．]\s*(.*?)\s*$"
)
_TITLE_KEYWORDS = ("操作结论卡", "结论卡", "action card", "action", "卡片")
_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

_MAX_TARGETS = 3
_MIN_HORIZON_DAYS = 1
_MAX_HORIZON_DAYS = 120
_MAX_TEXT_LEN = 400
_MAX_ONELINER_LEN = 120


class CardViolation(ValueError):
    """The card broke the published contract (malformed or inconsistent)."""


def _clean_title(line: str) -> str:
    return line.replace("*", "").replace("#", "").strip().lower()


def _find_section_body(text: str) -> str | None:
    """Return the text after the section-8 heading, or None when absent."""
    lines = text.splitlines()
    for idx, raw_line in enumerate(lines):
        match = _HEADING_RE.match(raw_line)
        if match is None:
            continue
        title = _clean_title(match.group(2))
        if not any(keyword in title for keyword in _TITLE_KEYWORDS):
            continue
        return "\n".join(lines[idx + 1 :])
    return None


def _extract_json(section_body: str) -> dict[str, Any] | None:
    """Pull the first fenced JSON object out of the section body.

    Returns the decoded dict, ``None`` when the section has no fenced
    block, and raises :class:`CardViolation` when the fence is present but
    cannot be decoded into a JSON object.
    """
    fenced: list[str] = _FENCE_RE.findall(section_body)
    if not fenced:
        return None
    # The first fence is the card; extra fences (e.g. quoted examples)
    # never override it.
    raw = fenced[0].strip()
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise CardViolation(f"invalid json: {exc.msg}") from exc
    if not isinstance(decoded, dict):
        raise CardViolation("card json must be an object")
    return decoded


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _finite_positive(value: Any, field: str) -> float:
    if not _is_number(value) or not math.isfinite(float(value)) or float(value) <= 0:
        raise CardViolation(f"{field} must be a positive number")
    return float(value)


def _optional_price(value: Any, field: str) -> float | None:
    if value is None:
        return None
    return _finite_positive(value, field)


def _base_date(value: Any) -> str:
    if not isinstance(value, str):
        raise CardViolation("base_date must be YYYY-MM-DD string")
    match = _DATE_RE.match(value.strip())
    if match is None:
        raise CardViolation("base_date must be YYYY-MM-DD")
    try:
        date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError as exc:
        raise CardViolation("base_date is not a real calendar date") from exc
    return value.strip()


def _enum(value: Any, field: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise CardViolation(f"{field} must be one of {','.join(allowed)}")
    return value


def _text(value: Any, field: str, *, max_len: int, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise CardViolation(f"{field} must be a string")
    cleaned = value.strip()
    if not allow_empty and not cleaned:
        raise CardViolation(f"{field} must not be empty")
    if len(cleaned) > max_len:
        raise CardViolation(f"{field} exceeds {max_len} chars")
    return cleaned


def _targets(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_TARGETS:
        raise CardViolation(f"target_prices must be 1-{_MAX_TARGETS} prices or null")
    # Ordering is direction-dependent (longs ascend, shorts descend) and
    # therefore checked in _validate alongside the other cross-field rules.
    return [_finite_positive(item, "target_prices") for item in value]


def _horizon(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CardViolation("horizon_days must be an integer")
    if not _MIN_HORIZON_DAYS <= value <= _MAX_HORIZON_DAYS:
        raise CardViolation(
            f"horizon_days must be within {_MIN_HORIZON_DAYS}-{_MAX_HORIZON_DAYS}"
        )
    return value


def _validate(data: dict[str, Any]) -> dict[str, Any]:
    """Validate raw decoded JSON into the normalized card row."""
    raw_version = data.get("schema_version", 1)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise CardViolation("schema_version must be integer 1")

    card: dict[str, Any] = {
        "schema_version": raw_version,
        "base_price": _finite_positive(data.get("base_price"), "base_price"),
        "base_date": _base_date(data.get("base_date")),
        "direction": _enum(data.get("direction"), "direction", DIRECTIONS),
        "action": _enum(data.get("action"), "action", ACTIONS),
        "setup_class": _enum(
            str(data.get("setup_class", "")).strip(), "setup_class", SETUPS
        ),
        "horizon_days": _horizon(data.get("horizon_days")),
        "trigger_price": _optional_price(data.get("trigger_price"), "trigger_price"),
        "stop_price": _optional_price(data.get("stop_price"), "stop_price"),
        "target_prices": _targets(data.get("target_prices")),
        "rr_at_t1": None,
        "invalidation": _text(
            data.get("invalidation", ""), "invalidation",
            max_len=_MAX_TEXT_LEN, allow_empty=False,
        ),
        "key_risks": _text(
            data.get("key_risks", ""), "key_risks",
            max_len=_MAX_TEXT_LEN, allow_empty=True,
        ),
        "one_liner": _text(
            data.get("one_liner", ""), "one_liner",
            max_len=_MAX_ONELINER_LEN, allow_empty=False,
        ),
    }
    rr = data.get("rr_at_t1")
    if rr is not None:
        if not _is_number(rr) or not math.isfinite(float(rr)) or float(rr) < 0:
            raise CardViolation("rr_at_t1 must be a non-negative number or null")
        card["rr_at_t1"] = round(float(rr), 2)

    confidence = data.get("confidence_pct")
    if not _is_number(confidence) or not 0 <= float(confidence) <= 100:
        raise CardViolation("confidence_pct must be within 0-100")
    card["confidence_pct"] = float(confidence)

    if card["schema_version"] != 1:
        raise CardViolation("unsupported schema_version")

    direction = card["direction"]
    action = card["action"]
    setup = card["setup_class"]
    trigger = card["trigger_price"]
    stop = card["stop_price"]
    targets = card["target_prices"]

    if direction == "neutral" or action == "wait":
        if any(value is not None for value in (trigger, stop, targets)):
            raise CardViolation(
                "neutral/wait card must set trigger/stop/targets to null"
            )
        if card["rr_at_t1"] is not None:
            raise CardViolation("neutral/wait card must set rr_at_t1 to null")
        if setup != "none":
            raise CardViolation("neutral/wait card must use setup_class none")
        return card

    if direction == "bullish":
        if action not in BULLISH_ACTIONS:
            raise CardViolation("bullish direction cannot use a sell-side action")
        if setup not in BUY_SETUPS + ("none",):
            raise CardViolation("bullish card cannot use a sell-point setup")
    else:  # bearish
        if action not in BEARISH_ACTIONS:
            raise CardViolation("bearish direction cannot use a buy-side action")
        if setup not in SELL_SETUPS + ("none",):
            raise CardViolation("bearish card cannot use a buy-point setup")

    # hold is allowed with no concrete plan yet; once prices are given the
    # trigger must exist and every level must be internally consistent.
    has_plan = any(value is not None for value in (trigger, stop, targets))
    if has_plan:
        if trigger is None:
            raise CardViolation("priced card needs a trigger_price")
        if stop is None:
            raise CardViolation("priced card needs a stop_price")
        if direction == "bullish":
            if not stop < trigger:
                raise CardViolation("long stop must be below trigger")
            if targets and not all(t > trigger for t in targets):
                raise CardViolation("long targets must be above trigger")
            if targets and any(b <= a for a, b in zip(targets, targets[1:])):
                raise CardViolation("long targets must be strictly ascending")
        else:
            if not stop > trigger:
                raise CardViolation("short stop must be above trigger")
            if targets and not all(t < trigger for t in targets):
                raise CardViolation("short targets must be below trigger")
            if targets and any(b >= a for a, b in zip(targets, targets[1:])):
                raise CardViolation("short targets must be strictly descending")
    return card


def parse_action_card(report: str) -> dict[str, Any]:
    """Parse the section-8 action card from a finished Chanlun report.

    Returns ``{"parse": ok|no_card|contract_violation, "card": dict|None,
    "error": str|None}``. The ``no_card`` state is permanent for reports
    produced before the contract existed and never raises; malformed cards
    degrade to ``contract_violation`` so the UI can flag (not fabricate)
    them.
    """
    if not report or not report.strip():
        return {"parse": PARSE_NO_CARD, "card": None, "error": None}
    body = _find_section_body(report)
    if body is None:
        return {"parse": PARSE_NO_CARD, "card": None, "error": None}
    try:
        decoded = _extract_json(body)
        if decoded is None:
            # Section 8 exists but the model wrote prose instead of JSON.
            return {
                "parse": PARSE_CONTRACT_VIOLATION,
                "card": None,
                "error": "section 8 has no fenced json block",
            }
        return {"parse": PARSE_OK, "card": _validate(decoded), "error": None}
    except CardViolation as exc:
        return {"parse": PARSE_CONTRACT_VIOLATION, "card": None, "error": str(exc)}
