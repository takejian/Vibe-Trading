"""Regression tests for :class:`SPAStaticFiles` fallback rules.

A GET to an unknown path must serve the SPA shell only for browser
navigations (``Accept: text/html``). XHR/fetch callers (``Accept: */*``)
must get a real 404 — otherwise a missing API path answers 200 with HTML
and the client reports a confusing data-load failure. The synthetic
fallback also carries ``Cache-Control: no-store`` so it can never be
cached under the requested URL.
"""

from __future__ import annotations

import asyncio

import pytest

from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.spa import SPAStaticFiles


def _scope(accept: str) -> dict:
    return {
        "type": "http",
        "method": "GET",
        "path": "/swarm/roles",
        "headers": [(b"accept", accept.encode())],
        "query_string": b"",
    }


def test_fetch_caller_gets_404_instead_of_html(tmp_path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    files = SPAStaticFiles(directory=str(tmp_path))

    with pytest.raises(StarletteHTTPException) as exc:
        asyncio.run(files.get_response("swarm/roles", _scope("*/*")))
    assert exc.value.status_code == 404


def test_browser_navigation_gets_index_with_no_store(tmp_path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    files = SPAStaticFiles(directory=str(tmp_path))

    response = asyncio.run(
        files.get_response("swarm/roles", _scope("text/html,application/xhtml+xml"))
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
