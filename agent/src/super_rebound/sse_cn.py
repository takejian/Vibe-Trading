"""Shanghai Stock Exchange (上交所) official ETF data collector.

直连 ``query.sse.com.cn`` 官方 JSONP 接口，**三个数据源**：

1. **官方份额**（主力）
   - ``COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L``
   - 上交所"产品-基金产品-ETF产品-基金规模"页面后端
   - ``STAT_DATE=YYYY-MM-DD`` 指定交易日，一次返回全市场 ETF 份额
   - 字段 ``TOT_VOL``，单位**万份**（已官方披露口径，无需换算）
   - **支持历史回溯**（从基金上市日起都有）

2. **市值** ``COMMON_JJZWZ_SCSJ_CJGK_JJCPMXB_L``（页面用，展示可选）

3. **单位净值 NAV** ``COMMON_SSE_CP_JJLB_ETFJJGK_GGSGSHQD_JBXX_C``
   - 仅返回**最近一次披露**的数据，不支持历史日期过滤
   - 所以 NAV 只有当日采集时能拿到历史回灌时 nav=None
"""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import date, datetime
from typing import Any, Iterable

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://query.sse.com.cn/commonQuery.do"
REQUEST_TIMEOUT = 20
_JSONP_RE = re.compile(r"^[^(]*\((.*)\)\s*;?\s*$", re.S)

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


class SseError(RuntimeError):
    """Raised when SSE upstream returns an error or malformed payload."""


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

def _headers(referer: str = "https://www.sse.com.cn/") -> dict[str, str]:
    return {
        "User-Agent": random.choice(_UA_POOL),
        "Referer": referer,
        "Accept": "*/*",
    }


