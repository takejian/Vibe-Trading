"""Static-file serving rules for the bundled single-page application."""

from __future__ import annotations

from typing import Any

from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException


class SPAStaticFiles(StaticFiles):
    """Serve index.html for browser refreshes on client-side routes."""

    async def get_response(self, path: str, scope: dict[str, Any]):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            # Only browser navigations (Accept includes text/html) get the SPA
            # shell. XHR/fetch callers send Accept: */* (or application/json)
            # and must receive a real 404 — otherwise an API path that does
            # not exist answers 200 with HTML, which the client surfaces as a
            # misleading data-load failure.
            accept = Headers(scope=scope).get("accept", "")
            if "text/html" not in accept:
                raise
            response = await super().get_response("index.html", scope)
            # The fallback is a synthetic representation for an arbitrary URL;
            # never cache it under that URL (hashed /assets keep normal caching).
            response.headers["Cache-Control"] = "no-store"
            return response
