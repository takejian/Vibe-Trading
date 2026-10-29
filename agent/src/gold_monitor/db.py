"""DuckDB persistence for the gold policy-cycle monitor module.

Three tables live under the shared market warehouse (``get_market_db_path()``):
    * ``gold_monthly``       — one row per YYYY-MM, key metrics
    * ``gold_policy_cycle``  — policy cycle boundaries and status
    * ``gold_refresh_log``   — audit trail of each refresh attempt

All connections are short-lived; this mirrors ``src.watchlist.db`` and
``src.paper.db`` patterns so multiple routes can interleave safely.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from src.config.paths import get_market_db_path

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS gold_monthly (
    month           VARCHAR(7) PRIMARY KEY,
    gold_price      DOUBLE,
    ffr             DOUBLE,
    yield_nominal   DOUBLE,
    bei             DOUBLE,
    tips_real       DOUBLE,
    gold_change_pct DOUBLE,
    ffr_change      DOUBLE,
    real_change     DOUBLE,
    updated_at      TIMESTAMP NOT NULL DEFAULT current_timestamp,
    source          VARCHAR(32) NOT NULL DEFAULT 'excel'
);

CREATE TABLE IF NOT EXISTS gold_policy_cycle (
    cycle_id            INTEGER PRIMARY KEY,
    cycle_name          VARCHAR(128) NOT NULL,
    start_month         VARCHAR(7) NOT NULL,
    end_month           VARCHAR(7),
    cycle_type          VARCHAR(16) NOT NULL,
    source              VARCHAR(16) NOT NULL DEFAULT 'excel',
    status              VARCHAR(16) NOT NULL DEFAULT 'active',
    gold_start          DOUBLE,
    gold_end            DOUBLE,
    gold_change_pct     DOUBLE,
    post_hoc_confidence DOUBLE,
    created_at          TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at          TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS gold_refresh_log (
    log_id          UUID PRIMARY KEY DEFAULT uuid(),
    refreshed_month VARCHAR(7) NOT NULL,
    action          VARCHAR(16) NOT NULL,
    diff_summary    VARCHAR(512),
    success         BOOLEAN NOT NULL,
    error_msg       VARCHAR(512),
    source          VARCHAR(16) NOT NULL,
    refreshed_at    TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS gold_signal (
    signal_id      UUID PRIMARY KEY DEFAULT uuid(),
    indicator_key  VARCHAR(32) NOT NULL,
    judgment       VARCHAR(16) NOT NULL,
    confidence     DOUBLE,
    summary        VARCHAR(1024),
    details        TEXT,
    source         VARCHAR(16) NOT NULL DEFAULT 'manual',
    cycle_id       INTEGER,
    created_at     TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS gold_signal_prompt (
    indicator_key  VARCHAR(32) PRIMARY KEY,
    system_prompt  TEXT NOT NULL,
    user_prompt    TEXT NOT NULL,
    updated_at     TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS gold_fomc (
    meeting_id     UUID PRIMARY KEY DEFAULT uuid(),
    meeting_date   DATE NOT NULL,
    title          VARCHAR(128),
    notes          VARCHAR(256),
    source         VARCHAR(16) NOT NULL DEFAULT 'llm',
    updated_at     TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""


def gold_connection() -> duckdb.DuckDBPyConnection:
    """Open a short-lived DuckDB connection to the shared market warehouse."""
    db_path: Path = get_market_db_path()
    return duckdb.connect(str(db_path))


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create gold_* tables if they do not yet exist."""
    conn.execute(_DDL)
    # Migration: gold_refresh_log.log_id was originally INTEGER; it is now UUID.
    # Drop and recreate the log table (audit-only, no critical data).
    try:
        log_id_type = conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'gold_refresh_log' AND column_name = 'log_id'"
        ).fetchone()
        if log_id_type and log_id_type[0] != "UUID":
            conn.execute("DROP TABLE gold_refresh_log")
            conn.execute(_DDL)
    except Exception:
        pass
    # Migration: add cycle_id to gold_signal (links signals to policy cycles).
    try:
        has_cycle_id = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'gold_signal' AND column_name = 'cycle_id'"
        ).fetchone()
        if not has_cycle_id:
            conn.execute("ALTER TABLE gold_signal ADD COLUMN cycle_id INTEGER")
    except Exception:
        pass
    # Migration: add post_hoc_confidence to gold_policy_cycle.
    try:
        has_phc = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'gold_policy_cycle' AND column_name = 'post_hoc_confidence'"
        ).fetchone()
        if not has_phc:
            conn.execute("ALTER TABLE gold_policy_cycle ADD COLUMN post_hoc_confidence DOUBLE")
    except Exception:
        pass
    # Seed default prompts for the 5 indicators if not present
    _seed_default_prompts(conn)


