"""Eastmoney margin daily-trade API client.

Endpoint (JSONP, report RPTA_WEB_MARGIN_DAILYTRADE):
    https://datacenter-web.eastmoney.com/api/data/v1/get

Field note (verified against the seed attachment):
    ``AVG_GUARANTEE_RATIO`` is the market-wide average maintenance margin
    ratio (维持担保比例, e.g. 259.34 on 2026-11-04). ``LOAN_BALANCE`` is the
    securities-lending balance, NOT the guarantee ratio.

Supports:
    * full backfill with paging;
    * date-windowed fetch (used to backfill 2015-2020);
    * watermark incremental fetch (rows newer than the DB's max date).
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from typing import Any, Iterator

import requests

logger = logging.getLogger(__name__)

API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
REPORT_NAME = "RPTA_WEB_MARGIN_DAILYTRADE"
PAGE_SIZE = 200
REQUEST_TIMEOUT = 20
_MAX_PAGES = 100  # hard safety stop

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
    "Accept": "*/*",
}

_JSONP_RE = re.compile(r"^[^(]*\((.*)\)\s*;?\s*$", re.S)


class EastmoneyError(RuntimeError):
    """Raised when the upstream API returns an error or malformed payload."""


def _request_page(
    page_number: int,
    page_size: int = PAGE_SIZE,
    date_filter: str | None = None,
    retries: int = 3,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "reportName": REPORT_NAME,
        "columns": "ALL",
        "pageNumber": page_number,
        "pageSize": page_size,
        "sortColumns": "STATISTICS_DATE",
        "sortTypes": -1,
        "p": 1,
        "pageNo": 1,
        "pageNum": 1,
    }
    if date_filter:
        params["filter"] = date_filter

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(
                API_URL, params=params, headers=_HEADERS, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            match = _JSONP_RE.match(resp.text)
            payload = json.loads(match.group(1) if match else resp.text)
            if not payload.get("success"):
                raise EastmoneyError(
                    f"upstream success=false: {payload.get('message')!r}"
                )
            return payload.get("result") or {}
        except (requests.RequestException, ValueError, EastmoneyError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise EastmoneyError(f"request failed after {retries} retries: {last_exc}")


def _row_date(row: dict[str, Any]) -> date | None:
    raw = row.get("STATISTICS_DATE")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def fetch_rows(
    start: date | None = None,
    end: date | None = None,
    stop_before: date | None = None,
    page_size: int = PAGE_SIZE,
) -> Iterator[dict[str, Any]]:
    """Yield upstream rows newest-first.

    Args:
        start / end: optional inclusive date window pushed into the API filter.
        stop_before: client-side guard — stop paging as soon as a row older
            than this date is seen (used for incremental "rows after X").
    """
    date_filter = None
    if start or end:
        clauses = []
        if start:
            clauses.append(f"(STATISTICS_DATE>='{start.isoformat()}')")
        if end:
            clauses.append(f"(STATISTICS_DATE<='{end.isoformat()}')")
        date_filter = "".join(clauses)

    for page in range(1, _MAX_PAGES + 1):
        result = _request_page(page, page_size=page_size, date_filter=date_filter)
        rows = result.get("data") or []
        if not rows:
            return

        total_pages = result.get("pages") or 1
        for row in rows:
            row_d = _row_date(row)
            if stop_before and row_d and row_d <= stop_before:
                # Reached rows already in the DB (newest-first ordering).
                return
            yield row

        if page >= int(total_pages):
            return
        # Be polite to the upstream.
        time.sleep(0.25)

    logger.warning("eastmoney: hit _MAX_PAGES=%d safety stop", _MAX_PAGES)
