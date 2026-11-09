"""Background daily refresh scheduler for super-rebound margin + ETF flow.

Mirrors ``src.gold_monitor.scheduler`` — an ``asyncio`` task started from the
FastAPI lifespan (``src.api.lifecycle``).

Behaviour:
    * shortly after server startup, one catch-up sync runs (both margin + ETF);
    * afterwards the loop ticks hourly:
        - 00:00–06:00 window  →  Eastmoney margin daily sync
        - 20:30–22:00 window  →  SSE official ETF flow sync (T-day data
                                 becomes available on query.sse.com.cn after
                                 market close)
    Each sync is run at most once per local calendar day. Failures are logged
    but never kill the server.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

logger = logging.getLogger(__name__)

_TICK_SECONDS = 60 * 15          # 15 min — fine granularity for two windows
_STARTUP_DELAY_SECONDS = 30      # catch-up shortly after boot
_MARGIN_WINDOW = (0, 6)          # 00:00–06:00 — Eastmoney publishes T-day margin in the evening
_ETF_WINDOW = (20, 22)           # 20:30–22:00 — SSE T-day ETF data lands after market close


def start_super_rebound_scheduler(app) -> None:
    existing = getattr(app.state, "super_rebound_scheduler_task", None)
    if existing is not None and not existing.done():
        return
    app.state.super_rebound_scheduler_task = asyncio.create_task(_sync_loop(app))


def stop_super_rebound_scheduler(app) -> None:
    task = getattr(app.state, "super_rebound_scheduler_task", None)
    if task is not None and not task.done():
        task.cancel()


async def _sync_loop(app) -> None:
    from src.super_rebound import service

    logger.info(
        "Super-rebound scheduler started "
        "(tick=%ds margin_window=%s etf_window=%s)",
        _TICK_SECONDS, _MARGIN_WINDOW, _ETF_WINDOW,
    )
    await asyncio.sleep(_STARTUP_DELAY_SECONDS)

    try:
        result = await asyncio.to_thread(service.run_daily_sync)
        logger.info("Super-rebound startup catch-up: %s", result)
    except Exception as exc:
        logger.warning("Super-rebound startup catch-up failed: %s", exc)

    app.state.sr_margin_last_date = None
    app.state.sr_etf_last_date = None

    try:
        while True:
            try:
                today = date.today()
                from datetime import datetime
                now_hour = datetime.now().hour
                margin_done = getattr(app.state, "sr_margin_last_date", None)
                etf_done = getattr(app.state, "sr_etf_last_date", None)

                if (
                    _MARGIN_WINDOW[0] <= now_hour < _MARGIN_WINDOW[1]
                    and margin_done != today
                ):
                    try:
                        result = await asyncio.to_thread(
                            service._sync_margin_incremental
                        )
                        app.state.sr_margin_last_date = today
                        logger.info("Super-rebound margin daily (%s): %d rows", today, result)
                    except Exception as exc:
                        logger.exception("Super-rebound margin daily failed: %s", exc)

                if (
                    _ETF_WINDOW[0] <= now_hour < _ETF_WINDOW[1]
                    and etf_done != today
                    and today.weekday() < 5   # 只在交易日跑
                ):
                    try:
                        result = await asyncio.to_thread(service.refresh_etf_flow)
                        app.state.sr_etf_last_date = today
                        logger.info(
                            "Super-rebound ETF daily (%s): upsert=%d updated=%d missing=%s szse_skipped=%d",
                            today,
                            result.get("sse_upserted"),
                            result.get("sse_updated"),
                            result.get("sse_missing_codes"),
                            result.get("szse_skipped"),
                        )
                    except Exception as exc:
                        logger.exception("Super-rebound ETF daily failed: %s", exc)

            except Exception as exc:
                logger.exception("Super-rebound scheduler loop error: %s", exc)

            # ---- 每日 23:00 超跌状态自动生成 ----
            try:
                from src.super_rebound import service as _service
                today = date.today()
                now_hour = datetime.now().hour
                status_done = getattr(app.state, "sr_daily_status_last_date", None)
                if (
                    now_hour == 23
                    and status_done != today
                    and today.weekday() < 5  # 只在交易日
                    and _service.is_schedule_enabled("daily_status_auto")
                ):
                    logger.info("Super-rebound daily status auto-generate (%s)", today)
                    for idx_code in ("沪深300", "科创50"):
                        logger.info("Super-rebound daily eval %s (%s)", idx_code, today)
                        try:
                            result = await asyncio.to_thread(_service.run_indicator_eval, idx_code)
                            logger.info("Super-rebound daily eval %s (%s): %s", idx_code, today,
                                        result.get("total_score", "pending"))
                        except Exception as exc:
                            logger.exception("Super-rebound daily eval %s failed: %s", idx_code, exc)
                        try:
                            await asyncio.to_thread(_service.refresh_volume_price_chip, idx_code)
                        except Exception as exc:
                            logger.exception("Super-rebound volume_price_chip %s failed: %s", idx_code, exc)
                        try:
                            await asyncio.to_thread(_service.refresh_rebound_tracking, idx_code)
                        except Exception as exc:
                            logger.exception("Super-rebound rebound_tracking %s failed: %s", idx_code, exc)
                    app.state.sr_daily_status_last_date = today
            except Exception as exc:
                logger.exception("Super-rebound daily status window error: %s", exc)

            await asyncio.sleep(_TICK_SECONDS)
    except asyncio.CancelledError:
        logger.info("Super-rebound scheduler stopped.")
