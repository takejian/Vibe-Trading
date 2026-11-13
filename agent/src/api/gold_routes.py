"""HTTP routes for the gold monitor module (``/api/gold/*``).

Mounted by ``agent/api_server.py`` via ``register_gold_routes(app)``.
All endpoints are behind ``require_auth``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.security import require_auth
from src.gold_monitor.exceptions import (
    GoldCycleDetectError,
    GoldDataError,
    GoldLLMError,
    GoldMonitorError,
    GoldValidationError,
)
from src.gold_monitor import service

logger = logging.getLogger(__name__)


# --- Request bodies ---------------------------------------------------------

class ConfirmDiffRequest(BaseModel):
    target_month: str = Field(..., description="YYYY-MM to confirm")
    accept_fields: list[str] | None = Field(default=None, description="Fields to accept; None = all")


class ApproveCycleRequest(BaseModel):
    pass


class ImportExcelRequest(BaseModel):
    excel_path: str = Field(..., min_length=1)


class UpdatePromptRequest(BaseModel):
    system_prompt: str = Field(..., min_length=1)
    user_prompt: str = Field(..., min_length=1)


class UpdateConfidenceRequest(BaseModel):
    confidence: float = Field(..., ge=0, le=1)


class UpdatePostHocConfidenceRequest(BaseModel):
    confidence: float | None = Field(default=None, ge=0, le=1)


# --- Registration -----------------------------------------------------------

def register_gold_routes(app: FastAPI) -> None:
    """Mount all /api/gold/* routes behind ``require_auth``."""

    @app.get("/api/gold/current", dependencies=[Depends(require_auth)])
    def gold_current() -> dict[str, Any]:
        try:
            return service.get_current_status()
        except GoldDataError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/gold/monthly", dependencies=[Depends(require_auth)])
    def gold_monthly(limit: int = Query(default=0, ge=0)) -> dict[str, Any]:
        with gold_connection_helper():
            from src.gold_monitor import db
            rows = db.get_all_monthly()
        if limit > 0:
            rows = rows[-limit:]
        return {"items": rows, "count": len(rows)}

    @app.get("/api/gold/cycles", dependencies=[Depends(require_auth)])
    def gold_cycles() -> dict[str, Any]:
        return {"items": service.list_cycles()}

    @app.get("/api/gold/cycles/{cycle_id}/months", dependencies=[Depends(require_auth)])
    def gold_cycle_months(cycle_id: int) -> dict[str, Any]:
        try:
            return service.get_cycle_months(cycle_id)
        except GoldDataError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/gold/refresh", dependencies=[Depends(require_auth)])
    def gold_refresh() -> dict[str, Any]:
        try:
            return service.trigger_refresh(source="manual")
        except GoldLLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except GoldMonitorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/gold/confirm", dependencies=[Depends(require_auth)])
    def gold_confirm(body: ConfirmDiffRequest) -> dict[str, Any]:
        try:
            return service.confirm_diff(body.target_month, body.accept_fields)
        except GoldDataError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except GoldLLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/gold/cycle/{cycle_id}/approve", dependencies=[Depends(require_auth)])
    def gold_cycle_approve(cycle_id: int) -> dict[str, Any]:
        try:
            return service.approve_cycle(cycle_id)
        except GoldDataError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/gold/refresh-needed", dependencies=[Depends(require_auth)])
    def gold_refresh_needed() -> dict[str, Any]:
        return service.check_refresh_needed()

    @app.post("/api/gold/import-excel", dependencies=[Depends(require_auth)])
    def gold_import_excel(body: ImportExcelRequest) -> dict[str, Any]:
        try:
            return service.import_excel(body.excel_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=f"Excel not found: {body.excel_path}") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Import failed: {exc}") from exc

    # --- V2: policy-cycle trend chart ---
    @app.get("/api/gold/cycle-trend", dependencies=[Depends(require_auth)])
    def gold_cycle_trend() -> dict[str, Any]:
        try:
            return service.get_cycle_trend()
        except GoldDataError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # --- V2: indicator signals ---
    @app.get("/api/gold/signals", dependencies=[Depends(require_auth)])
    def gold_signals() -> dict[str, Any]:
        return service.get_all_signals()

    @app.post("/api/gold/signals/{indicator_key}/refresh", dependencies=[Depends(require_auth)])
    def gold_signal_refresh(indicator_key: str) -> dict[str, Any]:
        try:
            return service.refresh_signal(indicator_key, source="manual")
        except GoldDataError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except GoldLLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/gold/signals/refresh-all", dependencies=[Depends(require_auth)])
    def gold_signals_refresh_all() -> dict[str, Any]:
        return service.refresh_all_signals(source="manual")

    @app.get("/api/gold/signals/{indicator_key}/history", dependencies=[Depends(require_auth)])
    def gold_signal_history(indicator_key: str, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        try:
            return service.get_signal_history(indicator_key, limit=limit)
        except GoldDataError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/gold/signals/{signal_id}/confidence", dependencies=[Depends(require_auth)])
    def gold_signal_confidence(signal_id: str, body: UpdateConfidenceRequest) -> dict[str, Any]:
        try:
            return service.update_signal_confidence(signal_id, body.confidence)
        except GoldDataError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except GoldValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- V2: prompts ---
    @app.get("/api/gold/prompts/{indicator_key}", dependencies=[Depends(require_auth)])
    def gold_get_prompt(indicator_key: str) -> dict[str, Any]:
        try:
            return service.get_prompt(indicator_key)
        except GoldDataError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/gold/prompts/{indicator_key}", dependencies=[Depends(require_auth)])
    def gold_update_prompt(indicator_key: str, body: UpdatePromptRequest) -> dict[str, Any]:
        try:
            return service.update_prompt(indicator_key, body.system_prompt, body.user_prompt)
        except GoldDataError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- V2: FOMC ---
    @app.get("/api/gold/fomc", dependencies=[Depends(require_auth)])
    def gold_fomc() -> dict[str, Any]:
        return service.get_next_fomc()

    @app.post("/api/gold/fomc/refresh", dependencies=[Depends(require_auth)])
    def gold_fomc_refresh() -> dict[str, Any]:
        try:
            return service.refresh_fomc()
        except GoldLLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    # --- V2: cycle-level 5-dimension state + post-hoc confidence ---
    @app.get("/api/gold/cycles/{cycle_id}/signals", dependencies=[Depends(require_auth)])
    def gold_cycle_signals(cycle_id: int) -> dict[str, Any]:
        try:
            return service.get_cycle_signals(cycle_id)
        except GoldDataError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/gold/cycles/{cycle_id}/post-hoc-confidence", dependencies=[Depends(require_auth)])
    def gold_cycle_post_hoc_confidence(cycle_id: int, body: UpdatePostHocConfidenceRequest) -> dict[str, Any]:
        try:
            return service.update_cycle_post_hoc_confidence(cycle_id, body.confidence)
        except GoldDataError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except GoldValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- V3: gold daily bar (SHFE AU0 via akshare, MySQL) ---
    @app.get("/api/gold/daily-bar", dependencies=[Depends(require_auth)])
    def gold_daily_bar(
        limit: int = Query(default=0, ge=0, le=2000),
        symbol: str = Query(default="AU0"),
    ) -> dict[str, Any]:
        from src.gold_monitor import daily_service
        if not daily_service.has_data(symbol):
            raise HTTPException(status_code=404, detail=f"gold_daily_bar 中无 symbol={symbol} 的数据, 请先 POST /api/gold/daily-refresh 初始化")
        bars = daily_service.get_daily_bars(symbol=symbol, limit=limit or None)
        latest = daily_service.get_latest_bar(symbol)
        latest_summary = daily_service.get_latest_price_summary(symbol)
        return {
            "symbol": symbol,
            "count": len(bars),
            "latest": latest,
            "latest_summary": latest_summary,
            "items": bars,
        }

    @app.get("/api/gold/daily-bar/latest", dependencies=[Depends(require_auth)])
    def gold_daily_bar_latest(symbol: str = Query(default="AU0")) -> dict[str, Any]:
        from src.gold_monitor import daily_service
        summary = daily_service.get_latest_price_summary(symbol)
        if summary is None:
            raise HTTPException(status_code=404, detail=f"gold_daily_bar 中无 symbol={symbol} 的数据")
        return summary

    @app.post("/api/gold/daily-refresh", dependencies=[Depends(require_auth)])
    def gold_daily_refresh(
        refresh_type: str = Query(default="manual", pattern="^(manual|scheduled|init)$"),
        symbol: str = Query(default="AU0"),
        force: bool = Query(default=False),
    ) -> dict[str, Any]:
        from src.gold_monitor import daily_service
        try:
            return daily_service.refresh_gold_daily(
                refresh_type=refresh_type, symbol=symbol, force=force,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("gold_daily_refresh failed")
            raise HTTPException(status_code=502, detail=f"akshare 拉取失败: {exc}") from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def gold_connection_helper():
    """Context manager used by routes that need direct db access."""
    from contextlib import contextmanager
    from src.gold_monitor.db import gold_connection, initialize_schema

    @contextmanager
    def _ctx():
        conn = gold_connection()
        initialize_schema(conn)
        try:
            yield conn
        finally:
            conn.close()

    return _ctx()