def _request(params: dict[str, Any], retries: int = 3,
             referer: str = "https://www.sse.com.cn/") -> dict[str, Any]:
    """GET + JSONP unwrap + retry with exponential backoff."""
    params = dict(params)
    params.setdefault("jsonCallBack", "cb")

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(API_BASE, params=params, headers=_headers(referer), timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            match = _JSONP_RE.match(resp.text)
            body = match.group(1) if match else resp.text
            import json as _json
            payload = _json.loads(body)
            if payload.get("success") == "false" or payload.get("error"):
                raise SseError(
                    f"upstream error: success={payload.get('success')} "
                    f"error={payload.get('error')!r}"
                )
            return payload
        except (requests.RequestException, ValueError, SseError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                wait = 1.5 * (attempt + 1) + random.random()
                time.sleep(wait)
    raise SseError(f"request failed after {retries} retries: {last_exc}") from last_exc


# ---------------------------------------------------------------------------
# 1. 官方份额（主力，支持历史）
# ---------------------------------------------------------------------------

def fetch_etf_scale_by_date(stat_date: date) -> list[dict[str, Any]]:
    """上交所全市场 ETF 某日的官方份额。

    ``sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L``
    ``STAT_DATE=YYYY-MM-DD``

    返回 list，每个元素含 ``SEC_CODE / SEC_NAME / TOT_VOL``。
    TOT_VOL 单位=万份（官方原始口径）。
    """
    params = {
        "isPagination": "true",
        "pageHelp.pageSize": "10000",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
        "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L",
        "STAT_DATE": stat_date.strftime("%Y-%m-%d"),
    }
    payload = _request(params, referer="https://www.sse.com.cn/assortment/fund/list/etfinfo/scale/")
    return list(payload.get("result") or [])


# ---------------------------------------------------------------------------
# 2. 市值 + 3. NAV（仅当日）
# ---------------------------------------------------------------------------

def fetch_fund_detail() -> list[dict[str, Any]]:
    """全市场 ETF 当日产品明细（含市值 SCALE，亿元）。

    注意：上交所此接口**不支持历史 queryDate 过滤**，永远返回最新交易日。
    """
    params = {
        "sqlId": "COMMON_JJZWZ_SCSJ_CJGK_JJCPMXB_L",
        "isPagination": "true",
        "pageHelp.beginPage": "1",
        "pageHelp.pageSize": "500",
    }
    payload = _request(params, referer="https://etf.sse.com.cn/")
    return list((payload.get("pageHelp") or {}).get("data") or [])


def fetch_nav_list() -> list[dict[str, Any]]:
    """全市场 ETF 申购赎回清单（含 NAV）。仅返回**最近一次披露**。"""
    params = {
        "sqlId": "COMMON_SSE_CP_JJLB_ETFJJGK_GGSGSHQD_JBXX_C",
    }
    payload = _request(params, referer="https://etf.sse.com.cn/")
    return list(payload.get("result") or [])


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_nav(raw: str | None) -> float | None:
    if not raw:
        return None
    m = re.search(r"[-+]?\d+(?:\.\d+)?", raw)
    return float(m.group()) if m else None


def _parse_trade_day(raw: str | None) -> date | None:
    if not raw or len(raw) < 8:
        return None
    try:
        return datetime.strptime(raw[:8], "%Y%m%d").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Public: 按交易日拉取（支持历史）
# ---------------------------------------------------------------------------

def fetch_scale_for_targets(
    stat_date: date, target_codes: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """返回 {fund_code: {share_wanfen, fund_name, stat_date}}。

    上交所官方份额接口（历史可用）。
    """
    target_set = set(target_codes)
    rows = fetch_etf_scale_by_date(stat_date)
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        code = r.get("SEC_CODE")
        if code not in target_set:
            continue
        tot_vol = r.get("TOT_VOL")
        try:
            share_wanfen = round(float(tot_vol), 1) if tot_vol else None
        except (TypeError, ValueError):
            share_wanfen = None
        out[code] = {
            "fund_code": code,
            "fund_name": r.get("SEC_NAME"),
            "trade_date": stat_date,
            "share_wanfen": share_wanfen,
        }
    if out:
        logger.info(
            "sse scale %s matched %d/%d target(s)",
            stat_date, len(out), len(target_set),
        )
    return out


# ---------------------------------------------------------------------------
# Public: 当日采集（份额 + NAV + 市值，用于计算净流入）
# ---------------------------------------------------------------------------

def fetch_sse_etf_rows_today(
    trade_date: date,
    target_codes: Iterable[str],
) -> list[dict[str, Any]]:
    """拉取上交所 12 只国家队 ETF 的当日数据（份额来自官方 scale 接口 + NAV 来自 sgInfo）。

    每个 dict 含:
        fund_code, fund_name, trade_date, nav, market_cap_bn(可选), share_wanfen
    """
    target_set = set(target_codes)
    if not target_set:
        return []

    # 1. 官方份额（指定日期）
    scale_map = fetch_scale_for_targets(trade_date, target_set)
    missing_share = target_set - set(scale_map)
    if missing_share:
        logger.warning("sse scale %s missing codes: %s", trade_date, sorted(missing_share))

    # 2. 市值（当日，永远返回最新）
    detail_rows = fetch_fund_detail()
    detail_by_code = {
        r["FUND_CODE"]: r for r in detail_rows if r.get("FUND_CODE") in target_set
    }

    # 3. NAV（最新披露）
    nav_rows = fetch_nav_list()
    nav_by_code: dict[str, tuple[date, float]] = {}
    for r in nav_rows:
        code = r.get("TRADE_CODE")
        if code not in target_set:
            continue
        nav_date = _parse_trade_day(r.get("TRADING_DAY"))
        nav_val = _parse_nav(r.get("NAV"))
        if code and nav_date and nav_val is not None:
            if code not in nav_by_code or abs((nav_date - trade_date).days) < abs((nav_by_code[code][0] - trade_date).days):
                nav_by_code[code] = (nav_date, nav_val)

    # 4. join
    out: list[dict[str, Any]] = []
    for code in sorted(scale_map.keys()):
        share_row = scale_map[code]
        nav_tup = nav_by_code.get(code)
        market_cap_bn = None
        detail_row = detail_by_code.get(code)
        if detail_row:
            try:
                market_cap_bn = float(detail_row.get("SCALE") or 0)
            except (TypeError, ValueError):
                pass

        out.append({
            "fund_code": code,
            "fund_name": detail_row.get("FUND_EXPAND_ABBR") or detail_row.get("FUND_ABBR") or share_row["fund_name"],
            "trade_date": trade_date,
            "nav": nav_tup[1] if nav_tup else None,
            "nav_date": nav_tup[0] if nav_tup else None,
            "market_cap_bn": market_cap_bn,
            "share_wanfen": share_row["share_wanfen"],
            "exchange": "SSE",
        })

    return out
