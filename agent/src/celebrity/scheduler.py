"""Weekly refresh scheduler for the investment celebrity module.

Runs every Sunday at 04:00 and refreshes all investors via the LLM.
Mirrors ``src.gold_monitor.scheduler``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 60 * 30  # check every 30 minutes


def start_celebrity_scheduler(app) -> None:
    existing = getattr(app.state, "celebrity_scheduler_task", None)
    if existing is not None and not existing.done():
        return
    app.state.celebrity_scheduler_task = asyncio.create_task(_refresh_loop(app))


def stop_celebrity_scheduler(app) -> None:
    task = getattr(app.state, "celebrity_scheduler_task", None)
    if task is not None and not task.done():
        task.cancel()


async def _refresh_loop(app) -> None:
    from src.celebrity import service as celebrity_service

    logger.info("Celebrity scheduler started (check interval=%ds)", _CHECK_INTERVAL_SECONDS)
    try:
        while True:
            try:
                now = datetime.now()
                # Sunday = weekday() == 6, hour == 4
                if now.weekday() == 6 and now.hour == 4:
                    logger.info("Celebrity scheduler: weekly refresh triggered at %s", now.isoformat())
                    try:
                        celebrity_service.refresh_all_investors()
                        logger.info("Celebrity scheduler: weekly refresh completed")
                    except Exception as exc:
                        logger.warning("Celebrity scheduler: refresh failed: %s", exc)
                    # sleep past 4am to avoid re-triggering within the same hour
                    await asyncio.sleep(60 * 60)
                    continue
            except Exception as exc:
                logger.exception("Celebrity scheduler: unhandled loop error: %s", exc)
            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Celebrity scheduler stopped.")
