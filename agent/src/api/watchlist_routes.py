"""HTTP routes for the personal A-share watchlist (M16).

Mounted by ``agent/api_server.py`` after the swarm routes. Overview refresh
buttons go straight to data APIs (``src.watchlist.market``) — never through
the agent/LLM runtime. Analysis endpoints drive swarm role runs via the
injected swarm runtime singleton.

Error mapping (uniform):
    ValueError               -> 400
    FileNotFoundError        -> 404
    AnalysisInProgress       -> 409
    WatchlistDataError       -> 502
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel

from src.api.security import require_auth
from src.watchlist import analysis as watch_analysis
from src.watchlist import db as watch_db
from src.watchlist import kline as watch_kline
from src.watchlist import outcome as watch_outcome
from src.watchlist import market as watch_market
from src.watchlist.market import normalize_a_share_symbol
from src.watchlist.models import QuoteSnapshot
from src.watchlist.role_catalog_filter import CHANLUN_ROLE_REF
from src.watchlist.store import (
    DuplicateWatchError,
    WatchlistStore,
)

_watch_store: WatchlistStore | None = None

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Singleton accessors (overridable in tests)
# ---------------------------------------------------------------------------
def _get_watch_store() -> WatchlistStore:
    global _watch_store
    if _watch_store is None:
        _watch_store = WatchlistStore()
    return _watch_store


def _get_runtime() -> Any:
    # L4 -> L3 dependency localized to one call site.
    from src.api.swarm_routes import _get_swarm_runtime

    return _get_swarm_runtime()


def _get_catalog_entries() -> list[dict[str, Any]]:
    from src.swarm.role_catalog import list_approved_role_refs

    return list_approved_role_refs()


def _get_team_names() -> dict[str, str]:
    """Preset-name -> human team-title map for role-source labels.

    Built-in roles originate from a swarm preset (agent team); custom roles
    are grouped under the ``"custom"`` label. L4 -> L3 dependency localized
    here so the L2 role filter stays swarm-free.
    """
    from src.swarm.presets import list_presets

    names = {
        str(summary["name"]): str(summary.get("title") or summary["name"])
        for summary in list_presets()
    }
    names["custom"] = "自建角色"
    return names


@contextmanager
def _db_connection():
    conn = watch_db.watchlist_connection()
    watch_db.initialize_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


def _decorate_chanlun_rows(
    symbol: str, rows: list[dict[str, Any]], conn: Any
) -> list[dict[str, Any]]:
    """Merge machine outcome + user rating onto card rows and add live state."""
    outcomes = {
        str(o["run_id"]): o
        for o in watch_db.list_chanlun_outcomes(symbol, conn)
    }
    items: list[dict[str, Any]] = []
    for row in rows:
        run_id = str(row["run_id"])
        item = dict(row)
        item.update(outcomes.get(run_id) or {})
        item["live_status"] = (
            watch_outcome.current_status(row, conn)
            if row.get("card_parse") == "ok"
            else None
        )
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _symbol_or_400(raw_symbol: str) -> str:
    try:
        return normalize_a_share_symbol(raw_symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _entry_or_404(store: WatchlistStore, symbol: str):
    try:
        return store.get_entry(symbol)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _parse_date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"{field} 日期格式应为 YYYY-MM-DD"
        ) from exc


def _matching_role_runs(runtime: Any, symbol: str) -> list[Any]:
    store = getattr(runtime, "_store", None)
    if store is None:
        return []
    needle = symbol.lower()
    return [
        run
        for run in store.list_runs(limit=10_000)
        if (getattr(run, "kind", "team") or "team") == "role_run"
        and needle in str(getattr(run, "research_target", "") or "").lower()
    ]


def _run_summary(run: Any) -> dict[str, Any]:
    status = getattr(run.status, "value", run.status)
    return {
        "id": run.id,
        "status": str(status),
        "kind": getattr(run, "kind", "role_run"),
        "trial_role": getattr(run, "trial_role", None),
    }


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class AddWatchBody(BaseModel):
    symbol: str
    name: str = ""
    industry: str | None = None


class ObjectiveFetchBody(BaseModel):
    note: str


class AnalyzeBody(BaseModel):
    category: str
    role_ref: str
    question: str = ""
    # Investor-acknowledged skip of the advisory Chanlun kline prompt
    # (BDD rule 18: the check is a non-blocking prompt, not a hard gate).
    skip_kline_gate: bool = False


class KlineUpdateBody(BaseModel):
    intervals: list[str] | None = None
    # Vendor id from GET /watch/{symbol}/kline/sources; defaults to eastmoney.
    source: str | None = None


class ChanlunRatingBody(BaseModel):
    # Post-hoc investor verdict on how the archived call actually played out.
    verdict: Literal["accurate", "partial", "wrong"]
    note: str = ""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register_watchlist_routes(app: FastAPI) -> None:
    """Mount all /watch/* routes, each behind ``require_auth``."""

    # -- Membership --------------------------------------------------------
    @app.get("/watch/list", dependencies=[Depends(require_auth)])
    def list_watch() -> dict[str, Any]:
        store = _get_watch_store()
        quote_error: str | None = None
        snapshots: dict[str, QuoteSnapshot] = {}
        entries = store.list_entries()
        if entries:
            try:
                snapshots = watch_market.fetch_quote_snapshots(
                    [entry.symbol for entry in entries]
                )
            except watch_market.WatchlistDataError as exc:
                quote_error = str(exc)

        # Merge every snapshot in a single document write (no per-row I/O).
        stamped = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            entries = store.apply_quote_snapshots(snapshots, stamped_at=stamped)
        except Exception:  # noqa: BLE001 - cache failure keeps page alive
            logger.warning("watchlist quote cache merge failed", exc_info=True)
        return {"items": [entry.model_dump() for entry in entries],
                "quote_error": quote_error}

    @app.post("/watch", dependencies=[Depends(require_auth)])
    def add_watch(body: AddWatchBody) -> dict[str, Any]:
        store = _get_watch_store()
        symbol = _symbol_or_400(body.symbol)
        try:
            entry = store.add_entry(
                symbol, name=body.name, industry=body.industry
            )
        except DuplicateWatchError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return entry.model_dump()

    @app.delete("/watch/{symbol}", dependencies=[Depends(require_auth)])
    def remove_watch(symbol: str) -> dict[str, Any]:
        store = _get_watch_store()
        symbol = _symbol_or_400(symbol)
        if not store.remove_entry(symbol):
            raise HTTPException(
                status_code=404, detail=f"标的不在关注列表中: {symbol}"
            )
        return {"ok": True, "symbol": symbol}

    # -- Search ------------------------------------------------------------
    @app.get("/watch/search", dependencies=[Depends(require_auth)])
    def search_watch(q: str = Query("", max_length=50)) -> dict[str, Any]:
        keyword = q.strip()
        if not keyword:
            return {"items": []}
        try:
            items = watch_market.search_a_shares(keyword)
        except watch_market.WatchlistDataError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        # FR-2 candidates carry industry; the suggest endpoint lacks it, so
        # enrich all candidates with ONE batched quote request. Degrade to
        # empty industry when the quote host fails — search still works.
        if items:
            try:
                snapshots = watch_market.fetch_quote_snapshots(
                    [item["symbol"] for item in items]
                )
                for item in items:
                    snapshot = snapshots.get(item["symbol"])
                    if snapshot and snapshot.industry:
                        item["industry"] = snapshot.industry
            except watch_market.WatchlistDataError as exc:
                logger.warning("watchlist search industry enrich failed: %s", exc)
        return {"items": items}

    # -- Profile / objective data -----------------------------------------
    @app.get("/watch/{symbol}/profile", dependencies=[Depends(require_auth)])
    def get_watch_profile(symbol: str) -> dict[str, Any]:
        store = _get_watch_store()
        symbol = _symbol_or_400(symbol)
        _entry_or_404(store, symbol)
        with _db_connection() as conn:
            raw = watch_db.list_raw_data(symbol, conn)
        instrument = raw["instrument"][0] if raw["instrument"] else None
        valuation = raw["valuation"][0] if raw["valuation"] else None
        return {
            "symbol": symbol,
            "instrument": instrument,
            "latest_valuation": valuation,
            "entry": store.get_entry(symbol).model_dump(),
        }

    @app.post(
        "/watch/{symbol}/refresh-quotes",
        dependencies=[Depends(require_auth)],
    )
    def refresh_quotes(symbol: str) -> dict[str, Any]:
        store = _get_watch_store()
        symbol = _symbol_or_400(symbol)
        _entry_or_404(store, symbol)

        # Direct data API only — no runtime, no LLM.
        try:
            snapshots = watch_market.fetch_quote_snapshots([symbol])
        except watch_market.WatchlistDataError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        snapshot = snapshots.get(symbol)
        if snapshot is None:
            raise HTTPException(
                status_code=502, detail="行情接口未返回该标的的数据，请稍后重试"
            )
        stamped = datetime.now(timezone.utc).isoformat(timespec="seconds")
        snapshot.quote_updated_at = stamped
        entry = store.update_quote(symbol, snapshot)
        with _db_connection() as conn:
            watch_db.persist_quote_snapshot(
                symbol, snapshot, date.today().isoformat(), conn
            )
        return {
            "symbol": symbol,
            "quote": entry.quote.model_dump(),
            "updated_at": stamped,
        }

    @app.post(
        "/watch/{symbol}/refresh-profile",
        dependencies=[Depends(require_auth)],
    )
    def refresh_profile(symbol: str) -> dict[str, Any]:
        store = _get_watch_store()
        symbol = _symbol_or_400(symbol)
        _entry_or_404(store, symbol)

        try:
            profile = watch_market.fetch_company_profile(symbol)
        except watch_market.WatchlistDataError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        store.update_meta(
            symbol, name=profile.name, industry=profile.industry
        )
        with _db_connection() as conn:
            watch_db.apply_profile_to_instrument(profile, conn)
        return profile.model_dump()

    @app.get("/watch/{symbol}/objective", dependencies=[Depends(require_auth)])
    def get_objective(symbol: str) -> dict[str, Any]:
        # AC-3: history stays queryable by symbol even after unfollowing, so
        # this endpoint intentionally does NOT require current membership.
        symbol = _symbol_or_400(symbol)

        runtime = _get_runtime()
        entries = _get_catalog_entries()
        with _db_connection() as conn:
            # Lazily archive any finished fetch/chanlun runs before reading.
            watch_analysis.persist_run_artifacts(
                _matching_role_runs(runtime, symbol),
                entries=entries,
                connection=conn,
            )
            raw = watch_db.list_raw_data(symbol, conn)
            fetches = watch_db.list_objective_records(symbol, conn)
        return {"symbol": symbol, "raw": raw, "fetches": fetches}

    @app.post(
        "/watch/{symbol}/objective-fetch",
        dependencies=[Depends(require_auth)],
    )
    def start_objective_fetch(symbol: str, body: ObjectiveFetchBody) -> dict[str, Any]:
        store = _get_watch_store()
        symbol = _symbol_or_400(symbol)
        runtime = _get_runtime()
        try:
            run = watch_analysis.start_objective_fetch(
                symbol=symbol,
                note=body.note,
                entries=_get_catalog_entries(),
                runtime=runtime,
                watch_store=store,
            )
        except watch_analysis.AnalysisInProgress as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except watch_analysis.AnalysisServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _run_summary(run)

    # -- Analyst roles / analyses -----------------------------------------
    @app.get("/watch/agents", dependencies=[Depends(require_auth)])
    def list_agents(
        category: str | None = Query(
            None, pattern="^(fundamental|technical|general)$"
        ),
    ) -> dict[str, Any]:
        from src.watchlist.role_catalog_filter import list_analyst_roles

        return {
            "items": list_analyst_roles(
                category,
                _get_catalog_entries(),
                team_names=_get_team_names(),
            )
        }

    @app.post("/watch/{symbol}/analyze", dependencies=[Depends(require_auth)])
    def start_analysis(symbol: str, body: AnalyzeBody) -> dict[str, Any]:
        store = _get_watch_store()
        symbol = _symbol_or_400(symbol)
        if body.category not in ("fundamental", "technical", "general"):
            raise HTTPException(status_code=400, detail="不支持的分析分类")
        if not body.role_ref.strip():
            raise HTTPException(status_code=400, detail="必须选择一个智能体")
        if (
            body.category == "technical"
            and body.role_ref.strip() == CHANLUN_ROLE_REF
        ):
            # Chanlun pre-run prompt (BDD rule 18): advisory by default.
            # The first attempt returns 412 listing non-ready levels; the
            # UI offers "update data" or "skip & run anyway" (re-POST with
            # skip_kline_gate=true). The optional 30m level never prompts.
            # BDD rule 21: the run itself reads archived bars via the
            # objective_kline tool (local-first, online fallback) — bars are
            # never injected into the prompt.
            with _db_connection() as gate_conn:
                states = watch_kline.list_level_states(symbol, gate_conn)
                missing = watch_kline.missing_required_levels(states)
                if missing and not body.skip_kline_gate:
                    raise HTTPException(
                        status_code=412,
                        detail={
                            "code": "kline_not_ready",
                            "message": "缠论分析所需的各级别行情尚未齐备，"
                            "可先更新行情数据，或跳过提示继续运行",
                            "items": missing,
                        },
                    )
        runtime = _get_runtime()
        try:
            run = watch_analysis.start_analysis(
                symbol=symbol,
                category=body.category,
                role_ref=body.role_ref,
                brief=body.question or "",
                entries=_get_catalog_entries(),
                runtime=runtime,
                watch_store=store,
            )
        except watch_analysis.AnalysisInProgress as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _run_summary(run)

    @app.get("/watch/{symbol}/analyses", dependencies=[Depends(require_auth)])
    def list_analyses(
        symbol: str,
        category: str | None = Query(
            None, pattern="^(fundamental|technical|general)$"
        ),
        role_ref: str = Query("", max_length=120),
        date_from: str | None = Query(None, alias="from"),
        date_to: str | None = Query(None, alias="to"),
        limit: int = Query(20, ge=1, le=100),
    ) -> dict[str, Any]:
        # History stays readable after unfollow (AC-3) — no membership gate.
        symbol = _symbol_or_400(symbol)
        start = _parse_date(date_from, "from")
        end = _parse_date(date_to, "to")
        runtime = _get_runtime()
        entries = _get_catalog_entries()
        with _db_connection() as conn:
            watch_analysis.persist_run_artifacts(
                _matching_role_runs(runtime, symbol),
                entries=entries,
                connection=conn,
            )
        items = watch_analysis.list_analyses(
            symbol=symbol,
            entries=entries,
            runtime=runtime,
            category=category,
            role_ref=role_ref.strip() or None,
            date_from=start,
            date_to=end,
            limit=limit,
        )
        return {"items": items}

    @app.get("/watch/{symbol}/chanlun", dependencies=[Depends(require_auth)])
    def list_chanlun(
        symbol: str,
        date_from: str | None = Query(None, alias="from"),
        date_to: str | None = Query(None, alias="to"),
        limit: int = Query(20, ge=1, le=100),
    ) -> dict[str, Any]:
        # History stays readable after unfollow (AC-3) — no membership gate.
        symbol = _symbol_or_400(symbol)
        start = _parse_date(date_from, "from")
        end = _parse_date(date_to, "to")
        runtime = _get_runtime()
        with _db_connection() as conn:
            watch_analysis.persist_run_artifacts(
                _matching_role_runs(runtime, symbol),
                entries=_get_catalog_entries(),
                connection=conn,
            )
            watch_outcome.refresh_due(symbol, conn)
            rows = watch_db.list_chanlun_records(
                symbol,
                conn,
                date_from=start.isoformat() if start else None,
                date_to=end.isoformat() if end else None,
                limit=limit,
            )
            items = _decorate_chanlun_rows(symbol, rows, conn)
        return {"items": items}

    # -- Chanlun action cards: closed-loop tracking ----------------------
    def _archive_and_collect_cards(symbol: str, limit: int) -> list[dict[str, Any]]:
        runtime = _get_runtime()
        with _db_connection() as conn:
            watch_analysis.persist_run_artifacts(
                _matching_role_runs(runtime, symbol),
                entries=_get_catalog_entries(),
                connection=conn,
            )
            # Lazy mechanical verification of cards whose horizon elapsed.
            watch_outcome.refresh_due(symbol, conn)
            rows = watch_db.list_chanlun_records(symbol, conn, limit=limit)
            return _decorate_chanlun_rows(symbol, rows, conn)

    @app.get(
        "/watch/{symbol}/chanlun/cards",
        dependencies=[Depends(require_auth)],
    )
    def list_chanlun_cards(
        symbol: str, limit: int = Query(50, ge=1, le=100)
    ) -> dict[str, Any]:
        # Only successfully parsed cards are trackable; contract violations
        # remain visible via GET .../chanlun (card_parse field).
        symbol = _symbol_or_400(symbol)
        items = [
            row
            for row in _archive_and_collect_cards(symbol, limit)
            if row.get("card_parse") == "ok"
        ]
        return {"items": items}

    @app.get(
        "/watch/{symbol}/chanlun/cards/latest",
        dependencies=[Depends(require_auth)],
    )
    def latest_chanlun_card(symbol: str) -> dict[str, Any]:
        symbol = _symbol_or_400(symbol)
        items = [
            row
            for row in _archive_and_collect_cards(symbol, 50)
            if row.get("card_parse") == "ok"
        ]
        if not items:
            raise HTTPException(status_code=404, detail="该标的暂无可追踪的操作结论卡")
        return items[0]

    @app.get(
        "/watch/{symbol}/chanlun/compare",
        dependencies=[Depends(require_auth)],
    )
    def compare_chanlun_cards(
        symbol: str, runs: str = Query(..., max_length=400)
    ) -> dict[str, Any]:
        # Side-by-side diff of 2-4 historical runs of the SAME symbol.
        symbol = _symbol_or_400(symbol)
        run_ids: list[str] = []
        for part in runs.split(","):
            part = part.strip()
            if part and part not in run_ids:
                run_ids.append(part)
        if not run_ids:
            raise HTTPException(status_code=400, detail="runs 参数至少包含一个 run_id")
        if len(run_ids) > 4:
            raise HTTPException(status_code=400, detail="一次最多对比 4 次分析")
        runtime = _get_runtime()
        with _db_connection() as conn:
            watch_analysis.persist_run_artifacts(
                _matching_role_runs(runtime, symbol),
                entries=_get_catalog_entries(),
                connection=conn,
            )
            rows: list[dict[str, Any]] = []
            for run_id in run_ids:
                row = watch_db.get_chanlun_record_by_run(run_id, conn)
                if row is None:
                    raise HTTPException(
                        status_code=404, detail=f"找不到分析记录: {run_id}"
                    )
                if normalize_a_share_symbol(str(row["symbol"])) != symbol:
                    raise HTTPException(
                        status_code=400,
                        detail=f"记录 {run_id} 不属于标的 {symbol}",
                    )
                rows.append(row)
            watch_outcome.refresh_due(symbol, conn)
            items = _decorate_chanlun_rows(symbol, rows, conn)
        return {"items": items}

    @app.post(
        "/watch/{symbol}/chanlun/{run_id}/rating",
        dependencies=[Depends(require_auth)],
    )
    def rate_chanlun_card(
        symbol: str, run_id: str, body: ChanlunRatingBody
    ) -> dict[str, Any]:
        # Investor's post-hoc accuracy review; never mutates machine columns.
        symbol = _symbol_or_400(symbol)
        run_id = run_id.strip()
        with _db_connection() as conn:
            row = watch_db.get_chanlun_record_by_run(run_id, conn)
            if row is None:
                raise HTTPException(
                    status_code=404, detail=f"找不到分析记录: {run_id}"
                )
            if normalize_a_share_symbol(str(row["symbol"])) != symbol:
                raise HTTPException(
                    status_code=400, detail="该记录不属于此标的"
                )
            watch_db.set_user_rating(
                run_id=run_id,
                symbol=symbol,
                verdict=body.verdict,
                note=body.note.strip() or None,
                conn=conn,
            )
            updated = watch_db.get_chanlun_outcome(run_id, conn)
        return updated or {"run_id": run_id, "user_verdict": body.verdict}

    @app.get(
        "/watch/{symbol}/chanlun/stats",
        dependencies=[Depends(require_auth)],
    )
    def chanlun_card_stats(symbol: str) -> dict[str, Any]:
        # Track-record aggregation: machine labels + investor ratings.
        symbol = _symbol_or_400(symbol)
        items = _archive_and_collect_cards(symbol, 100)
        return watch_outcome.summarize(items)

    @app.get(
        "/watch/{symbol}/kline/sources",
        dependencies=[Depends(require_auth)],
    )
    def kline_sources(symbol: str) -> dict[str, Any]:
        # Selectable data vendors for the card, in Settings-priority order.
        symbol = _symbol_or_400(symbol)
        return {"items": watch_kline.list_sources()}

    @app.get(
        "/watch/{symbol}/kline/status",
        dependencies=[Depends(require_auth)],
    )
    def kline_status(symbol: str) -> dict[str, Any]:
        # Per-level Chanlun readiness; readable after unfollow like history.
        symbol = _symbol_or_400(symbol)
        with _db_connection() as conn:
            return watch_kline.list_level_states(symbol, conn)

    @app.get(
        "/watch/{symbol}/kline/bars",
        dependencies=[Depends(require_auth)],
    )
    def kline_bars(
        symbol: str,
        interval: str = Query(..., max_length=10),
        limit: int = Query(2000, ge=1, le=10_000),
    ) -> dict[str, Any]:
        # Read-only view of ALREADY FETCHED bars for the Chanlun multi-level
        # K-line chart — never triggers a network fetch. Levels without
        # stored rows come back with an empty ``items`` list; the UI hides
        # such levels instead of requesting data on demand.
        symbol = _symbol_or_400(symbol)
        try:
            (normalized_interval,) = watch_kline.normalize_intervals([interval])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with _db_connection() as conn:
            rows = watch_db.list_kline_bars(
                symbol, normalized_interval, conn=conn
            )
        items = [
            {
                "time": row["trade_date"],
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "amount": row.get("amount"),
            }
            for row in rows[-limit:]
        ]
        return {
            "symbol": symbol,
            "interval": normalized_interval,
            "items": items,
        }

    @app.post(
        "/watch/{symbol}/kline/update",
        dependencies=[Depends(require_auth)],
    )
    def kline_update(symbol: str, body: KlineUpdateBody) -> dict[str, Any]:
        # Direct data-API fetch (never AI); per-level failures stay
        # independent and never overwrite other levels' existing bars.
        symbol = _symbol_or_400(symbol)
        try:
            intervals = watch_kline.normalize_intervals(body.intervals)
            source = watch_kline.normalize_source(body.source)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with _db_connection() as conn:
            watch_kline.update_levels(symbol, intervals, conn, source=source)
            return watch_kline.list_level_states(symbol, conn)
