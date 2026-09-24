"""Authenticated Web API for the macro-economic analysis module.

Endpoints (all mounted under ``/api/macro``):

* prompts: list/get/edit the a/b/c prompt definitions (edit needs settings
  write authorization)
* economies: preset economy list
* readiness: macro data availability probe result
* cycle judgments: run one (POST), list history, fetch one detail
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from src.api.security import (
    LOOPBACK_SUBJECT,
    SHARED_KEY_SUBJECT,
    require_auth,
    require_settings_write_auth,
)
from src.macro.db import MacroDataAccessError
from src.macro.models import DataReadiness
from src.macro.prompts import EDITABLE_CODES
from src.macro.service import (
    MacroAnalysisService,
    MacroDataInsufficientError,
    MacroGenerationInProgressError,
    MacroLLMTimeoutError,
    MacroServiceError,
    PromptNotEditableError,
    PromptNotFoundError,
    UnsupportedEconomyError,
)
from src.session.models import Principal

logger = logging.getLogger(__name__)


class MacroJudgeRequest(BaseModel):
    economy: str = Field(min_length=1, max_length=50)
    statistics_date: Optional[str] = Field(default=None, max_length=20)
    supplement: Optional[str] = Field(default=None, max_length=4000)


class MacroPromptUpdateRequest(BaseModel):
    prompt_text: str = Field(min_length=1, max_length=20000)


def get_macro_service() -> MacroAnalysisService:
    """Factory seam; tests monkeypatch this to inject a fake-backed service."""
    return MacroAnalysisService()


def _can_edit(principal: Principal) -> bool:
    """Every authenticated principal in the local-first model may edit.

    Loopback operators and shared-key holders are the two principals that
    ``require_auth`` can produce, and both satisfy the settings-write rule
    (loopback trust when no key is configured; the key itself otherwise).
    """
    return principal.subject in (LOOPBACK_SUBJECT, SHARED_KEY_SUBJECT)


def _prompt_payload(prompt: Any, can_edit: bool) -> dict[str, Any]:
    data = prompt.to_dict()
    data["editable"] = prompt.code in EDITABLE_CODES
    # Non-editable reserved prompts only expose their placeholder, never an
    # editable-looking empty body.
    data["can_edit"] = can_edit
    return data


def _readiness_payload(readiness: DataReadiness) -> dict[str, Any]:
    return {
        "ready": readiness.ready,
        "latest_month": readiness.latest_month,
        "reason": readiness.reason,
    }


def register_macro_routes(app: FastAPI) -> None:
    """Register macro analysis routes on the FastAPI application."""

    # -- prompts ---------------------------------------------------------

    @app.get("/api/macro/prompts", dependencies=[Depends(require_auth)])
    def list_macro_prompts(
        principal: Principal = Depends(require_auth),
        service: MacroAnalysisService = Depends(get_macro_service),
    ):
        try:
            prompts = service.list_prompts()
        except MacroDataAccessError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        can_edit = _can_edit(principal)
        return {"status": "ok", "prompts": [_prompt_payload(p, can_edit) for p in prompts]}

    @app.get("/api/macro/prompts/{code}", dependencies=[Depends(require_auth)])
    def get_macro_prompt(
        code: str,
        principal: Principal = Depends(require_auth),
        service: MacroAnalysisService = Depends(get_macro_service),
    ):
        try:
            prompt = service.get_prompt(code)
        except PromptNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MacroDataAccessError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"status": "ok", "prompt": _prompt_payload(prompt, _can_edit(principal))}

    @app.put(
        "/api/macro/prompts/{code}",
        dependencies=[Depends(require_settings_write_auth)],
    )
    def update_macro_prompt(
        code: str,
        body: MacroPromptUpdateRequest,
        service: MacroAnalysisService = Depends(get_macro_service),
    ):
        try:
            prompt = service.update_prompt_text(code, body.prompt_text)
        except PromptNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PromptNotEditableError as exc:
            return JSONResponse(
                status_code=409,
                content={"detail": {"code": "prompt_not_editable", "message": str(exc)}},
            )
        except MacroServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MacroDataAccessError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"status": "ok", "prompt": _prompt_payload(prompt, can_edit=True)}

    # -- economies / readiness ------------------------------------------

    @app.get("/api/macro/economies", dependencies=[Depends(require_auth)])
    def list_macro_economies(service: MacroAnalysisService = Depends(get_macro_service)):
        return {"status": "ok", "economies": service.list_economies()}

    @app.get("/api/macro/readiness", dependencies=[Depends(require_auth)])
    def macro_readiness(
        economy: str = Query(..., min_length=1, max_length=50),
        service: MacroAnalysisService = Depends(get_macro_service),
    ):
        try:
            readiness = service.assess_readiness(economy)
        except UnsupportedEconomyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "ok", "readiness": _readiness_payload(readiness)}

    # -- cycle judgments -------------------------------------------------

    @app.post("/api/macro/cycle/judgments", dependencies=[Depends(require_auth)])
    def run_macro_cycle_judgment(
        body: MacroJudgeRequest,
        service: MacroAnalysisService = Depends(get_macro_service),
    ):
        try:
            result = service.judge(
                body.economy,
                statistics_date=body.statistics_date,
                supplement=body.supplement,
            )
        except MacroDataInsufficientError as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "detail": {
                        "code": exc.code,
                        "message": str(exc),
                        "readiness": _readiness_payload(exc.readiness),
                    }
                },
            )
        except MacroGenerationInProgressError as exc:
            return JSONResponse(
                status_code=409,
                content={"detail": {"code": exc.code, "message": str(exc)}},
            )
        except MacroLLMTimeoutError as exc:
            return JSONResponse(
                status_code=504,
                content={"detail": {"code": exc.code, "message": str(exc)}},
            )
        except (UnsupportedEconomyError, MacroServiceError) as exc:
            status = getattr(exc, "status_code", 400)
            code = getattr(exc, "code", "analysis_failed")
            return JSONResponse(
                status_code=status,
                content={"detail": {"code": code, "message": str(exc)}},
            )
        except MacroDataAccessError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "status": "ok",
            "cached": result.cached,
            "judgment": result.judgment.to_dict(),
        }

    @app.get(
        "/api/macro/cycle/judgments",
        dependencies=[Depends(require_auth)],
    )
    def list_macro_cycle_judgments(
        economy: str = Query(..., min_length=1, max_length=50),
        service: MacroAnalysisService = Depends(get_macro_service),
    ):
        try:
            judgments = service.list_judgments(economy)
        except UnsupportedEconomyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MacroDataAccessError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "status": "ok",
            "economy": judgments[0].economy if judgments else economy,
            "judgments": [j.to_dict() for j in judgments],
        }

    @app.get(
        "/api/macro/cycle/judgments/{economy}/{statistics_date}",
        dependencies=[Depends(require_auth)],
    )
    def get_macro_cycle_judgment(
        economy: str,
        statistics_date: str,
        service: MacroAnalysisService = Depends(get_macro_service),
    ):
        try:
            judgment = service.get_judgment(economy, statistics_date)
        except UnsupportedEconomyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PromptNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MacroServiceError as exc:
            raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc)) from exc
        except MacroDataAccessError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"status": "ok", "judgment": judgment.to_dict()}
