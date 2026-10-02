"""Per-source adapters for the watchlist multi-level K-line card.

The Chanlun readiness card lets the investor pick WHICH market-data source
fetches the five required levels (plus the optional 30-minute level), using
the same source vocabulary (and priority order) as the Settings page's
"source priority" card (``MARKET_DATA_ORDER_A_SHARE``).

Every adapter returns ascending bars shaped like the Eastmoney client:

    {"trade_date": "2026-09-30" | "2026-09-30 11:30:00",
     "open", "high", "low", "close", "volume", "amount"}

Sources whose package/token is missing are still listed (so the dropdown
mirrors Settings) but marked unavailable; intervals a source cannot serve
natively (quarter/year for most vendors) are produced by resampling that
source's own monthly bars, never by silently mixing another source.
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.request
from collections import OrderedDict
from datetime import date
from importlib.util import find_spec
from typing import Any, Callable

from src.watchlist.market import WatchlistDataError

logger = logging.getLogger(__name__)

#: Levels in display/API order.
ALL_INTERVALS: tuple[str, ...] = ("1d", "1w", "1mo", "1q", "1y", "30m")

#: Uniform adapter signature:
#: (symbol ``600519.SH``, interval, start, end) -> ascending bar rows.
SourceAdapter = Callable[[str, str, date, date], list[dict[str, Any]]]

_SSL_CONTEXT = ssl.create_default_context()
try:  # certifi is a project dependency; stay defensive in stripped envs
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover - platform CA fallback
    pass

# ---------------------------------------------------------------------------
# Availability metadata
# ---------------------------------------------------------------------------

#: Intervals each source can serve (native or via its own resampling).
_CAPABILITIES: dict[str, frozenset[str]] = {
    "eastmoney": frozenset(ALL_INTERVALS),
    "tencent": frozenset(ALL_INTERVALS),
    "akshare": frozenset(ALL_INTERVALS),
    "tushare": frozenset(ALL_INTERVALS),
    # mootdx/baostock: 30m native, quarter/year aggregated from monthly.
    "mootdx": frozenset(ALL_INTERVALS),
    "baostock": frozenset(ALL_INTERVALS),
    "gildata": frozenset(),
    # Reads bars already incrementally stored in the local DuckDB warehouse.
    "local": frozenset(ALL_INTERVALS),
}

_REQUIRES_AUTH = {"tushare", "gildata"}

#: Machine-readable unavailability reasons (the UI owns the translated text).
REASON_NOT_INSTALLED = "not_installed"
REASON_NEEDS_AUTH = "needs_auth"
REASON_NO_ADAPTER = "no_adapter"

_PIP_PACKAGE = {
    "akshare": "akshare",
    "tushare": "tushare",
    "mootdx": "mootdx",
    "baostock": "baostock",
}


def _installed(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _token_configured() -> tuple[bool, bool]:
    """Return (tushare_ok, gildata_ok) without importing heavy clients."""
    try:
        from src.config.accessor import get_env_config

        data = get_env_config().data
        tushare_ok = data.tushare_token.strip() not in {"", "your-tushare-token"}
        gildata_ok = bool(data.gildata_token.strip())
        return tushare_ok, gildata_ok
    except Exception:  # pragma: no cover - config always present at runtime
        return False, False


def availability(source: str) -> tuple[bool, str | None]:
    """``(usable, reason_code)`` for one source id."""
    if source not in _CAPABILITIES:
        return False, REASON_NO_ADAPTER
    if source in {"eastmoney", "tencent", "local"}:
        return True, None
    if source in _PIP_PACKAGE and not _installed(_PIP_PACKAGE[source]):
        return False, REASON_NOT_INSTALLED
    if source in _REQUIRES_AUTH:
        tushare_ok, gildata_ok = _token_configured()
        if source == "tushare" and not tushare_ok:
            return False, REASON_NEEDS_AUTH
        if source == "gildata" and not gildata_ok:
            return False, REASON_NEEDS_AUTH
    if not _CAPABILITIES[source]:
        return False, REASON_NO_ADAPTER
    return True, None


def list_sources() -> list[dict[str, Any]]:
    """Source catalog for the dropdown, in effective A-share priority order.

    Mirrors the Settings page: the order follows the current
    ``MARKET_DATA_ORDER_A_SHARE`` override (default chain when unset).
    """
    try:
        from backtest.loaders import registry

        registry.refresh_source_order_overrides()
        ordered = list(registry.FALLBACK_CHAINS.get("a_share", []))
    except Exception:  # pragma: no cover - registry always present
        ordered = [
            "tencent",
            "mootdx",
            "eastmoney",
            "baostock",
            "akshare",
            "tushare",
            "gildata",
            "local",
        ]
    known = set(_CAPABILITIES)
    items: list[dict[str, Any]] = []
    for source in ordered:
        if source not in known:
            continue
        ok, reason = availability(source)
        items.append(
            {
                "id": source,
                "available": ok,
                "requires_auth": source in _REQUIRES_AUTH,
                "reason": reason,
                "intervals": [
                    interval
                    for interval in ALL_INTERVALS
                    if interval in _CAPABILITIES[source]
                ],
            }
        )
    return items


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _http_get_json(url: str, *, retries: int = 2) -> dict[str, Any]:
    """GET a JSON endpoint with a browser UA and one polite retry."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Referer": "https://gu.qq.com/",
    }
    last_exc: Exception | None = None
    for _attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15, context=_SSL_CONTEXT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - normalized below
            last_exc = exc
    raise WatchlistDataError(f"HTTP 请求失败: {last_exc}")


