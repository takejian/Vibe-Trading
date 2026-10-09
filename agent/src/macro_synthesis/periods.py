"""期次解析与归属判定（月 / 季）。

期次格式：
* 月：``2026-10``
* 季：``2026-Q4``

run 时间归属直接取 ISO 时间戳的日期前缀（与前端记录的展示口径一致），
不做时区换算，避免本地/UTC 跨日造成的归集抖动。
"""

from __future__ import annotations

import re
from datetime import date

from .models import PERIOD_MONTH, PERIOD_QUARTER

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")

_QUARTER_CN = {1: "第一季度", 2: "第二季度", 3: "第三季度", 4: "第四季度"}
_MONTH_CN = {
    1: "1月", 2: "2月", 3: "3月", 4: "4月", 5: "5月", 6: "6月",
    7: "7月", 8: "8月", 9: "9月", 10: "10月", 11: "11月", 12: "12月",
}


class InvalidPeriodError(ValueError):
    """期次格式或类型非法。"""


def validate(period_type: str, period: str) -> None:
    """校验期次类型与格式，非法时抛 :class:`InvalidPeriodError`。"""
    if period_type == PERIOD_MONTH:
        if not _MONTH_RE.match(period or ""):
            raise InvalidPeriodError("月期次必须为 YYYY-MM 格式。")
    elif period_type == PERIOD_QUARTER:
        if not _QUARTER_RE.match(period or ""):
            raise InvalidPeriodError("季期次必须为 YYYY-QN 格式。")
    else:
        raise InvalidPeriodError("period_type 仅支持 month / quarter。")


def current_period(period_type: str, today: date | None = None) -> str:
    """返回当前（月/季）期次字符串。"""
    today = today or date.today()
    if period_type == PERIOD_MONTH:
        return f"{today.year}-{today.month:02d}"
    if period_type == PERIOD_QUARTER:
        quarter = (today.month - 1) // 3 + 1
        return f"{today.year}-Q{quarter}"
    raise InvalidPeriodError("period_type 仅支持 month / quarter。")


def period_label(period_type: str, period: str) -> str:
    """返回期次中文标签。"""
    validate(period_type, period)
    if period_type == PERIOD_MONTH:
        year, month = _MONTH_RE.match(period).groups()
        return f"{year}年{_MONTH_CN[int(month)]}"
    year, quarter = _QUARTER_RE.match(period).groups()
    return f"{year}年{_QUARTER_CN[int(quarter)]}"


def run_belongs(iso_ts: str | None, period_type: str, period: str) -> bool:
    """判定一个 ISO 时间戳的 run 是否归属指定期次。"""
    validate(period_type, period)
    if not iso_ts or len(iso_ts) < 7:
        return False
    year_month = iso_ts[:7]
    if period_type == PERIOD_MONTH:
        return year_month == period
    match = _MONTH_RE.match(year_month)
    if not match:
        return False
    year, month = match.groups()
    quarter = (int(month) - 1) // 3 + 1
    return period == f"{year}-Q{quarter}"
