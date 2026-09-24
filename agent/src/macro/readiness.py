"""Pre-flight macro data availability assessment.

The module decides the *effective* statistics month for an economy and, on a
best-effort basis, probes whether macro indicator data is actually available
for it. Probes are deliberately defensive: a missing dependency, missing API
key, network error or parse problem degrades to ``UNKNOWN`` (the caller then
proceeds with the calendar-derived month); only a probe that positively
observes stale/empty data returns ``INSUFFICIENT``.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from typing import Callable, Dict, Optional, Protocol

from src.config.accessor import get_env_config
from src.macro.models import DataReadiness

logger = logging.getLogger(__name__)

#: Probe outcomes.
CONFIRMED = "confirmed"
INSUFFICIENT = "insufficient"
UNKNOWN = "unknown"

#: Canonical preset economies (display names are the canonical keys).
PRESET_ECONOMIES: tuple[str, ...] = ("中国", "美国", "日本", "欧元区")

#: Accept-and-normalise common aliases to the canonical Chinese display name.
ECONOMY_ALIASES: Dict[str, str] = {
    "中国": "中国",
    "china": "中国",
    "cn": "中国",
    "美国": "美国",
    "us": "美国",
    "usa": "美国",
    "united states": "美国",
    "日本": "日本",
    "japan": "日本",
    "jp": "日本",
    "欧元区": "欧元区",
    "euro area": "欧元区",
    "eurozone": "欧元区",
    "ea": "欧元区",
}

#: FRED series used by the default probe (monthly price indicators).
_FRED_SERIES: Dict[str, str] = {
    "美国": "CPIAUCSL",
    "日本": "JPNCPIALLMINMEI",
    "欧元区": "EA19CPALTT01GYM",
}

_MONTH_RE = re.compile(r"(\d{4})\s*年?\s*-?\s*(\d{1,2})")


def canonicalize_economy(economy: str) -> Optional[str]:
    """Return the canonical preset economy name, or ``None`` when unsupported."""
    if not economy:
        return None
    key = economy.strip().lower()
    if key in ECONOMY_ALIASES:
        return ECONOMY_ALIASES[key]
    return economy.strip() if economy.strip() in PRESET_ECONOMIES else None


def latest_available_month(today: Optional[_dt.date] = None) -> str:
    """Return the latest calendar month assumed to have published macro data.

    Monthly macro indicators publish with roughly a one-month lag, so the
    latest *complete* data month is the previous calendar month.
    """
    today = today or _dt.date.today()
    first_of_current = today.replace(day=1)
    previous = first_of_current - _dt.timedelta(days=1)
    return previous.strftime("%Y-%m")


def _parse_year_month(value: object) -> Optional[str]:
    if value is None:
        return None
    match = _MONTH_RE.search(str(value))
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{year:04d}-{month:02d}"


def _is_fresh_enough(data_month: str, *, today: Optional[_dt.date] = None) -> bool:
    """Fresh when the observed latest month is no older than two months back."""
    today = today or _dt.date.today()
    year, month = (int(part) for part in data_month.split("-"))
    total_data = year * 12 + (month - 1)
    floor_total = today.year * 12 + (today.month - 1) - 2
    return total_data >= floor_total


class MacroDataProbe(Protocol):
    """Best-effort data availability probe."""

    def probe(self, economy: str) -> str: ...


class DefaultMacroProbe:
    """Default probe: akshare for China, FRED for the other economies."""

    def __init__(
        self,
        http_get: Optional[Callable[..., object]] = None,
        akshare_provider: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        # Injectable seams keep the probe unit-testable without sockets.
        self._http_get = http_get
        self._akshare_provider = akshare_provider

    def probe(self, economy: str) -> str:
        canonical = canonicalize_economy(economy)
        if canonical is None:
            return INSUFFICIENT
        try:
            if canonical == "中国":
                month = self._probe_china()
            else:
                month = self._probe_fred(canonical)
        except Exception:  # any probe failure degrades to UNKNOWN, never blocks
            logger.debug("macro readiness probe failed for %s", economy, exc_info=True)
            return UNKNOWN
        if month is None:
            return UNKNOWN
        return CONFIRMED if _is_fresh_enough(month) else INSUFFICIENT

    # -- China -----------------------------------------------------------
    def _probe_china(self) -> Optional[str]:
        if self._akshare_provider is not None:
            return self._akshare_provider("中国")
        try:
            import akshare as ak  # local import: optional/heavy dependency
        except Exception:
            return None
        try:
            frame = ak.macro_china_cpi_monthly()
        except Exception:
            return None
        if frame is None or len(frame) == 0:
            return None
        # Column naming across akshare versions varies; scan the first column.
        first_col = frame.columns[0]
        for raw in reversed(frame[first_col].tolist()):
            month = _parse_year_month(raw)
            if month:
                return month
        return None

    # -- FRED (US / JP / Euro area) -------------------------------------
    def _probe_fred(self, economy: str) -> Optional[str]:
        api_key = get_env_config().data.fred_api_key
        series_id = _FRED_SERIES.get(economy)
        if not api_key or not series_id:
            return None
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "limit": 5,
            "sort_order": "desc",
        }
        if self._http_get is not None:
            payload = self._http_get(url, params)
        else:
            import requests

            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, str):
            payload = json.loads(payload)
        for observation in (payload or {}).get("observations", []):
            value = observation.get("value")
            if value in (None, "", "."):
                continue
            month = _parse_year_month(observation.get("date"))
            if month:
                return month
        return None


class ReadinessAssessor:
    """Assess data readiness for an economy using an injectable probe."""

    def __init__(
        self,
        probe: Optional[MacroDataProbe] = None,
        today_provider: Callable[[], _dt.date] = _dt.date.today,
    ) -> None:
        self._probe = probe or DefaultMacroProbe()
        self._today_provider = today_provider

    def assess(self, economy: str) -> DataReadiness:
        canonical = canonicalize_economy(economy)
        today = self._today_provider()
        latest = latest_available_month(today)
        if canonical is None:
            return DataReadiness(
                ready=False,
                latest_month=latest,
                reason=f"暂不支持的经济体：{economy}；当前仅支持 {'、'.join(PRESET_ECONOMIES)}",
            )
        status = self._probe.probe(canonical)
        if status == INSUFFICIENT:
            return DataReadiness(
                ready=False,
                latest_month=latest,
                reason=(
                    f"{canonical}当前宏观数据不足，无法确定最新可得数据月份；"
                    "可补充说明或手动指定数据截止月份后继续分析。"
                ),
            )
        # CONFIRMED and UNKNOWN both proceed with the calendar-derived month.
        return DataReadiness(ready=True, latest_month=latest, reason=None)
