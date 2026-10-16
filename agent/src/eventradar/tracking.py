# -*- coding: utf-8 -*-
"""Daily / weekly / monthly truth-tracking for archived radar events.

Only events the user kept in the archive (``archived=true``) and which have
not reached a terminal verdict are tracked. A recheck pulls the curated
feeds, appends genuinely new evidence for the event, and reruns the SAME
verification state machine as a live scan (no privileged paths):

* daily   — every day 05:00  → ``review_daily``
* weekly  — every Monday 05:00 → ``review_weekly``
* monthly — day 1 at 05:00     → ``review_monthly``
* manual  — user "立即复查"     → overwrites ``review_monthly``

Collection/LLM failures never overwrite an existing verdict: the field
gets an ``error`` record with a timestamp and the next anchor retries.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from src.eventradar import db as edb
from src.eventradar import dedup, scoring, service
from src.eventradar import sources as sources_mod

logger = logging.getLogger(__name__)

#: kind → (event column, timeline actor)
KINDS: dict[str, tuple[str, str]] = {
    "daily": ("review_daily", "system-daily"),
    "weekly": ("review_weekly", "system-weekly"),
    "monthly": ("review_monthly", "system-monthly"),
}
MANUAL_FIELD = "review_monthly"
MANUAL_ACTOR = "manual"

VERDICT_TRUE = "true"
VERDICT_FALSE = "false"
VERDICT_UNVERIFIED = "unverified"
VERDICT_ERROR = "error"

TRACKED_STATUSES = (
    scoring.STATUS_UNVERIFIED,
    scoring.STATUS_VERIFYING,
    scoring.STATUS_DISPUTED,
)
_TERMINAL = {
    scoring.STATUS_CONFIRMED,
    scoring.STATUS_RUMOR,
    scoring.STATUS_DISMISSED,
}


class TrackingError(RuntimeError):
    """Invalid precondition for a recheck (missing/unarchived event)."""


def review_kinds_for(now: datetime) -> list[str]:
    """Which review fields are due at a given anchor instant."""
    kinds = ["daily"]
    if now.weekday() == 0:  # Monday
        kinds.append("weekly")
    if now.day == 1:
        kinds.append("monthly")
    return kinds


def _entity_names(event: dict[str, Any]) -> list[str]:
    entities = event.get("entities")
    names: list[str] = []
    if isinstance(entities, dict):
        for value in entities.values():
            if isinstance(value, list):
                names.extend(str(v) for v in value)
    elif isinstance(entities, list):
        names.extend(str(v) for v in entities)
    return [n for n in names if n and n != "unknown" and len(n) >= 2]


def _related_candidates(
    event: dict[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Candidates about THIS event: title near-duplicate or entity hit."""
    title = event["title"]
    title_fp = dedup.simhash64(title)
    names = _entity_names(event)
    related: list[dict[str, Any]] = []
    for cand in candidates:
        cand_title = cand.get("title") or ""
        if dedup.is_near_duplicate(
            title_fp, dedup.simhash64(cand_title),
            left_text=title, right_text=cand_title,
        ) or any(name in cand_title for name in names):
            related.append(cand)
    return related


def _verdict_for_status(status: str) -> str:
    if status == scoring.STATUS_CONFIRMED:
        return VERDICT_TRUE
    if status in (scoring.STATUS_RUMOR, scoring.STATUS_DISMISSED):
        return VERDICT_FALSE
    return VERDICT_UNVERIFIED


def _reason(*, new_evidence: int, independent: int, best_tier: int,
            status: str, old_status: str) -> str:
    if status == scoring.STATUS_CONFIRMED and old_status != scoring.STATUS_CONFIRMED:
        return (f"复查新增 {new_evidence} 条证据，累计 {independent} 个独立信源"
                f"（最高 T{best_tier}），达到自动证实门限。")
    if status in (scoring.STATUS_RUMOR, scoring.STATUS_DISMISSED) and \
            old_status != status:
        return f"复查出现辟谣/否证证据，状态迁移为 {status}。"
    if new_evidence > 0:
        return (f"复查新增 {new_evidence} 条证据，累计 {independent} 个独立信源"
                f"（最高 T{best_tier}），尚不足以改变当前结论。")
    return (f"复查未发现新的独立信源（累计 {independent} 个，最高 T{best_tier}），"
            "维持当前结论。")


