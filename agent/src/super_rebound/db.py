"""MySQL persistence for the super-rebound (超跌反弹) finance module.

Two tables live in the MySQL ``vibe`` schema:
    * ``rebound_margin_daily_trade`` — Eastmoney RPTA_WEB_MARGIN_DAILYTRADE
      daily margin-trading rows. Columns keep the ORIGINAL Eastmoney field
      names so the upstream JSON payload can be upserted 1:1. The maintenance
      margin ratio (维持担保比例) is ``AVG_GUARANTEE_RATIO``.
    * ``rebound_etf_monitor``        — national-team ETF daily proxy net-buy
      rows (17 broad-based ETFs × N trade days).

Connection / credentials follow the same pattern as ``src.celebrity.db``:
typed config (``SUPER_REBOUND_DB_*``) with fallback to ``MACRO_DB_*``.
Connections are short-lived context managers.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date
from typing import Any, Iterator

import pymysql

from src.config.accessor import get_env_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def _connection_kwargs() -> dict[str, Any]:
    cfg = get_env_config()
    sr = cfg.super_rebound
    macro = cfg.macro
    # Default to the same local MySQL instance as the macro module so users
    # don't have to duplicate MACRO_DB_* into SUPER_REBOUND_DB_* unless they
    # want a separate store.
    return {
        "host": sr.super_rebound_db_host or macro.macro_db_host,
        "port": sr.super_rebound_db_port or macro.macro_db_port,
        "user": sr.super_rebound_db_user or macro.macro_db_user,
        "password": sr.super_rebound_db_password or macro.macro_db_password,
        "database": sr.super_rebound_db_name or macro.macro_db_name,
        "charset": "utf8mb4",
        "connect_timeout": 5,
        "autocommit": False,
        "cursorclass": pymysql.cursors.DictCursor,
    }


@contextmanager
def rebound_connection() -> Iterator[pymysql.connections.Connection]:
    """Yield a short-lived MySQL connection for the super-rebound schema."""
    conn = pymysql.connect(**_connection_kwargs())
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # best-effort close
            logger.debug("super-rebound MySQL connection close failed", exc_info=True)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# Column names mirror the Eastmoney RPTA_WEB_MARGIN_DAILYTRADE JSON payload
# exactly (including SUBSITUTION__CAP's double underscore).
_DDL = """
CREATE TABLE IF NOT EXISTS rebound_margin_daily_trade (
    STATISTICS_DATE           DATE NOT NULL PRIMARY KEY,
    DATE_MARK                 VARCHAR(8) DEFAULT NULL,
    FIN_BALANCE               DOUBLE DEFAULT NULL,
    LOAN_BALANCE              DOUBLE DEFAULT NULL,
    MARGIN_BALANCE            DOUBLE DEFAULT NULL,
    BALANCE_RATIO             DOUBLE DEFAULT NULL,
    FIN_BUY_AMT               DOUBLE DEFAULT NULL,
    LOAN_SELL_AMT             DOUBLE DEFAULT NULL,
    MARGIN_TRADE_AMT          DOUBLE DEFAULT NULL,
    TRADE_AMT_RATIO           DOUBLE DEFAULT NULL,
    SECURITY_ORG_NUM          INT DEFAULT NULL,
    OPERATEDEPT_NUM           INT DEFAULT NULL,
    PERSONAL_INVESTOR_NUM     DOUBLE DEFAULT NULL,
    ORG_INVESTOR_NUM          INT DEFAULT NULL,
    INVESTOR_NUM              INT DEFAULT NULL,
    MARGINLIAB_INVESTOR_NUM   INT DEFAULT NULL,
    FUND_MARKET_CAP           DOUBLE DEFAULT NULL,
    TOTAL_GUARANTEE           DOUBLE DEFAULT NULL,
    AVG_GUARANTEE_RATIO       DOUBLE DEFAULT NULL,
    SCI_CLOSE_PRICE           DOUBLE DEFAULT NULL,
    SCI_CHANGE_RATE           DOUBLE DEFAULT NULL,
    SUBSITUTION__CAP          DOUBLE DEFAULT NULL,
    source                    VARCHAR(32) NOT NULL DEFAULT 'eastmoney',
    created_at                DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_avg_guarantee (AVG_GUARANTEE_RATIO)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='两融每日交易统计（东方财富 RPTA_WEB_MARGIN_DAILYTRADE）';

CREATE TABLE IF NOT EXISTS rebound_etf_monitor (
    trade_date     DATE NOT NULL,
    etf_code       VARCHAR(64) NOT NULL,
    index_group    VARCHAR(16) NOT NULL,
    turnover_bn    DOUBLE NOT NULL DEFAULT 0,
    baseline_bn    DOUBLE DEFAULT NULL,
    source         VARCHAR(32) NOT NULL DEFAULT 'scraper',
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, etf_code),
    KEY idx_etf_group (index_group),
    KEY idx_etf_date (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='国家队ETF买入监测（成交额放大法，已废弃）';

CREATE TABLE IF NOT EXISTS etf_daily_flow (
    date          DATE NOT NULL COMMENT '交易日',
    index_tag     VARCHAR(16) NOT NULL COMMENT '指数分组标签 a500/sz50/hs300/zz500/zz1000/cyb/kc50',
    fund_code     VARCHAR(16) NOT NULL COMMENT 'ETF 代码',
    fund_name     VARCHAR(64) DEFAULT NULL COMMENT 'ETF 名称',
    exchange      VARCHAR(8)  DEFAULT NULL COMMENT 'SSE/SZSE',
    share_t       DOUBLE DEFAULT NULL COMMENT '当日总份额（万份）',
    share_t_1     DOUBLE DEFAULT NULL COMMENT '前一交易日总份额（万份），从本库历史读取',
    nav           DOUBLE DEFAULT NULL COMMENT '当日单位净值',
    market_cap_bn DOUBLE DEFAULT NULL COMMENT '当日总市值（亿元），SSE fund_detail 原始字段',
    net_flow      DOUBLE DEFAULT NULL COMMENT '净流入（亿元）=(share_t-share_t_1)*nav/10000',
    remark        VARCHAR(256) DEFAULT NULL COMMENT '清洗/异常标记（份额跳变、数据缺失等）',
    source        VARCHAR(32) NOT NULL DEFAULT 'sse_official' COMMENT 'sse_official / szse_official / fallback',
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (date, fund_code),
    KEY idx_etf_flow_tag (index_tag),
    KEY idx_etf_flow_date (date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='国家队ETF每日份额与净流入（份额口径，交易所官方数据源）';

CREATE TABLE IF NOT EXISTS etf_daily_net_flow (
    date            DATE NOT NULL COMMENT '交易日',
    a500_net_flow   DOUBLE DEFAULT NULL COMMENT '中证A500 净流入（亿元）',
    sz50_net_flow   DOUBLE DEFAULT NULL COMMENT '上证50 净流入（亿元）',
    hs300_net_flow  DOUBLE DEFAULT NULL COMMENT '沪深300 净流入（亿元）',
    zz500_net_flow  DOUBLE DEFAULT NULL COMMENT '中证500 净流入（亿元）',
    zz1000_net_flow DOUBLE DEFAULT NULL COMMENT '中证1000 净流入（亿元）',
    cyb_net_flow    DOUBLE DEFAULT NULL COMMENT '创业板 净流入（亿元）',
    kc50_net_flow   DOUBLE DEFAULT NULL COMMENT '科创50 净流入（亿元）',
    total_net_flow  DOUBLE DEFAULT NULL COMMENT '全部 ETF 净流入合计（亿元）',
    source          VARCHAR(32) NOT NULL DEFAULT 'derived' COMMENT 'derived',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (date),
    KEY idx_nf_date (date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='国家队ETF每日净流入宽表（每行一交易日，各指数组为列，前端表格/柱状图直接读取）';
"""


def initialize_schema(conn: pymysql.connections.Connection) -> None:
    """Create tables if they don't exist."""
    with conn.cursor() as cur:
        # pymysql executes one statement per cursor.execute; split on ';'
        for stmt in (s.strip() for s in _DDL.split(";")):
            if stmt:
                cur.execute(stmt)
    conn.commit()


# ---------------------------------------------------------------------------
# ETF code → index group mapping (17 broad-based ETFs)
# ---------------------------------------------------------------------------

ETF_GROUP_MAP = {
    # 中证A500 (4)
    "中证A500ETF国泰": "中证A500",
    "A500ETF华泰柏瑞": "中证A500",
    "A500ETF南方": "中证A500",
    "A500ETF易方达": "中证A500",
    # 上证50 (2)
    "上证50ETF华夏": "上证50",
    "上证50ETF易方达": "上证50",
    # 沪深300 (4)
    "沪深300ETF华泰柏瑞": "沪深300",
    "沪深300ETF易方达": "沪深300",
    "沪深300ETF嘉实": "沪深300",
    "沪深300ETF华夏": "沪深300",
    # 中证500 (2)
    "中证500ETF南方": "中证500",
    "中证500ETF华夏": "中证500",
    # 中证1000 (3)
    "中证1000ETF南方": "中证1000",
    "中证1000ETF华夏": "中证1000",
    "中证1000ETF广发": "中证1000",
    # 创业板 (1)
    "创业板ETF易方达": "创业板",
    # 科创50 (1)
    "科创50ETF华夏": "科创50",
}

INDEX_GROUPS = ["中证A500", "上证50", "沪深300", "中证500", "中证1000", "创业板", "科创50"]
INDEX_TAGS = ["a500", "sz50", "hs300", "zz500", "zz1000", "cyb", "kc50"]


# ---------------------------------------------------------------------------
# Margin daily trade CRUD
# ---------------------------------------------------------------------------

# Every upstream field except the date key.
_MARGIN_COLUMNS = [
    "DATE_MARK", "FIN_BALANCE", "LOAN_BALANCE", "MARGIN_BALANCE", "BALANCE_RATIO",
    "FIN_BUY_AMT", "LOAN_SELL_AMT", "MARGIN_TRADE_AMT", "TRADE_AMT_RATIO",
    "SECURITY_ORG_NUM", "OPERATEDEPT_NUM", "PERSONAL_INVESTOR_NUM",
    "ORG_INVESTOR_NUM", "INVESTOR_NUM", "MARGINLIAB_INVESTOR_NUM",
    "FUND_MARKET_CAP", "TOTAL_GUARANTEE", "AVG_GUARANTEE_RATIO",
    "SCI_CLOSE_PRICE", "SCI_CHANGE_RATE", "SUBSITUTION__CAP",
]


def _coerce_date(v: Any) -> date | None:
    """Eastmoney returns STATISTICS_DATE as 'YYYY-MM-DD HH:MM:SS' str."""
    if v is None:
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def upsert_margin_row(
    conn: pymysql.connections.Connection,
    row: dict[str, Any],
    source: str = "eastmoney",
) -> bool:
    """Upsert one Eastmoney payload row keyed by STATISTICS_DATE.

    Returns True if a new row was inserted, False if updated.
    """
    trade_date = _coerce_date(row.get("STATISTICS_DATE"))
    if trade_date is None:
        raise ValueError(f"invalid STATISTICS_DATE: {row.get('STATISTICS_DATE')!r}")

    values = [row.get(col) for col in _MARGIN_COLUMNS]
    placeholders = ", ".join(["%s"] * (len(_MARGIN_COLUMNS) + 2))
    col_sql = ", ".join(["STATISTICS_DATE"] + _MARGIN_COLUMNS + ["source"])
    update_sql = ", ".join(f"{c} = VALUES({c})" for c in _MARGIN_COLUMNS)

    sql = (
        f"INSERT INTO rebound_margin_daily_trade ({col_sql}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_sql}"
    )
    with conn.cursor() as cur:
        existed = cur.execute(
            "SELECT 1 FROM rebound_margin_daily_trade WHERE STATISTICS_DATE = %s",
            (trade_date,),
        )
        cur.execute(sql, [trade_date] + values + [source])
    conn.commit()
    return existed == 0


def upsert_margin_ratio_only(
    conn: pymysql.connections.Connection,
    trade_date: date,
    avg_guarantee_ratio: float,
    source: str = "attachment",
) -> bool:
    """Seed path: only the ratio is known (attachment data), other cols NULL.

    Existing rows are not overwritten; the attachment is the cold-start seed
    and Eastmoney backfill/full rows take precedence via ``upsert_margin_row``.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT IGNORE INTO rebound_margin_daily_trade "
            "(STATISTICS_DATE, AVG_GUARANTEE_RATIO, source) VALUES (%s, %s, %s)",
            (trade_date, avg_guarantee_ratio, source),
        )
        inserted = cur.rowcount > 0
    conn.commit()
    return inserted


def get_latest_margin_row(conn: pymysql.connections.Connection) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM rebound_margin_daily_trade "
            "WHERE AVG_GUARANTEE_RATIO IS NOT NULL "
            "ORDER BY STATISTICS_DATE DESC LIMIT 1"
        )
        return cur.fetchone()


def get_max_margin_date(conn: pymysql.connections.Connection) -> date | None:
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(STATISTICS_DATE) AS d FROM rebound_margin_daily_trade")
        row = cur.fetchone()
    return row["d"] if row and row["d"] is not None else None


def get_margin_rows(
    conn: pymysql.connections.Connection, start: date, end: date
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT STATISTICS_DATE, AVG_GUARANTEE_RATIO FROM rebound_margin_daily_trade "
            "WHERE STATISTICS_DATE BETWEEN %s AND %s "
            "AND AVG_GUARANTEE_RATIO IS NOT NULL "
            "ORDER BY STATISTICS_DATE ASC",
            (start, end),
        )
        return list(cur.fetchall())


def get_margin_stats(
    conn: pymysql.connections.Connection, start: date, end: date
) -> dict[str, Any]:
    """Aggregate stats for the finance panel within [start, end]."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS cnt,
                   MAX(AVG_GUARANTEE_RATIO) AS max_ratio,
                   MIN(AVG_GUARANTEE_RATIO) AS min_ratio
            FROM rebound_margin_daily_trade
            WHERE STATISTICS_DATE BETWEEN %s AND %s
              AND AVG_GUARANTEE_RATIO IS NOT NULL
            """,
            (start, end),
        )
        agg = cur.fetchone() or {}
        cur.execute(
            """
            SELECT STATISTICS_DATE AS d, AVG_GUARANTEE_RATIO AS r
            FROM rebound_margin_daily_trade
            WHERE STATISTICS_DATE BETWEEN %s AND %s AND AVG_GUARANTEE_RATIO IS NOT NULL
            ORDER BY AVG_GUARANTEE_RATIO DESC LIMIT 1
            """,
            (start, end),
        )
        max_row = cur.fetchone() or {}
        cur.execute(
            """
            SELECT STATISTICS_DATE AS d, AVG_GUARANTEE_RATIO AS r
            FROM rebound_margin_daily_trade
            WHERE STATISTICS_DATE BETWEEN %s AND %s AND AVG_GUARANTEE_RATIO IS NOT NULL
            ORDER BY AVG_GUARANTEE_RATIO ASC LIMIT 1
            """,
            (start, end),
        )
        min_row = cur.fetchone() or {}
    agg["max_date"] = max_row.get("d")
    agg["min_date"] = min_row.get("d")
    return agg


def count_margin_ratio_below(
    conn: pymysql.connections.Connection, value: float, start: date, end: date
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM rebound_margin_daily_trade
            WHERE STATISTICS_DATE BETWEEN %s AND %s
              AND AVG_GUARANTEE_RATIO IS NOT NULL AND AVG_GUARANTEE_RATIO <= %s
            """,
            (start, end, value),
        )
        row = cur.fetchone() or {"c": 0}
    return int(row["c"])


# ---------------------------------------------------------------------------
# ETF monitor CRUD
# ---------------------------------------------------------------------------

def upsert_etf_row(
    conn: pymysql.connections.Connection,
    trade_date: date,
    etf_code: str,
    index_group: str,
    turnover_bn: float,
    baseline_bn: float | None = None,
    source: str = "scraper",
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM rebound_etf_monitor WHERE trade_date = %s AND etf_code = %s",
            (trade_date, etf_code),
        )
        existed = cur.fetchone() is not None
        if existed:
            cur.execute(
                """
                UPDATE rebound_etf_monitor
                SET index_group = %s, turnover_bn = %s, baseline_bn = %s, source = %s
                WHERE trade_date = %s AND etf_code = %s
                """,
                (index_group, turnover_bn, baseline_bn, source, trade_date, etf_code),
            )
        else:
            cur.execute(
                """
                INSERT INTO rebound_etf_monitor
                    (trade_date, etf_code, index_group, turnover_bn, baseline_bn, source)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (trade_date, etf_code, index_group, turnover_bn, baseline_bn, source),
            )
    conn.commit()
    return not existed


def get_etf_monitor_detail(
    conn: pymysql.connections.Connection, start: date, end: date
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT trade_date, etf_code, index_group, turnover_bn
            FROM rebound_etf_monitor
            WHERE trade_date BETWEEN %s AND %s
            ORDER BY trade_date ASC, index_group ASC, etf_code ASC
            """,
            (start, end),
        )
        return list(cur.fetchall())


# ---------------------------------------------------------------------------
# ETF daily flow: target list + CRUD
# ---------------------------------------------------------------------------
# 17 只国家队宽基 ETF。
# 注：用户清单中 "563460 易方达A500ETF" 代码不存在，实际为 159361（深交所）。

ETF_TARGETS: list[dict[str, str]] = [
    # 中证A500 (4)
    {"fund_code": "560560", "fund_name": "国泰中证A500ETF",  "index_tag": "a500",  "exchange": "SSE"},
    {"fund_code": "563360", "fund_name": "华泰柏瑞中证A500ETF", "index_tag": "a500",  "exchange": "SSE"},
    {"fund_code": "563550", "fund_name": "南方中证A500ETF",  "index_tag": "a500",  "exchange": "SSE"},
    {"fund_code": "159361", "fund_name": "易方达中证A500ETF", "index_tag": "a500",  "exchange": "SZSE"},
    # 上证50 (2)
    {"fund_code": "510050", "fund_name": "华夏上证50ETF",    "index_tag": "sz50",  "exchange": "SSE"},
    {"fund_code": "510800", "fund_name": "易方达上证50ETF",  "index_tag": "sz50",  "exchange": "SSE"},
    # 沪深300 (4)
    {"fund_code": "510300", "fund_name": "华泰柏瑞沪深300ETF", "index_tag": "hs300", "exchange": "SSE"},
    {"fund_code": "510310", "fund_name": "易方达沪深300ETF", "index_tag": "hs300", "exchange": "SSE"},
    {"fund_code": "159919", "fund_name": "嘉实沪深300ETF",   "index_tag": "hs300", "exchange": "SZSE"},
    {"fund_code": "510330", "fund_name": "华夏沪深300ETF",   "index_tag": "hs300", "exchange": "SSE"},
    # 中证500 (2)
    {"fund_code": "510500", "fund_name": "南方中证500ETF",   "index_tag": "zz500", "exchange": "SSE"},
    {"fund_code": "510580", "fund_name": "华夏中证500ETF",   "index_tag": "zz500", "exchange": "SSE"},
    # 中证1000 (3)
    {"fund_code": "512100", "fund_name": "南方中证1000ETF",  "index_tag": "zz1000","exchange": "SSE"},
    {"fund_code": "159845", "fund_name": "华夏中证1000ETF",  "index_tag": "zz1000","exchange": "SZSE"},
    {"fund_code": "159846", "fund_name": "广发中证1000ETF",  "index_tag": "zz1000","exchange": "SZSE"},
    # 创业板 (1)
    {"fund_code": "159915", "fund_name": "易方达创业板ETF",  "index_tag": "cyb",   "exchange": "SZSE"},
    # 科创50 (1)
    {"fund_code": "588000", "fund_name": "华夏科创50ETF",    "index_tag": "kc50",  "exchange": "SSE"},
]

# 人类可读标签（前端展示用）
INDEX_TAG_LABEL = {
    "a500":  "中证A500",
    "sz50":  "上证50",
    "hs300": "沪深300",
    "zz500": "中证500",
    "zz1000":"中证1000",
    "cyb":   "创业板",
    "kc50":  "科创50",
}

SSE_TARGETS = [t for t in ETF_TARGETS if t["exchange"] == "SSE"]
SZSE_TARGETS = [t for t in ETF_TARGETS if t["exchange"] == "SZSE"]


def upsert_etf_flow_row(
    conn: pymysql.connections.Connection,
    trade_date: date,
    fund_code: str,
    fund_name: str | None = None,
    index_tag: str | None = None,
    exchange: str | None = None,
    share_t: float | None = None,
    share_t_1: float | None = None,
    nav: float | None = None,
    market_cap_bn: float | None = None,
    net_flow: float | None = None,
    remark: str | None = None,
    source: str = "sse_official",
) -> bool:
    """Upsert one row into ``etf_daily_flow``. Returns True if inserted."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM etf_daily_flow WHERE date = %s AND fund_code = %s",
            (trade_date, fund_code),
        )
        existed = cur.fetchone() is not None

        if existed:
            cur.execute(
                """
                UPDATE etf_daily_flow SET
                    fund_name = %s, index_tag = %s, exchange = %s,
                    share_t = %s, share_t_1 = %s, nav = %s,
                    market_cap_bn = %s, net_flow = %s, remark = %s, source = %s
                WHERE date = %s AND fund_code = %s
                """,
                (fund_name, index_tag, exchange,
                 share_t, share_t_1, nav, market_cap_bn, net_flow, remark, source,
                 trade_date, fund_code),
            )
        else:
            cur.execute(
                """
                INSERT INTO etf_daily_flow
                    (date, fund_code, fund_name, index_tag, exchange,
                     share_t, share_t_1, nav, market_cap_bn, net_flow, remark, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (trade_date, fund_code, fund_name, index_tag, exchange,
                 share_t, share_t_1, nav, market_cap_bn, net_flow, remark, source),
            )
    conn.commit()
    return not existed


def get_previous_etf_share(
    conn: pymysql.connections.Connection, trade_date: date, fund_code: str
) -> dict[str, Any] | None:
    """Return the row immediately before ``trade_date`` for this fund (or None)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, share_t, nav FROM etf_daily_flow
            WHERE fund_code = %s AND date < %s AND share_t IS NOT NULL
            ORDER BY date DESC LIMIT 1
            """,
            (fund_code, trade_date),
        )
        return cur.fetchone()


def get_etf_flow_detail(
    conn: pymysql.connections.Connection,
    start: date,
    end: date,
    index_tag: str | None = None,
) -> list[dict[str, Any]]:
    """Raw daily flow rows."""
    sql = (
        "SELECT date, index_tag, fund_code, fund_name, exchange, "
        "share_t, share_t_1, nav, market_cap_bn, net_flow, remark, source "
        "FROM etf_daily_flow WHERE date BETWEEN %s AND %s"
    )
    params: list[Any] = [start, end]
    if index_tag:
        sql += " AND index_tag = %s"
        params.append(index_tag)
    sql += " ORDER BY date ASC, index_tag ASC, fund_code ASC"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def get_etf_flow_summary(
    conn: pymysql.connections.Connection,
    start: date,
    end: date,
    index_tag: str | None = None,
) -> list[dict[str, Any]]:
    """Per (date, index_tag) aggregate net_flow in 亿元."""
    sql = (
        "SELECT date, index_tag, SUM(net_flow) AS total_net_flow_bn, COUNT(*) AS fund_count "
        "FROM etf_daily_flow WHERE date BETWEEN %s AND %s AND net_flow IS NOT NULL"
    )
    params: list[Any] = [start, end]
    if index_tag:
        sql += " AND index_tag = %s"
        params.append(index_tag)
    sql += " GROUP BY date, index_tag ORDER BY date ASC, index_tag ASC"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def get_max_etf_flow_date(
    conn: pymysql.connections.Connection, exchange: str | None = None
) -> date | None:
    sql = "SELECT MAX(date) AS d FROM etf_daily_flow"
    params: list[Any] = []
    if exchange:
        sql += " WHERE exchange = %s"
        params.append(exchange)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return row["d"] if row and row["d"] is not None else None


def update_etf_nav(
    conn: pymysql.connections.Connection,
    trade_date: date,
    fund_code: str,
    nav: float,
    source: str = "fundf10_eastmoney",
) -> bool:
    """UPDATE the nav column of an existing row (insert if missing).

    Only touches ``nav``, ``source``, ``updated_at`` on UPDATE — does NOT
    overwrite share_t or net_flow so the daily collector is not clobbered.
    On INSERT, auto-populates ``fund_name`` / ``index_tag`` / ``exchange``
    from the static ``ETF_TARGETS`` map so NOT NULL constraints are satisfied.
    """
    meta = next((t for t in ETF_TARGETS if t["fund_code"] == fund_code), None)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM etf_daily_flow WHERE date = %s AND fund_code = %s",
            (trade_date, fund_code),
        )
        existed = cur.fetchone() is not None
        if existed:
            cur.execute(
                "UPDATE etf_daily_flow SET nav = %s, source = %s WHERE date = %s AND fund_code = %s",
                (nav, source, trade_date, fund_code),
            )
        else:
            cur.execute(
                """INSERT INTO etf_daily_flow
                       (date, fund_code, fund_name, index_tag, exchange, nav, source)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    trade_date,
                    fund_code,
                    meta["fund_name"] if meta else None,
                    meta["index_tag"] if meta else None,
                    meta["exchange"] if meta else None,
                    nav,
                    source,
                ),
            )
    conn.commit()
    return existed


def recompute_etf_net_flow(
    conn: pymysql.connections.Connection,
    start: date,
    end: date,
) -> int:
    """Backfill net_flow for rows that now have nav + share_t + share_t_1.

    net_flow(亿元) = (share_t − share_t_1) × nav / 10000
    share_t / share_t_1 are in 万份, nav is yuan/unit.
    Returns number of rows updated.
    """
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE etf_daily_flow
                  SET net_flow = ROUND((share_t - share_t_1) * nav / 10000, 4)
                WHERE date BETWEEN %s AND %s
                  AND nav IS NOT NULL
                  AND share_t IS NOT NULL
                  AND share_t_1 IS NOT NULL
                  AND net_flow IS NULL""",
            (start, end),
        )
        n = cur.rowcount
    conn.commit()
    return n


def get_top_etf_by_day_scale(
    conn: pymysql.connections.Connection,
    trade_date: date,
    limit: int = 1,
) -> list[dict[str, Any]]:
    """Top-N ETF by daily scale (share_t × nav / 10000, 亿元)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT fund_code, fund_name, index_tag, exchange,
                      ROUND(share_t * nav / 10000, 4) AS scale_bn
                 FROM etf_daily_flow
                WHERE date = %s
                  AND share_t IS NOT NULL AND nav IS NOT NULL
                ORDER BY scale_bn DESC
                LIMIT %s""",
            (trade_date, limit),
        )
        return list(cur.fetchall())


def get_top_etf_by_avg_scale(
    conn: pymysql.connections.Connection,
    start: date,
    end: date,
    limit: int = 1,
) -> list[dict[str, Any]]:
    """Top-N ETF by average scale over a date window.

    平均规模 = AVG(share_t × nav / 10000)，仅统计 share_t + nav 均非空的行。
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT fund_code, fund_name, index_tag, exchange,
                      AVG(share_t * nav / 10000) AS avg_scale_bn
                 FROM etf_daily_flow
                WHERE date BETWEEN %s AND %s
                  AND share_t IS NOT NULL AND nav IS NOT NULL
                GROUP BY fund_code, fund_name, index_tag, exchange
                ORDER BY avg_scale_bn DESC
                LIMIT %s""",
            (start, end, limit),
        )
        return list(cur.fetchall())


def get_etf_scale_detail(
    conn: pymysql.connections.Connection,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Per-(date, index_tag) aggregated scale in 亿元 from etf_daily_flow.

    规模 = Σ(share_t × nav / 10000)，share_t 单位万份、nav 单位元/份。
    Used by the 堆叠柱状图 — one stacked bar per date, one segment per index.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT date, index_tag,
                      ROUND(SUM(share_t * nav / 10000), 4) AS scale_bn,
                      COUNT(*) AS fund_count
                 FROM etf_daily_flow
                WHERE date BETWEEN %s AND %s
                  AND share_t IS NOT NULL AND nav IS NOT NULL
                GROUP BY date, index_tag
                ORDER BY date ASC, index_tag ASC""",
            (start, end),
        )
        return list(cur.fetchall())


# ---------------------------------------------------------------------------
# etf_daily_net_flow — 每日净流入表（从 etf_daily_flow 派生）
# ---------------------------------------------------------------------------

def refresh_etf_daily_net_flow(
    conn: pymysql.connections.Connection,
    start: date,
    end: date,
) -> dict[str, int]:
    """从 ``etf_daily_flow`` 派生 ``etf_daily_net_flow`` **宽表**。

    每行一个交易日，7 个指数组各为一列净流入（亿元）+ 合计列。
    用 SQL 条件聚合（CASE WHEN）把 long 表 etf_daily_flow 透视为宽表。
    某指数组当日无数据时该列为 NULL（而非 0），便于前端识别缺失。

    返回 dict: {rows: 写入天数}。
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM etf_daily_net_flow WHERE date BETWEEN %s AND %s",
            (start, end),
        )

        cur.execute(
            """INSERT INTO etf_daily_net_flow
                   (date, a500_net_flow, sz50_net_flow, hs300_net_flow,
                    zz500_net_flow, zz1000_net_flow, cyb_net_flow,
                    kc50_net_flow, total_net_flow, source)
               SELECT
                   date,
                   CASE WHEN SUM(CASE WHEN index_tag='a500'   THEN 1 ELSE 0 END) > 0
                        THEN ROUND(SUM(CASE WHEN index_tag='a500'   THEN net_flow ELSE 0 END), 4) ELSE NULL END AS a500_net_flow,
                   CASE WHEN SUM(CASE WHEN index_tag='sz50'   THEN 1 ELSE 0 END) > 0
                        THEN ROUND(SUM(CASE WHEN index_tag='sz50'   THEN net_flow ELSE 0 END), 4) ELSE NULL END AS sz50_net_flow,
                   CASE WHEN SUM(CASE WHEN index_tag='hs300'  THEN 1 ELSE 0 END) > 0
                        THEN ROUND(SUM(CASE WHEN index_tag='hs300'  THEN net_flow ELSE 0 END), 4) ELSE NULL END AS hs300_net_flow,
                   CASE WHEN SUM(CASE WHEN index_tag='zz500'  THEN 1 ELSE 0 END) > 0
                        THEN ROUND(SUM(CASE WHEN index_tag='zz500'  THEN net_flow ELSE 0 END), 4) ELSE NULL END AS zz500_net_flow,
                   CASE WHEN SUM(CASE WHEN index_tag='zz1000' THEN 1 ELSE 0 END) > 0
                        THEN ROUND(SUM(CASE WHEN index_tag='zz1000' THEN net_flow ELSE 0 END), 4) ELSE NULL END AS zz1000_net_flow,
                   CASE WHEN SUM(CASE WHEN index_tag='cyb'    THEN 1 ELSE 0 END) > 0
                        THEN ROUND(SUM(CASE WHEN index_tag='cyb'    THEN net_flow ELSE 0 END), 4) ELSE NULL END AS cyb_net_flow,
                   CASE WHEN SUM(CASE WHEN index_tag='kc50'   THEN 1 ELSE 0 END) > 0
                        THEN ROUND(SUM(CASE WHEN index_tag='kc50'   THEN net_flow ELSE 0 END), 4) ELSE NULL END AS kc50_net_flow,
                   ROUND(SUM(net_flow), 4) AS total_net_flow,
                   'derived'
                 FROM etf_daily_flow
                WHERE date BETWEEN %s AND %s
                  AND net_flow IS NOT NULL
                GROUP BY date
                ORDER BY date""",
            (start, end),
        )
        rows = cur.rowcount

    conn.commit()
    return {"rows": rows}


def get_etf_netflow_detail(
    conn: pymysql.connections.Connection,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """从 ``etf_daily_net_flow`` 宽表读取每日各指数组净流入（亿元）。

    返回 [{date, a500_net_flow, sz50_net_flow, ..., kc50_net_flow, total_net_flow}, ...]，
    前端表格和堆叠柱状图直接使用，无需二次聚合。
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT date,
                      a500_net_flow, sz50_net_flow, hs300_net_flow,
                      zz500_net_flow, zz1000_net_flow, cyb_net_flow,
                      kc50_net_flow, total_net_flow
                 FROM etf_daily_net_flow
                WHERE date BETWEEN %s AND %s
                ORDER BY date ASC""",
            (start, end),
        )
        return list(cur.fetchall())


def get_top_etf_by_day_netflow(
    conn: pymysql.connections.Connection,
    trade_date: date,
    limit: int = 1,
) -> list[dict[str, Any]]:
    """Top-N ETF by daily net inflow (净流入, 亿元) on a given date.

    注意：``etf_daily_net_flow`` 是按指数组聚合的宽表，逐 ETF 排行需回源
    ``etf_daily_flow`` 查询。
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT fund_code, fund_name, index_tag, exchange, net_flow
                 FROM etf_daily_flow
                WHERE date = %s
                  AND net_flow IS NOT NULL
                ORDER BY net_flow DESC
                LIMIT %s""",
            (trade_date, limit),
        )
        return list(cur.fetchall())


def get_top_etf_by_avg_netflow(
    conn: pymysql.connections.Connection,
    start: date,
    end: date,
    limit: int = 1,
) -> list[dict[str, Any]]:
    """Top-N ETF by average daily net inflow over a date window (亿元).

    从 ``etf_daily_flow`` 按 ETF 聚合平均净流入。
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT fund_code, fund_name, index_tag, exchange,
                      AVG(net_flow) AS avg_net_flow_bn
                 FROM etf_daily_flow
                WHERE date BETWEEN %s AND %s
                  AND net_flow IS NOT NULL
                GROUP BY fund_code, fund_name, index_tag, exchange
                ORDER BY avg_net_flow_bn DESC
                LIMIT %s""",
            (start, end, limit),
        )
        return list(cur.fetchall())
