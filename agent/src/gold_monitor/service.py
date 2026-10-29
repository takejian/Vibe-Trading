"""Business logic for the gold monitor module."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from src.gold_monitor import db
from src.gold_monitor.db import gold_connection, initialize_schema
from src.gold_monitor.exceptions import (
    GoldCycleDetectError,
    GoldDataError,
    GoldLLMError,
    GoldValidationError,
)
from src.gold_monitor.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)

#: Thresholds for cycle auto-detection (R4 in BDD).
_FFR_CHANGE_THRESHOLD = 0.05  # pct points
_MIN_SEQUENCE_MONTHS = 2       # consecutive months required

# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------

def get_current_status() -> dict[str, Any]:
    """Return the latest month's indicators + the matching policy cycle + 12-month series."""
    with gold_connection() as conn:
        initialize_schema(conn)
        latest = db.get_latest_monthly(conn)
        if latest is None:
            raise GoldDataError("No monthly data available. Import Excel history first.")
        recent = db.get_recent_monthly(conn, limit=12)
        cycle = db.get_active_cycle_for_month(conn, latest["month"])

    # Build sparkline series for each indicator
    def _series(field: str) -> list[dict[str, Any]]:
        return [{"month": m["month"], "value": m.get(field)} for m in recent]

    return {
        "latest_month": latest["month"],
        "updated_at": str(latest["updated_at"]),
        "source": latest["source"],
        "cycle": {
            "name": cycle["cycle_name"] if cycle else None,
            "start_month": cycle["start_month"] if cycle else None,
            "end_month": cycle["end_month"] if cycle else None,
            "cycle_type": cycle["cycle_type"] if cycle else None,
            "status": cycle["status"] if cycle else None,
        },
        "indicators": {
            "gold_price":      {"current": latest.get("gold_price"),      "series": _series("gold_price")},
            "ffr":             {"current": latest.get("ffr"),             "series": _series("ffr")},
            "yield_nominal":   {"current": latest.get("yield_nominal"),   "series": _series("yield_nominal")},
            "bei":             {"current": latest.get("bei"),             "series": _series("bei")},
            "tips_real":       {"current": latest.get("tips_real"),       "series": _series("tips_real")},
            "gold_change_pct": {"current": latest.get("gold_change_pct"), "series": _series("gold_change_pct")},
            "ffr_change":      {"current": latest.get("ffr_change"),      "series": _series("ffr_change")},
            "real_change":     {"current": latest.get("real_change"),     "series": _series("real_change")},
        },
        "tips_available": _tips_available_for_month(latest["month"]),
    }


def list_cycles() -> list[dict[str, Any]]:
    """Return all policy cycles (active first, then by start_month desc)."""
    with gold_connection() as conn:
        initialize_schema(conn)
        cycles = db.get_all_cycles(conn)
    return cycles


def get_cycle_months(cycle_id: int) -> dict[str, Any]:
    """Return a single cycle's metadata plus all monthly rows within its window."""
    with gold_connection() as conn:
        initialize_schema(conn)
        cycle = db.get_cycle_by_id(conn, cycle_id)
        if cycle is None:
            raise GoldDataError(f"Cycle {cycle_id} not found.")
        start = cycle["start_month"]
        end = cycle["end_month"] or "9999-12"
        months = db.get_monthly_range(conn, start, end)
    return {"cycle": cycle, "months": months, "tips_available_from": "2003-01"}


