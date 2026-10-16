"""HTTP routes for event analysis (``/events/*``).

Two surfaces:
* breaking radar — scan runs, event stream, event detail, human review;
* macro Task Force — start live/retrospective runs, list/get reports.

Scan execution is asynchronous (daemon thread); clients poll the scan-run
row and then re-fetch the event stream. Report rows reconcile lazily
against the swarm run store on every read.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.security import require_auth
from src.api.swarm_routes import _get_swarm_runtime
from src.eventradar import service

logger = logging.getLogger(__name__)


class ScanBody(BaseModel):
    scope: str = Field(default="all", pattern="^(china|global|all)$")


class VerifyBody(BaseModel):
    action: str = Field(pattern="^(confirm|flag_dispute|mark_rumor|dismiss)$")
    note: str | None = None


class AnalyzeBody(BaseModel):
    mode: str = Field(default="live", pattern="^(live|retrospective)$")
    market: str = "A股+全球"
    time_horizon: str = ""


class CustomAnalyzeBody(BaseModel):
    event_title: str = Field(min_length=1, max_length=200)
    event_period: str = ""
    market: str = "A股+全球"
    mode: str = Field(default="retrospective", pattern="^retrospective$")


class ArchiveBody(BaseModel):
    archived: bool = True


class EvaluationBody(BaseModel):
    rating: str = Field(pattern="^(accurate|partial|off|wrong)$")
    note: str | None = None
    period_start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    related_report_id: str | None = None


def _handle_service_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, service.ScanInProgress):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, service.EventNotConfirmed):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, service.EventNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, service.EventRadarError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


def register_event_routes(app: FastAPI) -> None:
    """Mount all /events/* routes, each behind ``require_auth``."""

    # -- Scan -----------------------------------------------------------

    @app.post("/events/scan", dependencies=[Depends(require_auth)])
    def start_scan(body: ScanBody) -> dict[str, Any]:
        try:
            return service.start_scan(body.scope)
        except Exception as exc:  # mapped service errors
            raise _handle_service_errors(exc) from exc

    @app.get("/events/scan-runs", dependencies=[Depends(require_auth)])
    def list_scan_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
        return service.list_scan_runs(limit=limit)

    # -- Daily picks / archive / Task Force candidates (v1.2) ----------

    @app.get("/events/daily-picks", dependencies=[Depends(require_auth)])
    def list_daily_picks(
        date_from: str | None = Query(default=None),
        date_to: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        return {"items": service.daily_picks(date_from, date_to, limit)}

    @app.get("/events/tf-candidates", dependencies=[Depends(require_auth)])
    def list_tf_candidates(
        days: int | None = Query(default=None, ge=1, le=365),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return {"items": service.tf_candidates(days=days, limit=limit)}

    @app.get("/events/archive/leaderboard", dependencies=[Depends(require_auth)])
    def archive_leaderboard(
        window_days: int = Query(default=30, ge=1, le=365),
        limit: int = Query(default=10, ge=1, le=100),
    ) -> dict[str, Any]:
        return {"items": service.leaderboard(window_days, limit)}

    @app.get("/events/archive", dependencies=[Depends(require_auth)])
    def list_archive(
        status: str | None = Query(default=None),
        novelty: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
        keyword: str | None = Query(default=None),
        date_from: str | None = Query(default=None),
        date_to: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return service.list_archive(
            status=status, novelty=novelty, event_type=event_type,
            keyword=keyword, date_from=date_from, date_to=date_to, limit=limit,
        )

    # -- Events ---------------------------------------------------------

    @app.get("/events/events", dependencies=[Depends(require_auth)])
    def list_events(
        status: str | None = Query(default=None),
        novelty: str | None = Query(default=None),
        event_type: str | None = Query(default=None),
        region: str | None = Query(default=None),
        keyword: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=300),
    ) -> dict[str, Any]:
        items = service.list_events(
            status=status, novelty=novelty, event_type=event_type,
            region=region, keyword=keyword, limit=limit,
        )
        return {"items": items}

    @app.get("/events/events/{event_id}", dependencies=[Depends(require_auth)])
    def get_event(event_id: str) -> dict[str, Any]:
        try:
            return service.event_detail(event_id)
        except Exception as exc:
            raise _handle_service_errors(exc) from exc

    @app.post("/events/events/{event_id}/verify",
              dependencies=[Depends(require_auth)])
    def verify_event(event_id: str, body: VerifyBody) -> dict[str, Any]:
        try:
            return service.verify_event(event_id, body.action, body.note)
        except Exception as exc:
            raise _handle_service_errors(exc) from exc

    @app.post("/events/events/{event_id}/analyze",
              dependencies=[Depends(require_auth)])
    def analyze_event(event_id: str, body: AnalyzeBody) -> dict[str, Any]:
        try:
            return service.start_analysis(
                _get_swarm_runtime(),
                event_id=event_id, mode=body.mode, market=body.market,
                time_horizon=body.time_horizon,
            )
        except Exception as exc:
            raise _handle_service_errors(exc) from exc

    @app.post("/events/events/{event_id}/archive",
              dependencies=[Depends(require_auth)])
    def archive_event(event_id: str, body: ArchiveBody) -> dict[str, Any]:
        try:
            return service.archive_event(event_id, body.archived)
        except Exception as exc:
            raise _handle_service_errors(exc) from exc

    @app.delete("/events/events/{event_id}",
                dependencies=[Depends(require_auth)])
    def discard_event(event_id: str) -> dict[str, Any]:
        try:
            service.discard_event(event_id)
            return {"deleted": event_id}
        except Exception as exc:
            raise _handle_service_errors(exc) from exc

    @app.post("/events/events/{event_id}/recheck",
              dependencies=[Depends(require_auth)])
    def recheck_event(event_id: str) -> dict[str, Any]:
        try:
            return service.manual_recheck(event_id)
        except Exception as exc:
            raise _handle_service_errors(exc) from exc

    # -- Custom (historical retrospective) ------------------------------

    @app.post("/events/analyze", dependencies=[Depends(require_auth)])
    def analyze_custom(body: CustomAnalyzeBody) -> dict[str, Any]:
        try:
            return service.start_analysis(
                _get_swarm_runtime(),
                event_id=None, mode=body.mode, market=body.market,
                event_title=body.event_title, event_period=body.event_period,
            )
        except Exception as exc:
            raise _handle_service_errors(exc) from exc

    # -- Reports --------------------------------------------------------

    @app.get("/events/reports", dependencies=[Depends(require_auth)])
    def list_reports(
        mode: str | None = Query(default=None),
        status: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=300),
    ) -> dict[str, Any]:
        return {"items": service.list_reports(
            _get_swarm_runtime(), mode=mode, status=status, limit=limit
        )}

    @app.get("/events/reports/{report_id}",
             dependencies=[Depends(require_auth)])
    def get_report(report_id: str) -> dict[str, Any]:
        try:
            return service.get_report(_get_swarm_runtime(), report_id)
        except Exception as exc:
            raise _handle_service_errors(exc) from exc

    @app.post("/events/reports/{report_id}/cancel",
              dependencies=[Depends(require_auth)])
    def cancel_report(report_id: str) -> dict[str, Any]:
        try:
            return service.cancel_report(_get_swarm_runtime(), report_id)
        except Exception as exc:
            raise _handle_service_errors(exc) from exc

    @app.delete("/events/reports/{report_id}",
                dependencies=[Depends(require_auth)])
    def delete_report(report_id: str) -> dict[str, Any]:
        try:
            service.delete_report(report_id)
            return {"deleted": report_id}
        except Exception as exc:
            raise _handle_service_errors(exc) from exc

    @app.post("/events/reports/{report_id}/retry",
              dependencies=[Depends(require_auth)])
    def retry_report(report_id: str) -> dict[str, Any]:
        try:
            return service.retry_report(_get_swarm_runtime(), report_id)
        except Exception as exc:
            raise _handle_service_errors(exc) from exc

    @app.put("/events/reports/{report_id}/evaluation",
             dependencies=[Depends(require_auth)])
    def evaluate_report(report_id: str, body: EvaluationBody) -> dict[str, Any]:
        try:
            return service.evaluate_report(report_id, body.model_dump())
        except Exception as exc:
            raise _handle_service_errors(exc) from exc
