"""Background daily refresh scheduler for super-rebound margin + ETF flow.

Mirrors ``src.gold_monitor.scheduler`` — an ``asyncio`` task started from the
FastAPI lifespan (``src.api.lifecycle``).

Behaviour:
    * shortly after server startup, one catch-up sync runs (both margin + ETF);
    * afterwards the loop ticks every 15 min:
        - 23:00 (Beijing time) → 资金面数据自动采集：两融维持担保比例 + 国家队 ETF 净流入
          （两融数据 22:00 前后东方财富发布、ETF 份额接口盘后 20:30–22:00 更新，
           23:00 统一调度可保证两类数据源均已就绪）
        - 23:00 (Beijing time) → 每日超跌状态自动生成（沪深 300 + 科创 50）
    每个任务每交易日最多执行一次。非交易日（周末/节假日）跳过。
    Failures are logged but never kill the server.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

_TICK_SECONDS = 60 * 15          # 15 min — fine granularity
_STARTUP_DELAY_SECONDS = 30      # catch-up shortly after boot
_FINANCE_HOUR = 23               # 23:00 (北京时间) — 资金面定时采集
_DAILY_STATUS_HOUR = 23          # 23:00 (北京时间) — 每日超跌状态定时生成


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
        "(tick=%ds finance_hour=%d daily_status_hour=%d)",
        _TICK_SECONDS, _FINANCE_HOUR, _DAILY_STATUS_HOUR,
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
                now_hour = datetime.now().hour
                is_trading_day = today.weekday() < 5  # 周一至周五

                # ---- 每交易日 23:00 资金面数据自动采集（两融 + ETF）----
                margin_done = getattr(app.state, "sr_margin_last_date", None)
                etf_done = getattr(app.state, "sr_etf_last_date", None)

                if (
                    now_hour == _FINANCE_HOUR
                    and is_trading_day
                    and margin_done != today
                ):
                    try:
                        result = await asyncio.to_thread(
                            service._sync_margin_incremental
                        )
                        app.state.sr_margin_last_date = today
                        logger.info("Super-rebound 资金面-两融自动采集 (%s): %d rows", today, result)
                    except Exception as exc:
                        logger.exception("Super-rebound 资金面-两融自动采集失败: %s", exc)

                if (
                    now_hour == _FINANCE_HOUR
                    and is_trading_day
                    and etf_done != today
                ):
                    try:
                        result = await asyncio.to_thread(service.refresh_etf_flow)
                        app.state.sr_etf_last_date = today
                        logger.info(
                            "Super-rebound 资金面-ETF净流入自动采集 (%s): upsert=%d updated=%d missing=%s szse_skipped=%d",
                            today,
                            result.get("sse_upserted"),
                            result.get("sse_updated"),
                            result.get("sse_missing_codes"),
                            result.get("szse_skipped"),
                        )
                    except Exception as exc:
                        logger.exception("Super-rebound 资金面-ETF净流入自动采集失败: %s", exc)

                # ---- 每交易日 23:00 每日超跌状态自动生成 ----
                try:
                    from src.super_rebound import service as _service
                    status_done = getattr(app.state, "sr_daily_status_last_date", None)
                    if (
                        now_hour == _DAILY_STATUS_HOUR
                        and is_trading_day
                        and status_done != today
                        and _service.is_schedule_enabled("daily_status_auto")
                    ):
                        logger.info("Super-rebound 每日超跌状态自动生成 (%s)", today)
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

            except Exception as exc:
                logger.exception("Super-rebound scheduler loop error: %s", exc)

            await asyncio.sleep(_TICK_SECONDS)
    except asyncio.CancelledError:
        logger.info("Super-rebound scheduler stopped.")
