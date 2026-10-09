"""宏观量化汇总 Web API（挂载于 ``/api/macro/synthesis``）。

端点：
* ``GET  /coverage``            四团队当期结论覆盖情况
* ``POST /reports``             发起量化汇总（部分覆盖亦可）
* ``GET  /reports?economy=``    历史汇总报告列表
* ``GET  /reports/{id}``        单份报告详情
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from src.api.security import require_auth
from src.macro_synthesis.db import SynthesisDBError
from src.macro_synthesis.periods import InvalidPeriodError
from src.macro_synthesis.service import (
    MacroSynthesisService,
    SynthesisFailedError,
    SynthesisInProgressError,
    SynthesisLLMTimeoutError,
    SynthesisServiceError,
)

logger = logging.getLogger(__name__)


class SynthesisRequestBody(BaseModel):
    economy: str = Field(min_length=1, max_length=50)
    period_type: str = Field(default="month", max_length=10)
    period: Optional[str] = Field(default=None, max_length=20)
    allow_partial: bool = True


def get_synthesis_service() -> MacroSynthesisService:
    """工厂接缝；测试 monkeypatch 此函数注入伪服务。"""
    return MacroSynthesisService()


def _error_response(exc: SynthesisServiceError) -> dict:
    return {"detail": {"code": exc.code, "message": str(exc)}}


def register_macro_synthesis_routes(app: FastAPI) -> None:
    """在 FastAPI 应用上注册宏观量化汇总路由。"""

    @app.get(
        "/api/macro/synthesis/coverage",
        dependencies=[Depends(require_auth)],
    )
    def get_synthesis_coverage(
        economy: str = Query(..., min_length=1, max_length=50),
        period_type: str = Query("month", min_length=1, max_length=10),
        period: Optional[str] = Query(None, max_length=20),
        service: MacroSynthesisService = Depends(get_synthesis_service),
    ):
        try:
            resolved_period, teams = service.coverage(economy, period_type, period)
        except InvalidPeriodError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        from src.macro_synthesis.periods import period_label

        return {
            "status": "ok",
            "economy": economy,
            "period_type": period_type,
            "period": resolved_period,
            "period_label": period_label(period_type, resolved_period),
            "all_covered": all(team.present for team in teams),
            "teams": [team.to_dict() for team in teams],
        }

    @app.post(
        "/api/macro/synthesis/reports",
        dependencies=[Depends(require_auth)],
    )
    def create_synthesis_report(
        body: SynthesisRequestBody,
        service: MacroSynthesisService = Depends(get_synthesis_service),
    ):
        try:
            report, cached = service.synthesize(
                body.economy,
                period_type=body.period_type,
                period=body.period,
                allow_partial=body.allow_partial,
            )
        except InvalidPeriodError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SynthesisInProgressError as exc:
            return JSONResponse(status_code=409, content=_error_response(exc))
        except SynthesisLLMTimeoutError as exc:
            return JSONResponse(status_code=504, content=_error_response(exc))
        except SynthesisFailedError as exc:
            return JSONResponse(
                status=exc.status_code, content=_error_response(exc)
            )
        except SynthesisServiceError as exc:
            return JSONResponse(status_code=400, content=_error_response(exc))
        except SynthesisDBError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "status": "ok",
            "cached": cached,
            "report": report.to_dict(cached=cached),
        }

    @app.get(
        "/api/macro/synthesis/reports",
        dependencies=[Depends(require_auth)],
    )
    def list_synthesis_reports(
        economy: str = Query(..., min_length=1, max_length=50),
        service: MacroSynthesisService = Depends(get_synthesis_service),
    ):
        with service._get_repo() as repo:
            reports = repo.list_reports(economy)
        return {
            "status": "ok",
            "reports": [report.summary_row() for report in reports],
        }

    @app.get(
        "/api/macro/synthesis/reports/{report_id}",
        dependencies=[Depends(require_auth)],
    )
    def get_synthesis_report(
        report_id: int,
        service: MacroSynthesisService = Depends(get_synthesis_service),
    ):
        with service._get_repo() as repo:
            report = repo.get_report_by_id(report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="汇总报告不存在。")
        return {"status": "ok", "report": report.to_dict()}
