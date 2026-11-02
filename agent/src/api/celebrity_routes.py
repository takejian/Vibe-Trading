"""HTTP routes for the investment celebrity module (``/api/celebrity/*``)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.api.security import require_auth
from src.celebrity import service
from src.celebrity.service import (
    CelebrityError,
    CelebrityLLMError,
    CelebrityNotFoundError,
    CelebrityValidationError,
)

logger = logging.getLogger(__name__)


# --- Request bodies ---------------------------------------------------------

class AddInvestorRequest(BaseModel):
    name: str = Field(..., min_length=1)
    invest_style: str = ""
    remark: str = ""


class UpdateStyleRequest(BaseModel):
    invest_style: str = ""


class SavePerformanceRequest(BaseModel):
    recent_performance: str = ""
    return_1y: str = ""
    return_3y: str = ""
    return_5y: str = ""
    return_10y: str = ""
    max_drawdown: str = ""
    stability_tag: str = ""
    stability_desc: str = ""
    peer_compare: str = ""
    risk_note: str = ""


class ReviewOpinionsRequest(BaseModel):
    investor_id: int
    items: list[dict[str, Any]] = Field(default_factory=list)


class ReviewAdjustsRequest(BaseModel):
    investor_id: int
    items: list[dict[str, Any]] = Field(default_factory=list)


class UpdatePromptRequest(BaseModel):
    content: str = Field(..., min_length=1)


# --- Registration -----------------------------------------------------------

def register_celebrity_routes(app: FastAPI) -> None:
    """Mount all /api/celebrity/* routes behind require_auth."""

    def _handle(exc: CelebrityError) -> HTTPException:
        if isinstance(exc, CelebrityNotFoundError):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, CelebrityValidationError):
            return HTTPException(status_code=400, detail=str(exc))
        if isinstance(exc, CelebrityLLMError):
            return HTTPException(status_code=502, detail=str(exc))
        return HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/celebrity/investors", dependencies=[Depends(require_auth)])
    def list_investors() -> dict[str, Any]:
        return {"items": service.list_investors()}

    @app.post("/api/celebrity/investors", dependencies=[Depends(require_auth)])
    def add_investor(req: AddInvestorRequest) -> dict[str, Any]:
        try:
            return service.add_investor(req.name, req.invest_style, req.remark)
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.delete("/api/celebrity/investors/{investor_id}", dependencies=[Depends(require_auth)])
    def delete_investor(investor_id: int) -> dict[str, Any]:
        try:
            return service.delete_investor(investor_id)
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.get("/api/celebrity/investors/{investor_id}/card", dependencies=[Depends(require_auth)])
    def get_card(investor_id: int) -> dict[str, Any]:
        try:
            return service.get_investor_card(investor_id)
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.post("/api/celebrity/investors/{investor_id}/refresh", dependencies=[Depends(require_auth)])
    def refresh_investor(investor_id: int) -> dict[str, Any]:
        try:
            return service.refresh_investor(investor_id)
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.post("/api/celebrity/investors/{investor_id}/backfill", dependencies=[Depends(require_auth)])
    def backfill_history(investor_id: int) -> dict[str, Any]:
        try:
            return service.backfill_history(investor_id)
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.get("/api/celebrity/investors/{investor_id}/performance", dependencies=[Depends(require_auth)])
    def get_performance(investor_id: int) -> dict[str, Any]:
        try:
            perf = service.get_performance(investor_id)
            return {"performance": perf}
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.post("/api/celebrity/investors/{investor_id}/performance", dependencies=[Depends(require_auth)])
    def generate_performance(investor_id: int) -> dict[str, Any]:
        try:
            return service.generate_performance(investor_id)
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.put("/api/celebrity/investors/{investor_id}/performance", dependencies=[Depends(require_auth)])
    def save_performance(investor_id: int, req: SavePerformanceRequest) -> dict[str, Any]:
        try:
            return service.save_performance(investor_id, req.model_dump())
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.put("/api/celebrity/investors/{investor_id}/style", dependencies=[Depends(require_auth)])
    def update_style(investor_id: int, req: UpdateStyleRequest) -> dict[str, Any]:
        try:
            return service.update_invest_style(investor_id, req.invest_style)
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.post("/api/celebrity/review/opinions", dependencies=[Depends(require_auth)])
    def review_opinions(req: ReviewOpinionsRequest) -> dict[str, Any]:
        try:
            return service.review_opinions(req.investor_id, req.items)
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.post("/api/celebrity/review/adjusts", dependencies=[Depends(require_auth)])
    def review_adjusts(req: ReviewAdjustsRequest) -> dict[str, Any]:
        try:
            return service.review_adjusts(req.investor_id, req.items)
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.get("/api/celebrity/weekly", dependencies=[Depends(require_auth)])
    def weekly_dynamics() -> dict[str, Any]:
        return service.get_weekly_dynamics()

    @app.get("/api/celebrity/prompts/{key}", dependencies=[Depends(require_auth)])
    def get_prompt(key: str) -> dict[str, Any]:
        try:
            return service.get_prompt(key)
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.put("/api/celebrity/prompts/{key}", dependencies=[Depends(require_auth)])
    def update_prompt(key: str, req: UpdatePromptRequest) -> dict[str, Any]:
        try:
            return service.update_prompt(key, req.content)
        except CelebrityError as exc:
            raise _handle(exc) from exc

    @app.post("/api/celebrity/prompts/{key}/reset", dependencies=[Depends(require_auth)])
    def reset_prompt(key: str) -> dict[str, Any]:
        try:
            return service.reset_prompt(key)
        except CelebrityError as exc:
            raise _handle(exc) from exc