def trigger_refresh(source: str = "manual") -> dict[str, Any]:
    """Refresh the latest month via LLM. Returns diff summary + pending flags.

    - ``source="manual"``: target = current month (try fetching the in-progress
      month; if not yet official, keep last month's snapshot).
    - ``source="scheduler"``: target = previous month (run on the 1st).
    """
    today = date.today()
    if source == "scheduler":
        target_month = _previous_month_str(today)
    else:
        target_month = _current_month_str(today)

    try:
        llm_data = _fetch_via_llm(target_month)
    except GoldLLMError as exc:
        with gold_connection() as conn:
            initialize_schema(conn)
            db.log_refresh(conn, target_month, "failed", False, source,
                           error_msg=str(exc))
        raise

    if llm_data.get("not_published"):
        # Month not yet official — no-op, keep existing
        with gold_connection() as conn:
            initialize_schema(conn)
            db.log_refresh(conn, target_month, "not_published", True, source)
        return {
            "status": "not_published",
            "target_month": target_month,
            "message": "数据尚未发布，将保留上月快照",
        }

    # Validate + compute derived fields
    validated = _validate_and_compute(target_month, llm_data)

    # Diff against existing record
    with gold_connection() as conn:
        initialize_schema(conn)
        existing = db.get_monthly_by_month(conn, target_month)
        diff = _compute_diff(existing, validated)

        if diff["has_diff"]:
            # Do NOT auto-write — return diff for user confirmation
            db.log_refresh(
                conn, target_month, "pending_diff", True, source,
                diff_summary=_format_diff_summary(diff),
            )
            return {
                "status": "pending_diff",
                "target_month": target_month,
                "diff": diff,
                "new_values": validated,
                "message": "检测到数据差异，请确认是否覆盖",
            }

        # No diff or new month — write directly
        inserted = db.insert_or_update_monthly(conn, target_month, **validated, source=source)
        db.log_refresh(conn, target_month, "insert" if inserted else "update", True, source)
        # Auto-detect cycle
        pending_cycle = _auto_detect_cycle(conn)
        conn.commit()

    return {
        "status": "inserted" if inserted else "updated",
        "target_month": target_month,
        "auto_cycle": pending_cycle,
        "message": "刷新成功",
    }


def confirm_diff(target_month: str, accept_fields: list[str] | None = None) -> dict[str, Any]:
    """Apply previously-fetched LLM values to the monthly table after user confirmation.

    This requires a two-step contract: trigger_refresh fetches and caches in
    memory-less mode, then confirm_diff writes. Since our REST endpoint is
    stateless, we use a simpler approach: re-run the LLM fetch and write
    atomically here (same month, same data).
    """
    llm_data = _fetch_via_llm(target_month)
    validated = _validate_and_compute(target_month, llm_data)

    with gold_connection() as conn:
        initialize_schema(conn)
        db.insert_or_update_monthly(conn, target_month, **validated, source="llm-confirmed")
        db.log_refresh(conn, target_month, "confirmed_update", True, "manual")
        pending_cycle = _auto_detect_cycle(conn)
        conn.commit()

    return {"target_month": target_month, "auto_cycle": pending_cycle}


def approve_cycle(cycle_id: int) -> dict[str, Any]:
    """Promote a pending_review cycle to active."""
    with gold_connection() as conn:
        initialize_schema(conn)
        cycle = db.get_cycle_by_id(conn, cycle_id)
        if cycle is None:
            raise GoldDataError(f"Cycle {cycle_id} not found.")
        if cycle["status"] != "pending_review":
            raise GoldDataError(f"Cycle {cycle_id} is not pending review (status={cycle['status']}).")
        db.close_active_cycle(conn, _previous_month_str(date.today()))
        db.approve_cycle(conn, cycle_id)
        conn.commit()
    return {"cycle_id": cycle_id, "status": "active"}


def check_refresh_needed() -> dict[str, Any]:
    """Check whether the last-completed month needs a refresh (scheduler may have failed)."""
    with gold_connection() as conn:
        initialize_schema(conn)
        latest = db.get_latest_monthly(conn)
    if latest is None:
        return {"needed": True, "reason": "no_data"}

    target = _previous_month_str(date.today())
    if latest["month"] < target:
        return {
            "needed": True,
            "reason": "missing_last_month",
            "latest": latest["month"],
            "target": target,
        }
    return {"needed": False, "latest": latest["month"]}


def import_excel(excel_path: str) -> dict[str, Any]:
    """Import historical Excel data into the DuckDB tables."""
    with gold_connection() as conn:
        initialize_schema(conn)
        result = db.import_excel_history(conn, excel_path)
        conn.commit()
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_via_llm(target_month: str) -> dict[str, Any]:
    """Call the LLM and return parsed JSON data for the target month."""
    from src.providers.chat import ChatLLM

    user_prompt = USER_PROMPT_TEMPLATE.format(month=target_month)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    try:
        llm = ChatLLM()
        response = llm.chat(messages, timeout=30)
        content = getattr(response, "content", str(response))
    except Exception as exc:
        raise GoldLLMError(f"LLM call failed: {exc}") from exc

    # Extract JSON from response (may be wrapped in markdown)
    json_str = _extract_json(content)
    if not json_str:
        raise GoldLLMError(f"LLM returned non-JSON: {content[:200]}")
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise GoldLLMError(f"LLM JSON parse failed: {exc}") from exc

    if data.get("not_published"):
        return data
    # Require at least gold_price or ffr to consider the response complete
    if data.get("gold_price") is None and data.get("ffr") is None:
        raise GoldLLMError("LLM returned all-null values — month may truly be unavailable.")
    return data


