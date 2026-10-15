"""Application service for the event radar and macro Task Force reports.

Scan orchestration runs in a daemon thread (the pipeline performs many
throttled network calls and LLM batches); API requests create the scan run
row and return immediately. Report rows reconcile lazily on read against
the swarm run store, so archiving survives server restarts without a
callback bus.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime
from typing import Any, Callable

from src.eventradar import db as edb
from src.eventradar import dedup, extract, report as report_mod, scoring, sources

logger = logging.getLogger(__name__)

PRESET_NAME = "macro_event_task_force"

VALID_SCOPES = ("china", "global", "all")
VALID_MODES = ("live", "retrospective")
TERMINAL_REPORT_STATUSES = ("completed", "incomplete", "failed")


class EventRadarError(ValueError):
    """400-level service error."""


class ScanInProgress(EventRadarError):
    pass


class EventNotFound(EventRadarError):
    pass


class EventNotConfirmed(EventRadarError):
    pass


#: scope -> daemon running flag (in-process guard against double scans)
_active_scans: set[str] = set()
_scan_guard = threading.Lock()


# ---------------------------------------------------------------------------
# Scan orchestration
# ---------------------------------------------------------------------------

def _cfg() -> Any:
    from src.config.accessor import get_env_config

    return get_env_config().event_radar


def list_scan_runs(limit: int = 20) -> list[dict[str, Any]]:
    conn = edb.event_connection()
    try:
        edb.initialize_schema(conn)
        return edb.list_scan_runs(conn, limit=limit)
    finally:
        conn.close()


def start_scan(
    scope: str = "all",
    *,
    trigger_type: str = "manual",
    llm_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    if scope not in VALID_SCOPES:
        raise EventRadarError(f"非法扫描范围：{scope}")
    with _scan_guard:
        if scope in _active_scans:
            raise ScanInProgress("该范围的扫描正在进行中")
        conn = edb.event_connection()
        try:
            edb.initialize_schema(conn)
            stale = edb.get_running_scan(conn, scope)
            if stale is not None:
                # Row left by an interrupted process — close it before retry.
                edb.update_scan_run(
                    conn, stale["id"], status="failed", error="服务重启，扫描中断"
                )
            scan_id = str(uuid.uuid4())
            row = edb.insert_scan_run(
                conn, scan_id=scan_id, scope=scope, trigger_type=trigger_type
            )
            _active_scans.add(scope)
        finally:
            conn.close()
    thread = threading.Thread(
        target=_run_scan_safely,
        args=(scan_id, scope, llm_factory),
        name=f"event-radar-scan-{scan_id[:8]}",
        daemon=True,
    )
    thread.start()
    return row


def _run_scan_safely(scan_id: str, scope: str,
                     llm_factory: Callable[[], Any] | None) -> None:
    try:
        _run_scan(scan_id, scope, llm_factory)
    except Exception:
        logger.exception("radar scan %s crashed", scan_id)
        try:
            conn = edb.event_connection()
            try:
                edb.update_scan_run(conn, scan_id, status="failed",
                                    error="扫描管道异常")
            finally:
                conn.close()
        finally:
            with _scan_guard:
                _active_scans.discard(scope)
    else:
        with _scan_guard:
            _active_scans.discard(scope)


def _run_scan(scan_id: str, scope: str,
              llm_factory: Callable[[], Any] | None) -> None:
    cfg = _cfg()
    conn = edb.event_connection()
    try:
        edb.initialize_schema(conn)

        # 1. Multi-source collection (per-source failures isolated).
        collected = sources.collect(scope)
        raw_candidates = collected["candidates"]

        # 2. Count within-batch near-dups for reporting, but keep every
        # candidate: reworded reposts carry independent source URLs that
        # must be merged into the event's evidence chain, not discarded.
        unique = raw_candidates
        fingerprints: list[tuple[int, str]] = []
        duplicates = 0
        for candidate in raw_candidates:
            fp = dedup.simhash64(candidate["title"])
            if any(
                dedup.is_near_duplicate(fp, prior_fp,
                                        left_text=candidate["title"],
                                        right_text=prior_title)
                for prior_fp, prior_title in fingerprints
            ):
                duplicates += 1
            fingerprints.append((fp, candidate["title"]))

        # 3. Structured extraction against known events.
        known = edb.recent_events_for_lookup(conn)
        events, _used_llm = extract.extract_all(
            unique, known, llm_factory=llm_factory
        )

        # 4. Match -> merge or create.
        new_count = 0
        escalated = 0
        for event in events:
            indexes = [i for i in event["evidence_indexes"] if 0 <= i < len(unique)]
            if not indexes:
                continue
            evidences = [unique[i] for i in indexes]
            existing = _match_existing(conn, event, known, evidences,
                                       cfg.vibe_event_dedup_window_hours)
            if existing is not None:
                if _merge_into_event(conn, existing, event, evidences, scan_id, cfg):
                    escalated += 1
            else:
                _create_event(conn, event, evidences, scan_id, cfg)
                new_count += 1

        to_review_rows = conn.execute(
            "SELECT count(*) FROM radar_event WHERE verify_status IN "
            "('unverified', 'verifying', 'disputed', 'rumor')"
        ).fetchone()
        to_review = int(to_review_rows[0]) if to_review_rows else 0

        source_failed = any(s.get("status") == "error"
                            for s in collected["sources"])
        edb.update_scan_run(
            conn, scan_id,
            status="partial" if source_failed else "completed",
            source_status=collected["sources"],
            candidates=len(raw_candidates),
            duplicates=duplicates,
            new_events=new_count,
            escalated=escalated,
            to_review=to_review,
            error="部分数据源不可用" if source_failed else None,
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Event matching / creation / merge
# ---------------------------------------------------------------------------

def _cluster_key_for(
    entities: list[str] | None, event_type: str, title: str,
    seen_at: datetime, window_hours: int,
) -> str:
    """Cluster key, with a title discriminator for entity-less events.

    Stories without a recognizable primary entity cannot share a type+time
    bucket key (unrelated items would collide); reworded reposts of the same
    entity-less story still merge through the title-similarity path.
    """
    key = dedup.cluster_key(entities, event_type, seen_at, window_hours)
    if dedup.primary_entity(entities) == "unknown":
        key += f"|{dedup.to_hex(dedup.simhash64(title))[:12]}"
    return key


def _seen_at(evidences: list[dict[str, Any]]) -> datetime:
    for item in evidences:
        parsed = dedup.parse_published(item.get("published_at"))
        if parsed is not None:
            return parsed
    return datetime.now()


def _match_existing(
    conn: Any,
    event: dict[str, Any],
    known: list[dict[str, Any]],
    evidences: list[dict[str, Any]],
    window_hours: int,
) -> dict[str, Any] | None:
    # Explicit LLM merge directive.
    if event["action"] == "merge" and event.get("event_id"):
        direct = edb.get_event(conn, event["event_id"])
        if direct is not None:
            return direct
    seen_at = _seen_at(evidences)
    # Server-side cluster key. A shared key only merges when the primary
    # entity is real ("unknown" would otherwise fuse unrelated stories of
    # the same type in one time bucket); unknown-entity pairs fall through
    # to the title-similarity check below.
    key = _cluster_key_for(event.get("entities"), event["event_type"],
                           event["title"], seen_at, window_hours)
    clustered = edb.get_event_by_cluster_key(conn, key)
    if clustered is not None:
        return clustered
    # SimHash near-duplicate / exact title against recent events.
    fp = dedup.simhash64(event["title"])
    for prior in known:
        if prior.get("simhash"):
            try:
                prior_fp = int(prior["simhash"], 16)
            except ValueError:
                prior_fp = 0
            if dedup.is_near_duplicate(fp, prior_fp,
                                       left_text=event["title"],
                                       right_text=prior.get("title", "")):
                prior_seen = datetime.fromisoformat(prior["first_seen_at"])
                if dedup.within_window(seen_at, prior_seen, window_hours):
                    return prior
        if prior.get("title") == event["title"]:
            return prior
    return None


def _evidence_metrics(
    conn: Any, event_id: str, extra: list[dict[str, Any]] | None = None
) -> tuple[int, int, int]:
    """Return (total_rows, independent_count, best_tier) for an event."""
    rows = edb.list_evidence(conn, event_id)
    seen_urls = {r["url"] for r in rows}
    for item in extra or []:
        if item["url"] not in seen_urls:
            rows.append({
                "url": item["url"], "source_tier": scoring.source_tier(
                    item.get("source_name"), item.get("url")
                ),
                "is_independent": not scoring.is_repost(
                    item.get("snippet"), item.get("title")
                ),
            })
    independent = [r for r in rows if r.get("is_independent", True)]
    best_tier = min((r.get("source_tier") or 4 for r in independent), default=4)
    return len(rows), len(independent), best_tier


def _insert_evidence_rows(
    conn: Any, event_id: str, evidences: list[dict[str, Any]], scan_id: str
) -> int:
    inserted = 0
    for item in evidences:
        if edb.evidence_url_exists(conn, item["url"]):
            continue
        repost = scoring.is_repost(item.get("snippet"), item.get("title"))
        edb.insert_evidence(
            conn,
            event_id=event_id,
            url=item["url"],
            source_name=item.get("source_name"),
            source_tier=scoring.source_tier(item.get("source_name"), item.get("url")),
            title=item.get("title"),
            snippet=item.get("snippet"),
            published_at=dedup.parse_published(item.get("published_at")),
            is_independent=not repost,
            scan_id=scan_id,
        )
        inserted += 1
    return inserted


def _apply_paradigm(event: dict[str, Any], cfg: Any) -> tuple[str, int | None,
                                                             dict[str, int] | None,
                                                             list[str]]:
    novelty, total, scores = scoring.validate_paradigm(
        event["novelty_class"], event.get("paradigm_scores"),
        threshold=cfg.vibe_event_paradigm_threshold,
    )
    text = f"{event['title']} {event.get('summary') or ''}"
    themes = scoring.map_themes(text)
    return novelty, total, scores, themes


def _create_event(
    conn: Any,
    event: dict[str, Any],
    evidences: list[dict[str, Any]],
    scan_id: str,
    cfg: Any,
) -> None:
    seen_at = _seen_at(evidences)
    novelty, total, scores, themes = _apply_paradigm(event, cfg)
    event_id = str(uuid.uuid4())
    key = _cluster_key_for(event.get("entities"), event["event_type"],
                           event["title"], seen_at,
                           cfg.vibe_event_dedup_window_hours)
    best_tier = min(
        (scoring.source_tier(i.get("source_name"), i.get("url")) for i in evidences),
        default=4,
    )
    independent = sum(
        1 for i in evidences
        if not scoring.is_repost(i.get("snippet"), i.get("title"))
    )
    consistency = effective_consistency(
        float(event.get("fact_consistency", 0.5)),
        independent=independent, best_tier=best_tier,
    )
    confidence = scoring.confidence_score(
        best_tier=best_tier, independent_sources=independent,
        fact_consistency=consistency,
    )
    status = scoring.derive_status(
        best_tier=best_tier, independent_sources=independent,
        fact_consistency=consistency,
        confidence=confidence,
        min_sources=cfg.vibe_event_verify_min_sources,
        confirm_threshold=cfg.vibe_event_confirm_threshold,
    )
    row = {
        "event_id": event_id,
        "title": event["title"],
        "event_type": event["event_type"],
        "entities": event.get("entities") or [],
        "regions": event.get("regions") or [],
        "summary": event.get("summary"),
        "impact_direction": event.get("impact_direction", "uncertain"),
        "affected_assets": event.get("affected_assets") or [],
        "cluster_key": key,
        "simhash": dedup.to_hex(dedup.simhash64(event["title"])),
        "novelty_class": novelty,
        "paradigm_scores": scores,
        "paradigm_total": total,
        "long_term_themes": themes,
        "impact_level": scoring.impact_level_from_type(event["event_type"], novelty),
        "verify_status": status,
        "confidence": confidence,
        "source_count": len(evidences),
        "first_seen_at": seen_at,
        "last_update_at": datetime.now(),
    }
    edb.insert_event(conn, row)
    _insert_evidence_rows(conn, event_id, evidences, scan_id)
    edb.add_timeline(conn, event_id=event_id, change_type="created",
                     to_value=status, note=f"sources={len(evidences)}")
    if status != scoring.STATUS_UNVERIFIED:
        edb.add_timeline(conn, event_id=event_id, change_type="status_changed",
                         from_value=scoring.STATUS_UNVERIFIED, to_value=status)


def _merge_into_event(
    conn: Any,
    existing: dict[str, Any],
    event: dict[str, Any],
    evidences: list[dict[str, Any]],
    scan_id: str,
    cfg: Any,
) -> bool:
    """Merge incoming evidence into an event. Returns True on escalation."""
    event_id = existing["event_id"]
    inserted = _insert_evidence_rows(conn, event_id, evidences, scan_id)
    if inserted:
        edb.add_timeline(conn, event_id=event_id, change_type="evidence_added",
                         note=f"+{inserted} source(s)")

    escalated = False
    # Human-terminal events: evidence only, never auto-rewrite the verdict.
    if existing.get("locked_by_human") and \
            existing["verify_status"] in scoring.HUMAN_LOCKED_STATUSES:
        total, _independent, _tier = _evidence_metrics(conn, event_id)
        edb.update_event_fields(conn, event_id, {"source_count": total})
        return False

    fields: dict[str, Any] = {}
    total, independent, best_tier = _evidence_metrics(conn, event_id)
    fields["source_count"] = total

    consistency = effective_consistency(
        max(existing_event_consistency(existing),
            float(event.get("fact_consistency", 0.5))),
        independent=independent, best_tier=best_tier,
    )
    confidence = scoring.confidence_score(
        best_tier=best_tier, independent_sources=independent,
        fact_consistency=consistency,
    )
    fields["confidence"] = confidence
    target_status = scoring.derive_status(
        best_tier=best_tier, independent_sources=independent,
        fact_consistency=consistency, confidence=confidence,
        min_sources=cfg.vibe_event_verify_min_sources,
        confirm_threshold=cfg.vibe_event_confirm_threshold,
    )
    if target_status != existing["verify_status"] and scoring.can_transition(
        existing["verify_status"], target_status
    ):
        fields["verify_status"] = target_status
        edb.add_timeline(conn, event_id=event_id, change_type="status_changed",
                         from_value=existing["verify_status"],
                         to_value=target_status)
        if target_status == scoring.STATUS_CONFIRMED:
            escalated = True

    # Novelty upgrade: a validated new-paradigm read can upgrade an existing
    # event; downgrades are never applied automatically.
    if event["novelty_class"] == "new_paradigm" and \
            existing["novelty_class"] != "new_paradigm":
        novelty, total_score, scores, themes = _apply_paradigm(event, cfg)
        if novelty == "new_paradigm":
            fields["novelty_class"] = novelty
            fields["paradigm_scores"] = scores
            fields["paradigm_total"] = total_score
            merged_themes = sorted(set((existing.get("long_term_themes") or [])
                                       + themes))
            fields["long_term_themes"] = merged_themes
            fields["impact_level"] = scoring.impact_level_from_type(
                existing["event_type"], novelty
            )
            edb.add_timeline(conn, event_id=event_id,
                             change_type="novelty_changed",
                             from_value=existing["novelty_class"],
                             to_value=novelty)
            escalated = True

    edb.update_event_fields(conn, event_id, fields)
    return escalated


def existing_event_consistency(existing: dict[str, Any]) -> float:
    """Approximate prior fact consistency from stored confidence."""
    confidence = existing.get("confidence")
    return float(confidence) if isinstance(confidence, (int, float)) else 0.5


def effective_consistency(
    declared: float, *, independent: int, best_tier: int
) -> float:
    """Observed agreement floor for the no-LLM path.

    When >=2 independent T1/T2 reports were clustered into one event, the
    clustering decision itself is cross-source agreement. The LLM path
    supplies an explicit fact-consistency score which always wins.
    """
    if independent >= 2 and best_tier <= 2:
        return max(declared, 0.7)
    return declared


# ---------------------------------------------------------------------------
# Reads + human review
# ---------------------------------------------------------------------------

def list_events(**filters: Any) -> list[dict[str, Any]]:
    conn = edb.event_connection()
    try:
        edb.initialize_schema(conn)
        return edb.list_events(conn, **filters)
    finally:
        conn.close()


def event_detail(event_id: str) -> dict[str, Any]:
    conn = edb.event_connection()
    try:
        edb.initialize_schema(conn)
        event = edb.get_event(conn, event_id)
        if event is None:
            raise EventNotFound("事件不存在")
        event["evidence"] = edb.list_evidence(conn, event_id)
        event["timeline"] = edb.list_timeline(conn, event_id)
        event["reports"] = [
            {"id": r["id"], "mode": r["mode"], "status": r["status"],
             "title": r["title"], "created_at": r["created_at"]}
            for r in edb.list_reports(conn, limit=20) if r.get("event_id") == event_id
        ]
        return event
    finally:
        conn.close()


def verify_event(event_id: str, action: str, note: str | None = None,
                 actor: str = "manual") -> dict[str, Any]:
    if action not in scoring.HUMAN_ACTIONS:
        raise EventRadarError(f"非法复核动作：{action}")
    conn = edb.event_connection()
    try:
        edb.initialize_schema(conn)
        event = edb.get_event(conn, event_id)
        if event is None:
            raise EventNotFound("事件不存在")
        target = scoring.HUMAN_ACTIONS[action]
        if not scoring.can_transition(event["verify_status"], target):
            raise EventRadarError(
                f"不能将状态 {event['verify_status']} 变更为 {target}"
            )
        fields: dict[str, Any] = {"verify_status": target}
        if action in ("confirm", "mark_rumor", "dismiss"):
            fields["locked_by_human"] = True
        edb.update_event_fields(conn, event_id, fields)
        edb.add_timeline(conn, event_id=event_id, change_type="human_action",
                         from_value=event["verify_status"], to_value=target,
                         actor=actor, note=note)
        return edb.get_event(conn, event_id)  # type: ignore[return-value]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Task Force runs + reports
# ---------------------------------------------------------------------------

def _build_event_brief(event: dict[str, Any], conn: Any) -> str:
    evidence = edb.list_evidence(conn, event["event_id"])
    lines = [
        f"事件：{event['title']}",
        f"类型：{event['event_type']}｜区域：{', '.join(event.get('regions') or []) or '未标注'}",
        f"摘要：{event.get('summary') or ''}",
        f"新颖度：{event['novelty_class']}｜长期赛道："
        f"{', '.join(event.get('long_term_themes') or []) or '无'}",
        "证据链：",
    ]
    for item in evidence:
        lines.append(
            f"- [T{item['source_tier']}] {item['title']} ({item['url']})"
        )
    return "\n".join(lines)


def start_analysis(
    runtime: Any,
    *,
    event_id: str | None = None,
    mode: str = "live",
    market: str = "A股+全球",
    time_horizon: str = "",
    event_title: str = "",
    event_period: str = "",
) -> dict[str, Any]:
    if mode not in VALID_MODES:
        raise EventRadarError(f"非法分析模式：{mode}")
    conn = edb.event_connection()
    try:
        edb.initialize_schema(conn)
        brief = ""
        if event_id:
            event = edb.get_event(conn, event_id)
            if event is None:
                raise EventNotFound("事件不存在")
            if event["verify_status"] != scoring.STATUS_CONFIRMED:
                raise EventNotConfirmed("仅已证实事件可发起 Task Force 分析")
            title = event["title"]
            brief = _build_event_brief(event, conn)
        else:
            title = (event_title or "").strip()
            if not title:
                raise EventRadarError("历史复盘需要提供事件名称")
            if mode != "retrospective":
                raise EventRadarError("自定义事件仅支持 retrospective 模式")
            brief = f"历史事件：{title}\n复盘区间：{event_period or '由分析团队界定'}"

        horizon = time_horizon or (
            event_period if mode == "retrospective" else "未来3-6个月"
        )
        user_vars = {
            "event": brief,
            "mode": mode,
            "market": market or "A股+全球",
            "time_horizon": horizon or "未来3-6个月",
        }
        run = runtime.start_run(PRESET_NAME, user_vars)

        report_id = str(uuid.uuid4())
        row = {
            "id": report_id,
            "event_id": event_id,
            "run_id": run.id,
            "mode": mode,
            "title": title,
            "market": user_vars["market"],
            "time_horizon": user_vars["time_horizon"],
            "status": getattr(run.status, "value", str(run.status)),
            "created_at": datetime.now(),
        }
        edb.insert_report(conn, row)
        return {"report_id": report_id, "run_id": run.id,
                "status": row["status"], "title": title}
    finally:
        conn.close()


def _reconcile(conn: Any, item: dict[str, Any], runtime: Any) -> dict[str, Any]:
    if item["status"] in TERMINAL_REPORT_STATUSES:
        return item
    try:
        loaded = runtime._store.load_run(item["run_id"])
    except Exception:
        logger.debug("run lookup failed for %s", item["run_id"], exc_info=True)
        return item
    if loaded is None:
        return item
    run = runtime._store.reconcile_run(loaded, write=True)
    run_status = getattr(run.status, "value", str(run.status))
    if run_status in ("pending", "running"):
        if run_status != item["status"]:
            edb.update_report_fields(conn, item["id"], {"status": run_status})
            item["status"] = run_status
        return item
    if run_status in ("failed", "cancelled"):
        edb.update_report_fields(conn, item["id"], {"status": "failed"})
        item["status"] = "failed"
        return item
    # succeeded / completed
    final_report = str(getattr(run, "final_report", "") or "").strip()
    if not final_report:
        edb.update_report_fields(conn, item["id"], {"status": "failed"})
        item["status"] = "failed"
        return item
    complete, present = report_mod.validate_report(final_report, item["mode"])
    edb.update_report_fields(conn, item["id"], {
        "status": "completed" if complete else "incomplete",
        "markdown": final_report,
        "sections_present": present,
        "completed_at": datetime.now(),
    })
    archived = edb.get_report(conn, item["id"])
    return archived or item


def list_reports(runtime: Any, mode: str | None = None,
                 status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    conn = edb.event_connection()
    try:
        edb.initialize_schema(conn)
        items = edb.list_reports(conn, mode=mode, status=status, limit=limit)
        return [_reconcile(conn, item, runtime) for item in items]
    finally:
        conn.close()


def get_report(runtime: Any, report_id: str) -> dict[str, Any]:
    conn = edb.event_connection()
    try:
        edb.initialize_schema(conn)
        item = edb.get_report(conn, report_id)
        if item is None:
            raise EventNotFound("报告不存在")
        return _reconcile(conn, item, runtime)
    finally:
        conn.close()
