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