def _to_bar(
    trade_date: str,
    open_: Any,
    high: Any,
    low: Any,
    close: Any,
    volume: Any,
    amount: Any = None,
) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "open": _num(open_),
        "high": _num(high),
        "low": _num(low),
        "close": _num(close),
        "volume": _num(volume),
        "amount": _num(amount),
    }


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resample_bars(rows: list[dict[str, Any]], rule: str) -> list[dict[str, Any]]:
    """Aggregate monthly bars into quarter/year bars.

    Grouping uses each monthly bar's own label (vendors date monthly bars at
    the last trading day of the month), so a bar never lands in the wrong
    calendar bucket around holidays. Open = first month, close = last month,
    high/low are extremes, volume/amount sum.
    """
    groups: "OrderedDict[tuple[int, int], list[dict[str, Any]]]" = OrderedDict()
    for row in sorted(rows, key=lambda r: r["trade_date"]):
        label = str(row["trade_date"])[:10]
        year, month = int(label[:4]), int(label[5:7])
        if rule == "1q":
            key = (year, (month - 1) // 3 + 1)
        elif rule == "1y":
            key = (year, 0)
        else:  # pragma: no cover - internal call only
            raise ValueError(f"unsupported resample rule: {rule}")
        groups.setdefault(key, []).append(row)

    out: list[dict[str, Any]] = []
    for bucket in groups.values():
        first, last = bucket[0], bucket[-1]
        out.append(
            {
                "trade_date": str(last["trade_date"])[:10],
                "open": first["open"],
                "high": max(b["high"] for b in bucket if b["high"] is not None),
                "low": min(b["low"] for b in bucket if b["low"] is not None),
                "close": last["close"],
                "volume": _sum(bucket, "volume"),
                "amount": _sum(bucket, "amount"),
            }
        )
    return out


def _sum(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [r[key] for r in rows if r.get(key) is not None]
    return float(sum(values)) if values else None


# ---------------------------------------------------------------------------
# Tencent (web.ifzq.gtimg.cn) — no-auth HTTP, day/week/month + 30-minute
# ---------------------------------------------------------------------------

_TENCENT_DAY_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_TENCENT_MIN_URL = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"


def _tencent_code(symbol: str) -> str:
    code, _, suffix = symbol.partition(".")
    suffix = suffix.upper()
    if suffix == "SH":
        return f"sh{code}"
    if suffix == "SZ":
        return f"sz{code}"
    raise WatchlistDataError(
        f"腾讯财经接口暂不支持该市场的标的: {symbol}（仅支持沪深 A 股）"
    )


def _fetch_tencent(symbol: str, interval: str, start: date, end: date) -> list[dict[str, Any]]:
    code = _tencent_code(symbol)

    if interval == "30m":
        # mkline returns the latest N 30-minute bars (320 ≈ 40 trading days);
        # it takes no date window.
        url = f"{_TENCENT_MIN_URL}?param={code},m30,,320"
        payload = _http_get_json(url)
        node = (payload.get("data") or {}).get(code) or {}
        raw_rows = node.get("m30") or []
        rows = []
        for raw in raw_rows:
            if len(raw) < 6 or not str(raw[0]).isdigit() or len(str(raw[0])) < 12:
                continue
            stamp = str(raw[0])
            label = (
                f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]} "
                f"{stamp[8:10]}:{stamp[10:12]}:00"
            )
            # Tencent minute rows: [time, open, close, high, low, volume, ...].
            rows.append(_to_bar(label, raw[1], raw[3], raw[4], raw[2], raw[5]))
        return rows

    period = {"1d": "day", "1w": "week", "1mo": "month"}.get(interval)
    if period is None:
        # Quarter/year are aggregated from this source's own monthly bars;
        # the caller's lookback window is already wide enough (>= 6/11 years).
        period = "month"

    count = 1000
    url = (
        f"{_TENCENT_DAY_URL}?param={code},{period},"
        f"{start.isoformat()},{end.isoformat()},{count},qfq"
    )
    payload = _http_get_json(url)
    if payload.get("code") not in (0, None):
        raise WatchlistDataError(
            f"腾讯财经接口返回错误: code={payload.get('code')} msg={payload.get('msg')}"
        )
    node = (payload.get("data") or {}).get(code) or {}
    raw_rows = node.get(f"qfq{period}") or node.get(period) or []
    rows = [
        _to_bar(
            raw[0],
            raw[1],
            raw[3],
            raw[4],
            raw[2],
            raw[5] if len(raw) > 5 else None,
        )
        for raw in raw_rows
        if len(raw) >= 5
    ]
    if interval in {"1q", "1y"}:
        rows = resample_bars(rows, interval)
    return rows


