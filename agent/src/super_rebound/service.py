"""Business logic for the super-rebound finance module.

Storage: MySQL (``src.super_rebound.db``), short-lived connections.
Margin data source: Eastmoney RPTA_WEB_MARGIN_DAILYTRADE via
``src.super_rebound.eastmoney``. The maintenance margin ratio is
``AVG_GUARANTEE_RATIO``.
ETF share/nav data source: SSE ``query.sse.com.cn`` official endpoints
(``src.super_rebound.sse_cn``). SZSE official endpoints have been
decommissioned since 2025-01; those 5 ETFs are currently flagged TODO
and will be filled once an official replacement is confirmed.
"""

from __future__ import annotations

import logging
import time as _time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any

import akshare as ak

from src.super_rebound import db
from src.super_rebound.db import ETF_GROUP_MAP, rebound_connection
from src.super_rebound.eastmoney import fetch_rows
from src.super_rebound.sse_cn import (
    SseError,
    fetch_scale_for_targets,
    fetch_sse_etf_rows_today,
)
from src.super_rebound.szse_cn import (
    SzseError,
    fetch_szse_etf_snapshot,
)
import time as _time

logger = logging.getLogger(__name__)

WARNING_LINE = 240.0  # 常用警戒参考线 (%)
BACKFILL_START = date(2015, 11, 5)  # 附件起点(2020-11-05)之前的 5 年


@contextmanager
def _conn():
    with rebound_connection() as conn:
        db.initialize_schema(conn)
        yield conn


def _years_ago(d: date, years: int) -> date:
    """Same month/day N calendar years ago (Feb-29 safe)."""
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # Feb 29 on a non-leap target year
        return d.replace(year=d.year - years, day=28)


# ---------------------------------------------------------------------------
# Margin ratio public API
# ---------------------------------------------------------------------------

def get_margin_ratio_latest() -> dict[str, Any]:
    """Latest margin ratio + 6Y/10Y percentiles + 6Y range stats."""
    with _conn() as conn:
        latest = db.get_latest_margin_row(conn)
        if latest is None:
            return {"error": "no_data", "message": "尚未有两融担保比例数据，请先刷新"}

        latest_value = float(latest["AVG_GUARANTEE_RATIO"])
        trade_date = latest["STATISTICS_DATE"]
        if isinstance(trade_date, datetime):
            trade_date = trade_date.date()

        six_start = _years_ago(trade_date, 6)
        ten_start = _years_ago(trade_date, 10)

        # Percentiles: share of historical samples <= latest value.
        six_stats = db.get_margin_stats(conn, six_start, trade_date)
        ten_stats = db.get_margin_stats(conn, ten_start, trade_date)
        six_total = int(six_stats.get("cnt") or 0)
        ten_total = int(ten_stats.get("cnt") or 0)

        six_below = db.count_margin_ratio_below(conn, latest_value, six_start, trade_date)
        ten_below = db.count_margin_ratio_below(conn, latest_value, ten_start, trade_date)

        six_pct = round(six_below / six_total * 100, 1) if six_total else 0.0
        ten_pct = round(ten_below / ten_total * 100, 1) if ten_total else 0.0

        range_high = six_stats.get("max_ratio")
        range_low = six_stats.get("min_ratio")
        range_high = float(range_high) if range_high is not None else None
        range_low = float(range_low) if range_low is not None else None

        vs_high = None
        if range_high:
            vs_high = round((latest_value - range_high) / range_high * 100, 2)

        # History series for chart
        history_rows = db.get_margin_rows(conn, six_start, trade_date)
        history_series = [
            {
                "date": str(r["STATISTICS_DATE"]),
                "ratio": float(r["AVG_GUARANTEE_RATIO"]),
            }
            for r in history_rows
        ]

        updated_at = latest.get("updated_at") or latest.get("created_at")

        def _pct(v: float | None) -> str | None:
            return f"{v:.2f}%" if v is not None else None

        return {
            "trade_date": str(trade_date),
            "margin_ratio": latest_value,
            "margin_ratio_pct": f"{latest_value:.2f}%",
            "six_year_percentile": six_pct,
            "six_year_percentile_display": f"{six_pct}%",
            "ten_year_percentile": ten_pct,
            "ten_year_percentile_display": f"{ten_pct}%",
            "vs_range_high_pct": vs_high,
            "vs_range_high_display": f"{vs_high:.2f}%" if vs_high is not None else None,
            "range_high": range_high,
            "range_high_display": _pct(range_high),
            "range_high_date": str(six_stats["max_date"]) if six_stats.get("max_date") else None,
            "range_low": range_low,
            "range_low_display": _pct(range_low),
            "range_low_date": str(six_stats["min_date"]) if six_stats.get("min_date") else None,
            "sample_count": six_total,
            "data_range_start": str(six_start),
            "data_range_end": str(trade_date),
            "warning_line": WARNING_LINE,
            "history_series": history_series,
            "source": latest.get("source"),
            "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at or ""),
        }


