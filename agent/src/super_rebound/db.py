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

CREATE TABLE IF NOT EXISTS rebound_indicator_def (
    id                BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
    dimension         VARCHAR(32) NOT NULL COMMENT '所属维度：赔率层/技术超卖/资金承接/情绪广度/外部流动性',
    indicator_name    VARCHAR(128) NOT NULL COMMENT '指标名称',
    judgment_criteria TEXT NOT NULL COMMENT '超跌判断标准（如 RSI < 30, ERP > 5）',
    weight            DOUBLE NOT NULL DEFAULT 1 COMMENT '该指标在维度内的权重',
    sort_order        INT NOT NULL DEFAULT 0 COMMENT '排序序号',
    is_active         TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用：1启用 0停用（软删除）',
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_dimension (dimension),
    KEY idx_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='超跌指标定义表（维度内动态增删指标）';

CREATE TABLE IF NOT EXISTS rebound_indicator_result (
    id              BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
    trade_date      DATE NOT NULL COMMENT '交易日',
    index_code      VARCHAR(16) NOT NULL COMMENT '宽基指数代码',
    indicator_id    BIGINT NOT NULL COMMENT '关联 rebound_indicator_def.id',
    indicator_value VARCHAR(64) DEFAULT NULL COMMENT '大模型返回的指标原始值',
    judgment_result TINYINT DEFAULT NULL COMMENT '本地代码判断结果：1=满足超跌标准，0=不满足，NULL=未判断',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_date_indicator (trade_date, index_code, indicator_id),
    KEY idx_date (trade_date),
    KEY idx_indicator (indicator_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='超跌指标原始值与判断结果表（大模型取值，本地代码按判断标准计算0/1）';

CREATE TABLE IF NOT EXISTS rebound_daily_status (
    id                  BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
    trade_date          DATE NOT NULL COMMENT '交易日',
    index_code          VARCHAR(16) NOT NULL COMMENT '宽基指数代码',
    odds_score          DOUBLE DEFAULT NULL COMMENT '赔率层维度得分',
    technical_score     DOUBLE DEFAULT NULL COMMENT '技术超卖维度得分',
    capital_score       DOUBLE DEFAULT NULL COMMENT '资金承接维度得分',
    sentiment_score     DOUBLE DEFAULT NULL COMMENT '情绪广度维度得分',
    external_score      DOUBLE DEFAULT NULL COMMENT '外部流动性/政策维度得分',
    total_score         DOUBLE DEFAULT NULL COMMENT '五维度加权综合得分',
    signal_light        VARCHAR(8) DEFAULT NULL COMMENT '信号灯：green/yellow/red',
    volume_price_chip   VARCHAR(32) DEFAULT NULL COMMENT '量价与筹码判断结果（真反弹/假反弹）',
    rebound_tracking    VARCHAR(32) DEFAULT NULL COMMENT '反弹存续跟踪结果（存续中/衰退信号）',
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_date_index (trade_date, index_code),
    KEY idx_trade_date (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='每日超跌状态表（各维度得分+综合得分+量价与筹码+反弹存续跟踪）';

CREATE TABLE IF NOT EXISTS rebound_prompt (
    id             BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
    prompt_type    VARCHAR(32) NOT NULL COMMENT '提示词类型：oversold_indicator/volume_price_chip/rebound_tracking',
    prompt_name    VARCHAR(128) NOT NULL COMMENT '提示词名称',
    prompt_content MEDIUMTEXT NOT NULL COMMENT '提示词内容',
    updated_by     VARCHAR(64) DEFAULT NULL COMMENT '最后修改人',
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_prompt_type (prompt_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='大模型提示词表（超跌指标/量价与筹码/反弹存续跟踪）';

CREATE TABLE IF NOT EXISTS rebound_schedule_config (
    id          BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
    task_name   VARCHAR(64) NOT NULL COMMENT '任务名称',
    is_enabled  TINYINT NOT NULL DEFAULT 1 COMMENT '是否开启：1开启 0关闭（全局）',
    run_time    VARCHAR(8) NOT NULL DEFAULT '23:00' COMMENT '执行时间 HH:MM',
    timezone    VARCHAR(32) NOT NULL DEFAULT 'Asia/Shanghai' COMMENT '时区',
    updated_by  VARCHAR(64) DEFAULT NULL COMMENT '最后修改人',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_task_name (task_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='定时任务配置表（全局开关）';
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


# ===================================================================
# 超跌指标定义 CRUD (rebound_indicator_def)
# ===================================================================

DIMENSION_WEIGHTS: dict[str, float] = {
    "赔率层": 30.0,
    "技术超卖": 20.0,
    "资金承接": 25.0,
    "情绪广度": 15.0,
    "外部流动性/政策": 10.0,
}

INITIAL_INDICATOR_DEFS: list[dict[str, Any]] = [
    # 赔率层
    {"dimension": "赔率层", "indicator_name": "ERP", "judgment_criteria": "> 5", "weight": 1.0, "sort_order": 1},
    {"dimension": "赔率层", "indicator_name": "估值分位", "judgment_criteria": "> 80%", "weight": 1.0, "sort_order": 2},
    {"dimension": "赔率层", "indicator_name": "阶段回撤", "judgment_criteria": "> 15%", "weight": 1.0, "sort_order": 3},
    # 技术超卖
    {"dimension": "技术超卖", "indicator_name": "RSI(14)", "judgment_criteria": "< 30", "weight": 1.0, "sort_order": 1},
    {"dimension": "技术超卖", "indicator_name": "负乖离", "judgment_criteria": "< 0 (明显负乖离)", "weight": 1.0, "sort_order": 2},
    {"dimension": "技术超卖", "indicator_name": "MACD 底背离", "judgment_criteria": "定性（底背离出现=1，否则=0）", "weight": 1.0, "sort_order": 3},
    # 资金承接
    {"dimension": "资金承接", "indicator_name": "两融维持担保比例", "judgment_criteria": "< 250%", "weight": 1.0, "sort_order": 1},
    {"dimension": "资金承接", "indicator_name": "ETF 持续流入", "judgment_criteria": "> 500", "weight": 1.0, "sort_order": 2},
    # 情绪广度
    {"dimension": "情绪广度", "indicator_name": "上涨家数占比", "judgment_criteria": "< 20%", "weight": 1.0, "sort_order": 1},
    {"dimension": "情绪广度", "indicator_name": "成交量 PCR", "judgment_criteria": "> 1", "weight": 1.0, "sort_order": 2},
    # 外部流动性/政策
    {"dimension": "外部流动性/政策", "indicator_name": "资金利率(SHIBOR/DR007)", "judgment_criteria": "定性（高位=1，否则=0）", "weight": 1.0, "sort_order": 1},
    {"dimension": "外部流动性/政策", "indicator_name": "外部风险事件", "judgment_criteria": "定性（发生=1，否则=0）", "weight": 1.0, "sort_order": 2},
]

INITIAL_PROMPTS: list[dict[str, Any]] = [
    {
        "prompt_type": "oversold_indicator",
        "prompt_name": "超跌指标取值提示词",
        "prompt_content": (
            "你是一个A股金融数据助手。请为指定宽基指数获取以下各指标的最新原始值。"
            "严格只返回 JSON 对象，key 为指标名称，value 为数值或 0/1，不要有任何解释文字。\n\n"
            "数值型指标（返回数值，含单位含义）：\n"
            "- ERP：股债性价比数值，通常 >0 表示权益相对债券有溢价（如 6.2）\n"
            "- 估值分位：历史估值百分位，范围 0-100（如 85 表示高于历史 85% 时间）\n"
            "- 阶段回撤：从阶段高点的最大回撤幅度，百分比数值（如 18 表示回撤 18%）\n"
            "- RSI(14)：14 日相对强弱指标，范围 0-100（如 28 表示超卖）\n"
            "- 负乖离：当前价相对均线的乖离率，负数表示低于均线（如 -2.1 表示 -2.1%）\n"
            "- 两融维持担保比例：百分比数值（如 235 表示 235%）\n"
            "- ETF 持续流入：国家队 ETF 净流入金额，单位亿元（如 620 表示 620 亿）\n"
            "- 上涨家数占比：上涨股票占全部 A 股比例，百分比数值（如 15 表示 15%）\n"
            "- 成交量 PCR：Put/Call 成交量比值（如 1.3 表示看跌期权成交量是看涨的 1.3 倍）\n\n"
            "定性指标（直接返回 1 表示条件成立，0 表示不成立）：\n"
            "- MACD 底背离：价格创新低但 MACD 未创新低，出现底背离返回 1，否则 0\n"
            "- 资金利率(SHIBOR/DR007)：市场资金利率处于高位（紧张）返回 1，否则 0\n"
            "- 外部风险事件：发生美股大跌、地缘冲突等重大外部风险事件返回 1，否则 0\n\n"
            "返回示例：{\"ERP\":6.2,\"估值分位\":85,\"阶段回撤\":18,\"RSI(14)\":28,"
            "\"负乖离\":-2.1,\"MACD 底背离\":1,\"两融维持担保比例\":235,"
            "\"ETF 持续流入\":620,\"上涨家数占比\":15,\"成交量 PCR\":1.3,"
            "\"资金利率(SHIBOR/DR007)\":1,\"外部风险事件\":0}"
        ),
    },
    {
        "prompt_type": "volume_price_chip",
        "prompt_name": "量价与筹码提示词（真假反弹过滤器）",
        "prompt_content": (
            "你是一个量价分析专家。请判断当前A股主要指数是否为真反弹。判断标准：\n"
            "1. 下跌末端缩量\n2. 企稳阳线放量\n3. 成交量 PCR 小于 0.6\n"
            "请返回 JSON：{\"result\": \"真反弹\" 或 \"假反弹\", \"reason\": \"简要说明\"}"
        ),
    },
    {
        "prompt_type": "rebound_tracking",
        "prompt_name": "反弹存续跟踪提示词（开仓之后）",
        "prompt_content": (
            "你是一个反弹存续分析专家。请监测反弹是否可持续。衰退信号包括：\n"
            "1. 指数创新高，但成交跟不上、量价背离\n"
            "2. 涨跌家数再次萎缩、新高数量下降\n"
            "3. ERP 快速回落、估值分位回到中性区间\n"
            "4. 北向 / ETF 资金由流入转为流出\n"
            "请返回 JSON：{\"result\": \"存续中\" 或 \"衰退信号\", \"reason\": \"简要说明\"}"
        ),
    },
]


def get_all_indicator_defs(conn: pymysql.connections.Connection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM rebound_indicator_def WHERE is_active = 1 ORDER BY dimension, sort_order"
        )
        return list(cur.fetchall())


def get_indicator_defs_by_dimension(
    conn: pymysql.connections.Connection, dimension: str
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM rebound_indicator_def WHERE dimension = %s AND is_active = 1 ORDER BY sort_order",
            (dimension,),
        )
        return list(cur.fetchall())


def upsert_indicator_def(
    conn: pymysql.connections.Connection, row: dict[str, Any]
) -> bool:
    """Upsert indicator def by id; insert if id not present."""
    with conn.cursor() as cur:
        if row.get("id"):
            cur.execute(
                "SELECT 1 FROM rebound_indicator_def WHERE id = %s",
                (row["id"],),
            )
            existed = cur.fetchone() is not None
            if existed:
                cur.execute(
                    """UPDATE rebound_indicator_def SET
                        dimension = %s, indicator_name = %s, judgment_criteria = %s,
                        weight = %s, sort_order = %s, is_active = %s
                       WHERE id = %s""",
                    (
                        row["dimension"], row["indicator_name"], row["judgment_criteria"],
                        row.get("weight", 1.0), row.get("sort_order", 0), row.get("is_active", 1),
                        row["id"],
                    ),
                )
                conn.commit()
                return False
        cur.execute(
            """INSERT INTO rebound_indicator_def
                   (dimension, indicator_name, judgment_criteria, weight, sort_order, is_active)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                row["dimension"], row["indicator_name"], row["judgment_criteria"],
                row.get("weight", 1.0), row.get("sort_order", 0), row.get("is_active", 1),
            ),
        )
    conn.commit()
    return True


def delete_indicator_def(conn: pymysql.connections.Connection, def_id: int) -> bool:
    """Soft delete: set is_active = 0."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE rebound_indicator_def SET is_active = 0 WHERE id = %s",
            (def_id,),
        )
    conn.commit()
    return cur.rowcount > 0


# ===================================================================
# 提示词 CRUD (rebound_prompt)
# ===================================================================

def get_all_prompts(conn: pymysql.connections.Connection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM rebound_prompt ORDER BY prompt_type")
        return list(cur.fetchall())


def get_prompt_by_type(conn: pymysql.connections.Connection, prompt_type: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM rebound_prompt WHERE prompt_type = %s", (prompt_type,)
        )
        return cur.fetchone()


def upsert_prompt(
    conn: pymysql.connections.Connection, row: dict[str, Any]
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM rebound_prompt WHERE prompt_type = %s",
            (row["prompt_type"],),
        )
        existed = cur.fetchone() is not None
        if existed:
            cur.execute(
                """UPDATE rebound_prompt SET
                    prompt_name = %s, prompt_content = %s, updated_by = %s
                   WHERE prompt_type = %s""",
                (row["prompt_name"], row["prompt_content"], row.get("updated_by"), row["prompt_type"]),
            )
        else:
            cur.execute(
                """INSERT INTO rebound_prompt (prompt_type, prompt_name, prompt_content, updated_by)
                   VALUES (%s, %s, %s, %s)""",
                (row["prompt_type"], row["prompt_name"], row["prompt_content"], row.get("updated_by")),
            )
    conn.commit()
    return not existed


# ===================================================================
# 指标结果 CRUD (rebound_indicator_result)
# ===================================================================

def upsert_indicator_result(
    conn: pymysql.connections.Connection, row: dict[str, Any]
) -> None:
    """Upsert by uk_date_indicator (trade_date, index_code, indicator_id)."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO rebound_indicator_result
                   (trade_date, index_code, indicator_id, indicator_value, judgment_result)
               VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   indicator_value = VALUES(indicator_value),
                   judgment_result = VALUES(judgment_result)""",
            (
                row["trade_date"], row["index_code"], row["indicator_id"],
                row.get("indicator_value"), row.get("judgment_result"),
            ),
        )
    conn.commit()


def batch_upsert_indicator_results(
    conn: pymysql.connections.Connection, rows: list[dict[str, Any]]
) -> int:
    """批量 upsert，返回写入行数。"""
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """INSERT INTO rebound_indicator_result
                       (trade_date, index_code, indicator_id, indicator_value, judgment_result)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                       indicator_value = VALUES(indicator_value),
                       judgment_result = VALUES(judgment_result)""",
                (
                    row["trade_date"], row["index_code"], row["indicator_id"],
                    row.get("indicator_value"), row.get("judgment_result"),
                ),
            )
    conn.commit()
    return len(rows)


def get_indicator_results_for_date(
    conn: pymysql.connections.Connection, trade_date: date, index_code: str
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT r.*, d.dimension, d.indicator_name, d.judgment_criteria, d.weight
                 FROM rebound_indicator_result r
                 JOIN rebound_indicator_def d ON r.indicator_id = d.id
                WHERE r.trade_date = %s AND r.index_code = %s
                ORDER BY d.dimension, d.sort_order""",
            (trade_date, index_code),
        )
        return list(cur.fetchall())


# ===================================================================
# 每日超跌状态 CRUD (rebound_daily_status)
# ===================================================================

def upsert_daily_status(
    conn: pymysql.connections.Connection, row: dict[str, Any]
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO rebound_daily_status
                   (trade_date, index_code, odds_score, technical_score, capital_score,
                    sentiment_score, external_score, total_score, signal_light,
                    volume_price_chip, rebound_tracking)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   odds_score = VALUES(odds_score),
                   technical_score = VALUES(technical_score),
                   capital_score = VALUES(capital_score),
                   sentiment_score = VALUES(sentiment_score),
                   external_score = VALUES(external_score),
                   total_score = VALUES(total_score),
                   signal_light = VALUES(signal_light),
                   volume_price_chip = VALUES(volume_price_chip),
                   rebound_tracking = VALUES(rebound_tracking)""",
            (
                row["trade_date"], row["index_code"],
                row.get("odds_score"), row.get("technical_score"), row.get("capital_score"),
                row.get("sentiment_score"), row.get("external_score"), row.get("total_score"),
                row.get("signal_light"), row.get("volume_price_chip"), row.get("rebound_tracking"),
            ),
        )
    conn.commit()
    return True


def update_daily_status_fields(
    conn: pymysql.connections.Connection,
    trade_date: date,
    index_code: str,
    volume_price_chip: str | None = None,
    rebound_tracking: str | None = None,
) -> None:
    """只更新量价筹码或反弹跟踪字段。"""
    if volume_price_chip is None and rebound_tracking is None:
        return
    sets: list[str] = []
    params: list[Any] = []
    if volume_price_chip is not None:
        sets.append("volume_price_chip = %s")
        params.append(volume_price_chip)
    if rebound_tracking is not None:
        sets.append("rebound_tracking = %s")
        params.append(rebound_tracking)
    params.extend([trade_date, index_code])
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE rebound_daily_status SET {', '.join(sets)} WHERE trade_date = %s AND index_code = %s",
            params,
        )
    conn.commit()


def get_daily_status_list(
    conn: pymysql.connections.Connection,
    start_date: date,
    end_date: date,
    index_code: str = "沪深300",
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT * FROM rebound_daily_status
                WHERE trade_date BETWEEN %s AND %s AND index_code = %s
                ORDER BY trade_date DESC""",
            (start_date, end_date, index_code),
        )
        return list(cur.fetchall())


def get_latest_daily_status(
    conn: pymysql.connections.Connection, index_code: str = "沪深300"
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT * FROM rebound_daily_status
                WHERE index_code = %s ORDER BY trade_date DESC LIMIT 1""",
            (index_code,),
        )
        return cur.fetchone()


# ===================================================================
# 定时配置 CRUD (rebound_schedule_config)
# ===================================================================

def get_schedule_config(
    conn: pymysql.connections.Connection, task_name: str
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM rebound_schedule_config WHERE task_name = %s",
            (task_name,),
        )
        return cur.fetchone()


def upsert_schedule_config(
    conn: pymysql.connections.Connection, row: dict[str, Any]
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO rebound_schedule_config
                   (task_name, is_enabled, run_time, timezone, updated_by)
               VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   is_enabled = VALUES(is_enabled),
                   run_time = VALUES(run_time),
                   timezone = VALUES(timezone),
                   updated_by = VALUES(updated_by)""",
            (
                row["task_name"], row["is_enabled"], row.get("run_time", "23:00"),
                row.get("timezone", "Asia/Shanghai"), row.get("updated_by"),
            ),
        )
    conn.commit()


def is_schedule_enabled(
    conn: pymysql.connections.Connection, task_name: str
) -> bool:
    cfg = get_schedule_config(conn, task_name)
    return bool(cfg and cfg.get("is_enabled"))


# ===================================================================
# 种子数据初始化
# ===================================================================

def seed_initial_data(conn: pymysql.connections.Connection) -> dict[str, int]:
    """Idempotent seed: initial indicator defs + prompts + schedule config.

    Returns counts of what was inserted (not total).
    """
    inserted = {"indicator_defs": 0, "prompts": 0, "schedule": 0}

    for defn in INITIAL_INDICATOR_DEFS:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM rebound_indicator_def WHERE indicator_name = %s AND dimension = %s",
                (defn["indicator_name"], defn["dimension"]),
            )
            if cur.fetchone() is None:
                cur.execute(
                    """INSERT INTO rebound_indicator_def
                           (dimension, indicator_name, judgment_criteria, weight, sort_order, is_active)
                       VALUES (%s, %s, %s, %s, %s, 1)""",
                    (defn["dimension"], defn["indicator_name"], defn["judgment_criteria"],
                     defn["weight"], defn["sort_order"]),
                )
                conn.commit()
                inserted["indicator_defs"] += 1

    for p in INITIAL_PROMPTS:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM rebound_prompt WHERE prompt_type = %s", (p["prompt_type"],)
            )
            if cur.fetchone() is None:
                cur.execute(
                    """INSERT INTO rebound_prompt (prompt_type, prompt_name, prompt_content)
                       VALUES (%s, %s, %s)""",
                    (p["prompt_type"], p["prompt_name"], p["prompt_content"]),
                )
                conn.commit()
                inserted["prompts"] += 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM rebound_schedule_config WHERE task_name = 'daily_status_auto'"
        )
        if cur.fetchone() is None:
            cur.execute(
                """INSERT INTO rebound_schedule_config
                       (task_name, is_enabled, run_time, timezone)
                   VALUES ('daily_status_auto', 1, '23:00', 'Asia/Shanghai')"""
            )
            conn.commit()
            inserted["schedule"] += 1

    return inserted


def ensure_schema_seeded() -> dict[str, Any]:
    """Convenience entry: connect → initialize_schema → seed_initial_data → close."""
    from src.super_rebound.db import rebound_connection, initialize_schema, seed_initial_data
    with rebound_connection() as conn:
        initialize_schema(conn)
        seeded = seed_initial_data(conn)
    return {"schema": "ok", "seeded": seeded}
