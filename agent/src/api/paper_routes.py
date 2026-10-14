"""HTTP routes for the simulated paper portfolio (``/api/paper/*``).

Fully isolated from the live ``/api/portfolio`` surface. Error mapping:
    PaperError / WatchlistError (ValueError) -> 400
    PaperDataError / WatchlistDataError      -> 502
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.security import require_auth
from src.paper import db as paper_db
from src.paper import service
from src.paper.errors import PaperDataError, PaperError
from src.watchlist.market import WatchlistDataError
from src.watchlist.store import WatchlistError

logger = logging.getLogger(__name__)


@contextmanager
def _db_connection():
    conn = paper_db.paper_connection()
    paper_db.initialize_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _paper_errors():
    try:
        yield
    except (PaperError, WatchlistError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (PaperDataError, WatchlistDataError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class TradeBody(BaseModel):
    symbol: str
    qty: int = Field(gt=0)


def register_paper_routes(app: FastAPI) -> None:
    """Mount all /api/paper/* routes, each behind ``require_auth``."""

    @app.get("/api/paper/account", dependencies=[Depends(require_auth)])
    def paper_account() -> dict[str, Any]:
        with _db_connection() as conn, _paper_errors():
            return service.account(conn)

    @app.get("/api/paper/positions", dependencies=[Depends(require_auth)])
    def paper_positions() -> dict[str, Any]:
        with _db_connection() as conn, _paper_errors():
            return service.positions(conn)

    @app.post("/api/paper/buy", dependencies=[Depends(require_auth)])
    def paper_buy(body: TradeBody) -> dict[str, Any]:
        with _db_connection() as conn, _paper_errors():
            return service.buy(conn, body.symbol, body.qty)

    @app.post("/api/paper/sell", dependencies=[Depends(require_auth)])
    def paper_sell(body: TradeBody) -> dict[str, Any]:
        with _db_connection() as conn, _paper_errors():
            return service.sell(conn, body.symbol, body.qty)

    @app.get("/api/paper/orders", dependencies=[Depends(require_auth)])
    def paper_orders(
        symbol: str | None = Query(default=None),
        side: str | None = Query(default=None, pattern="^(buy|sell)$"),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        with _db_connection() as conn, _paper_errors():
            items = paper_db.list_orders(
                conn, symbol=symbol, side=side, limit=limit, offset=offset
            )
            return {"items": items}

    @app.get("/api/paper/closes", dependencies=[Depends(require_auth)])
    def paper_closes(
        symbol: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        with _db_connection() as conn, _paper_errors():
            items = paper_db.list_close_view(
                conn, symbol=symbol, limit=limit, offset=offset
            )
            return {"items": items, "stats": paper_db.close_stats(conn),
                    "total_fees": paper_db.total_fees(conn)}

    @app.get("/api/paper/nav", dependencies=[Depends(require_auth)])
    def paper_nav(
        range: str = Query(default="all", pattern="^(all|5d|20d)$"),
    ) -> dict[str, Any]:
        with _db_connection() as conn, _paper_errors():
            return {"items": service.nav_series(conn, range)}

    @app.get("/api/paper/buy-preview", dependencies=[Depends(require_auth)])
    def paper_buy_preview(
        symbol: str,
        qty: int | None = Query(default=None, ge=1),
        side: str = Query(default="buy", pattern="^(buy|sell)$"),
    ) -> dict[str, Any]:
        with _db_connection() as conn, _paper_errors():
            return service.preview(conn, symbol, qty, side=side)

    @app.post("/api/paper/refresh", dependencies=[Depends(require_auth)])
    def paper_refresh() -> dict[str, Any]:
        with _db_connection() as conn, _paper_errors():
            count = service.refresh_quotes(conn)
            return {"refreshed": count}

    @app.post("/api/paper/reset", dependencies=[Depends(require_auth)])
    def paper_reset() -> dict[str, Any]:
        with _db_connection() as conn, _paper_errors():
            service.reset(conn)
            return {"status": "ok"}
