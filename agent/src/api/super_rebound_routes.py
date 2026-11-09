"""HTTP routes for the super-rebound (超跌反弹) finance module.

Mounted by ``agent/api_server.py`` via ``register_super_rebound_routes(app)``.
All endpoints are behind ``require_auth``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query

from src.api.security import require_auth
from src.super_rebound import service

logger = logging.getLogger(__name__)


def register_super_rebound_routes(app: FastAPI) -> None:
    """Mount all /api/super-rebound/* routes behind require_auth."""

    @app.get("/api/super-rebound/finance/margin-ratio", dependencies=[Depends(require_auth)])
    def rebound_margin_ratio() -> dict[str, Any]:
        result = service.get_margin_ratio_latest()
        if result.get("error") == "no_data":
            raise HTTPException(status_code=404, detail=result.get("message", "No data"))
        return result

    @app.get("/api/super-rebound/finance/etf-monitor", dependencies=[Depends(require_auth)])
    def rebound_etf_monitor(
        start_date: str | None = Query(default=None, description="YYYY-MM-DD"),
        end_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    ) -> dict[str, Any]:
        """ETF 净流入头部汇总（份额口径，上交所官方数据源）。"""
        return service.get_etf_flow_overview(start_date, end_date)

    @app.get("/api/super-rebound/finance/etf-monitor-detail", dependencies=[Depends(require_auth)])
    def rebound_etf_monitor_detail(
        start_date: str | None = Query(default=None, description="YYYY-MM-DD"),
        end_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    ) -> dict[str, Any]:
        """ETF 净流入每日明细 + 累计（份额口径）。"""
        return service.get_etf_flow_detail(start_date, end_date)

    @app.get("/api/super-rebound/finance/etf-flow-overview", dependencies=[Depends(require_auth)])
    def rebound_etf_flow_overview(
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return service.get_etf_flow_overview(start_date, end_date)

    @app.get("/api/super-rebound/finance/etf-flow-detail", dependencies=[Depends(require_auth)])
    def rebound_etf_flow_detail(
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return service.get_etf_flow_detail(start_date, end_date)

    @app.post("/api/super-rebound/finance/etf-flow-collect", dependencies=[Depends(require_auth)])
    def rebound_etf_flow_collect() -> dict[str, Any]:
        """手动触发 ETF 净流入采集（上交所官方接口，最新交易日）。"""
        try:
            return service.refresh_etf_flow()
        except Exception as exc:
            logger.exception("etf flow collect failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/super-rebound/finance/etf-flow-backfill", dependencies=[Depends(require_auth)])
    def rebound_etf_flow_backfill(
        start_date: str = Query(..., description="起始 YYYY-MM-DD"),
        end_date: str = Query(..., description="结束 YYYY-MM-DD"),
    ) -> dict[str, Any]:
        """上交所 ETF 历史份额回灌（官方 scale 接口，按交易日循环）。"""
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
            return service.backfill_etf_history(start, end)
        except Exception as exc:
            logger.exception("etf flow backfill failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/super-rebound/finance/refresh-needed", dependencies=[Depends(require_auth)])
    def rebound_refresh_needed() -> dict[str, Any]:
        return service.refresh_needed()

    @app.post("/api/super-rebound/finance/refresh", dependencies=[Depends(require_auth)])
    def rebound_refresh() -> dict[str, Any]:
        try:
            return service.refresh_data()
        except Exception as exc:
            logger.exception("super-rebound refresh failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    # --- Indicator (超跌指标) routes ---

    @app.get("/api/super-rebound/indicator/defs", dependencies=[Depends(require_auth)])
    def rebound_indicator_defs() -> dict[str, Any]:
        return {"indicator_defs": service.get_indicator_defs()}

    @app.post("/api/super-rebound/indicator/defs", dependencies=[Depends(require_auth)])
    def rebound_indicator_defs_upsert(body: dict[str, Any]) -> dict[str, Any]:
        created = service.upsert_indicator_def(body)
        return {"created": created, "indicator": body}

    @app.delete("/api/super-rebound/indicator/defs/{def_id}", dependencies=[Depends(require_auth)])
    def rebound_indicator_def_delete(def_id: int) -> dict[str, Any]:
        deleted = service.delete_indicator_def(def_id)
        return {"deleted": deleted, "def_id": def_id}

    @app.get("/api/super-rebound/indicator/prompts", dependencies=[Depends(require_auth)])
    def rebound_indicator_prompts() -> dict[str, Any]:
        return {"prompts": service.get_prompts()}

    @app.get("/api/super-rebound/indicator/prompts/{prompt_type}", dependencies=[Depends(require_auth)])
    def rebound_indicator_prompt_by_type(prompt_type: str) -> dict[str, Any]:
        prompt = service.get_prompt(prompt_type)
        if not prompt:
            raise HTTPException(status_code=404, detail=f"Prompt {prompt_type} not found")
        return {"prompt": prompt}

    @app.put("/api/super-rebound/indicator/prompts", dependencies=[Depends(require_auth)])
    def rebound_indicator_prompt_upsert(body: dict[str, Any]) -> dict[str, Any]:
        if "prompt_type" not in body:
            raise HTTPException(status_code=400, detail="prompt_type required")
        created = service.upsert_prompt(body)
        return {"created": created, "prompt_type": body["prompt_type"]}

    @app.post("/api/super-rebound/indicator/eval", dependencies=[Depends(require_auth)])
    def rebound_indicator_eval(
        index_code: str = Query(default="沪深300"),
    ) -> dict[str, Any]:
        """手动触发指标评估（LLM 取值 + 本地 0/1 判断 + 写库）。"""
        try:
            return service.run_indicator_eval(index_code)
        except Exception as exc:
            logger.exception("indicator eval failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    # --- Daily status (每日超跌状态) routes ---

    @app.get("/api/super-rebound/daily-status/list", dependencies=[Depends(require_auth)])
    def rebound_daily_status_list(
        start_date: str | None = Query(default=None, description="YYYY-MM-DD"),
        end_date: str | None = Query(default=None, description="YYYY-MM-DD"),
        index_code: str = Query(default="沪深300"),
        days: int = Query(default=30),
    ) -> dict[str, Any]:
        return service.get_daily_status_list(start_date, end_date, index_code, days)

    @app.post("/api/super-rebound/daily-status/volume-price-chip/refresh", dependencies=[Depends(require_auth)])
    def rebound_refresh_volume_price_chip(
        index_code: str = Query(default="沪深300"),
    ) -> dict[str, Any]:
        try:
            return service.refresh_volume_price_chip(index_code)
        except Exception as exc:
            logger.exception("volume_price_chip refresh failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/super-rebound/daily-status/rebound-tracking/refresh", dependencies=[Depends(require_auth)])
    def rebound_refresh_rebound_tracking(
        index_code: str = Query(default="沪深300"),
    ) -> dict[str, Any]:
        try:
            return service.refresh_rebound_tracking(index_code)
        except Exception as exc:
            logger.exception("rebound_tracking refresh failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/super-rebound/daily-status/schedule", dependencies=[Depends(require_auth)])
    def rebound_schedule_get(
        task_name: str = Query(default="daily_status_auto"),
    ) -> dict[str, Any]:
        return {"schedule": service.get_schedule_config(task_name)}

    @app.put("/api/super-rebound/daily-status/schedule", dependencies=[Depends(require_auth)])
    def rebound_schedule_toggle(body: dict[str, Any]) -> dict[str, Any]:
        task_name = body.get("task_name", "daily_status_auto")
        is_enabled = bool(body.get("is_enabled", True))
        return service.toggle_schedule(task_name, is_enabled)

    # --- Schema init endpoint (called once on startup) ---

    @app.post("/api/super-rebound/schema/ensure", dependencies=[Depends(require_auth)])
    def rebound_schema_ensure() -> dict[str, Any]:
        try:
            return service.ensure_schema_seeded()
        except Exception as exc:
            logger.exception("schema ensure failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc
