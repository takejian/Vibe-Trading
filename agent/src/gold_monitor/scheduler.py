"""Background monthly refresh scheduler for gold-monitor data.

Mirrors ``src.paper.scheduler`` — uses ``asyncio.create_task`` and is
started/stopped from the FastAPI lifespan (see ``src.api.lifecycle``).

The task loops daily; on the 1st of each month it attempts to refresh
the previous month's data via the LLM. Failures are logged but do not
kill the server.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 60 * 60 * 24  # daily check


def start_gold_scheduler(app) -> None:
    """Create the background refresh loop task if not already running."""
    existing = getattr(app.state, "gold_scheduler_task", None)
    if existing is not None and not existing.done():
        return
    app.state.gold_scheduler_task = asyncio.create_task(_refresh_loop(app))


def stop_gold_scheduler(app) -> None:
    """Cancel the background refresh loop on server shutdown."""
    task = getattr(app.state, "gold_scheduler_task", None)
    if task is not None and not task.done():
        task.cancel()


async def _refresh_loop(app) -> None:
    """Daily check — trigger LLM refresh on the 1st of each month."""
    from src.gold_monitor import db as gold_db
    from src.gold_monitor import service as gold_service

    logger.info("Gold monitor scheduler started (check interval=%ds)", _CHECK_INTERVAL_SECONDS)
    try:
        while True:
            try:
                today = date.today()
                if today.day == 1:
                    # Refresh previous natural month
                    prev_year = today.year
                    prev_month = today.month - 1
                    if prev_month == 0:
                        prev_month = 12
                        prev_year -= 1
                    target = f"{prev_year:04d}-{prev_month:02d}"

                    with gold_db.gold_connection() as conn:
                        gold_db.initialize_schema(conn)
                        already = gold_db.has_refreshed_today(conn, source="scheduler")
                    if already:
                        logger.info("Gold scheduler: already refreshed target=%s today, skipping", target)
                    else:
                        try:
                            gold_service.trigger_refresh(source="scheduler")
                            logger.info("Gold scheduler: refreshed target=%s", target)
                        except Exception as exc:
                            logger.warning("Gold scheduler: refresh failed target=%s error=%s", target, exc)
                            with gold_db.gold_connection() as conn:
                                gold_db.initialize_schema(conn)
                                gold_db.log_refresh(
                                    conn, target, "failed", False, "scheduler",
                                    error_msg=str(exc),
                                )
            except Exception as exc:
                logger.exception("Gold scheduler: unhandled loop error: %s", exc)

            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Gold monitor scheduler stopped.")
