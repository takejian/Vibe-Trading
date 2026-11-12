"""HTTP routes for the super-rebound (超跌反弹) finance module.

Mounted by ``agent/api_server.py`` via ``register_super_rebound_routes(app)``.
All endpoints are behind ``require_auth``.
"""

from __future__ import annotations

import logging
import re
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

    # ⚠️ 顺序敏感：静态路径 "/prompts/full" 必须在动态路径 "/prompts/{prompt_type}" 之前
    # FastAPI 按定义顺序匹配，full 被 {prompt_type} 捕获就会报 404 Prompt full not found

    @app.get("/api/super-rebound/indicator/prompts/full", dependencies=[Depends(require_auth)])
    def rebound_indicator_prompt_full(
        prompt_type: str = Query(default="oversold_indicator"),
    ) -> dict[str, Any]:
        """直接返回 DB 里存的完整提示词（已经是 [System]+[User] 组装好的）。"""
        full_prompt = service.get_full_prompt_from_db()
        # 同时把 base_user_hint 也返回（用户编辑时可能想知道那段）
        base_hint = ""
        m = re.search(
            r"【详细要求】\s*\n(.*?)\n\s*【当前需要返回的指标清单】",
            full_prompt, re.DOTALL,
        )
        if m:
            base_hint = m.group(1).strip()
        return {
            "prompt_type": prompt_type,
            "prompt_name": "超跌指标取值提示词",
            "full_prompt": full_prompt,
            "base_user_hint": base_hint,
        }

    @app.post("/api/super-rebound/indicator/prompts/full-save", dependencies=[Depends(require_auth)])
    def rebound_indicator_prompt_full_save(body: dict[str, Any]) -> dict[str, Any]:
        """保存完整提示词到 DB。

        直接把前端编辑框里的 [System]...[User]... 全量文本写进 prompt_content。
        如果是 oversold_indicator，保存后还会刷新一次（确保指标清单和最新 defs 对齐）。
        """
        prompt_type = body.get("prompt_type", "oversold_indicator")
        prompt_name = body.get("prompt_name", "超跌指标取值提示词")
        full_prompt = body.get("full_prompt", "").strip()
        if not full_prompt:
            raise HTTPException(status_code=400, detail="full_prompt required")

        service.upsert_prompt({
            "prompt_type": prompt_type,
            "prompt_name": prompt_name,
            "prompt_content": full_prompt,  # ← 完整文本直接写
        })

        # oversold_indicator：保存后再 regenerate 一次，用最新 indicator_defs 覆盖
        # 【当前需要返回的指标清单】段，保证指标变动立即生效
        if prompt_type == "oversold_indicator":
            regenerated = service.refresh_full_prompt_in_db()
            return {"saved": True, "regenerated": True, "full_prompt": regenerated}

        return {"saved": True, "full_prompt": full_prompt}

    # 动态路径放最后
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

    @app.get("/api/super-rebound/indicator/latest", dependencies=[Depends(require_auth)])
    def rebound_indicator_latest(
        index_code: str = Query(default="沪深300"),
    ) -> dict[str, Any]:
        """从 DB 读最近一次 eval 结果（不调 LLM，ms 级响应）。
        用于页面初始加载和切换指数时展示缓存结果。"""
        result = service.get_latest_eval_result(index_code)
        if result is None:
            return {"has_data": False, "message": "暂无 eval 结果，请先手动触发"}
        return {"has_data": True, "result": result}

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
