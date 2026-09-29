"""Swarm HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_swarm_routes(app, ...)``.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_swarm_runtime = None


def _get_swarm_runtime():
    """Lazy-init SwarmRuntime singleton."""
    global _swarm_runtime
    if _swarm_runtime is not None:
        return _swarm_runtime
    from src.config import load_swarm_agent_config
    from src.swarm.store import SwarmStore, swarm_runs_root
    from src.swarm.runtime import SwarmRuntime

    store = SwarmStore(base_dir=swarm_runs_root())
    # Boot-time / operator-trusted: REST API callers cannot influence the
    # config path. See docs/2026-05-25_swarm_mcp_tools_roadmap.md.
    agent_config = load_swarm_agent_config()
    _swarm_runtime = SwarmRuntime(store=store, agent_config=agent_config)
    return _swarm_runtime


def _skill_admin_enabled() -> bool:
    """Whether operator-only skill import/sync endpoints are unlocked."""
    from src.config.accessor import get_env_config

    return bool(get_env_config().agent_tuning.vibe_trading_enable_skill_admin)


def _run_created_date(run: Any) -> date | None:
    raw = getattr(run, "created_at", None)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _run_summary_item(runtime: Any, reconciled: Any) -> dict:
    excerpt = (reconciled.final_report or "")[:280]
    return {
        "id": reconciled.id,
        "preset_name": reconciled.preset_name,
        "status": reconciled.status.value,
        "is_stale": runtime._store.is_run_stale(reconciled),
        "created_at": reconciled.created_at,
        "completed_at": reconciled.completed_at,
        "task_count": len(reconciled.tasks),
        "completed_count": sum(
            1 for t in reconciled.tasks if t.status.value == "completed"
        ),
        "customized": bool(getattr(reconciled, "customized", False)),
        "research_target": getattr(reconciled, "research_target", None),
        "research_question": getattr(reconciled, "research_question", None),
        "kind": getattr(reconciled, "kind", "team") or "team",
        "trial_skill": getattr(reconciled, "trial_skill", None),
        "final_report_excerpt": excerpt or None,
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_swarm_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
    require_event_stream_auth: AuthDep | None = None,
) -> None:
    """Mount the swarm routes onto ``app``.

    Resolves ``require_auth`` and ``require_event_stream_auth`` from the host
    ``api_server`` module via ``sys.modules`` when not passed explicitly.
    """
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    if host is None:
        raise RuntimeError(
            "register_swarm_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    if require_auth is None:
        require_auth = host.require_auth
    if require_event_stream_auth is None:
        require_event_stream_auth = host.require_event_stream_auth

    def _host_validate_path_param(value: str, kind: str) -> None:
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        h._validate_path_param(value, kind)

    def _host_shell_tools_enabled_for_request(request: Request) -> bool:
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return h._shell_tools_enabled_for_request(request)

    # --- Routes ---

    @app.get("/swarm/presets", dependencies=[Depends(require_auth)])
    async def list_swarm_presets():
        """List Swarm YAML presets.

        Authenticated for the same reason as ``/skills``: the preset inventory
        describes configured agent capabilities and should not be readable by a
        peer that cannot start a swarm run.
        """
        from src.swarm.presets import list_presets

        return list_presets()

    @app.get("/swarm/presets/{name}/detail", dependencies=[Depends(require_auth)])
    async def swarm_preset_detail(name: str):
        """Full editable definition of one preset (web orchestration canvas)."""
        from src.swarm.presets import get_preset_detail

        try:
            return get_preset_detail(name)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/swarm/runs", dependencies=[Depends(require_auth)])
    async def create_swarm_run(payload: dict, http_request: Request):
        """Start a swarm run: body must include preset_name and user_vars.

        Optional ``custom`` object (nodes/edges/target/question) launches a
        single-use web-orchestrated run; the source preset stays untouched.
        Optional ``skill_trial`` object (skill_name/target/question) launches
        a standalone single-skill trial; it is mutually exclusive with
        ``custom``.
        """
        runtime = _get_swarm_runtime()
        preset_name = payload.get("preset_name", "")
        user_vars = payload.get("user_vars", {})
        custom = payload.get("custom")
        skill_trial = payload.get("skill_trial")
        if custom is not None and not isinstance(custom, dict):
            raise HTTPException(status_code=400, detail="custom must be an object")
        if skill_trial is not None and not isinstance(skill_trial, dict):
            raise HTTPException(status_code=400, detail="skill_trial must be an object")
        try:
            run = runtime.start_run(
                preset_name,
                user_vars,
                include_shell_tools=_host_shell_tools_enabled_for_request(http_request),
                custom_spec=custom,
                skill_trial=skill_trial,
            )
            return {
                "id": run.id,
                "status": run.status.value,
                "preset_name": run.preset_name,
                "kind": run.kind,
                "trial_skill": run.trial_skill,
            }
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    def _list_runs_filtered(
        *,
        kind: str,
        target: str,
        date_from: date | None,
        date_to: date | None,
        limit: int,
    ) -> list[dict]:
        runtime = _get_swarm_runtime()
        runs = runtime._store.list_runs(limit=limit)
        items: list[dict] = []
        for r in runs:
            # Reconcile each row: a zombie running run will be auto-finalized so
            # the dashboard never shows a "running" stuck row.
            reconciled = runtime._store.reconcile_run(r, write=True)
            row_kind = getattr(reconciled, "kind", "team") or "team"
            if kind != "all" and row_kind != kind:
                continue
            needle = (target or "").strip().lower()
            if needle:
                haystack = (getattr(reconciled, "research_target", None) or "").lower()
                if needle not in haystack:
                    continue
            if date_from is not None or date_to is not None:
                created = _run_created_date(reconciled)
                if created is None:
                    continue
                if date_from is not None and created < date_from:
                    continue
                if date_to is not None and created > date_to:
                    continue
            items.append(_run_summary_item(runtime, reconciled))
        return items

    @app.get("/swarm/runs", dependencies=[Depends(require_auth)])
    async def list_swarm_runs(
        limit: int = Query(20, ge=1, le=100),
        kind: str = Query("team", pattern="^(team|skill_trial|all)$"),
        target: str = Query("", max_length=100),
        date_from: date | None = Query(None, alias="from"),
        date_to: date | None = Query(None, alias="to"),
    ):
        """List swarm runs (newest first), reconciled and filterable.

        Defaults to team evaluations (``kind=team``); the Skill Square reads
        ``kind=skill_trial``. ``target`` fuzzy-matches research_target and
        ``from``/``to`` bound the creation date (inclusive).
        """
        return _list_runs_filtered(
            kind=kind,
            target=target,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    @app.get("/swarm/runs/{run_id}", dependencies=[Depends(require_auth)])
    async def get_swarm_run(run_id: str):
        """Swarm run detail including task statuses (reconciled)."""
        _host_validate_path_param(run_id, "run_id")
        runtime = _get_swarm_runtime()
        loaded = runtime._store.load_run(run_id)
        if not loaded:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        run = runtime._store.reconcile_run(loaded, write=True)

        from src.swarm.serialization import serialize_task

        return {
            "id": run.id,
            "preset_name": run.preset_name,
            "status": run.status.value,
            "is_stale": runtime._store.is_run_stale(run),
            "user_vars": run.user_vars,
            "agents": [a.model_dump() for a in run.agents],
            "tasks": [
                {
                    **serialize_task(t),
                    # Keep the existing REST field while sharing the public
                    # serializer used by the other swarm read paths.
                    "worker_iterations": getattr(t, "worker_iterations", 0),
                }
                for t in run.tasks
            ],
            "created_at": run.created_at,
            "completed_at": run.completed_at,
            "final_report": run.final_report,
            "customized": bool(getattr(run, "customized", False)),
            "research_target": getattr(run, "research_target", None),
            "research_question": getattr(run, "research_question", None),
            "kind": getattr(run, "kind", "team") or "team",
            "trial_skill": getattr(run, "trial_skill", None),
        }

    @app.get(
        "/swarm/runs/{run_id}/events",
        dependencies=[Depends(require_event_stream_auth)],
    )
    async def swarm_run_events(
        run_id: str,
        request: Request,
        last_index: int = Query(0, ge=0),
        last_event_id: int | None = Header(None, alias="Last-Event-ID", ge=0),
    ):
        """SSE stream for a swarm run."""
        import asyncio

        _host_validate_path_param(run_id, "run_id")
        runtime = _get_swarm_runtime()
        if not runtime._store.load_run(run_id):
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        async def event_stream():
            # Browser EventSource reconnects with Last-Event-ID. Keep the
            # existing query parameter for non-browser and older clients.
            idx = last_event_id if last_event_id is not None else last_index
            while True:
                if await request.is_disconnected():
                    break
                events = runtime._store.read_events(run_id, after_index=idx)
                for evt in events:
                    idx += 1
                    yield f"id: {idx}\nevent: {evt.type}\ndata: {json.dumps(evt.model_dump(), ensure_ascii=False)}\n\n"
                run = runtime._store.load_run(run_id)
                if not run:
                    yield 'event: done\ndata: {"status": "missing"}\n\n'
                    break
                # Reconcile so a zombie running run can still close this SSE
                # stream cleanly — without it, a dead host would keep the
                # stream open forever and block the dashboard's "done" state.
                reconciled = runtime._store.reconcile_run(run, write=True)
                if reconciled.status.value in ("completed", "failed", "cancelled"):
                    yield f'event: done\ndata: {{"status": "{reconciled.status.value}"}}\n\n'
                    break
                await asyncio.sleep(2)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/swarm/runs/{run_id}/cancel", dependencies=[Depends(require_auth)])
    async def cancel_swarm_run(run_id: str):
        """Cancel an active swarm run."""
        _host_validate_path_param(run_id, "run_id")
        runtime = _get_swarm_runtime()
        ok = runtime.cancel_run(run_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"No active run {run_id}")
        return {"status": "cancelled"}

    @app.post("/swarm/runs/{run_id}/retry", dependencies=[Depends(require_auth)])
    async def retry_swarm_run(run_id: str, http_request: Request, resume: bool = Query(False)):
        """Retry a failed, stale, or cancelled swarm run.

        Creates a new run with the same preset and user_vars as the original.
        ``resume=true`` replays: completed upstream tasks and their artifacts
        are carried into the new run and only the failed/cancelled subgraph
        re-executes.
        """
        _host_validate_path_param(run_id, "run_id")
        runtime = _get_swarm_runtime()
        loaded = runtime._store.load_run(run_id)
        if not loaded:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        # Reconcile first so a stale "running" run whose host died gets demoted
        # before we gate on status; only a genuinely active run blocks retry.
        from src.swarm.models import RunStatus

        reconciled = runtime._store.reconcile_run(loaded, write=True)
        if reconciled.status == RunStatus.running:
            raise HTTPException(
                status_code=409, detail="Cannot retry a running run. Cancel it first."
            )
        if resume and reconciled.status not in (RunStatus.failed, RunStatus.cancelled):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot resume a run in status '{reconciled.status.value}'; "
                    "resume only applies to failed or cancelled runs."
                ),
            )

        try:
            trial_kwargs: dict[str, Any] = {}
            is_trial = getattr(reconciled, "kind", "team") == "skill_trial"
            if is_trial:
                # Re-run the same standalone skill trial; resume is not
                # meaningful for a single-node graph.
                trial_kwargs["skill_trial"] = {
                    "skill_name": reconciled.trial_skill,
                    "target": reconciled.research_target,
                    "question": reconciled.research_question,
                }
            new_run = runtime.start_run(
                reconciled.preset_name,
                reconciled.user_vars or {},
                include_shell_tools=_host_shell_tools_enabled_for_request(http_request),
                resume_from=(reconciled if resume and not is_trial else None),
                **trial_kwargs,
            )
            return {
                "id": new_run.id,
                "status": new_run.status.value,
                "preset_name": new_run.preset_name,
            }
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ------------------------------------------------------------------
    # Custom teams ("my teams")
    # ------------------------------------------------------------------

    @app.get("/swarm/custom-teams", dependencies=[Depends(require_auth)])
    async def list_custom_teams():
        """List the operator's saved custom teams."""
        from src.swarm.custom_teams import CustomTeamStore

        teams = CustomTeamStore().list_teams()
        return [
            {
                "id": team.id,
                "name": team.name,
                "description": team.description,
                "source_preset": team.source_preset,
                "role_count": len(team.nodes),
                "created_at": team.created_at,
                "updated_at": team.updated_at,
            }
            for team in teams
        ]

    def _team_payload(payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="body must be an object")
        return payload

    @app.post("/swarm/custom-teams", dependencies=[Depends(require_auth)])
    async def create_custom_team(payload: dict):
        """Save the current canvas graph as a new custom team."""
        from src.swarm.custom_teams import CustomTeamStore, DuplicateTeamNameError

        payload = _team_payload(payload)
        try:
            team = CustomTeamStore().save_team(
                name=str(payload.get("name", "")),
                description=str(payload.get("description", "") or ""),
                source_preset=str(payload.get("source_preset", "")),
                nodes=payload.get("nodes", []),
                edges=payload.get("edges", []),
            )
        except DuplicateTeamNameError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"id": team.id, "name": team.name, "updated_at": team.updated_at}

    @app.get("/swarm/custom-teams/{team_id}", dependencies=[Depends(require_auth)])
    async def get_custom_team(team_id: str):
        """Full editable definition of one custom team."""
        from src.swarm.custom_teams import CustomTeamStore

        _host_validate_path_param(team_id, "team_id")
        try:
            team = CustomTeamStore().get_team(team_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return team.model_dump()

    @app.put("/swarm/custom-teams/{team_id}", dependencies=[Depends(require_auth)])
    async def update_custom_team(team_id: str, payload: dict):
        """Replace one custom team definition in place."""
        from src.swarm.custom_teams import CustomTeamStore, DuplicateTeamNameError

        _host_validate_path_param(team_id, "team_id")
        payload = _team_payload(payload)
        try:
            team = CustomTeamStore().update_team(
                team_id,
                name=str(payload.get("name", "")),
                description=str(payload.get("description", "") or ""),
                source_preset=str(payload.get("source_preset", "")),
                nodes=payload.get("nodes", []),
                edges=payload.get("edges", []),
            )
        except DuplicateTeamNameError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"id": team.id, "name": team.name, "updated_at": team.updated_at}

    @app.delete("/swarm/custom-teams/{team_id}", dependencies=[Depends(require_auth)])
    async def delete_custom_team(team_id: str):
        """Delete one custom team (run snapshots are intentionally untouched)."""
        from src.swarm.custom_teams import CustomTeamStore

        _host_validate_path_param(team_id, "team_id")
        try:
            CustomTeamStore().delete_team(team_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"status": "deleted"}

    # ------------------------------------------------------------------
    # Skill Square: catalog, capabilities, standalone trials
    # ------------------------------------------------------------------

    @app.get("/swarm/skills/capabilities", dependencies=[Depends(require_auth)])
    async def skill_square_capabilities():
        """Tell the UI whether the operator-only admin zone may render."""
        from src.config.accessor import get_env_config

        return {
            "admin_enabled": _skill_admin_enabled(),
            "sync_source_configured": bool(
                get_env_config().paths.vibe_trading_skill_sync_source.strip()
            ),
        }

    @app.get("/swarm/skills/catalog", dependencies=[Depends(require_auth)])
    async def list_skill_catalog():
        """All assembled skills with global approval state."""
        from src.swarm.skill_catalog import list_assembled_skills

        return {"skills": list_assembled_skills()}

    @app.post("/swarm/skill-trials", dependencies=[Depends(require_auth)])
    async def create_skill_trial(payload: dict, http_request: Request):
        """Launch a standalone single-skill trial run."""
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="body must be an object")
        runtime = _get_swarm_runtime()
        try:
            run = runtime.start_run(
                "",
                {},
                include_shell_tools=_host_shell_tools_enabled_for_request(http_request),
                skill_trial={
                    "skill_name": payload.get("skill_name", ""),
                    "target": payload.get("target", ""),
                    "question": payload.get("question", ""),
                },
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {
            "id": run.id,
            "status": run.status.value,
            "kind": run.kind,
            "trial_skill": run.trial_skill,
        }

    @app.get("/swarm/skill-trials", dependencies=[Depends(require_auth)])
    async def list_skill_trials(
        limit: int = Query(20, ge=1, le=100),
        target: str = Query("", max_length=100),
        date_from: date | None = Query(None, alias="from"),
        date_to: date | None = Query(None, alias="to"),
        skill_name: str = Query("", max_length=100),
    ):
        """Trial history (runs of kind=skill_trial), newest first."""
        items = _list_runs_filtered(
            kind="skill_trial",
            target=target,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        wanted = (skill_name or "").strip()
        if wanted:
            items = [item for item in items if item.get("trial_skill") == wanted]
        return items

    # ------------------------------------------------------------------
    # Operator-only skill package administration
    # ------------------------------------------------------------------

    @app.post("/swarm/skills/import", dependencies=[Depends(require_auth)])
    async def import_skill_package(file: UploadFile = File(...)):
        """Validate and install an uploaded zip of finance skill packages."""
        if not _skill_admin_enabled():
            raise HTTPException(status_code=403, detail="Skill administration is disabled")
        from src.swarm.skill_packages import SkillPackageError, import_zip_bytes

        payload = await file.read()
        try:
            installed = import_zip_bytes(payload)
        except SkillPackageError as e:
            raise HTTPException(
                status_code=400,
                detail=e.reasons if len(e.reasons) > 1 else e.reasons[0],
            )
        return {
            "installed": [
                {"name": item.name, "slug": item.slug} for item in installed
            ],
            "rejected": [],
        }

    @app.post("/swarm/skills/sync", dependencies=[Depends(require_auth)])
    async def sync_skill_packages():
        """One-click sync finance skills from the configured source."""
        if not _skill_admin_enabled():
            raise HTTPException(status_code=403, detail="Skill administration is disabled")
        from src.config.accessor import get_env_config
        from src.swarm.skill_packages import SkillPackageError, sync_from_source

        source = get_env_config().paths.vibe_trading_skill_sync_source.strip()
        if not source:
            raise HTTPException(status_code=409, detail="Skill sync source is not configured")
        try:
            result = sync_from_source(source)
        except SkillPackageError as e:
            status_code = 409 if "未配置" in str(e) else 400
            raise HTTPException(
                status_code=status_code,
                detail=e.reasons if len(e.reasons) > 1 else e.reasons[0],
            )
        return result