# ---------------------------------------------------------------------------
# ETF monitor public API
# ---------------------------------------------------------------------------

def _group_of(etf_code: str) -> str:
    return ETF_GROUP_MAP.get(etf_code, "其他")


def _etf_codes_by_group() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {g: [] for g in db.INDEX_GROUPS}
    for code, group in ETF_GROUP_MAP.items():
        if group in out:
            out[group].append(code)
    return out


def _empty_detail(start: date, end: date) -> dict[str, Any]:
    return {
        "date_range_start": str(start),
        "date_range_end": str(end),
        "groups": db.INDEX_GROUPS,
        "etf_codes_by_group": _etf_codes_by_group(),
        "daily_rows": [],
        "cumulative_row": None,
        "latest_date": None,
        "note": "暂无数据，请先刷新",
    }


def get_etf_monitor_detail(
    start_date: str | None = None, end_date: str | None = None
) -> dict[str, Any]:
    """Full detail: date rows with per-index net-flow subtotals + total + average.

    数据源：``etf_daily_net_flow`` **宽表**（每行一交易日，7 个指数组各为一列）。
    净流入是流量，不做累计；表格底部展示区间平均净流入行。
    """
    with _conn() as conn:
        if start_date and end_date:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        else:
            end = date.today()
            start = end - timedelta(days=40)

        raw_rows = db.get_etf_netflow_detail(conn, start, end)
        if not raw_rows:
            return _empty_detail(start, end)

        # index_tag → 人类可读组名（前端图表/表格直接展示）
        groups_labeled = [db.INDEX_TAG_LABEL.get(tag, tag) for tag in db.INDEX_TAGS]
        # index_tag → 宽表列名
        tag_to_col = {tag: f"{tag}_net_flow" for tag in db.INDEX_TAGS}

        by_date: dict[date, dict[str, float]] = {}
        for r in raw_rows:
            d = r["date"]
            if isinstance(d, datetime):
                d = d.date()
            day = {}
            for tag in db.INDEX_TAGS:
                label = db.INDEX_TAG_LABEL.get(tag, tag)
                val = r.get(tag_to_col[tag])
                day[label] = float(val) if val is not None else 0.0
            by_date[d] = day

        dates_sorted = sorted(by_date)
        # latest_date 取"数据最完整的最新交易日"：优先取所有 7 个指数组都有数据的最新日期，
        # 否则取非零指数组数量最多的最新日期
        n_groups = len(groups_labeled)
        best_date: date | None = None
        best_nonzero = -1
        for trade_date in reversed(dates_sorted):
            nonzero = sum(1 for v in by_date[trade_date].values() if v != 0)
            if nonzero >= n_groups:
                best_date = trade_date
                break
            if nonzero > best_nonzero:
                best_nonzero = nonzero
                best_date = trade_date
        latest_date = best_date or dates_sorted[-1]

        group_sum = {g: 0.0 for g in groups_labeled}
        daily_rows_out: list[dict[str, Any]] = []

        for trade_date in dates_sorted:
            day_groups = {g: float(by_date[trade_date].get(g, 0.0)) for g in groups_labeled}
            day_total = round(sum(day_groups.values()), 2)
            per_group = {g: round(v, 2) for g, v in day_groups.items()}
            per_group["__total__"] = day_total

            daily_rows_out.append({
                "trade_date": str(trade_date),
                "values": {"per_group": per_group, "total": day_total},
                "is_latest": trade_date == latest_date,
            })
            for g, v in day_groups.items():
                group_sum[g] += v

        n_days = len(dates_sorted)
        avg_per_group = {g: round(group_sum[g] / n_days, 2) for g in groups_labeled}
        avg_total = round(sum(group_sum.values()) / n_days, 2)
        avg_per_group["__total__"] = avg_total

        return {
            "date_range_start": str(start),
            "date_range_end": str(end),
            "groups": groups_labeled,
            "etf_codes_by_group": _etf_codes_by_group(),
            "daily_rows": daily_rows_out,
            # 净流入是流量，底部展示区间平均净流入（兼容旧字段名 cumulative_row）
            "cumulative_row": {
                "trade_date": "区间平均",
                "values": {"per_group": avg_per_group, "total": avg_total},
                "is_latest": False,
                "is_cumulative": True,
                "is_average": True,
            },
            "latest_date": str(latest_date),
        }


