"""Shenzhen Stock Exchange (深交所) official ETF daily snapshot collector.

数据源：``fund.szse.cn/api/report/ShowReport`` (CATALOGID=1000_lf)
    深交所旧站的基金份额 XLSX 导出接口（新站 szse.cn 已于 2025 年下线
    ShowReport API，但旧站还活着）。

返回字段：基金代码 / 基金简称 / 当前规模(份) / 净值。
**仅当日快照**，不支持历史回溯（AKShare fund_etf_scale_szse 也是这个）。

单位：份额单位是"份"，入库前 ÷ 10000 统一成"万份"（与上交所对齐）。
"""

from __future__ import annotations

import io
import logging
import random
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Iterable

import pandas as pd
import requests

logger = logging.getLogger(__name__)

API_URL = "https://fund.szse.cn/api/report/ShowReport"
REQUEST_TIMEOUT = 20

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


class SzseError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(_UA_POOL),
        "Referer": "https://fund.szse.cn/marketdata/fundslist/index.html",
    }


def _request_xlsx(retries: int = 3) -> pd.DataFrame:
    params = {
        "SHOWTYPE": "xlsx",
        "CATALOGID": "1000_lf",
        "TABKEY": "tab1",
        "random": f"{random.random():.10f}",
    }
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(API_URL, params=params, headers=_headers(), timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return pd.read_excel(io.BytesIO(resp.content), engine="openpyxl",
                                 dtype={"基金代码": str})
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1) + random.random())
    raise SzseError(f"szse xlsx failed after {retries}: {last_exc}") from last_exc


def _latest_trading_day_on_or_before(d: date) -> date:
    """Return the most recent weekday on or before ``d`` (no holiday calendar)."""
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def szse_data_date(as_of: date | None = None) -> date:
    """深交所 fund.szse.cn 接口存在 T-1 滞后：在日 D 拉取的份额实际是 D 之前
    最近一个交易日的收盘份额。本函数返回该数据对应的真实交易日。

    例：周五拉取 → 周四数据；周六/周一拉取 → 周五数据。
    """
    if as_of is None:
        as_of = date.today()
    return _latest_trading_day_on_or_before(as_of - timedelta(days=1))


def fetch_szse_etf_snapshot(
    target_codes: Iterable[str],
    as_of_date: date | None = None,
) -> list[dict[str, Any]]:
    """深交所 ETF 当日快照。

    返回 list，每个元素含 fund_code / fund_name / share_wanfen（万份）/ nav。
    份额原始单位"份"，入库前已 ÷10000。

    注意：深交所接口有 T-1 滞后，``trade_date`` 字段已自动修正为数据对应的
    真实交易日（见 :func:`szse_data_date`），而非 ``as_of_date`` 当天。
    """
    if as_of_date is None:
        as_of_date = date.today()
    trade_date = szse_data_date(as_of_date)

    target_set = set(target_codes)
    if not target_set:
        return []

    df = _request_xlsx()

    # 字段兼容：有时列名带空格
    code_col = "基金代码"
    name_col = "基金简称"
    share_col = "当前规模(份)" if "当前规模(份)" in df.columns else (
        "基金份额" if "基金份额" in df.columns else None
    )
    nav_col = "净值"

    if share_col is None or nav_col not in df.columns:
        raise SzseError(f"szse xlsx unexpected columns: {list(df.columns)}")

    # 清洗份额（千分位逗号 + 转 float）
    shares = df[share_col].astype(str).str.replace(",", "", regex=False)
    shares = pd.to_numeric(shares, errors="coerce")
    df = df.copy()
    df["_share_raw"] = shares
    df["_nav"] = pd.to_numeric(df[nav_col], errors="coerce")

    mask = df[code_col].astype(str).isin(target_set)
    matched = df[mask]

    out: list[dict[str, Any]] = []
    for _, row in matched.iterrows():
        fund_code = str(row[code_col]).strip()
        share_raw = row["_share_raw"]
        nav = row["_nav"]
        share_wanfen = round(share_raw / 10000, 1) if pd.notna(share_raw) and share_raw > 0 else None
        out.append({
            "fund_code": fund_code,
            "fund_name": str(row[name_col]).strip(),
            "trade_date": trade_date,
            "share_wanfen": share_wanfen,
            "nav": round(float(nav), 4) if pd.notna(nav) else None,
            "exchange": "SZSE",
        })

    missing = target_set - {r["fund_code"] for r in out}
    if missing:
        logger.warning("szse snapshot missing codes: %s", sorted(missing))

    logger.info(
        "szse snapshot matched %d/%d target(s) (as_of=%s -> trade_date=%s)",
        len(out), len(target_set), as_of_date, trade_date,
    )
    return out
