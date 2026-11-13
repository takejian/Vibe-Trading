"""Background monthly refresh scheduler for gold-monitor data.

Mirrors ``src.paper.scheduler`` — uses ``asyncio.create_task`` and is
started/stopped from the FastAPI lifespan (see ``src.api.lifecycle``).

The task loops hourly and triggers three refresh flows:
    * **Daily 08:00** — gold daily bar refresh (pre-market, picks up yesterday's close)
    * **Daily 18:00** — gold daily bar refresh (post-day-session, intra-bar refresh)
    * **1st of month** — monthly indicator refresh via LLM
    * **Mondays** — indicator signal batch refresh
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time

logger = logging.getLogger(__name__)

#: Check every hour (enough granular to fire exactly on 08:00 / 18:00)
_CHECK_INTERVAL_SECONDS = 60 * 60


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
    """Hourly check — fires daily-bar refresh at 08:00 / 18:00 local time,
    monthly LLM refresh on the 1st, signal batch refresh on Mondays."""
    from src.gold_monitor import db as gold_db
    from src.gold_monitor import service as gold_service

    logger.info("Gold monitor scheduler started (check interval=%ds)", _CHECK_INTERVAL_SECONDS)
    _last_daily_refresh_hour: int | None = None  # guard double-fire in same hour
    try:
        while True:
            try:
                now = datetime.now()
                today = date.today()
                hour = now.hour

                # 0) Daily bar refresh at 08:00 and 18:00
                if hour in (8, 18) and _last_daily_refresh_hour != hour:
                    _last_daily_refresh_hour = hour
                    _scheduled_daily_bar_refresh(hour)

                # 1) Monthly data refresh on the 1st of each month
                if today.day == 1 and hour == 8:
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

                # 2) Batch signal refresh every Monday at 9:00
                if today.weekday() == 0 and hour == 9:
                    with gold_db.gold_connection() as conn:
                        gold_db.initialize_schema(conn)
                        sig_done = gold_db.has_refreshed_today(conn, source="scheduler_signals")
                    if not sig_done:
                        try:
                            gold_service.refresh_all_signals(source="scheduler")
                            logger.info("Gold scheduler: batch signal refresh done")
                            with gold_db.gold_connection() as conn:
                                gold_db.initialize_schema(conn)
                                gold_db.log_refresh(
                                    conn, today.strftime("%Y-%m"), "signals_batch", True,
                                    "scheduler_signals",
                                )
                        except Exception as exc:
                            logger.warning("Gold scheduler: signal batch refresh failed: %s", exc)
            except Exception as exc:
                logger.exception("Gold scheduler: unhandled loop error: %s", exc)

            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Gold monitor scheduler stopped.")


def _scheduled_daily_bar_refresh(hour: int) -> None:
    """Trigger the daily-bar refresh pipeline synchronously (called inside asyncio loop
    via asyncio.get_event_loop().run_in_executor on the first heavy op; but because
    our akshare + pymysql calls are not async we just run inline — the 2-hourly
    cadence makes this acceptable)."""
    try:
        from src.gold_monitor import daily_service

        # 08:00 = pre-market (refresh_type='scheduled_pre'), 18:00 = post-market
        refresh_type = "scheduled"
        logger.info("Gold scheduler: triggering daily-bar refresh (hour=%d)", hour)
        result = daily_service.refresh_gold_daily(refresh_type=refresh_type, force=False)
        logger.info(
            "Gold scheduler: daily-bar refresh done — fetched=%d inserted=%d updated=%d latest=%s status=%s",
            result.get("rows_fetched"), result.get("rows_inserted"),
            result.get("rows_updated"), result.get("latest_trade_date"),
            result.get("status"),
        )
    except Exception as exc:
        logger.warning("Gold scheduler: daily-bar refresh failed (hour=%d): %s", hour, exc)