def _extract_json(text: str) -> str | None:
    """Best-effort extraction of a JSON object/array from a possibly-markdown response."""
    text = text.strip()
    # Direct JSON object or array
    if text.startswith("{") or text.startswith("["):
        return text
    # Fenced code block
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("{") or block.startswith("["):
                return block
            # Strip possible language tag like "json\n"
            if "\n" in block:
                block = block.split("\n", 1)[1]
                if block.startswith("{") or block.startswith("["):
                    return block
    return None


def _validate_and_compute(month: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM JSON output + compute derived metrics (tips_real from BEI)."""
    gold_price = _num_or_none(raw.get("gold_price"))
    ffr = _num_or_none(raw.get("ffr"))
    yield_nominal = _num_or_none(raw.get("yield_nominal"))
    bei = _num_or_none(raw.get("bei"))
    tips_real = _num_or_none(raw.get("tips_real"))

    # Compute tips_real = yield_nominal - bei if bei available
    if tips_real is None and yield_nominal is not None and bei is not None:
        tips_real = round(yield_nominal - bei, 4)

    return {
        "gold_price": gold_price,
        "ffr": ffr,
        "yield_nominal": yield_nominal,
        "bei": bei,
        "tips_real": tips_real,
    }


def _compute_diff(
    existing: dict[str, Any] | None, new: dict[str, Any]
) -> dict[str, Any]:
    """Compare an existing monthly row against new LLM values."""
    fields = ["gold_price", "ffr", "yield_nominal", "bei", "tips_real"]
    per_field: dict[str, dict[str, Any]] = {}
    has_diff = False
    for f in fields:
        old_val = existing.get(f) if existing else None
        new_val = new.get(f)
        diff = _values_differ(old_val, new_val)
        if diff:
            has_diff = True
        per_field[f] = {"old": old_val, "new": new_val, "diff": diff}
    return {"has_diff": has_diff, "fields": per_field}


def _values_differ(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    return abs(float(a) - float(b)) > 1e-6


def _format_diff_summary(diff: dict[str, Any]) -> str:
    parts = []
    for fname, info in diff["fields"].items():
        if info["diff"]:
            parts.append(f"{fname}: {info['old']} -> {info['new']}")
    return "; ".join(parts)[:500]


def _auto_detect_cycle(conn: Any) -> dict[str, Any] | None:
    """Apply R4 to the most recent FFR data. Returns a pending_cycle dict or None."""
    months = db.get_all_monthly(conn)
    if len(months) < 3:
        return None

    # Build ffr_change sequence
    ffr_seq: list[tuple[str, float]] = []
    for i in range(1, len(months)):
        prev_ffr = months[i - 1].get("ffr")
        cur_ffr = months[i].get("ffr")
        if prev_ffr is not None and cur_ffr is not None:
            ffr_seq.append((months[i]["month"], cur_ffr - prev_ffr))

    if len(ffr_seq) < 3:
        return None

    # Get current cycle type (latest active)
    last_cycle = db.get_last_cycle(conn)
    current_type = last_cycle["cycle_type"] if last_cycle else "unknown"

    # Check recent 2 months for a consistent direction
    recent_2 = ffr_seq[-2:]
    all_positive = all(d > _FFR_CHANGE_THRESHOLD for _, d in recent_2)
    all_negative = all(d < -_FFR_CHANGE_THRESHOLD for _, d in recent_2)
    all_plateau = all(abs(d) <= _FFR_CHANGE_THRESHOLD for _, d in recent_2)

    new_type: str | None = None
    if all_positive and current_type != "hiking":
        new_type = "hiking"
    elif all_negative and current_type != "cutting":
        new_type = "cutting"
    elif all_plateau and current_type not in ("plateau", "unknown"):
        new_type = "plateau"

    if new_type is None:
        return None

    # Find the start month = the month where direction first began
    start_month = recent_2[0][0]

    # Cycle name (CN)
    cn_type = {"hiking": "加息周期", "cutting": "降息周期", "plateau": "利率平台"}[new_type]
    cycle_name = f"{start_month}~至今 {cn_type}"

    # Close previous active cycle
    db.close_active_cycle(conn, _previous_month_str(date.today()))

    # Get gold prices for start/end
    gold_start = None
    gold_end = None
    start_row = db.get_monthly_by_month(conn, start_month)
    if start_row:
        gold_start = start_row.get("gold_price")
    latest_row = db.get_latest_monthly(conn)
    if latest_row:
        gold_end = latest_row.get("gold_price")

    cycle_id = db.insert_cycle(
        conn,
        cycle_name=cycle_name,
        start_month=start_month,
        end_month=None,
        cycle_type=new_type,
        source="auto",
        status="pending_review",
        gold_start=gold_start,
        gold_end=gold_end,
        gold_change_pct=_pct_change(gold_start, gold_end),
    )
    logger.info(
        "Auto-detected new policy cycle: id=%d type=%s start=%s (ffr_change recent=%s)",
        cycle_id, new_type, start_month, recent_2,
    )
    return {"cycle_id": cycle_id, "cycle_type": new_type, "start_month": start_month,
            "cycle_name": cycle_name}


def _tips_available_for_month(month: str) -> bool:
    """TIPS data only exists from 2003-01 onward."""
    return month >= "2003-01"


def _current_month_str(today: date) -> str:
    return f"{today.year:04d}-{today.month:02d}"


def _previous_month_str(today: date) -> str:
    year = today.year
    month = today.month - 1
    if month == 0:
        month = 12
        year -= 1
    return f"{year:04d}-{month:02d}"


def _num_or_none(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _pct_change(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start == 0:
        return None
    return round((end - start) / start * 100, 2)


# ---------------------------------------------------------------------------
# V2: Policy-cycle rate trend chart
# ---------------------------------------------------------------------------

#: The 5 indicator keys for LLM-driven gold analysis.
INDICATOR_KEYS = ["ffr_drivers", "bei_drivers", "usd_fx", "tail_risk", "physical_flow"]


def get_cycle_trend() -> dict[str, Any]:
    """Return FFR / 10Y nominal / 10Y real monthly series for the active cycle."""
    with gold_connection() as conn:
        initialize_schema(conn)
        latest = db.get_latest_monthly(conn)
        if latest is None:
            raise GoldDataError("No monthly data available.")
        cycle = db.get_active_cycle_for_month(conn, latest["month"])
        start = cycle["start_month"] if cycle else latest["month"]
        end = latest["month"]
        months = db.get_monthly_range(conn, start, end)
    return {
        "cycle_name": cycle["cycle_name"] if cycle else None,
        "start_month": start,
        "end_month": end,
        "months": [
            {
                "month": m["month"],
                "gold_price": m.get("gold_price"),
                "ffr": m.get("ffr"),
                "yield_nominal": m.get("yield_nominal"),
                "tips_real": m.get("tips_real"),
            }
            for m in months
        ],
    }


# ---------------------------------------------------------------------------
# V2: Indicator signal analysis (LLM)
# ---------------------------------------------------------------------------

def _call_llm_for_signal(indicator_key: str) -> dict[str, Any]:
    """Call LLM with the indicator's stored prompt, return parsed JSON."""
    from src.providers.chat import ChatLLM

    with gold_connection() as conn:
        initialize_schema(conn)
        prompt = db.get_prompt(conn, indicator_key)
    if prompt is None:
        raise GoldDataError(f"No prompt configured for indicator '{indicator_key}'.")

    messages = [
        {"role": "system", "content": prompt["system_prompt"]},
        {"role": "user", "content": prompt["user_prompt"]},
    ]
    try:
        llm = ChatLLM()
        response = llm.chat(messages, timeout=60)
        content = getattr(response, "content", str(response))
    except Exception as exc:
        raise GoldLLMError(f"LLM call failed for {indicator_key}: {exc}") from exc

    json_str = _extract_json(content)
    if not json_str:
        raise GoldLLMError(f"LLM returned non-JSON for {indicator_key}: {content[:200]}")
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise GoldLLMError(f"LLM JSON parse failed for {indicator_key}: {exc}") from exc

    judgment = str(data.get("judgment", "neutral")).lower()
    if judgment not in ("bullish", "bearish", "neutral"):
        judgment = "neutral"
    confidence = data.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
        if confidence is not None:
            confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = None

    return {
        "judgment": judgment,
        "confidence": confidence,
        "summary": str(data.get("summary", ""))[:1024],
        "details": json.dumps(data, ensure_ascii=False)[:8000],
    }


def refresh_signal(indicator_key: str, source: str = "manual") -> dict[str, Any]:
    """Run LLM analysis for a single indicator and persist the result."""
    if indicator_key not in INDICATOR_KEYS:
        raise GoldDataError(f"Unknown indicator key: {indicator_key}")

    result = _call_llm_for_signal(indicator_key)
    with gold_connection() as conn:
        initialize_schema(conn)
        # Link the signal to the currently active policy cycle (if any).
        latest = db.get_latest_monthly(conn)
        cycle_id = None
        if latest is not None:
            cycle = db.get_active_cycle_for_month(conn, latest["month"])
            if cycle is not None:
                cycle_id = cycle["cycle_id"]
        signal_id = db.insert_signal(
            conn,
            indicator_key=indicator_key,
            judgment=result["judgment"],
            confidence=result["confidence"],
            summary=result["summary"],
            details=result["details"],
            source=source,
            cycle_id=cycle_id,
        )
        conn.commit()
    return {"signal_id": signal_id, **result}


def refresh_all_signals(source: str = "scheduled") -> dict[str, Any]:
    """Run LLM analysis for all 5 indicators. Failures are isolated."""
    results: dict[str, Any] = {}
    for key in INDICATOR_KEYS:
        try:
            results[key] = refresh_signal(key, source=source)
        except Exception as exc:
            logger.warning("Signal refresh failed for %s: %s", key, exc)
            results[key] = {"error": str(exc)}
    return {"results": results}


def get_all_signals() -> dict[str, Any]:
    """Return the latest signal for each of the 5 indicators."""
    with gold_connection() as conn:
        initialize_schema(conn)
        latest = db.get_all_latest_signals(conn)
    by_key: dict[str, Any] = {}
    for row in latest:
        by_key[row["indicator_key"]] = row
    # Ensure all 5 keys are present (null if no record yet)
    items = []
    for key in INDICATOR_KEYS:
        items.append({"indicator_key": key, "signal": by_key.get(key)})
    return {"items": items}


def get_signal_history(indicator_key: str, limit: int = 20) -> dict[str, Any]:
    if indicator_key not in INDICATOR_KEYS:
        raise GoldDataError(f"Unknown indicator key: {indicator_key}")
    with gold_connection() as conn:
        initialize_schema(conn)
        rows = db.get_signal_history(conn, indicator_key, limit=limit)
    return {"items": rows}


def update_signal_confidence(signal_id: str, confidence: float) -> dict[str, Any]:
    if not 0 <= confidence <= 1:
        raise GoldValidationError("confidence must be between 0 and 1.")
    with gold_connection() as conn:
        initialize_schema(conn)
        db.update_signal_confidence(conn, signal_id, confidence)
        conn.commit()
    return {"signal_id": signal_id, "confidence": confidence}


def get_cycle_signals(cycle_id: int) -> dict[str, Any]:
    """Return the latest signal per indicator linked to the given cycle."""
    with gold_connection() as conn:
        initialize_schema(conn)
        cycle = db.get_cycle_by_id(conn, cycle_id)
        if cycle is None:
            raise GoldDataError(f"Cycle {cycle_id} not found.")
        rows = db.get_latest_signals_for_cycle(conn, cycle_id)
    by_key: dict[str, Any] = {}
    for row in rows:
        by_key[row["indicator_key"]] = row
    items = []
    for key in INDICATOR_KEYS:
        items.append({"indicator_key": key, "signal": by_key.get(key)})
    return {"cycle_id": cycle_id, "cycle_name": cycle.get("cycle_name"), "items": items}


def update_cycle_post_hoc_confidence(cycle_id: int, confidence: float | None) -> dict[str, Any]:
    """Set the user's post-hoc confidence judgment for a historical cycle."""
    if confidence is not None and not 0 <= confidence <= 1:
        raise GoldValidationError("confidence must be between 0 and 1, or null.")
    with gold_connection() as conn:
        initialize_schema(conn)
        cycle = db.get_cycle_by_id(conn, cycle_id)
        if cycle is None:
            raise GoldDataError(f"Cycle {cycle_id} not found.")
        db.update_post_hoc_confidence(conn, cycle_id, confidence)
        conn.commit()
    return {"cycle_id": cycle_id, "post_hoc_confidence": confidence}


# ---------------------------------------------------------------------------
# V2: Prompt management
# ---------------------------------------------------------------------------

def get_prompt(indicator_key: str) -> dict[str, Any]:
    if indicator_key not in INDICATOR_KEYS:
        raise GoldDataError(f"Unknown indicator key: {indicator_key}")
    with gold_connection() as conn:
        initialize_schema(conn)
        prompt = db.get_prompt(conn, indicator_key)
    if prompt is None:
        raise GoldDataError(f"No prompt for indicator '{indicator_key}'.")
    return prompt


def update_prompt(indicator_key: str, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    if indicator_key not in INDICATOR_KEYS:
        raise GoldDataError(f"Unknown indicator key: {indicator_key}")
    with gold_connection() as conn:
        initialize_schema(conn)
        db.upsert_prompt(conn, indicator_key, system_prompt, user_prompt)
        conn.commit()
    return {"indicator_key": indicator_key, "updated": True}


# ---------------------------------------------------------------------------
# V2: FOMC meeting schedule
# ---------------------------------------------------------------------------

_FOMC_PROMPT = {
    "system": (
        "你是美联储日程分析助手。返回未来12个月内已公布的FOMC议息会议日期列表。"
        "输出严格JSON数组，每个元素含 meeting_date(YYYY-MM-DD)、title、notes。"
        "只返回JSON，不要markdown。"
    ),
    "user": (
        "请列出未来12个月内已公布的美联储FOMC议息会议日期。"
        "返回JSON数组，格式：[{\"meeting_date\":\"YYYY-MM-DD\",\"title\":\"...\",\"notes\":\"...\"}]"
    ),
}


def get_next_fomc() -> dict[str, Any]:
    with gold_connection() as conn:
        initialize_schema(conn)
        next_meeting = db.get_next_fomc(conn)
        all_meetings = db.get_all_fomc(conn)
    return {"next": next_meeting, "all": all_meetings}


def refresh_fomc() -> dict[str, Any]:
    """Fetch FOMC schedule via LLM and replace future meetings."""
    from src.providers.chat import ChatLLM

    messages = [
        {"role": "system", "content": _FOMC_PROMPT["system"]},
        {"role": "user", "content": _FOMC_PROMPT["user"]},
    ]
    try:
        llm = ChatLLM()
        response = llm.chat(messages, timeout=30)
        content = getattr(response, "content", str(response))
    except Exception as exc:
        raise GoldLLMError(f"LLM call failed for FOMC: {exc}") from exc

    json_str = _extract_json(content)
    if not json_str:
        raise GoldLLMError(f"LLM returned non-JSON for FOMC: {content[:200]}")
    try:
        meetings = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise GoldLLMError(f"LLM JSON parse failed for FOMC: {exc}") from exc

    if not isinstance(meetings, list):
        raise GoldLLMError("LLM FOMC response is not a JSON array.")

    normalized = []
    for m in meetings:
        if not isinstance(m, dict) or "meeting_date" not in m:
            continue
        normalized.append({
            "meeting_date": str(m["meeting_date"])[:10],
            "title": str(m.get("title", "FOMC议息会议"))[:128],
            "notes": str(m.get("notes", ""))[:256],
            "source": "llm",
        })

    with gold_connection() as conn:
        initialize_schema(conn)
        count = db.replace_future_fomc(conn, normalized)
        conn.commit()
    return {"inserted": count, "meetings": normalized}