_DEFAULT_PROMPTS: dict[str, dict[str, str]] = {
    "ffr_drivers": {
        "system_prompt": (
            "你是美联储政策路径分析专家。你需要基于截至当前最新可获得的美国增长与就业数据，"
            "判断这些数据对联邦基金利率(FFR)路径的影响，进而判断对金价的方向性影响。"
            "请使用你自身知识库中最新的宏观经济数据进行分析，不要编造数值；若某项数据未知，"
            "在 details 中说明并降低 confidence。"
            "输出严格JSON，字段：judgment(bullish/bearish/neutral)、confidence(0~1)、"
            "summary(一句话中文摘要)、details(中文详细分析，列出你依据的关键数据点)。"
            "判断逻辑：增长/就业数据走弱→降息预期升温→利空实际利率/美元→利多黄金；"
            "数据强劲→加息或高利率维持更久→利空黄金。"
            "关注指标：非农就业人数、失业率、平均时薪同比、ISM制造业PMI、ISM服务业PMI、GDP增速。"
        ),
        "user_prompt": (
            "请基于你掌握的最新美国增长与就业数据（非农、失业率、平均时薪、ISM制造业/服务业PMI、GDP），"
            "自行采集并综合判断当前数据组合对美联储FFR降息/加息路径的影响，以及对金价的利多/利空方向。"
            "在 details 中列出你引用的关键数据及其数值/方向。"
        ),
    },
    "bei_drivers": {
        "system_prompt": (
            "你是通胀预期分析专家。你需要基于截至当前最新可获得的美国通胀数据，"
            "判断10年期盈亏平衡通胀率(BEI)的走向，进而判断对金价的方向性影响。"
            "请使用你自身知识库中最新的通胀数据进行分析，不要编造数值；若某项数据未知，"
            "在 details 中说明并降低 confidence。"
            "输出严格JSON：judgment(bullish/bearish/neutral)、confidence(0~1)、summary、details。"
            "判断逻辑：通胀黏性/超预期→降息空间压缩、抗通胀属性凸显→利多黄金；"
            "通胀回落至2%锚附近→实际利率走升→利空黄金。注意美联储通胀锚为PCE，且PCE权重高于CPI。"
            "关注指标：核心PCE同比/环比、CPI同比/环比、PPI、达拉斯联储trimmed-mean PCE。"
        ),
        "user_prompt": (
            "请基于你掌握的最新美国通胀数据（核心PCE、CPI、PPI、达拉斯联储trimmed-mean PCE），"
            "自行采集并综合判断通胀预期(BEI)的走向及对金价的影响。"
            "在 details 中列出你引用的关键数据及其数值/方向。"
        ),
    },
    "usd_fx": {
        "system_prompt": (
            "你是美元与汇率分析专家。你需要基于截至当前最新可获得的美元指数与汇率数据，"
            "判断美元强弱对金价的影响。请使用你自身知识库中最新的汇率数据进行分析，"
            "不要编造数值；若某项数据未知，在 details 中说明并降低 confidence。"
            "输出严格JSON：judgment(bullish/bearish/neutral)、confidence(0~1)、summary、details。"
            "判断逻辑：美元走弱→以美元计价黄金相对便宜→利多；美元走强→利空。"
            "⚠️若DXY走势主要由欧元单边行情驱动，需降档扣分；优先参考Broad贸易加权美元指数。"
            "关注指标：广义贸易加权美元指数(Broad)、美元指数DXY、在岸/离岸人民币汇率(USD/CNY)。"
        ),
        "user_prompt": (
            "请基于你掌握的最新美元与汇率数据（Broad贸易加权美元指数、DXY、在岸/离岸人民币汇率），"
            "自行采集并综合判断美元强弱及对金价的影响，注意区分DXY是否被欧元单边行情主导。"
            "在 details 中列出你引用的关键数据及其数值/方向。"
        ),
    },
    "tail_risk": {
        "system_prompt": (
            "你是尾部风险溢价分析专家。你需要基于截至当前最新可获得的地缘政治、金融稳定、"
            "美债市场等风险事件信息，判断尾部风险溢价对金价的影响。"
            "请使用你自身知识库中最新的事件信息进行分析，不要编造事件；若某类风险无最新进展，"
            "在 details 中说明。"
            "输出严格JSON：judgment(bullish/bearish/neutral)、confidence(0~1)、summary、details。"
            "判断逻辑：风险发酵→避险需求+去美元化→利多黄金；风险缓和→利空。"
            "关注维度：地缘冲突、美国银行体系风险、美债市场流动性、美国债务上限/财政赤字担忧。"
        ),
        "user_prompt": (
            "请基于你掌握的最新信息，自行采集并综合评估当前尾部风险（地缘冲突、银行风险、"
            "美债流动性、美国债务/财政担忧）的发酵程度，判断风险溢价走向及对金价的影响。"
            "在 details 中列出你依据的关键事件。"
        ),
    },
    "physical_flow": {
        "system_prompt": (
            "你是黄金实物与资金流分析专家。你需要基于截至当前最新可获得的央行购金、ETF持仓、"
            "库存、价差等数据，判断实物供需对金价的影响。"
            "请使用你自身知识库中最新的数据进行分析，不要编造数值；若某项数据未知，"
            "在 details 中说明并降低 confidence。"
            "输出严格JSON：judgment(bullish/bearish/neutral)、confidence(0~1)、summary、details。"
            "判断逻辑：持续大额净买入/库存下降→利多；购金放缓/减持/库存上升→利空。"
            "关注指标：世界黄金协会(WGC)月度央行净购金量、各国央行储备报告、"
            "全球黄金ETF持仓变动、COMEX黄金库存、上期所(SHFE)黄金库存、沪金-伦敦金价差。"
        ),
        "user_prompt": (
            "请基于你掌握的最新黄金实物与资金流数据（WGC央行净购金、各国储备报告、"
            "全球黄金ETF持仓、COMEX/SHFE库存、沪金-伦敦金价差），"
            "自行采集并综合判断实物供需对金价的影响。"
            "在 details 中列出你引用的关键数据及其数值/方向。"
        ),
    },
}


