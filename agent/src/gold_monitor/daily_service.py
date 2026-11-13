"""黄金日线行情 service — akshare 拉取 + vibe MySQL 幂等 upsert.

数据源固定为 ``akshare.futures_main_sina(symbol="AU0")``（上期所黄金主力连续）。
经实测，Yahoo Finance 自 2021-11-01 起对中国大陆 IP 全域名封禁，不可用。

落库目标:
    * ``vibe.gold_daily_bar``          — 日线 OHLCV + 当日实时价
    * ``vibe.gold_daily_refresh_log``  — 每次刷新一条审计记录

设计要点（来自项目经验）:
    * upsert 用 ``INSERT ... ON DUPLICATE KEY UPDATE`` 幂等写入，避免冻结盘中半成品数据。
    * ``prev_close`` / ``change_amt`` / ``change_pct`` / ``price_usd_per_oz`` 由后端计算，不信任 akshare。
    * 同一自然日内同一 symbol 最多刷新 10 次，防止疯狂点击触发 akshare 限流。
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime, time
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from src.config.accessor import get_env_config

logger = logging.getLogger(__name__)

#: akshare futures_main_sina 的 symbol 参数 — 上期所黄金主力连续
_DEFAULT_SYMBOL = "AU0"
_DEFAULT_EXCHANGE = "SHFE"
_DEFAULT_SOURCE = "akshare.futures_main_sina"
_DEFAULT_INIT_START = "20200101"

#: USD/CNY 参考汇率（换算 USD/oz 用）。
# 默认值为 2026-11-13 08:35 实时汇率 6.6707；
# 若 akshare 实时汇率接口可用会在运行时覆盖此字段。
_DEFAULT_FX_CNY_USD = 6.6707

#: 同一自然日内同一 symbol 最多刷新次数（防 akshare 限流）
_MAX_REFRESH_PER_DAY = 10

#: USD/oz 换算常量: 1 troy ounce = 31.1035 grams
_OZ_PER_GRAM = 31.1035


# ---------------------------------------------------------------------------
# MySQL 连接（vibe schema）
# ---------------------------------------------------------------------------

@contextmanager
def vibe_connection():
    """Open a short-lived pymysql connection to the vibe MySQL schema."""
    cfg = get_env_config()
    macro = cfg.macro
    sr = cfg.super_rebound
    kwargs = {
        "host": macro.macro_db_host or sr.super_rebound_db_host or "127.0.0.1",
        "port": int(macro.macro_db_port or sr.super_rebound_db_port or 3306),
        "user": macro.macro_db_user or sr.super_rebound_db_user or "root",
        "password": macro.macro_db_password or sr.super_rebound_db_password or "",
        "database": macro.macro_db_name or sr.super_rebound_db_name or "vibe",
        "charset": "utf8mb4",
        "connect_timeout": 8,
        "cursorclass": DictCursor,
        "autocommit": True,
    }
    conn = pymysql.connect(**kwargs)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 拉取 akshare
# ---------------------------------------------------------------------------

def _fetch_akshare(symbol: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """调用 akshare futures_main_sina 拉取日线, 返回清洗后的 list[dict]."""
    import akshare as ak

    logger.info("akshare.futures_main_sina symbol=%s start=%s end=%s", symbol, start_date, end_date)
    df = ak.futures_main_sina(symbol=symbol, start_date=start_date, end_date=end_date)

    if df is None or len(df) == 0:
        raise RuntimeError(f"akshare 返回空数据 symbol={symbol} start={start_date} end={end_date}")

    # 中文列 → 英文字段
    col_map = {
        "日期": "trade_date",
        "开盘价": "open",
        "最高价": "high",
        "最低价": "low",
        "收盘价": "close",
        "成交量": "volume",
        "持仓量": "open_interest",
        "动态结算价": "settlement",
    }
    df = df.rename(columns={c: v for c, v in col_map.items() if c in df.columns})

    # 类型清洗
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        td = r["trade_date"]
        # akshare 返回的 trade_date 可能是 datetime.date 或字符串
        if isinstance(td, str):
            td = datetime.strptime(td, "%Y-%m-%d").date()
        elif isinstance(td, datetime):
            td = td.date()
        elif not isinstance(td, date):
            td = date.fromisoformat(str(td))

        def _f(v: Any) -> float | None:
            try:
                if v is None:
                    return None
                fv = float(v)
                if fv != fv:  # NaN
                    return None
                return fv
            except (TypeError, ValueError):
                return None

        def _i(v: Any) -> int | None:
            try:
                if v is None:
                    return None
                iv = int(v)
                return iv if iv != iv else None  # NaN check
            except (TypeError, ValueError):
                return None

        rows.append({
            "trade_date": td,
            "open": _f(r.get("open")),
            "high": _f(r.get("high")),
            "low": _f(r.get("low")),
            "close": _f(r.get("close")),
            "volume": _i(r.get("volume")),
            "open_interest": _i(r.get("open_interest")),
            "settlement": _f(r.get("settlement")),
        })

    # 按日期升序
    rows.sort(key=lambda x: x["trade_date"])
    return rows


# ---------------------------------------------------------------------------
# 盘中状态判断
# ---------------------------------------------------------------------------

def _is_interday() -> bool:
    """判断当前时间是否处于上期所黄金交易时段（日盘 9:00-15:00 / 夜盘 21:00-02:30）."""
    now = datetime.now()
    t = now.time()
    weekday = now.weekday()  # 0=Monday
    # 周末不交易
    if weekday >= 5:
        return False
    # 日盘
    if time(9, 0) <= t <= time(15, 0):
        return True
    # 夜盘
    if t >= time(21, 0) or t <= time(2, 30):
        return True
    return False


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

def _upsert_rows(
    conn: pymysql.connections.Connection,
    rows: list[dict[str, Any]],
    symbol: str,
    fx_rate: float,
    is_interday: bool,
) -> tuple[int, int]:
    """将 rows upsert 到 gold_daily_bar. 返回 (inserted, updated)."""
    if not rows:
        return 0, 0

    upsert_sql = """
    INSERT INTO gold_daily_bar (
        trade_date, symbol, exchange, open, high, low, close,
        prev_close, volume, open_interest, settlement,
        change_amt, change_pct, fx_rate_cny_usd, price_usd_per_oz,
        is_interday, source
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s
    )
    ON DUPLICATE KEY UPDATE
        open = VALUES(open),
        high = VALUES(high),
        low = VALUES(low),
        close = VALUES(close),
        prev_close = VALUES(prev_close),
        volume = VALUES(volume),
        open_interest = VALUES(open_interest),
        settlement = VALUES(settlement),
        change_amt = VALUES(change_amt),
        change_pct = VALUES(change_pct),
        fx_rate_cny_usd = VALUES(fx_rate_cny_usd),
        price_usd_per_oz = VALUES(price_usd_per_oz),
        is_interday = VALUES(is_interday),
        source = VALUES(source),
        updated_at = CURRENT_TIMESTAMP
    """

    cur = conn.cursor()
    inserted = 0
    updated = 0

    for i, row in enumerate(rows):
        td = row["trade_date"]

        # 计算 prev_close: 优先取结果集中前一行, 否则查库
        prev_close: float | None = None
        if i > 0 and rows[i - 1]["trade_date"] < td:
            prev_close = rows[i - 1]["close"]
        if prev_close is None:
            cur.execute(
                "SELECT close FROM gold_daily_bar WHERE symbol = %s AND trade_date < %s ORDER BY trade_date DESC LIMIT 1",
                [symbol, td],
            )
            r = cur.fetchone()
            if r:
                prev_close = float(r["close"])

        close = row["close"]
        change_amt = round(close - prev_close, 2) if (close is not None and prev_close is not None) else None
        change_pct = round(change_amt / prev_close * 100, 2) if (change_amt is not None and prev_close and prev_close != 0) else None
        price_usd_per_oz = round(close * _OZ_PER_GRAM / fx_rate, 2) if (close is not None and fx_rate) else None

        values = [
            td, symbol, _DEFAULT_EXCHANGE,
            row["open"], row["high"], row["low"], close,
            prev_close,
            row["volume"], row["open_interest"], row["settlement"],
            change_amt, change_pct, fx_rate, price_usd_per_oz,
            1 if is_interday else 0,
            _DEFAULT_SOURCE,
        ]
        cur.execute(upsert_sql, values)
        if cur.rowcount == 1:
            inserted += 1
        elif cur.rowcount == 2:
            updated += 1
        # cur.rowcount == 0 时 MySQL ON DUPLICATE 表示值未变, 不计入

    cur.close()
    return inserted, updated


# ---------------------------------------------------------------------------
# 刷新频率限流
# ---------------------------------------------------------------------------

def _check_daily_rate_limit(conn: pymysql.connections.Connection, symbol: str) -> None:
    """同一自然日内同一 symbol 刷新次数超过阈值时 raise RuntimeError."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS cnt FROM gold_daily_refresh_log
        WHERE refresh_type IN ('manual', 'scheduled', 'init')
          AND fetch_symbol = %s
          AND DATE(fetched_at) = CURDATE()
        """,
        [symbol],
    )
    cnt = cur.fetchone()["cnt"]
    cur.close()
    if cnt >= _MAX_REFRESH_PER_DAY:
        raise RuntimeError(
            f"刷新过于频繁: 今日已对 {symbol} 刷新 {cnt} 次, 上限 {_MAX_REFRESH_PER_DAY}"
        )


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------

def _write_refresh_log(
    conn: pymysql.connections.Connection,
    refresh_type: str,
    symbol: str,
    rows_fetched: int,
    rows_inserted: int,
    rows_updated: int,
    latest_trade_date: date | None,
    is_interday: bool,
    status: str,
    error_msg: str | None = None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO gold_daily_refresh_log (
            refresh_type, fetch_symbol, rows_fetched, rows_inserted, rows_updated,
            latest_trade_date, is_interday, source, status, error_msg
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [
            refresh_type, symbol, rows_fetched, rows_inserted, rows_updated,
            latest_trade_date, 1 if is_interday else 0,
            _DEFAULT_SOURCE, status, error_msg,
        ],
    )
    cur.close()


# ---------------------------------------------------------------------------
# 公开入口
# ---------------------------------------------------------------------------

def refresh_gold_daily(
    refresh_type: str = "manual",
    symbol: str = _DEFAULT_SYMBOL,
    start_date: str | None = None,
    fx_rate: float = _DEFAULT_FX_CNY_USD,
    force: bool = False,
) -> dict[str, Any]:
    """拉取黄金日线并 upsert 到 vibe MySQL.

    :param refresh_type: 'manual' / 'scheduled' / 'init'
    :param symbol: 默认 AU0
    :param start_date: None → 增量拉取（从库里最新 trade_date 次日开始）,
                       否则 YYYYMMDD 格式（初始化时用）
    :param fx_rate: USD/CNY 汇率参考
    :param force: 跳过频率限制
    :return: dict 包含 rows_fetched / rows_inserted / rows_updated / latest_trade_date / is_interday
    """
    today_str = date.today().strftime("%Y%m%d")
    is_interday = _is_interday()

    with vibe_connection() as conn:
        if not force:
            _check_daily_rate_limit(conn, symbol)

        # 确定拉取起点（akshare 日期是闭区间 [start, end], 边界日容易空）
        latest_in_db: date | None = None
        if start_date is None:
            cur = conn.cursor()
            cur.execute(
                "SELECT MAX(trade_date) AS m FROM gold_daily_bar WHERE symbol = %s",
                [symbol],
            )
            row = cur.fetchone()
            cur.close()
            latest_in_db = row["m"] if row and row["m"] else None
            if latest_in_db is None:
                start_date = _DEFAULT_INIT_START
            else:
                # 回退 3 天重拉 — 因为 akshare 日线闭区间, 今日可能还没交易
                # 或库里最后一根是半成品，重拉确保覆盖
                fallback_3 = latest_in_db - _delta_days(3)
                start_date = fallback_3.strftime("%Y%m%d")
                # 如果回退后 start_date > today_str, 说明数据已经完全新鲜
                if start_date > today_str:
                    logger.info("gold_daily: 已是最新 (库里 latest=%s, start_date=%s)", latest_in_db, start_date)
                    _write_refresh_log(conn, refresh_type, symbol, 0, 0, 0, latest_in_db, is_interday, "ok")
                    return {
                        "rows_fetched": 0, "rows_inserted": 0, "rows_updated": 0,
                        "latest_trade_date": str(latest_in_db) if latest_in_db else None,
                        "is_interday": is_interday, "status": "ok_already_latest",
                    }

        rows_fetched = 0
        rows_inserted = 0
        rows_updated = 0
        latest_trade_date: date | None = None
        status = "ok"
        error_msg: str | None = None

        try:
            rows = _fetch_akshare(symbol, start_date, today_str)
            rows_fetched = len(rows)
            if rows_fetched == 0:
                # akshare 返回空 → 非交易日 / 今日数据尚未发布 → 视为已是最新
                logger.info("gold_daily: akshare 返回 0 行 (start=%s end=%s), 视为已是最新", start_date, today_str)
                _write_refresh_log(
                    conn, refresh_type, symbol,
                    0, 0, 0, latest_in_db,
                    is_interday, "ok_already_latest",
                )
                return {
                    "rows_fetched": 0, "rows_inserted": 0, "rows_updated": 0,
                    "latest_trade_date": str(latest_in_db) if latest_in_db else None,
                    "is_interday": is_interday, "status": "ok_already_latest",
                }
            latest_trade_date = rows[-1]["trade_date"]
            rows_inserted, rows_updated = _upsert_rows(conn, rows, symbol, fx_rate, is_interday)
        except Exception as exc:
            logger.exception("gold_daily refresh failed")
            status = "failed"
            error_msg = f"{type(exc).__name__}: {exc}"

        _write_refresh_log(
            conn, refresh_type, symbol,
            rows_fetched, rows_inserted, rows_updated,
            latest_trade_date, is_interday, status, error_msg,
        )

        result = {
            "rows_fetched": rows_fetched,
            "rows_inserted": rows_inserted,
            "rows_updated": rows_updated,
            "latest_trade_date": str(latest_trade_date) if latest_trade_date else None,
            "is_interday": is_interday,
            "status": status,
            "error_msg": error_msg,
        }
        logger.info("gold_daily refresh %s: %s", refresh_type, result)
        return result


def _delta_days(n: int) -> timedelta:
    from datetime import timedelta
    return timedelta(days=n)


# ---------------------------------------------------------------------------
# 查询接口
# ---------------------------------------------------------------------------

def get_daily_bars(
    symbol: str = _DEFAULT_SYMBOL,
    limit: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    latest_first: bool = False,
) -> list[dict[str, Any]]:
    """从 vibe MySQL 查询日线 bars.

    :param latest_first: True → 按 trade_date DESC 返回 (latest-first)；
                         False → 按 trade_date ASC 返回 (oldest-first).
    :param limit: 取 N 根；若 latest_first=True 则最新 N 根；否则最老 N 根.
    """
    sql = "SELECT * FROM gold_daily_bar WHERE symbol = %s"
    args: list[Any] = [symbol]
    if start_date:
        sql += " AND trade_date >= %s"
        args.append(start_date)
    if end_date:
        sql += " AND trade_date <= %s"
        args.append(end_date)
    sql += " ORDER BY trade_date DESC" if latest_first else " ORDER BY trade_date ASC"
    if limit:
        sql += f" LIMIT {int(limit)}"

    with vibe_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, args)
        rows = cur.fetchall()
        cur.close()

    # oldest-first 语义: 如果调用方要最新 limit 根，最后在内存里再倒一下
    if latest_first and not limit:
        # 全量倒回 oldest-first 更符合下游习惯
        rows = list(reversed(rows))
    elif latest_first and limit:
        # 只取最新 N 根 → 倒回 oldest-first
        rows = list(reversed(rows))

    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for k in ("trade_date", "latest_trade_date"):
            if k in d and isinstance(d[k], date):
                d[k] = d[k].isoformat()
        for k in ("fetched_at", "updated_at"):
            if k in d and isinstance(d[k], (datetime,)):
                d[k] = d[k].isoformat()
        out.append(d)
    return out


def get_latest_bar(symbol: str = _DEFAULT_SYMBOL) -> dict[str, Any] | None:
    """获取最新一根日线 (当日或最近一个交易日)."""
    with vibe_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM gold_daily_bar WHERE symbol = %s ORDER BY trade_date DESC LIMIT 1",
            [symbol],
        )
        row = cur.fetchone()
        cur.close()
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("trade_date"), date):
        d["trade_date"] = d["trade_date"].isoformat()
    if isinstance(d.get("fetched_at"), datetime):
        d["fetched_at"] = d["fetched_at"].isoformat()
    if isinstance(d.get("updated_at"), datetime):
        d["updated_at"] = d["updated_at"].isoformat()
    d["is_interday"] = bool(d.get("is_interday"))
    return d


def get_latest_price_summary(symbol: str = _DEFAULT_SYMBOL) -> dict[str, Any] | None:
    """返回前端最新价卡片所需的紧凑结构.

    优先用库里已计算好的 prev_close / change_amt / change_pct; 缺失时现场计算.
    """
    latest = get_latest_bar(symbol)
    if latest is None:
        return None

    prev_close = latest.get("prev_close")
    close = latest["close"]
    if prev_close is None:
        with vibe_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT close FROM gold_daily_bar WHERE symbol = %s AND trade_date < %s ORDER BY trade_date DESC LIMIT 1",
                [symbol, latest["trade_date"]],
            )
            r = cur.fetchone()
            cur.close()
            prev_close = float(r["close"]) if r else None
        if prev_close is not None:
            latest["prev_close"] = prev_close

    if prev_close is not None and latest.get("change_amt") is None:
        change_amt = round(float(close) - prev_close, 2)
        change_pct = round(change_amt / prev_close * 100, 2) if prev_close else None
        latest["change_amt"] = change_amt
        latest["change_pct"] = change_pct

    latest["is_interday"] = bool(latest.get("is_interday"))
    return latest


def count_bars(symbol: str = _DEFAULT_SYMBOL) -> int:
    with vibe_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM gold_daily_bar WHERE symbol = %s", [symbol])
        cnt = cur.fetchone()["c"]
        cur.close()
    return int(cnt)


def has_data(symbol: str = _DEFAULT_SYMBOL) -> bool:
    return count_bars(symbol) > 0