def get_etf_monitor_summary(
    start_date: str | None = None, end_date: str | None = None
) -> dict[str, Any]:
    """Lightweight header summary derived from the detail payload.

    返回 7 张卡所需字段（**净流入口径**，份额变动 × 净值）：
      latest_total_net_flow_bn / latest_day_net_flow_bn / latest_day /
      range_high_net_flow_bn / range_high_net_flow_date /
      latest_strongest_etf / avg_largest_etf /
      monitor_days / sample_etf_count / date_range_start / date_range_end
    """
    detail = get_etf_monitor_detail(start_date, end_date)
    rows = detail.get("daily_rows") or []

    with _conn() as conn:
        if start_date and end_date:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        else:
            end = date.today()
            start = end - timedelta(days=40)

        latest_date = None
        latest_strongest_etf: dict[str, Any] | None = None
        avg_largest_etf: dict[str, Any] | None = None
        if rows:
            latest_date_str = rows[-1]["trade_date"]
            latest_date = datetime.strptime(latest_date_str, "%Y-%m-%d").date()
            top_day = db.get_top_etf_by_day_netflow(conn, latest_date, limit=1)
            if top_day:
                t = top_day[0]
                latest_strongest_etf = {
                    "etf_code": t["fund_code"],
                    "etf_name": t.get("fund_name") or "",
                    "index_group": db.INDEX_TAG_LABEL.get(t["index_tag"], t["index_tag"] or ""),
                    "net_flow_bn": float(t["net_flow"] or 0),
                }
            top_avg = db.get_top_etf_by_avg_netflow(conn, start, end, limit=1)
            if top_avg:
                t = top_avg[0]
                avg_largest_etf = {
                    "etf_code": t["fund_code"],
                    "etf_name": t.get("fund_name") or "",
                    "index_group": db.INDEX_TAG_LABEL.get(t["index_tag"], t["index_tag"] or ""),
                    "avg_net_flow_bn": float(t["avg_net_flow_bn"] or 0),
                }

    if not rows:
        return {
            "latest_total_net_flow_bn": 0,
            "latest_day_net_flow_bn": 0,
            "latest_day": None,
            "range_high_net_flow_bn": 0,
            "range_high_net_flow_date": None,
            "latest_strongest_etf": None,
            "avg_largest_etf": None,
            "monitor_days": 0,
            "sample_etf_count": len(db.ETF_TARGETS),
            "date_range_start": detail["date_range_start"],
            "date_range_end": detail["date_range_end"],
        }
    totals = [(r["trade_date"], r["values"]["total"]) for r in rows]
    high_day, high_total = max(totals, key=lambda x: x[1])
    # latest_day 取 is_latest=True 的那行（数据最完整的最新交易日），而非 rows 最后一行
    latest_row = next((r for r in rows if r.get("is_latest")), rows[-1])
    latest_day = latest_row["trade_date"]
    latest_total = latest_row["values"]["total"]
    return {
        "latest_total_net_flow_bn": latest_total,
        "latest_day_net_flow_bn": latest_total,
        "latest_day": latest_day,
        "range_high_net_flow_bn": high_total,
        "range_high_net_flow_date": high_day,
        "latest_strongest_etf": latest_strongest_etf,
        "avg_largest_etf": avg_largest_etf,
        "monitor_days": len(rows),
        "sample_etf_count": len(db.ETF_TARGETS),
        "date_range_start": detail["date_range_start"],
        "date_range_end": detail["date_range_end"],
    }


# ---------------------------------------------------------------------------
# Refresh orchestration (Eastmoney)
# ---------------------------------------------------------------------------

def _sync_margin_incremental(backfill_start: date | None = None) -> int:
    """Fetch upstream rows and upsert. Returns number of rows upserted.

    * With no local data: full history backfill (optionally windowed from
      ``backfill_start``).
    * Otherwise: watermark fetch — only rows strictly newer than the DB max.
    """
    with _conn() as conn:
        watermark = db.get_max_margin_date(conn)

    count = 0
    if watermark is None:
        # Cold start: full history (or windowed backfill).
        logger.info("margin sync: cold start, full backfill from %s", backfill_start)
        rows_iter = fetch_rows(start=backfill_start)
    else:
        logger.info("margin sync: incremental after watermark %s", watermark)
        rows_iter = fetch_rows(stop_before=watermark)

    # Re-open per batch to keep transactions short.
    for row in rows_iter:
        with _conn() as conn:
            try:
                db.upsert_margin_row(conn, row, source="eastmoney")
                count += 1
            except Exception:
                logger.exception("margin sync: failed to upsert row %s", row.get("STATISTICS_DATE"))
        if count % 100 == 0:
            logger.info("margin sync: %d rows upserted so far", count)

    logger.info("margin sync: done, %d rows upserted", count)
    return count