# ---------------------------------------------------------------------------
# AKShare (eastmoney-backed hist endpoints; present in the project venv)
# ---------------------------------------------------------------------------


def _fetch_akshare(symbol: str, interval: str, start: date, end: date) -> list[dict[str, Any]]:
    try:
        import akshare as ak
    except ImportError as exc:
        raise WatchlistDataError("AKShare 未安装（pip install akshare）") from exc

    bare = symbol.split(".")[0]

    if interval == "30m":
        try:
            frame = ak.stock_zh_a_hist_min_em(
                symbol=bare,
                start_date=f"{start.isoformat()} 09:30:00",
                end_date=f"{end.isoformat()} 15:00:00",
                period="30",
                adjust="qfq",
            )
        except Exception as exc:  # noqa: BLE001
            raise WatchlistDataError(f"AKShare 30 分钟接口请求失败: {exc}") from exc
        return _ak_frame_to_bars(frame, time_col="时间")

    period_alias = {"1d": "daily", "1w": "weekly", "1mo": "monthly"}
    if interval in period_alias:
        target = interval
        period = period_alias[interval]
    else:
        # Quarter/year via monthly bars.
        target, period = "1mo", "monthly"
    try:
        frame = ak.stock_zh_a_hist(
            symbol=bare,
            period=period,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )
    except Exception as exc:  # noqa: BLE001
        raise WatchlistDataError(f"AKShare 行情接口请求失败: {exc}") from exc
    rows = _ak_frame_to_bars(frame, time_col="日期")
    if target in {"1q", "1y"}:
        rows = resample_bars(rows, target)
    return rows


