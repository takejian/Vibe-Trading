"""gold_monitor monthly_indicator_service.py

从公开 API 拉取黄金政策周期月度指标, 直接写 DuckDB gold_monthly.

数据源 (全部实测可用, 无需 key):
    * 黄金月均价    → vibe MySQL gold_daily_bar 日线聚合
                     (close CNY/g → USD/oz = close * 31.1035 / fx_rate)
    * 联邦基金利率   → FRED FEDFUNDS (已月频, observation_date=月初)
    * 10Y 美债名义收益率 → FRED DGS10 (日频 → 月均值)
    * 10Y TIPS 实际收益率 → FRED DFII10 (日频 → 月均值)
    * BEI          → FRED T10YIE (日频 → 月均值, 但我们也会用 yield - tips 校验)

FRED CSV 端点: https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES}
    — 实测 HTTP 200, 无需 API key.

DuckDB 目标表: ~/.vibe-trading/data/market.duckdb / gold_monthly
    source 写 "fred_api" (区分之前的 "excel" 手工导入数据).

设计: 优先这条 API 链路, 如果某指标失败 (网络/限流/无数据) 则字段留 NULL,
      不是整月失败; 回退 LLM 只在 API 拉不到任何有效数据时触发.
"""

from __future__ import annotations

import io
import logging
from datetime import date
from typing import Any

import duckdb
import pandas as pd
import requests

from src.gold_monitor.db import (
    get_monthly_by_month,
    insert_or_update_monthly,
    gold_connection,
    initialize_schema,
)

logger = logging.getLogger(__name__)

#: 美元/盎司换算常量
_OZ_PER_GRAM = 31.1035
_DEFAULT_FX_CNY_USD = 6.6707

#: FRED 公开 CSV 端点 (实测 HTTP 200, 无需 key)
_FRED_CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"

#: 需要的 FRED 序列
_FRED_SERIES = {
    "ffr":            "FEDFUNDS",   # 联邦基金利率 (月频, observation_date 是月初)
    "yield_nominal":  "DGS10",      # 10Y 美债名义收益率 (日频)
    "tips_real":      "DFII10",     # 10Y TIPS 实际收益率 (日频)
}


# ---------------------------------------------------------------------------
# FRED CSV 拉取 + 解析 + 月聚合
# ---------------------------------------------------------------------------

def _fetch_fred_csv(series: str) -> pd.DataFrame:
    """拉取 FRED CSV, 返回 DataFrame[date, value] 已解析数值 + 日期."""
    url = f"{_FRED_CSV_BASE}?id={series}"
    resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    # 列: observation_date, {SERIES}
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    return df


def _aggregate_monthly(df: pd.DataFrame) -> dict[str, float]:
    """把日频/月频 DataFrame 按月聚合 → { 'YYYY-MM': mean_value }.

    月频数据 (FEDFUNDS 的 observation_date 本身就是月初) 直接按 month 映射.
    日频数据按当月所有交易日的均值.
    """
    if df.empty:
        return {}
    df = df.copy()
    df["month"] = df["date"].dt.to_period("M").astype(str)
    # 对同一份数据, 一个 month 下可能多条记录 → 取 mean
    grouped = df.groupby("month")["value"].mean().round(6)
    return grouped.to_dict()


# ---------------------------------------------------------------------------
# 黄金月均价 (从 MySQL gold_daily_bar 聚合)
# ---------------------------------------------------------------------------

def _fetch_gold_monthly(start_month: str = "2024-01") -> dict[str, float]:
    """从 vibe MySQL gold_daily_bar 聚合黄金月均价 (USD/oz).

    返回 { 'YYYY-MM': gold_price_usd_per_oz }.
    """
    import pymysql
    from pymysql.cursors import DictCursor
    from src.config.accessor import get_env_config

    cfg = get_env_config()
    macro = cfg.macro
    sr = cfg.super_rebound

    conn = pymysql.connect(
        host=macro.macro_db_host or sr.super_rebound_db_host or "127.0.0.1",
        port=int(macro.macro_db_port or sr.super_rebound_db_port or 3306),
        user=macro.macro_db_user or sr.super_rebound_db_user or "root",
        password=macro.macro_db_password or sr.super_rebound_db_password or "",
        database=macro.macro_db_name or sr.super_rebound_db_name or "vibe",
        charset="utf8mb4", cursorclass=DictCursor,
    )
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT trade_date, close, fx_rate_cny_usd FROM gold_daily_bar "
            "WHERE trade_date >= %s ORDER BY trade_date",
            [start_month + "-01"],
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    if not rows:
        return {}

    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    # 用每行自己的 fx_rate, 空的用默认值
    df["fx_rate"] = df["fx_rate_cny_usd"].fillna(_DEFAULT_FX_CNY_USD)
    df["price_usd_per_oz"] = df["close"] * _OZ_PER_GRAM / df["fx_rate"]
    df["month"] = df["trade_date"].dt.to_period("M").astype(str)

    grouped = df.groupby("month")["price_usd_per_oz"].mean().round(2)
    return grouped.to_dict()


# ---------------------------------------------------------------------------
# 主入口: 拉取 + 写入 DuckDB
# ---------------------------------------------------------------------------