def recheck_event(
    event_id: str,
    *,
    kind: str = "manual",
    candidates: list[dict[str, Any]] | None = None,
    collector: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one verification pass; returns the review record that was stored."""
    if kind not in KINDS and kind != "manual":
        raise TrackingError(f"未知复查类型: {kind}")
    field, actor = (
        (MANUAL_FIELD, MANUAL_ACTOR) if kind == "manual" else KINDS[kind]
    )
    now_iso = datetime.now().isoformat(timespec="seconds")
    conn = edb.event_connection()
    try:
        edb.initialize_schema(conn)
        event = edb.get_event(conn, event_id)
        if event is None:
            raise TrackingError("事件不存在")
        if not event.get("archived"):
            raise TrackingError("仅事件档案中的事件可跟踪复查")
        if event["verify_status"] in _TERMINAL:
            return {
                "verdict": _verdict_for_status(event["verify_status"]),
                "reason": "事件已是终态，无需复查。",
                "checked_at": now_iso, "actor": actor, "skipped": True,
            }

        try:
            if candidates is None:
                collect = collector or sources_mod.collect
                candidates = collect("all").get("candidates", [])
            related = _related_candidates(event, candidates)
            added = service._insert_evidence_rows(conn, event_id, related, None)

            cfg = service._cfg()
            total, independent, best_tier = service._evidence_metrics(
                conn, event_id
            )
            consistency = service.effective_consistency(
                service.existing_event_consistency(event),
                independent=independent, best_tier=best_tier,
            )
            confidence = scoring.confidence_score(
                best_tier=best_tier, independent_sources=independent,
                fact_consistency=consistency,
            )
            target = scoring.derive_status(
                best_tier=best_tier, independent_sources=independent,
                fact_consistency=consistency, confidence=confidence,
                min_sources=cfg.vibe_event_verify_min_sources,
                confirm_threshold=cfg.vibe_event_confirm_threshold,
            )
            old_status = event["verify_status"]
            new_status = old_status
            activity_fields: dict[str, Any] = {}
            if added:
                activity_fields["source_count"] = total
                activity_fields["confidence"] = confidence
            if target != old_status and scoring.can_transition(old_status, target):
                new_status = target
                activity_fields["verify_status"] = target
                activity_fields["confidence"] = confidence
                activity_fields["source_count"] = total
                edb.add_timeline(
                    conn, event_id=event_id, change_type="status_changed",
                    from_value=old_status, to_value=target, actor=actor,
                )
            if activity_fields:
                edb.update_event_fields(conn, event_id, activity_fields)

            review = {
                "verdict": _verdict_for_status(new_status),
                "reason": _reason(
                    new_evidence=added, independent=independent,
                    best_tier=best_tier, status=new_status,
                    old_status=old_status,
                ),
                "checked_at": now_iso,
                "actor": actor,
                "new_evidence": added,
                "independent_sources": independent,
                "best_tier": best_tier,
                "status": new_status,
            }
            # Review bookkeeping alone never bumps last_update_at.
            edb.update_event_fields(conn, event_id, {field: review})
            return review
        except Exception as exc:  # a bad recheck must not destroy old findings
            logger.warning("event %s recheck (%s) failed: %s",
                           event_id, kind, exc, exc_info=True)
            error_review = {
                "verdict": VERDICT_ERROR,
                "reason": f"复查失败：{exc}",
                "checked_at": now_iso,
                "actor": actor,
            }
            edb.update_event_fields(conn, event_id, {field: error_review})
            return error_review
    finally:
        conn.close()


def list_tracked_events() -> list[str]:
    conn = edb.event_connection()
    try:
        edb.initialize_schema(conn)
        placeholders = ", ".join("?" for _ in TRACKED_STATUSES)
        rows = conn.execute(
            f"SELECT event_id FROM radar_event WHERE COALESCE(archived, false) = true "
            f"AND verify_status IN ({placeholders})",
            list(TRACKED_STATUSES),
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def run_due_reviews(
    kinds: list[str] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect the feeds once and apply all due review kinds per event."""
    anchor = now or datetime.now()
    due_kinds = kinds or review_kinds_for(anchor)
    event_ids = list_tracked_events()
    if not event_ids or not due_kinds:
        return {"events": 0, "kinds": due_kinds, "results": []}
    try:
        candidates = sources_mod.collect("all").get("candidates", [])
    except Exception as exc:  # feed outage: record errors, retry next anchor
        logger.warning("scheduled review collection failed: %s", exc)
        candidates = []
    results: list[dict[str, Any]] = []
    for event_id in event_ids:
        for kind in due_kinds:
            try:
                review = recheck_event(
                    event_id, kind=kind, candidates=candidates
                )
            except Exception as exc:  # TrackingError etc.: skip, keep loop alive
                logger.warning("review %s/%s skipped: %s", event_id, kind, exc)
                continue
            results.append({"event_id": event_id, "kind": kind, **review})
    logger.info("event radar reviews done: %d event(s), %d record(s)",
                len(event_ids), len(results))
    return {"events": len(event_ids), "kinds": due_kinds, "results": results}