def backfill_history() -> dict[str, Any]:
    """Explicit backfill: fetch the 5 years before the attachment start
    (2015-11-05 .. 2020-11-04) plus fill NULL columns on overlapping dates
    where useful."""
    attachment_start = date(2020, 11, 5)
    end = attachment_start - timedelta(days=1)
    count = 0
    with _conn() as conn:
        pass  # ensure schema
    for row in fetch_rows(start=BACKFILL_START, end=end):
        with _conn() as conn:
            db.upsert_margin_row(conn, row, source="eastmoney")
            count += 1
    return {"success": True, "window": f"{BACKFILL_START} ~ {end}", "rows": count}


def refresh_data() -> dict[str, Any]:
    """Manual refresh: incremental margin sync from Eastmoney + latest-trade-day
    ETF flow sync from SSE official.
    """
    margin_rows = 0
    etf_rows = 0
    message_parts: list[str] = []

    try:
        margin_rows = _sync_margin_incremental()
        message_parts.append(f"东方财富两融增量 {margin_rows} 行")
    except Exception as exc:
        logger.exception("margin refresh failed")
        return {
            "success": False,
            "message": f"东方财富数据抓取失败：{exc}",
            "margin_rows": 0,
            "etf_rows": 0,
        }

    try:
        etf_res = refresh_etf_flow()
        etf_rows = int(etf_res.get("upserted") or 0) + int(etf_res.get("updated") or 0)
        sse_codes = etf_res.get("sse_codes") or []
        szse_codes = etf_res.get("szse_codes") or []
        sse_missing = etf_res.get("sse_missing_codes") or []
        szse_missing = etf_res.get("szse_missing_codes") or []
        if sse_missing:
            message_parts.append(f"上交所缺失 {sse_missing}")
        if szse_missing:
            message_parts.append(f"深交所缺失 {szse_missing}")
        message_parts.append(
            f"上交所 {etf_res.get('trade_date')} upsert={etf_res.get('upserted')} updated={etf_res.get('updated')} "
            f"(SSE {len(sse_codes)} 只 + SZSE {len(szse_codes)} 只)"
        )
    except Exception as exc:
        logger.exception("etf refresh failed")
        message_parts.append(f"ETF 采集失败：{exc}")

    return {
        "success": True,
        "message": "；".join(message_parts),
        "margin_rows": margin_rows,
        "etf_rows": etf_rows,
        "etf_detail": {
            "trade_date": etf_res.get("trade_date") if 'etf_res' in locals() else None,
            "upserted": etf_res.get("upserted") if 'etf_res' in locals() else 0,
            "sse_codes": sse_codes,
            "szse_codes": szse_codes,
            "sse_missing_codes": sse_missing,
            "szse_missing_codes": szse_missing,
        },
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


def refresh_needed() -> dict[str, Any]:
    """True when the newest local row predates the latest trade day."""
    with _conn() as conn:
        latest = db.get_max_margin_date(conn)
    if latest is None:
        return {"needed": True, "reason": "no_data"}
    # Eastmoney publishes T-day data in the evening; flag stale if the
    # local max is more than 4 calendar days behind.
    if latest < date.today() - timedelta(days=4):
        return {"needed": True, "reason": "stale", "latest": str(latest)}
    return {"needed": False, "latest": str(latest)}


def run_daily_sync() -> dict[str, Any]:
    """Entry point for the background scheduler (incremental, quiet).

    Runs both margin sync (Eastmoney) and ETF flow sync (SSE official).
    """
    margin_rows = 0
    etf_rows = 0
    errors: list[str] = []

    try:
        margin_rows = _sync_margin_incremental()
        logger.info("scheduler margin sync: %d new rows", margin_rows)
    except Exception as exc:
        logger.exception("scheduler margin sync failed")
        errors.append(f"margin: {exc}")

    try:
        etf_result = run_etf_flow_collection()
        etf_rows = int(etf_result.get("upserted") or 0) + int(etf_result.get("updated") or 0)
    except Exception as exc:
        logger.exception("scheduler etf sync failed")
        errors.append(f"etf: {exc}")

    success = len(errors) == 0
    return {
        "success": success,
        "margin_rows": margin_rows,
        "etf_rows": etf_rows,
        "errors": errors or None,
    }


# ---------------------------------------------------------------------------
# ETF daily flow — SSE 官方 + SZSE TODO
# ---------------------------------------------------------------------------

# 份额异常跳变阈值：超过前日 50% 视为可能折算/拆分，remark 标记
_SHARE_JUMP_RATIO = 0.5


def _calc_net_flow(
    share_t: float | None, share_t_1: float | None, nav: float | None
) -> tuple[float | None, str | None]:
    """Return (net_flow_bn, remark).

    Formula (份额口径一级申赎净流入):
        net_flow(亿元) = (share_t - share_t_1) × nav / 10000
    share_t/_1 单位是"万份"；nav 单位是元。
    """
    remark: str | None = None
    if share_t is None or nav is None or nav <= 0:
        return None, "份额或净值缺失"
    if share_t_1 is None:
        return None, "缺少前置份额（首次入库）"

    delta_wanfen = share_t - share_t_1
    net_flow_bn = round(delta_wanfen * nav / 10000, 4)  # 万份 × 元 / 10000 = 亿元

    # 份额异常跳变检测
    if share_t_1 > 0:
        ratio = abs(delta_wanfen) / share_t_1
        if ratio > _SHARE_JUMP_RATIO:
            remark = f"份额异常跳变 {ratio:.1%}（疑似折算/拆分），不计入汇总"

    return net_flow_bn, remark


def run_etf_flow_collection(trade_date: date | None = None) -> dict[str, Any]:
    """ETF 净流入采集（上交所 12 只 + 深交所 5 只）。

    深交所用 AKShare 逆向的 fund.szse.cn 接口（仅当日快照、不能回灌）。
    上交所同时支持历史回灌（见 backfill_etf_history）。
    """
    if trade_date is None:
        trade_date = date.today()

    sse_codes = [t["fund_code"] for t in db.SSE_TARGETS]
    szse_codes = [t["fund_code"] for t in db.SZSE_TARGETS]
    code_to_target = {t["fund_code"]: t for t in db.ETF_TARGETS}

    upserted = 0
    updated = 0
    errors: list[str] = []
    collected: list[dict[str, Any]] = []

    # ---- 上交所 ----
    try:
        sse_rows = fetch_sse_etf_rows_today(trade_date, sse_codes)
    except Exception as exc:
        logger.exception("sse fetch failed for %s", trade_date)
        sse_rows = []
        errors.append(f"sse: {exc}")

    # ---- 深交所（仅最新交易日快照，T-1 滞后，不能回灌）----
    szse_rows: list[dict[str, Any]] = []
    if trade_date == date.today():
        try:
            szse_rows = fetch_szse_etf_snapshot(szse_codes, as_of_date=date.today())
        except SzseError as exc:
            logger.exception("szse fetch failed for %s", trade_date)
            errors.append(f"szse: {exc}")
        except Exception as exc:
            logger.exception("szse unexpected error")
            errors.append(f"szse: {exc}")

    with _conn() as conn:
        # ---- SSE ----
        for row in sse_rows:
            target = code_to_target[row["fund_code"]]
            prev = db.get_previous_etf_share(conn, trade_date, row["fund_code"])
            share_t = row["share_wanfen"]
            share_t_1 = prev["share_t"] if prev else None
            nav = row["nav"]
            net_flow, remark = _calc_net_flow(share_t, share_t_1, nav)

            is_insert = db.upsert_etf_flow_row(
                conn,
                trade_date=trade_date,
                fund_code=row["fund_code"],
                fund_name=target["fund_name"],
                index_tag=target["index_tag"],
                exchange="SSE",
                share_t=share_t,
                share_t_1=share_t_1,
                nav=nav,
                market_cap_bn=row.get("market_cap_bn"),
                net_flow=net_flow,
                remark=remark,
                source="sse_official",
            )
            if is_insert: upserted += 1
            else: updated += 1
            collected.append({
                "code": row["fund_code"], "name": target["fund_name"],
                "nav": nav, "share_t": share_t, "net_flow": net_flow,
                "remark": remark, "exchange": "SSE",
            })

        # ---- SZSE ----
        # 注意：SZSE 接口 T-1 滞后，row["trade_date"] 是修正后的真实交易日
        for row in szse_rows:
            szse_trade_date = row["trade_date"]
            target = code_to_target[row["fund_code"]]
            prev = db.get_previous_etf_share(conn, szse_trade_date, row["fund_code"])
            share_t = row["share_wanfen"]
            share_t_1 = prev["share_t"] if prev else None
            nav = row["nav"]
            net_flow, remark = _calc_net_flow(share_t, share_t_1, nav)

            is_insert = db.upsert_etf_flow_row(
                conn,
                trade_date=szse_trade_date,
                fund_code=row["fund_code"],
                fund_name=target["fund_name"],
                index_tag=target["index_tag"],
                exchange="SZSE",
                share_t=share_t,
                share_t_1=share_t_1,
                nav=nav,
                market_cap_bn=None,
                net_flow=net_flow,
                remark=remark,
                source="szse_official",
            )
            if is_insert: upserted += 1
            else: updated += 1
            collected.append({
                "code": row["fund_code"], "name": target["fund_name"],
                "nav": nav, "share_t": share_t, "net_flow": net_flow,
                "remark": remark, "exchange": "SZSE",
            })

    sse_missing = set(sse_codes) - {r["fund_code"] for r in sse_rows}
    szse_missing = set(szse_codes) - {r["fund_code"] for r in szse_rows}
    if sse_missing: logger.warning("sse collection %s missing: %s", trade_date, sorted(sse_missing))
    if szse_missing: logger.warning("szse collection %s missing: %s (接口可能暂无该代码)", trade_date, sorted(szse_missing))

    # 同步刷新每日净流入表（etf_daily_net_flow）
    try:
        nf = db.refresh_etf_daily_net_flow(conn, trade_date, trade_date)
        logger.info("etf_daily_net_flow refreshed for %s: %s", trade_date, nf)
    except Exception as exc:
        logger.exception("refresh etf_daily_net_flow failed for %s", trade_date)
        errors.append(f"net_flow_refresh: {exc}")

    return {
        "success": not errors,
        "trade_date": str(trade_date),
        "sse_codes": [r["fund_code"] for r in sse_rows],
        "szse_codes": [r["fund_code"] for r in szse_rows],
        "sse_missing_codes": sorted(sse_missing),
        "szse_missing_codes": sorted(szse_missing),
        "upserted": upserted,
        "updated": updated,
        "errors": errors or None,
        "rows": collected,
    }


# ---------------------------------------------------------------------------
# ETF 历史回灌（上交所官方份额接口，按交易日循环）
# ---------------------------------------------------------------------------

def _trading_days(start: date, end: date) -> list[date]:
    """工作日清单（简单跳过周六周日；不识别法定节假日，但 SSE 节假日接口
    会返回空结果，fetch_scale_for_targets 自动空列表，upsert 幂等）。"""
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def backfill_etf_history(
    start: date,
    end: date,
    fund_codes: list[str] | None = None,
    sleep_per_call: float = 0.15,
) -> dict[str, Any]:
    """回灌上交所 ETF 历史份额（官方接口）。

    NAV 只有 sgInfo 能拿但不支持历史回溯，所以回灌时 nav=None，
    等每日自动采集自然能拿到当日 NAV + 之前已入库的份额（跨日后自动算出 net_flow）。

    断点续跑：已存在的 (date, fund_code) 会被 UPDATE 覆盖（幂等，不增长）。
    """
    if fund_codes is None:
        fund_codes = [t["fund_code"] for t in db.SSE_TARGETS]
    code_to_target = {t["fund_code"]: t for t in db.ETF_TARGETS}

    days = _trading_days(start, end)
    logger.info("etf backfill window %s~%s: %d trading days, %d funds", start, end, len(days), len(fund_codes))

    total_upserted = 0
    total_updated = 0
    total_missing = 0
    errors: list[dict[str, str]] = []

    with _conn() as conn:
        for i, trade_date in enumerate(days, 1):
            if i % 20 == 0 or i == len(days):
                logger.info("etf backfill progress %d/%d (%s)", i, len(days), trade_date)

            try:
                scale_map = fetch_scale_for_targets(trade_date, fund_codes)
            except SseError as exc:
                logger.warning("sse scale %s error: %s", trade_date, exc)
                errors.append({"date": str(trade_date), "error": str(exc)})
                _time.sleep(max(1.0, sleep_per_call * 4))
                continue
            except Exception as exc:
                logger.exception("etf backfill %s unexpected", trade_date)
                errors.append({"date": str(trade_date), "error": str(exc)})
                _time.sleep(max(1.0, sleep_per_call * 4))
                continue

            if not scale_map:
                _time.sleep(sleep_per_call)
                continue  # 法定节假日或基金尚未上市

            for code, srow in scale_map.items():
                target = code_to_target.get(code)
                if not target:
                    continue
                # 前一日份额：直接查库（backfill 按时间顺序跑，T-1 一定已入库）
                prev = db.get_previous_etf_share(conn, trade_date, code)
                share_t = srow["share_wanfen"]
                share_t_1 = prev["share_t"] if prev else None

                is_insert = db.upsert_etf_flow_row(
                    conn,
                    trade_date=trade_date,
                    fund_code=code,
                    fund_name=target["fund_name"],
                    index_tag=target["index_tag"],
                    exchange="SSE",
                    share_t=share_t,
                    share_t_1=share_t_1,
                    nav=None,                # sgInfo 不支持历史
                    market_cap_bn=None,       # fund_detail 不支持历史
                    net_flow=None,           # 等 NAV 后续补入或每日自然生成
                    remark="历史回灌（上交所官方份额接口）",
                    source="sse_official_backfill",
                )
                if is_insert:
                    total_upserted += 1
                else:
                    total_updated += 1

            missing = set(fund_codes) - set(scale_map)
            total_missing += len(missing)

            _time.sleep(sleep_per_call)

    return {
        "success": True,
        "window": f"{start} ~ {end}",
        "trading_days": len(days),
        "funds": len(fund_codes),
        "upserted": total_upserted,
        "updated": total_updated,
        "missing_count": total_missing,
        "errors": errors or None,
    }


def backfill_etf_history_recent(years: int = 5) -> dict[str, Any]:
    """Convenience: backfill last N years of SSE ETF shares."""
    today = date.today()
    start = today - timedelta(days=years * 365)
    return backfill_etf_history(start=start, end=today - timedelta(days=1))


def refresh_etf_flow() -> dict[str, Any]:
    """Manual refresh — run collection for the latest trade day (today if
    weekday, otherwise the most recent Friday)."""
    today = date.today()
    d = today
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return run_etf_flow_collection(trade_date=d)


def backfill_etf_nav(
    start: date | None = None,
    end: date | None = None,
    fund_codes: list[str] | None = None,
    sleep_per_call: float = 0.25,
) -> dict[str, Any]:
    """Backfill NAV for all ETFs in ``etf_daily_flow`` via Eastmoney fundf10.

    Uses ``akshare.fund_open_fund_info_em(symbol, indicator='单位净值走势',
    period='成立来')`` which returns the full history of 单位净值 for any
    ETF code (SSE/SZSE both work).  Rows that already have ``share_t`` and
    ``share_t_1`` are auto-promoted to ``net_flow`` once ``nav`` lands.

    This function is idempotent — running it a second time just updates the
    nav column (share_t / net_flow untouched) and recomputes only rows where
    net_flow IS NULL.
    """
    targets = [t for t in db.ETF_TARGETS if not fund_codes or t["fund_code"] in fund_codes]
    if not targets:
        return {"success": False, "message": "没有匹配的 ETF", "etf_count": 0}

    total_nav_updated = 0
    skipped = []

    with _conn() as conn:
        for t in targets:
            code = t["fund_code"]
            try:
                df = ak.fund_open_fund_info_em(
                    symbol=code, indicator="单位净值走势", period="成立来"
                )
            except Exception as exc:
                logger.warning("backfill nav: akshare failed for %s: %s", code, exc)
                skipped.append(code)
                _time.sleep(sleep_per_call)
                continue

            # Normalize columns (akshare may return different names)
            if df is None or df.empty:
                skipped.append(code)
                _time.sleep(sleep_per_call)
                continue

            date_col = "净值日期"
            nav_col = "单位净值"
            if date_col not in df.columns or nav_col not in df.columns:
                logger.warning("backfill nav: unexpected columns for %s: %s", code, df.columns.tolist())
                skipped.append(code)
                _time.sleep(sleep_per_call)
                continue

            for _, row in df.iterrows():
                d_raw = row[date_col]
                nav_raw = row[nav_col]
                if nav_raw is None or (isinstance(nav_raw, float) and nav_raw != nav_raw):
                    continue
                try:
                    if isinstance(d_raw, (datetime,)):
                        trade_d = d_raw.date()
                    elif isinstance(d_raw, date):
                        trade_d = d_raw
                    else:
                        trade_d = datetime.strptime(str(d_raw), "%Y-%m-%d").date()
                    nav = float(nav_raw)
                except Exception:
                    continue

                if start and trade_d < start:
                    continue
                if end and trade_d > end:
                    continue

                db.update_etf_nav(conn, trade_d, code, nav)
                total_nav_updated += 1

            _time.sleep(sleep_per_call)

        # Recompute net_flow where share_t + share_t_1 + nav are now all in.
        # 使用最早有 share_t 的日期作为 recalc_start，全量覆盖。
        with _conn() as conn2:
            with conn2.cursor() as cur2:
                cur2.execute(
                    "SELECT MIN(date) AS d FROM etf_daily_flow WHERE share_t IS NOT NULL"
                )
                row2 = cur2.fetchone()
                recalc_start = row2["d"] if row2 and row2["d"] else date(2020, 1, 1)
                if isinstance(recalc_start, datetime):
                    recalc_start = recalc_start.date()
            recalc_end = end or db.get_max_etf_flow_date(conn2) or date.today()
            if isinstance(recalc_end, datetime):
                recalc_end = recalc_end.date()
            recomputed = db.recompute_etf_net_flow(conn2, recalc_start, recalc_end)

    return {
        "success": True,
        "etf_count": len(targets),
        "nav_rows_updated": total_nav_updated,
        "net_flow_rows_recomputed": recomputed,
        "skipped_codes": skipped,
    }


# ---------------------------------------------------------------------------
# ETF daily flow — 查询接口（前端）
# ---------------------------------------------------------------------------

def get_etf_flow_overview(
    start_date: str | None = None, end_date: str | None = None
) -> dict[str, Any]:
    """头部汇总：累计净流入、最新日净流入、最大单日净流入、监测天数。"""
    with _conn() as conn:
        if start_date and end_date:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        else:
            end = date.today()
            start = end - timedelta(days=60)

        summary = db.get_etf_flow_summary(conn, start, end)
        if not summary:
            return {
                "cumulative_net_flow_bn": 0.0,
                "latest_day_total_bn": 0.0,
                "latest_day": None,
                "max_day_total_bn": 0.0,
                "max_day": None,
                "monitor_days": 0,
                "date_range_start": str(start),
                "date_range_end": str(end),
                "note": "暂无数据，请先刷新",
            }

        # 按日期再汇总一次（不同 index_tag 要相加）
        by_date: dict[date, float] = {}
        for row in summary:
            d = row["date"]
            if isinstance(d, datetime):
                d = d.date()
            by_date[d] = by_date.get(d, 0.0) + float(row["total_net_flow_bn"] or 0)

        dates = sorted(by_date)
        latest = dates[-1]
        high_date = max(by_date, key=by_date.get)
        return {
            "cumulative_net_flow_bn": round(sum(by_date.values()), 4),
            "latest_day_total_bn": round(by_date[latest], 4),
            "latest_day": str(latest),
            "max_day_total_bn": round(by_date[high_date], 4),
            "max_day": str(high_date),
            "monitor_days": len(dates),
            "date_range_start": str(start),
            "date_range_end": str(end),
        }


def get_etf_flow_detail(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """全量明细 + 按日期分组 + 累计行，前端表格/折线直接消费。"""
    with _conn() as conn:
        if start_date and end_date:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        else:
            end = date.today()
            start = end - timedelta(days=60)

        raw = db.get_etf_flow_detail(conn, start, end)
        if not raw:
            return {
                "date_range_start": str(start),
                "date_range_end": str(end),
                "tags": list(db.INDEX_TAG_LABEL.values()),
                "daily_rows": [],
                "cumulative_row": None,
                "latest_date": None,
                "note": "暂无数据，请先刷新",
                "disclaimer": (
                    "本数据采集自上交所官方披露（深交所官方接口 2025 年起下线，暂缺）；"
                    "净流入 =（当日份额 − 前交易日份额）× 单位净值，为一级市场申赎口径，"
                    "不等于二级市场成交净买入。"
                ),
            }

        # 按 (date, index_tag) 聚合净流入
        by_date_tag: dict[tuple[date, str], float] = {}
        by_date_funds: dict[tuple[date, str], list[dict[str, Any]]] = {}
        for row in raw:
            d = row["date"]
            if isinstance(d, datetime):
                d = d.date()
            tag = row["index_tag"]
            nf = float(row["net_flow"] or 0)
            by_date_tag[(d, tag)] = by_date_tag.get((d, tag), 0.0) + nf
            by_date_funds.setdefault((d, tag), []).append({
                "fund_code": row["fund_code"],
                "fund_name": row["fund_name"],
                "nav": row["nav"],
                "share_t": row["share_t"],
                "share_t_1": row["share_t_1"],
                "market_cap_bn": row["market_cap_bn"],
                "net_flow": row["net_flow"],
                "exchange": row["exchange"],
                "remark": row["remark"],
            })

        dates_sorted = sorted({d for d, _ in by_date_tag})
        latest_date = dates_sorted[-1]

        cum_tag = {tag: 0.0 for tag in db.INDEX_TAG_LABEL}
        daily_rows_out: list[dict[str, Any]] = []

        for trade_date in dates_sorted:
            day_tags: dict[str, float] = {tag: 0.0 for tag in db.INDEX_TAG_LABEL}
            day_funds: dict[str, list[dict[str, Any]]] = {}
            for (d, tag), v in by_date_tag.items():
                if d == trade_date:
                    day_tags[tag] = round(v, 4)
                    day_funds[tag] = by_date_funds[(d, tag)]
            day_total = round(sum(day_tags.values()), 4)
            for tag in db.INDEX_TAG_LABEL:
                cum_tag[tag] += day_tags[tag]

            daily_rows_out.append({
                "trade_date": str(trade_date),
                "values": {"per_tag": day_tags, "total": day_total},
                "funds_by_tag": day_funds,
                "is_latest": trade_date == latest_date,
            })

        cum_per_tag = {tag: round(v, 4) for tag, v in cum_tag.items()}
        cum_total = round(sum(cum_tag.values()), 4)

        return {
            "date_range_start": str(start),
            "date_range_end": str(end),
            "tags": list(db.INDEX_TAG_LABEL.values()),
            "tag_label": db.INDEX_TAG_LABEL,
            "daily_rows": daily_rows_out,
            "cumulative_row": {
                "trade_date": "累计",
                "values": {"per_tag": cum_per_tag, "total": cum_total},
                "is_latest": False,
                "is_cumulative": True,
            },
            "latest_date": str(latest_date),
            "disclaimer": (
                "本数据采集自上交所官方披露（深交所官方接口 2025 年起下线，暂缺）；"
                "净流入 =（当日份额 − 前交易日份额）× 单位净值，为一级市场申赎口径，"
                "不等于二级市场成交净买入。"
            ),
        }
