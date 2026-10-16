# -*- coding: utf-8 -*-
"""Daily auto-scan loop for the event radar.

Fires one full-scope radar scan every day at the configured anchor
(default 04:00 Asia/Shanghai, ``VIBE_EVENT_DAILY_SCAN_AT``). The loop owns
no scheduler dependency: a bare ``asyncio`` task on ``app.state`` mirrors
``src/paper/scheduler.py``. Scan work itself runs on the radar's daemon
threads; this task only enqueues at the anchor. A missed server-down
anchor is not backfilled.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.eventradar import service

logger = logging.getLogger(__name__)

TICK_SECONDS = 300
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def parse_daily_at(spec: str | None) -> tuple[int, int] | None:
    """Parse a ``HH:MM`` anchor; ``None`` when malformed/empty."""
    if not spec:
        return None
    try:
        hour_str, minute_str = str(spec).strip().split(":")
        hour, minute = int(hour_str), int(minute_str)
    except (ValueError, AttributeError):
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def next_run_after(now: datetime, hour: int, minute: int) -> datetime:
    """Next daily-anchor instant still ahead of ``now``.

    Today's anchor when it is still in the future, otherwise tomorrow's
    (an instant equal to ``now`` counts as past, so the loop never
    re-fires the same anchor). Timezone-aware when ``now`` is.
    """
    anchor = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if anchor <= now:
        anchor += timedelta(days=1)
    return anchor


async def _daily_loop(app: Any) -> None:
    from src.config.accessor import get_env_config

    try:
        cfg = get_env_config().event_radar
        parsed = parse_daily_at(cfg.vibe_event_daily_scan_at)
    except Exception:  # stubbed/missing config (tests) -> loop stays dormant
        logger.info("event radar daily scan disabled: config unavailable")
        return
    if not cfg.vibe_event_daily_scan_enabled or parsed is None:
        logger.info(
            "event radar daily scan disabled (enabled=%s, anchor=%r)",
            cfg.vibe_event_daily_scan_enabled, cfg.vibe_event_daily_scan_at,
        )
        return
    hour, minute = parsed
    next_due = next_run_after(datetime.now(SHANGHAI_TZ), hour, minute)
    logger.info("event radar daily scan scheduled at %s",
                next_due.strftime("%Y-%m-%d %H:%M %Z"))
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            now = datetime.now(SHANGHAI_TZ)
            if now < next_due:
                continue
            try:
                row = service.start_scan("all", trigger_type="scheduled")
                logger.info("event radar daily scan started: %s", row["id"])
            except service.ScanInProgress:
                logger.info("event radar daily scan skipped: scan in progress")
            except Exception:  # noqa: BLE001 - loop must survive a bad day
                logger.warning("event radar daily scan failed to start",
                               exc_info=True)
            next_due = next_run_after(now, hour, minute)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - defensive: never kill the loop
            logger.warning("event radar scheduler tick failed", exc_info=True)


async def _review_loop(app: Any) -> None:
    """05:00 daily/weekly/monthly truth-tracking for archived events."""
    from src.config.accessor import get_env_config
    from src.eventradar import tracking

    try:
        cfg = get_env_config().event_radar
        parsed = parse_daily_at(cfg.vibe_event_review_at)
    except Exception:  # stubbed/missing config (tests) -> loop stays dormant
        logger.info("event radar review loop disabled: config unavailable")
        return
    if not cfg.vibe_event_review_enabled or parsed is None:
        logger.info(
            "event radar review loop disabled (enabled=%s, anchor=%r)",
            cfg.vibe_event_review_enabled, cfg.vibe_event_review_at,
        )
        return
    hour, minute = parsed
    next_due = next_run_after(datetime.now(SHANGHAI_TZ), hour, minute)
    logger.info("event radar review loop scheduled at %s (daily/Mon/1st)",
                next_due.strftime("%Y-%m-%d %H:%M %Z"))
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            now = datetime.now(SHANGHAI_TZ)
            if now < next_due:
                continue
            kinds = tracking.review_kinds_for(now)
            try:
                summary = await asyncio.to_thread(
                    tracking.run_due_reviews, kinds
                )
                logger.info("event radar reviews %s: %s", kinds,
                            {k: summary[k] for k in ("events",)})
            except Exception:  # noqa: BLE001 - loop must survive a bad anchor
                logger.warning("event radar review run failed", exc_info=True)
            next_due = next_run_after(now, hour, minute)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.warning("event radar review tick failed", exc_info=True)


def start_event_radar_scheduler(app: Any) -> None:
    """Create scan + review tasks (idempotent — one set per app)."""
    scan_task = getattr(app.state, "event_radar_scheduler_task", None)
    if scan_task is None or scan_task.done():
        app.state.event_radar_scheduler_task = asyncio.create_task(
            _daily_loop(app)
        )
    review_task = getattr(app.state, "event_radar_review_task", None)
    if review_task is None or review_task.done():
        app.state.event_radar_review_task = asyncio.create_task(
            _review_loop(app)
        )


async def stop_event_radar_scheduler(app: Any) -> None:
    for attr in ("event_radar_scheduler_task", "event_radar_review_task"):
        task = getattr(app.state, attr, None)
        if task is None:
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