def _ak_frame_to_bars(frame: Any, *, time_col: str) -> list[dict[str, Any]]:
    if frame is None or len(frame) == 0:
        raise WatchlistDataError("AKShare 行情接口未返回数据")
    cols = set(frame.columns)
    needed = [time_col, "开盘", "最高", "最低", "收盘", "成交量"]
    missing = [name for name in needed if name not in cols]
    if missing:
        raise WatchlistDataError(f"AKShare 返回字段缺失: {','.join(missing)}")
    amount_col = "成交额" if "成交额" in cols else None
    rows = []
    for record in frame.to_dict("records"):
        rows.append(
            _to_bar(
                str(record[time_col]),
                record["开盘"],
                record["最高"],
                record["最低"],
                record["收盘"],
                record["成交量"],
                record[amount_col] if amount_col else None,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Tushare (token-gated; pro_bar with forward adjustment)
# ---------------------------------------------------------------------------


def _fetch_tushare(symbol: str, interval: str, start: date, end: date) -> list[dict[str, Any]]:
    try:
        import tushare as ts
    except ImportError as exc:
        raise WatchlistDataError("Tushare 未安装（pip install tushare）") from exc

    if interval == "30m":
        freq = "30min"
        target = interval
    else:
        freq = {"1d": "D", "1w": "W", "1mo": "M"}.get(interval)
        target = interval
        if freq is None:
            freq, target = "M", "1mo"
    try:
        frame = ts.pro_bar(
            ts_code=symbol,
            adj="qfq",
            freq=freq,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
    except Exception as exc:  # noqa: BLE001
        raise WatchlistDataError(f"Tushare 行情接口请求失败: {exc}") from exc
    if frame is None or len(frame) == 0:
        raise WatchlistDataError("Tushare 行情接口未返回数据（可能缺少接口积分/权限）")
    rows = []
    for record in frame.to_dict("records"):
        rows.append(
            _to_bar(
                str(record.get("trade_time") or record.get("trade_date")),
                record.get("open"),
                record.get("high"),
                record.get("low"),
                record.get("close"),
                record.get("vol"),
                record.get("amount"),
            )
        )
    rows.sort(key=lambda row: row["trade_date"])
    if target in {"1q", "1y"}:
        rows = resample_bars(rows, target)
    return rows


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, SourceAdapter] = {
    "tencent": _fetch_tencent,
    "akshare": _fetch_akshare,
    "tushare": _fetch_tushare,
}

#: Per-source Chinese hints attached to unavailability errors.
_REASON_HINT = {
    REASON_NOT_INSTALLED: "数据源组件未安装，请在环境中安装后重试",
    REASON_NEEDS_AUTH: "数据源需要先在「设置 - 数据源设置」中配置 Token",
    REASON_NO_ADAPTER: "该数据源暂不支持多级别在线取数，请选择其他数据源",
}


def fetch_source_level(
    source: str,
    symbol: str,
    interval: str,
    start: date,
    end: date,
    *,
    adapter: SourceAdapter | None = None,
) -> list[dict[str, Any]]:
    """Fetch one symbol/interval from an explicit source.

    ``adapter`` overrides the network implementation (used by tests and by
    the Eastmoney path, whose client has a different native signature).

    Raises :class:`WatchlistDataError` for every user-facing failure.
    """
    ok, reason = availability(source)
    if not ok:
        raise WatchlistDataError(
            f"数据源 {source} 当前不可用：{_REASON_HINT.get(reason, reason)}"
        )
    if interval not in _CAPABILITIES.get(source, frozenset()):
        raise WatchlistDataError(f"数据源 {source} 不支持 {interval} 级别")

    try:
        if adapter is not None:
            rows = adapter(symbol, interval, start, end)
        else:
            rows = _ADAPTERS[source](symbol, interval, start, end)
    except WatchlistDataError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize adapter surprises
        raise WatchlistDataError(f"{source} 取数失败: {exc}") from exc
    if not rows:
        raise WatchlistDataError(f"{source} 未返回 {interval} K 线数据")
    return rows
