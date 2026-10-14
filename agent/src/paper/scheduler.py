# -*- coding: utf-8 -*-
"""Background price-refresh loop for the paper portfolio.

The loop wakes once a minute and runs the refresh when the current time
reaches a 2-hour anchor (11:30 / 15:00) on a trading day. A missed anchor
(gap wider than the 5-minute grace) is never backfilled. Each refresh is one
batch quote call + one NAV snapshot; failures are logged and retried next
tick within the grace window. No new dependency (no APScheduler) — a bare
``asyncio`` task owned by ``app.state``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.paper import calendar as paper_calendar
from src.paper import db as paper_db
from src.paper import service
from src.paper.service import FeePolicy

TICK_SECONDS = 60

logger = logging.getLogger(__name__)


async def _refresh_loop(app: Any) -> None:
    executed: set[tuple[Any, Any]] = set()
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            policy = FeePolicy.from_env()
            if not policy.refresh_enabled:
                continue
            now = paper_calendar.now_cn()
            conn = paper_db.paper_connection()
            try:
                paper_db.initialize_schema(conn)
                if paper_db.get_account(conn) is None:
                    continue  # no paper account yet -> nothing to refresh
                due = paper_calendar.due_anchors(conn, now=now,
                                                 executed=executed)
                if due:
                    count = service.refresh_quotes(conn, now=now,
                                                   policy=policy)
                    # Same anchors refresh the Chanlun K-line bars; the 15:00
                    # run replaces the 11:30 half-session daily bar in place.
                    synced = service.sync_position_klines(
                        conn, today=now.date()
                    )
                    for anchor in due:
                        executed.add((now.date(), anchor))
                    logger.info(
                        "paper refresh: %d quotes, %d symbols kline-synced "
                        "at anchors %s",
                        count, len(synced),
                        [a.strftime("%H:%M") for a in due],
                    )
            finally:
                conn.close()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - loop must survive bad ticks
            logger.warning("paper refresh loop tick failed", exc_info=True)


def start_paper_scheduler(app: Any) -> None:
    """Create the refresh task (idempotent — one task per app)."""
    existing = getattr(app.state, "paper_scheduler_task", None)
    if existing is None or existing.done():
        app.state.paper_scheduler_task = asyncio.create_task(_refresh_loop(app))


async def stop_paper_scheduler(app: Any) -> None:
    task = getattr(app.state, "paper_scheduler_task", None)
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