def _seed_default_prompts(conn: duckdb.DuckDBPyConnection) -> None:
    """Seed default prompts. Existing prompts are only overwritten if they still
    contain the legacy '以下数据' pattern (which referenced data that was never
    actually passed in). User-edited prompts are preserved."""
    for key, prompts in _DEFAULT_PROMPTS.items():
        row = conn.execute(
            "SELECT user_prompt FROM gold_signal_prompt WHERE indicator_key = ?",
            [key],
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO gold_signal_prompt (indicator_key, system_prompt, user_prompt) VALUES (?, ?, ?)",
                [key, prompts["system_prompt"], prompts["user_prompt"]],
            )
        elif "以下" in row[0]:
            # Legacy buggy prompt — upgrade to the corrected default.
            conn.execute(
                "UPDATE gold_signal_prompt SET system_prompt = ?, user_prompt = ?, updated_at = current_timestamp WHERE indicator_key = ?",
                [prompts["system_prompt"], prompts["user_prompt"], key],
            )


# ---------------------------------------------------------------------------
# gold_monthly CRUD
# ---------------------------------------------------------------------------

def insert_or_update_monthly(
    conn: duckdb.DuckDBPyConnection,
    month: str,
    gold_price: float | None,
    ffr: float | None,
    yield_nominal: float | None,
    bei: float | None,
    tips_real: float | None,
    gold_change_pct: float | None = None,
    ffr_change: float | None = None,
    real_change: float | None = None,
    source: str = "llm",
) -> bool:
    """Upsert one row into gold_monthly. Returns True if a new row was inserted."""
    existing = conn.execute(
        "SELECT month FROM gold_monthly WHERE month = ?", [month]
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE gold_monthly SET
                gold_price = ?, ffr = ?, yield_nominal = ?, bei = ?,
                tips_real = ?, gold_change_pct = ?, ffr_change = ?,
                real_change = ?, source = ?, updated_at = current_timestamp
            WHERE month = ?
            """,
            [gold_price, ffr, yield_nominal, bei, tips_real,
             gold_change_pct, ffr_change, real_change, source, month],
        )
        return False
    conn.execute(
        """
        INSERT INTO gold_monthly
            (month, gold_price, ffr, yield_nominal, bei, tips_real,
             gold_change_pct, ffr_change, real_change, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [month, gold_price, ffr, yield_nominal, bei, tips_real,
         gold_change_pct, ffr_change, real_change, source],
    )
    return True


def get_all_monthly(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM gold_monthly ORDER BY month ASC"
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def get_monthly_range(
    conn: duckdb.DuckDBPyConnection, start_month: str, end_month: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM gold_monthly WHERE month >= ? AND month <= ? ORDER BY month ASC",
        [start_month, end_month],
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def get_latest_monthly(conn: duckdb.DuckDBPyConnection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM gold_monthly ORDER BY month DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def get_recent_monthly(
    conn: duckdb.DuckDBPyConnection, limit: int = 12
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM gold_monthly ORDER BY month DESC LIMIT ?", [limit]
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return list(reversed([dict(zip(cols, r)) for r in rows]))


def get_monthly_by_month(
    conn: duckdb.DuckDBPyConnection, month: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM gold_monthly WHERE month = ?", [month]
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# gold_policy_cycle CRUD
# ---------------------------------------------------------------------------

def get_all_cycles(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM gold_policy_cycle ORDER BY start_month DESC"
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def get_active_cycle_for_month(
    conn: duckdb.DuckDBPyConnection, month: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM gold_policy_cycle
        WHERE start_month <= ?
          AND (end_month IS NULL OR end_month >= ?)
          AND status = 'active'
        ORDER BY start_month DESC
        LIMIT 1
        """,
        [month, month],
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def get_cycle_by_id(
    conn: duckdb.DuckDBPyConnection, cycle_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM gold_policy_cycle WHERE cycle_id = ?", [cycle_id]
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def get_last_cycle(conn: duckdb.DuckDBPyConnection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM gold_policy_cycle ORDER BY start_month DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def insert_cycle(
    conn: duckdb.DuckDBPyConnection,
    cycle_name: str,
    start_month: str,
    end_month: str | None,
    cycle_type: str,
    source: str = "auto",
    status: str = "pending_review",
    gold_start: float | None = None,
    gold_end: float | None = None,
    gold_change_pct: float | None = None,
) -> int:
    # DuckDB INTEGER PRIMARY KEY is not auto-incremented — compute next id manually
    row = conn.execute("SELECT coalesce(max(cycle_id), 0) + 1 FROM gold_policy_cycle").fetchone()
    next_id = int(row[0]) if row else 1
    conn.execute(
        """
        INSERT INTO gold_policy_cycle
            (cycle_id, cycle_name, start_month, end_month, cycle_type, source, status,
             gold_start, gold_end, gold_change_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [next_id, cycle_name, start_month, end_month, cycle_type, source, status,
         gold_start, gold_end, gold_change_pct],
    )
    return next_id


def approve_cycle(conn: duckdb.DuckDBPyConnection, cycle_id: int) -> None:
    conn.execute(
        "UPDATE gold_policy_cycle SET status = 'active', updated_at = current_timestamp WHERE cycle_id = ?",
        [cycle_id],
    )


def close_active_cycle(conn: duckdb.DuckDBPyConnection, end_month: str) -> None:
    """Close any active (end_month IS NULL) cycle by setting its end_month."""
    conn.execute(
        "UPDATE gold_policy_cycle SET end_month = ?, updated_at = current_timestamp WHERE end_month IS NULL AND status = 'active'",
        [end_month],
    )


# ---------------------------------------------------------------------------
# gold_refresh_log
# ---------------------------------------------------------------------------

def log_refresh(
    conn: duckdb.DuckDBPyConnection,
    refreshed_month: str,
    action: str,
    success: bool,
    source: str,
    diff_summary: str | None = None,
    error_msg: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO gold_refresh_log
            (log_id, refreshed_month, action, diff_summary, success, error_msg, source)
        VALUES (uuid(), ?, ?, ?, ?, ?, ?)
        """,
        [refreshed_month, action, diff_summary, success, error_msg, source],
    )


def has_refreshed_today(
    conn: duckdb.DuckDBPyConnection, source: str = "scheduler"
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM gold_refresh_log
        WHERE refreshed_at >= current_date
          AND source = ?
          AND success = true
        LIMIT 1
        """,
        [source],
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Excel history import (一次性)
# ---------------------------------------------------------------------------

#: 列名映射（Excel 中文列 → 数据库字段）
_COLUMN_MAP = {
    "月份": "month",
    "国际金价(美元/盎司,月均)": "gold_price",
    "联邦基金有效利率(%)": "ffr",
    "10年期美债名义利率(%)": "yield_nominal",
    "10年期盈亏平衡通胀率BEI(%)": "bei",
    "10年期TIPS实际利率(%)": "tips_real",
    "金价环比涨跌(%)": "gold_change_pct",
    "政策利率月度变动(pct点)": "ffr_change",
    "实际利率月度变动(pct点)": "real_change",
}


def import_excel_history(
    conn: duckdb.DuckDBPyConnection, excel_path: str
) -> dict[str, Any]:
    """Import the two sheets from the historical Excel file.

    Returns a summary dict with row counts for each target table.
    """
    import pandas as pd

    # --- 月度数据 sheet ---
    df_monthly = pd.read_excel(excel_path, sheet_name="月度数据")
    # Rename to English column names
    rename_map = {k: v for k, v in _COLUMN_MAP.items() if k in df_monthly.columns}
    df_monthly = df_monthly.rename(columns=rename_map)

    rows_inserted = 0
    rows_updated = 0
    for _, row in df_monthly.iterrows():
        month = str(row.get("month", ""))
        if not month or month == "nan":
            continue
        # Normalize month format (Excel may give "1996-10", fine)
        gp = row.get("gold_price")
        ffr = row.get("ffr")
        yn = row.get("yield_nominal")
        bei_val = row.get("bei")
        tips = row.get("tips_real")
        # Compute tips_real if bei is present but tips_real is NaN
        if (pd.isna(tips) or tips is None) and not (pd.isna(yn) or pd.isna(bei_val)):
            tips = float(yn) - float(bei_val)

        inserted = insert_or_update_monthly(
            conn,
            month=month,
            gold_price=_to_float_or_none(gp),
            ffr=_to_float_or_none(ffr),
            yield_nominal=_to_float_or_none(yn),
            bei=_to_float_or_none(bei_val),
            tips_real=_to_float_or_none(tips),
            gold_change_pct=_to_float_or_none(row.get("gold_change_pct")),
            ffr_change=_to_float_or_none(row.get("ffr_change")),
            real_change=_to_float_or_none(row.get("real_change")),
            source="excel",
        )
        if inserted:
            rows_inserted += 1
        else:
            rows_updated += 1

    # --- 政策周期对比 sheet ---
    df_cycles = pd.read_excel(excel_path, sheet_name="政策周期对比", header=None)
    # Data starts at row index 2 (rows 0-1 are title + header)
    data = df_cycles.iloc[2:].dropna(subset=[0])
    rows_cycles = 0
    for _, row in data.iterrows():
        name_raw = str(row[0]).strip()
        start = str(row[1]).strip()
        end = str(row[2]).strip()
        if not name_raw or not start or start == "nan":
            continue
        # Determine cycle_type from the name
        cycle_type = _classify_cycle_name(name_raw)
        gp_start = _to_float_or_none(row[7])
        gp_end = _to_float_or_none(row[8])
        gp_chg = _to_float_or_none(row[9])

        insert_cycle(
            conn,
            cycle_name=name_raw,
            start_month=start,
            end_month=None if end == "至今" or end == "nan" else end,
            cycle_type=cycle_type,
            source="excel",
            status="active",
            gold_start=gp_start,
            gold_end=gp_end,
            gold_change_pct=gp_chg,
        )
        rows_cycles += 1

    logger.info(
        "Excel import complete: monthly inserted=%d updated=%d, cycles=%d",
        rows_inserted, rows_updated, rows_cycles,
    )
    return {
        "monthly_inserted": rows_inserted,
        "monthly_updated": rows_updated,
        "cycles_inserted": rows_cycles,
    }


def _to_float_or_none(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _classify_cycle_name(name: str) -> str:
    if "加息" in name or "hiking" in name.lower():
        return "hiking"
    if "降息" in name or "cutting" in name.lower() or "LTCM" in name:
        return "cutting"
    if "平台" in name or "stable" in name.lower():
        return "plateau"
    # LTCM 预防式降息
    if "LTCM" in name:
        return "cutting"
    return "plateau"


# ---------------------------------------------------------------------------
# gold_signal — indicator analysis history
# ---------------------------------------------------------------------------

def insert_signal(
    conn: duckdb.DuckDBPyConnection,
    indicator_key: str,
    judgment: str,
    confidence: float | None,
    summary: str | None,
    details: str | None,
    source: str = "manual",
    cycle_id: int | None = None,
) -> str:
    conn.execute(
        """
        INSERT INTO gold_signal
            (indicator_key, judgment, confidence, summary, details, source, cycle_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        RETURNING signal_id
        """,
        [indicator_key, judgment, confidence, summary, details, source, cycle_id],
    )
    row = conn.fetchone()
    return str(row[0]) if row else ""


def get_latest_signal(
    conn: duckdb.DuckDBPyConnection, indicator_key: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM gold_signal WHERE indicator_key = ? ORDER BY created_at DESC LIMIT 1",
        [indicator_key],
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def get_signal_history(
    conn: duckdb.DuckDBPyConnection, indicator_key: str, limit: int = 20
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM gold_signal WHERE indicator_key = ? ORDER BY created_at DESC LIMIT ?",
        [indicator_key, limit],
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def update_signal_confidence(
    conn: duckdb.DuckDBPyConnection, signal_id: str, confidence: float
) -> None:
    conn.execute(
        "UPDATE gold_signal SET confidence = ? WHERE signal_id = ?",
        [confidence, signal_id],
    )


def get_all_latest_signals(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Return the latest signal for each indicator."""
    rows = conn.execute(
        """
        SELECT s.* FROM gold_signal s
        INNER JOIN (
            SELECT indicator_key, max(created_at) AS max_at
            FROM gold_signal GROUP BY indicator_key
        ) m ON s.indicator_key = m.indicator_key AND s.created_at = m.max_at
        """
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def get_latest_signals_for_cycle(
    conn: duckdb.DuckDBPyConnection, cycle_id: int
) -> list[dict[str, Any]]:
    """Return the latest signal per indicator that is linked to the given cycle."""
    rows = conn.execute(
        """
        SELECT s.* FROM gold_signal s
        INNER JOIN (
            SELECT indicator_key, max(created_at) AS max_at
            FROM gold_signal WHERE cycle_id = ? GROUP BY indicator_key
        ) m ON s.indicator_key = m.indicator_key AND s.created_at = m.max_at
        WHERE s.cycle_id = ?
        """,
        [cycle_id, cycle_id],
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def update_post_hoc_confidence(
    conn: duckdb.DuckDBPyConnection, cycle_id: int, confidence: float | None
) -> None:
    conn.execute(
        "UPDATE gold_policy_cycle SET post_hoc_confidence = ?, updated_at = current_timestamp WHERE cycle_id = ?",
        [confidence, cycle_id],
    )


# ---------------------------------------------------------------------------
# gold_signal_prompt — editable prompts
# ---------------------------------------------------------------------------

def get_prompt(
    conn: duckdb.DuckDBPyConnection, indicator_key: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM gold_signal_prompt WHERE indicator_key = ?",
        [indicator_key],
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def get_all_prompts(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM gold_signal_prompt").fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def upsert_prompt(
    conn: duckdb.DuckDBPyConnection,
    indicator_key: str,
    system_prompt: str,
    user_prompt: str,
) -> None:
    existing = conn.execute(
        "SELECT indicator_key FROM gold_signal_prompt WHERE indicator_key = ?",
        [indicator_key],
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE gold_signal_prompt
            SET system_prompt = ?, user_prompt = ?, updated_at = current_timestamp
            WHERE indicator_key = ?
            """,
            [system_prompt, user_prompt, indicator_key],
        )
    else:
        conn.execute(
            """
            INSERT INTO gold_signal_prompt (indicator_key, system_prompt, user_prompt)
            VALUES (?, ?, ?)
            """,
            [indicator_key, system_prompt, user_prompt],
        )


# ---------------------------------------------------------------------------
# gold_fomc — FOMC meeting schedule
# ---------------------------------------------------------------------------

def get_next_fomc(conn: duckdb.DuckDBPyConnection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM gold_fomc WHERE meeting_date >= current_date ORDER BY meeting_date ASC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.description]
    return dict(zip(cols, row))


def get_all_fomc(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM gold_fomc ORDER BY meeting_date ASC"
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]


def replace_future_fomc(
    conn: duckdb.DuckDBPyConnection, meetings: list[dict[str, Any]]
) -> int:
    """Delete all future meetings and insert the new list."""
    conn.execute("DELETE FROM gold_fomc WHERE meeting_date >= current_date")
    count = 0
    for m in meetings:
        conn.execute(
            """
            INSERT INTO gold_fomc (meeting_date, title, notes, source)
            VALUES (?, ?, ?, ?)
            """,
            [m.get("meeting_date"), m.get("title", "FOMC议息会议"),
             m.get("notes"), m.get("source", "llm")],
        )
        count += 1
    return count