def fetch_and_write_monthly(
    target_month: str | None = None,
    backfill_months: int = 12,
    source_tag: str = "fred_api",
) -> dict[str, Any]:
    """拉取月度指标 + 写入 DuckDB gold_monthly.

    :param target_month: 指定只写某一月 "YYYY-MM"; None → 自动从 MySQL 日线覆盖区间
    :param backfill_months: 覆盖目标月前多少个月 (确保历史可比)
    :param source_tag: 写入 source 字段
    :return: 写入汇总信息
    """
    logger.info("fetch_and_write_monthly start: target=%s backfill=%d", target_month, backfill_months)

    # --- Step 1: 并行拉所有 FRED 序列 ---
    fred_data: dict[str, dict[str, float]] = {}
    for key, series in _FRED_SERIES.items():
        try:
            raw = _fetch_fred_csv(series)
            fred_data[key] = _aggregate_monthly(raw)
            logger.info("  FRED %s (%s): %d months", series, key, len(fred_data[key]))
        except Exception as exc:
            logger.warning("  FRED %s (%s) 失败: %s", series, key, exc)
            fred_data[key] = {}

    # --- Step 2: 黄金月均价 ---
    gold_months = _month_range(target_month, backfill_months)
    # 取范围里最早的那个月 (降序列表的最后一个) 作为 MySQL 查询起点
    gold_start = gold_months[-1] if gold_months else "2020-01"
    gold_data = _fetch_gold_monthly(start_month=gold_start)
    logger.info("  黄金月均价: %d months (覆盖 %s ~ %s)",
                len(gold_data), min(gold_data) if gold_data else "?", max(gold_data) if gold_data else "?")

    # --- Step 3: 合并成统一的 { 'YYYY-MM': {field: value} } ---
    # 黄金决定覆盖范围 (它是我们自己的数据源, 最可靠)
    months_to_write = sorted(set(gold_data.keys()) |
                             set(fred_data["ffr"].keys()) |
                             set(fred_data["yield_nominal"].keys()) |
                             set(fred_data["tips_real"].keys()))
    if target_month:
        # 只写 target_month 附近
        start = _offset_month(target_month, -backfill_months)
        months_to_write = [m for m in months_to_write if m >= start and m <= target_month]

    logger.info("  目标月份范围: %d 个 (%s ~ %s)",
                len(months_to_write), months_to_write[0] if months_to_write else "?",
                months_to_write[-1] if months_to_write else "?")

    # --- Step 4: 逐行写 DuckDB ---
    written = 0
    updated = 0
    failed_months: list[str] = []

    for ym in months_to_write:
        gold = gold_data.get(ym)
        ffr = fred_data["ffr"].get(ym)
        yn = fred_data["yield_nominal"].get(ym)
        tr = fred_data["tips_real"].get(ym)

        # === 完整度门禁: 核心字段有任一缺失 → 跳过 ===
        # 原因: FRED 各序列发布时间不同 (FEDFUNDS 月频滞后约 2 周, DGS10/DFII10 日频)
        # 跳过部分数据的月, 保证入库的每月都是完整可用于计算的
        if gold is None or ffr is None or yn is None or tr is None:
            logger.debug("  跳过 %s: 核心字段缺失 (gold=%s ffr=%s yn=%s tr=%s)", ym, gold, ffr, yn, tr)
            continue

        # 计算 BEI (通胀预期)
        bei = round(yn - tr, 6)

        # 同比/环比 (需要拿去年和上月数据)
        yoy_month = _offset_month(ym, -12)
        prev_month = _offset_month(ym, -1)

        prev_gold = gold_data.get(prev_month)
        yoy_gold = gold_data.get(yoy_month)
        prev_ffr = fred_data["ffr"].get(prev_month)
        prev_tips = fred_data["tips_real"].get(prev_month)

        gold_change_pct = round((gold - yoy_gold) / yoy_gold * 100, 4) if (gold and yoy_gold) else None
        ffr_change = round(ffr - prev_ffr, 4) if (ffr is not None and prev_ffr is not None) else None
        real_change = round(tr - prev_tips, 4) if (tr is not None and prev_tips is not None) else None

        row = {
            "gold_price": gold,
            "ffr": ffr,
            "yield_nominal": yn,
            "bei": bei,
            "tips_real": tr,
            "gold_change_pct": gold_change_pct,
            "ffr_change": ffr_change,
            "real_change": real_change,
        }

        try:
            with gold_connection() as conn:
                initialize_schema(conn)
                existing = get_monthly_by_month(conn, ym)
                insert_or_update_monthly(conn, ym, **row, source=source_tag)
                conn.commit()
            if existing is None:
                written += 1
            else:
                updated += 1
        except Exception as exc:
            logger.exception("  写入 %s 失败", ym)
            failed_months.append(ym)

    result = {
        "months_written": written,
        "months_updated": updated,
        "failed_months": failed_months,
        "range": (months_to_write[0] if months_to_write else None,
                  months_to_write[-1] if months_to_write else None),
        "source": source_tag,
    }
    logger.info("fetch_and_write_monthly done: %s", result)
    return result


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _offset_month(month: str, delta: int) -> str:
    """'2026-11', -1 → '2026-10'."""
    year, m = [int(x) for x in month.split("-")]
    total = year * 12 + m + delta
    new_year, new_m = divmod(total - 1, 12)
    new_m += 1
    return f"{new_year:04d}-{new_m:02d}"


def _month_range(center: str | None, months: int) -> list[str]:
    """返回 center 往前 months 月的列表 (降序)."""
    if center is None:
        return []
    return [_offset_month(center, -i) for i in range(months)]
