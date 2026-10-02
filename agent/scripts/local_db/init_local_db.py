"""本地 DuckDB 行情库初始化 / 增量灌数脚本。

从工程已有的免费数据源（Tencent、Eastmoney、Frankfurter）把数据落到
~/.vibe-trading/data/market.duckdb，灌完用 local loader 经
~/.vibe-trading/data-bridge/config.yaml 读取（调用符号 local:01810.HK）。

灌入内容：
  1. instrument_master          证券主数据（内置少量种子名称，其余按代码后缀推导）
  2. daily_bar                  日线 raw 原始价（HK: tencent 主 / eastmoney 备；
                                 A股/美股: eastmoney fqt=0 不复权）
  3. trading_calendar           由实际成交日期推导的交易日历
  4. fx_rate                    HKDCNY / USDCNY / USDHKD 参考汇率（Frankfurter/ECB）
  5. shares_outstanding         港股已发行股本（Eastmoney F10）
  6. valuation_daily            港股 PE_TTM / PB / 总市值参考快照（F10，仅交叉验证用）

幂等：全部按主键 INSERT OR REPLACE，可重复执行做日度增量更新。

用法（必须在 agent/ 目录下运行，与其它 scripts 一致）：
    cd agent
    python scripts/local_db/init_local_db.py
    python scripts/local_db/init_local_db.py --symbols 01810.HK,00700.HK \
        --start 2023-01-01
    python scripts/local_db/init_local_db.py --symbols 600519.SH --skip-fx --skip-shares
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
AGENT_DIR = HERE.parent.parent  # agent/scripts/local_db -> agent
sys.path.insert(0, str(AGENT_DIR))

from backtest.loaders.eastmoney_client import KLT_BY_INTERVAL, fetch_kline, resolve_secid  # noqa: E402
from backtest.loaders.tencent_loader import DataLoader as TencentLoader  # noqa: E402
from src.config.paths import get_market_db_path  # noqa: E402

logger = logging.getLogger("init_local_db")

DEFAULT_DB_PATH = get_market_db_path()
SCHEMA_PATH = HERE / "schema.sql"

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/{start}..{end}"
EASTMONEY_F10_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"

# 后缀 -> (market, currency, exchange)
_MARKET_BY_SUFFIX = {
    "HK": ("hk_equity", "HKD", "HKEX"),
    "SH": ("a_share", "CNY", "SSE"),
    "SZ": ("a_share", "CNY", "SZSE"),
    "BJ": ("a_share", "CNY", "BSE"),
    "US": ("us_equity", "USD", None),
}

# 常用种子名称（其余标的 name 留空，可手工补 instrument_master）
# symbol -> (中文名, 英文名, 每手股数)
_SEED_NAMES = {
    "01810.HK": ("小米集团-W", "Xiaomi Corp", 200),
    "00700.HK": ("腾讯控股", "Tencent Holdings", 100),
    "09988.HK": ("阿里巴巴-W", "Alibaba Group-W", 100),
    "600519.SH": ("贵州茅台", "Kweichow Moutai", 100),
    "000001.SZ": ("平安银行", "Ping An Bank", 100),
    "AAPL.US": ("苹果", "Apple Inc.", 1),
}

# 必灌的三条汇率腿；HKDCNY 直接给出，另两条用于三角换算交叉验证
_FX_PAIRS = [("HKD", "CNY"), ("USD", "CNY"), ("USD", "HKD")]

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://emweb.securities.eastmoney.com/",
}


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def _split_symbol(symbol: str) -> tuple[str, str]:
    code, _, suffix = symbol.strip().upper().rpartition(".")
    return code, suffix


def _market_info(symbol: str) -> tuple[str, str, Optional[str]]:
    _, suffix = _split_symbol(symbol)
    if suffix in _MARKET_BY_SUFFIX:
        return _MARKET_BY_SUFFIX[suffix]
    return ("unknown", None, None)


def _stage_upsert(conn, table: str, frame: pd.DataFrame) -> int:
    """通过临时视图对 table 做 INSERT OR REPLACE；返回写入行数。"""
    if frame is None or frame.empty:
        return 0
    conn.register("_stg", frame)
    cols = ", ".join(frame.columns)
    conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) SELECT {cols} FROM _stg")
    conn.unregister("_stg")
    return len(frame)


def _log_ingest(conn, task: str, symbol: str, status: str, rows: int, message: str = "") -> None:
    conn.execute(
        "INSERT INTO ingest_log (task, symbol, status, rows, message) VALUES (?, ?, ?, ?, ?)",
        [task, symbol, status, rows, message],
    )


# --------------------------------------------------------------------------
# 1) 主数据
# --------------------------------------------------------------------------

def upsert_instrument(conn, symbol: str) -> str:
    market, currency, exchange = _market_info(symbol)
    name, name_en, lot_size = _SEED_NAMES.get(symbol, (None, None, None))
    frame = pd.DataFrame([{
        "symbol": symbol,
        "name": name,
        "name_en": name_en,
        "market": market,
        "currency": currency,
        "exchange": exchange,
        "list_date": None,
        "delist_date": None,
        "lot_size": lot_size,
        "sector": None,
        "industry": None,
        "is_active": True,
        "source": "seed",
    }])
    _stage_upsert(conn, "instrument_master", frame)
    return market


# --------------------------------------------------------------------------
# 2) 日线行情（raw）
# --------------------------------------------------------------------------

def _bars_from_eastmoney(symbol: str, start: str, end: str) -> Optional[pd.DataFrame]:
    secid = resolve_secid(symbol)
    if not secid:
        return None
    rows = fetch_kline(
        secid,
        klt=KLT_BY_INTERVAL["1D"],
        fqt=0,  # 0 = 不复权，保证落库的是 raw 原始价
        beg=start.replace("-", ""),
        end=end.replace("-", ""),
    )
    if not rows:
        return None
    return pd.DataFrame(rows)


def _bars_from_tencent(symbol: str, start: str, end: str) -> Optional[pd.DataFrame]:
    # tencent A股返回的是加法平移 qfq（非 raw），港股端点只有 day 原始价，
    # 因此 tencent 仅用于港股。
    fetched = TencentLoader().fetch([symbol], start, end, interval="1D")
    df = fetched.get(symbol)
    if df is None or df.empty:
        return None
    return df.reset_index().rename(columns={"trade_date": "trade_date"})


def fetch_daily_raw(symbol: str, start: str, end: str) -> tuple[Optional[pd.DataFrame], str]:
    """返回 (OHLCV长表, source)。长表列：trade_date/open/high/low/close/volume/amount。"""
    _, suffix = _split_symbol(symbol)

    if suffix == "HK":
        # 港股 tencent 即 raw，优先；eastmoney fqt=0 兜底
        try:
            df = _bars_from_tencent(symbol, start, end)
            if df is not None and not df.empty:
                df["amount"] = None
                return df, "tencent"
        except Exception as exc:  # noqa: BLE001 - 单源失败后降级
            logger.warning("tencent 拉取 %s 失败，降级 eastmoney: %s", symbol, exc)
        df = _bars_from_eastmoney(symbol, start, end)
        return (df, "eastmoney") if df is not None else (None, "")

    # A股 / 美股：eastmoney fqt=0 取 raw（tencent A股是 qfq，不能作为 raw 落库）
    df = _bars_from_eastmoney(symbol, start, end)
    return (df, "eastmoney") if df is not None else (None, "")


def upsert_daily_bars(conn, symbol: str, start: str, end: str) -> int:
    raw, source = fetch_daily_raw(symbol, start, end)
    if raw is None or raw.empty:
        logger.warning("%s 未取得任何日线（%s ~ %s）", symbol, start, end)
        _log_ingest(conn, "daily_bar", symbol, "skipped", 0, "no bars from any source")
        return 0

    market, _, _ = _market_info(symbol)
    volume_unit = "lots" if market == "a_share" else "shares"

    frame = pd.DataFrame({
        "symbol": symbol,
        "trade_date": pd.to_datetime(raw["trade_date"]).dt.date,
        "open": pd.to_numeric(raw["open"], errors="coerce"),
        "high": pd.to_numeric(raw["high"], errors="coerce"),
        "low": pd.to_numeric(raw["low"], errors="coerce"),
        "close": pd.to_numeric(raw["close"], errors="coerce"),
        "volume": pd.to_numeric(raw["volume"], errors="coerce"),
        "amount": pd.to_numeric(raw["amount"], errors="coerce") if "amount" in raw else None,
        "volume_unit": volume_unit,
        "price_caliber": "raw",
        "source": source,
    }).dropna(subset=["open", "high", "low", "close", "trade_date"])

    rows = _stage_upsert(conn, "daily_bar", frame)
    _log_ingest(conn, "daily_bar", symbol, "ok", rows, f"source={source}")
    logger.info("daily_bar %s: 写入 %d 行（source=%s, raw）", symbol, rows, source)
    return rows


# --------------------------------------------------------------------------
# 3) 交易日历（由 daily_bar 实际成交日推导）
# --------------------------------------------------------------------------

def rebuild_calendar(conn, symbols: list[str]) -> None:
    """用本次标的实际成交日期填充各市场日历（仅标记开市日）。"""
    if not symbols:
        return
    quoted = ", ".join(f"'{s}'" for s in symbols)
    rows = conn.execute(
        f"""
        SELECT m.market AS market, CAST(b.trade_date AS DATE) AS cal_date
        FROM daily_bar b
        JOIN instrument_master m ON m.symbol = b.symbol
        WHERE b.symbol IN ({quoted})
        GROUP BY 1, 2
        """
    ).fetchall()
    if not rows:
        return
    frame = pd.DataFrame(rows, columns=["market", "cal_date"])
    frame["is_open"] = True
    written = _stage_upsert(conn, "trading_calendar", frame)
    _log_ingest(conn, "trading_calendar", ",".join(symbols), "ok", written,
                "derived from observed trading dates")
    logger.info("trading_calendar: 写入 %d 个开市日", written)


# --------------------------------------------------------------------------
# 4) 外汇参考汇率（Frankfurter / ECB）
# --------------------------------------------------------------------------

def upsert_fx_rates(conn, start: str, end: str) -> None:
    session = requests.Session()
    total = 0
    for base, quote in _FX_PAIRS:
        url = FRANKFURTER_URL.format(start=start, end=end)
        try:
            resp = session.get(
                url,
                params={"base": base, "symbols": quote},
                timeout=20,
                headers=_HTTP_HEADERS,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - 单腿失败不影响其它腿
            logger.warning("FX %s%s 拉取失败: %s", base, quote, exc)
            _log_ingest(conn, "fx_rate", f"{base}{quote}", "error", 0, str(exc))
            continue

        rates = payload.get("rates", {})
        frame = pd.DataFrame([
            {
                "base": base,
                "quote": quote,
                "rate_date": datetime.strptime(d, "%Y-%m-%d").date(),
                "rate": float(v[quote]),
                "rate_type": "reference",
                "source": "frankfurter_ecb",
            }
            for d, v in sorted(rates.items())
            if isinstance(v, dict) and quote in v
        ])
        total += _stage_upsert(conn, "fx_rate", frame)
        time.sleep(0.2)  # 礼貌限速
    logger.info("fx_rate: 写入 %d 行（HKDCNY/USDCNY/USDHKD）", total)
    _log_ingest(conn, "fx_rate", "ALL", "ok", total, "frankfurter reference rates")


# --------------------------------------------------------------------------
# 5/6) 港股股本 + 估值快照（Eastmoney 港股 F10）
# --------------------------------------------------------------------------

_F10_COLUMNS = ",".join([
    "SECUCODE",
    "REPORT_DATE",
    "ISSUED_COMMON_SHARES",  # 已发行股本
    "HK_COMMON_SHARES",      # 港股流通股本
    "TOTAL_MARKET_CAP",      # 总市值（HKD）
    "PE_TTM",
    "PB_TTM",
])


def fetch_hk_f10(symbol: str, page_size: int = 40) -> list[dict]:
    params = {
        "reportName": "RPT_CUSTOM_HKF10_FN_MAININDICATORMAX",
        "columns": _F10_COLUMNS,
        "filter": f'(SECUCODE="{symbol}")',
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortTypes": "-1",
        "sortColumns": "REPORT_DATE",
        "source": "F10",
        "client": "PC",
    }
    resp = requests.get(EASTMONEY_F10_URL, params=params, timeout=20, headers=_HTTP_HEADERS)
    resp.raise_for_status()
    payload = resp.json()
    result = payload.get("result")
    if not isinstance(result, dict):
        return []
    data = result.get("data")
    return data if isinstance(data, list) else []


def upsert_hk_shares_and_valuation(conn, symbol: str) -> None:
    rows = fetch_hk_f10(symbol)
    if not rows:
        logger.warning("%s F10 未返回股本/估值数据", symbol)
        _log_ingest(conn, "shares_outstanding", symbol, "skipped", 0, "empty F10 payload")
        return

    shares_rows = []
    valuation_rows = []
    for r in rows:
        report_date = pd.to_datetime(r.get("REPORT_DATE"), errors="coerce")
        if pd.isna(report_date):
            continue
        report_day = report_date.date()
        issued = r.get("ISSUED_COMMON_SHARES")
        float_shares = r.get("HK_COMMON_SHARES")

        shares_rows.append({
            "symbol": symbol,
            "report_date": report_day,
            "ann_date": None,  # F10 该接口不提供披露日；PIT 取数前需补公告日
            "shares_issued": int(issued) if issued is not None else None,
            "shares_float": int(float_shares) if float_shares is not None else None,
            "share_class": "common",
            "change_reason": None,
            "currency": "HKD",
            "source": "eastmoney_hk_f10",
        })
        valuation_rows.append({
            "symbol": symbol,
            "trade_date": report_day,  # 报告期末快照，非交易日行情（见 note）
            "pe_ttm": r.get("PE_TTM"),
            "pb": r.get("PB_TTM"),
            "total_market_cap": r.get("TOTAL_MARKET_CAP"),
            "currency": "HKD",
            "note": "period_end_reference",
            "source": "eastmoney_hk_f10",
        })

    n1 = _stage_upsert(conn, "shares_outstanding", pd.DataFrame(shares_rows))
    n2 = _stage_upsert(conn, "valuation_daily", pd.DataFrame(valuation_rows))
    _log_ingest(conn, "shares_outstanding", symbol, "ok", n1, "F10 issued/common shares")
    logger.info("shares_outstanding %s: %d 期；valuation_daily: %d 期", symbol, n1, n2)


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="初始化/增量更新本地 DuckDB 行情库")
    parser.add_argument("--symbols", default="01810.HK",
                        help="逗号分隔的标的列表，默认 01810.HK")
    parser.add_argument("--start", default=None,
                        help="起始日 YYYY-MM-DD，默认三年前")
    parser.add_argument("--end", default=date.today().isoformat(),
                        help="结束日 YYYY-MM-DD，默认今天")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH),
                        help=f"DuckDB 路径，默认 {DEFAULT_DB_PATH}")
    parser.add_argument("--skip-fx", action="store_true", help="跳过汇率灌数")
    parser.add_argument("--skip-shares", action="store_true", help="跳过港股股本/估值灌数")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    if args.start is None:
        args.start = (date.today() - timedelta(days=365 * 3)).isoformat()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    db_path = Path(args.db).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    import duckdb

    with duckdb.connect(str(db_path)) as conn:
        # 1) 建表（幂等）
        conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        logger.info("schema 就绪: %s", db_path)

        # 2) 主数据 + 日线
        hk_symbols: list[str] = []
        for symbol in symbols:
            market = upsert_instrument(conn, symbol)
            upsert_daily_bars(conn, symbol, args.start, args.end)
            if market == "hk_equity":
                hk_symbols.append(symbol)
            time.sleep(1.0)  # 跨标的限速，避免 eastmoney 封 IP

        # 3) 交易日历
        rebuild_calendar(conn, symbols)

        # 4) 汇率
        if not args.skip_fx:
            upsert_fx_rates(conn, args.start, args.end)

        # 5) 港股股本 / 估值
        if not args.skip_shares:
            for symbol in hk_symbols:
                try:
                    upsert_hk_shares_and_valuation(conn, symbol)
                except Exception as exc:  # noqa: BLE001 - 单个标的失败不影响整体
                    logger.warning("%s 股本灌数失败: %s", symbol, exc)
                    _log_ingest(conn, "shares_outstanding", symbol, "error", 0, str(exc))
                time.sleep(1.0)

        # 汇总
        logger.info("---- 灌数结果 ----")
        for table in ["instrument_master", "trading_calendar", "daily_bar",
                      "fx_rate", "shares_outstanding", "valuation_daily"]:
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            logger.info("%-20s %d 行", table, count)

    logger.info("完成。local loader 调用方式：local:<symbol>，配置见 "
                "~/.vibe-trading/data-bridge/config.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
