"""Direct (never-LLM) A-share market data services for the watchlist.

The two overview refresh buttons ("更新股价与估值" / "更新获取基本信息") MUST
hit data APIs directly — this module is that boundary:

* :func:`search_a_shares` — Eastmoney suggest endpoint, filtered to A-share
  equities (SH/SZ/BJ only).
* :func:`fetch_quote_snapshots` — one batched push2 ``ulist`` request for
  price / PE(TTM) / PB / total market cap / industry.
* :func:`fetch_company_profile` — Eastmoney F10 ``stock/get`` basic info
  (name / industry / list date / total shares) via the throttled JSON
  client (same host as quotes, with browser headers — a bare request gets
  the connection dropped).

All network entry points accept an injectable ``fetcher``; tests run fully
offline with fakes. Network/parse failures raise
:class:`WatchlistDataError` (mapped to HTTP 502 with a clear reason).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any

from src.watchlist.models import CompanyProfile, QuoteSnapshot
from src.watchlist.store import WatchlistError, validate_symbol

logger = logging.getLogger(__name__)

_SUGGEST_URL = "https://searchapi.eastmoney.com/api/suggest/get"
_ULIST_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
_STOCK_GET_URL = "https://push2.eastmoney.com/api/qt/stock/get"

# stock/get field ids used for the company profile: f58 name, f127 industry,
# f189 list date (YYYYMMDD), f84 total shares.
_PROFILE_FIELDS = "f57,f58,f84,f127,f189"

# clist/ulist field ids: f2 price, f9 PE(TTM dynamic), f12 code, f14 name,
# f20 total market cap, f23 PB, f100 industry.
_QUOTE_FIELDS = "f2,f9,f12,f14,f20,f23,f100"

#: Suggest MktNum 1 = Shanghai, 0 = Shenzhen/Beijing (disambiguate by code).
_SEARCH_LIMIT = 20

#: A JSON fetcher: (url, params) -> decoded payload (dict).
JsonFetcher = Callable[[str, dict[str, Any]], Any]
#: A profile-row fetcher: bare code -> iterable of (item, value) pairs.
ProfileFetcher = Callable[[str], Sequence[tuple[str, Any]]]


class WatchlistDataError(RuntimeError):
    """A data-API call failed or returned an unusable payload (HTTP 502)."""


# ----------------------------------------------------------------------
# Symbol normalization
# ----------------------------------------------------------------------
def _suffix_for_code(code: str) -> str | None:
    """Map a 6-digit A-share code's number segment to its exchange suffix.

    B-share segments (SH 900xxx, SZ 200xxx) are rejected — this module is
    A-share only. BJ's newer 920xxx segment maps to Beijing.
    """
    head = code[0]
    if head == "6":
        return "SH"
    if head in ("0", "3"):
        return "SZ"
    if head in ("4", "8") or code.startswith("920"):
        return "BJ"
    return None


def normalize_a_share_symbol(raw: str) -> str:
    """Normalize a bare/prefixed/suffixed A-share code to ``600519.SH``.

    Accepts ``"600519"``, ``"sh600519"`` and ``"600519.SH"`` (case/space
    insensitive). Non-A-share-looking inputs raise
    :class:`~src.watchlist.store.WatchlistError`.
    """
    text = (raw or "").strip().upper()
    if not text:
        raise WatchlistError("标的代码不能为空")
    if "." in text:
        return validate_symbol(text)
    if len(text) == 8 and text[:2] in ("SH", "SZ", "BJ") and text[2:].isdigit():
        text = text[2:]
    if len(text) == 6 and text.isdigit():
        suffix = _suffix_for_code(text)
        if suffix is None:
            raise WatchlistError(f"无法识别 A 股交易所号段: {raw!r}")
        return f"{text}.{suffix}"
    raise WatchlistError(f"标的代码不合法（仅支持 A 股，如 600519.SH）: {raw!r}")


def to_eastmoney_secid(symbol: str) -> str:
    """Map an engineering symbol to Eastmoney ``market.code`` secid.

    SH uses market 1; SZ and BJ share market 0 on Eastmoney.
    """
    normalized = normalize_a_share_symbol(symbol)
    code, _, suffix = normalized.partition(".")
    market = "1" if suffix == "SH" else "0"
    return f"{market}.{code}"


# ----------------------------------------------------------------------
# Numeric helpers
# ----------------------------------------------------------------------
def _num(value: Any) -> float | None:
    """Coerce an Eastmoney cell ("-" sentinel) to float or ``None``."""
    if value is None or value == "-":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _default_json_fetcher(url: str, params: dict[str, Any]) -> Any:
    # Imported lazily in the call so unit tests injecting fakes pay no
    # transport/throttler import cost and nothing touches the network.
    from backtest.loaders.eastmoney_client import get_json

    return get_json(url, params=params)


# ----------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------
def _candidate_from_suggest_row(row: dict[str, Any]) -> dict[str, str] | None:
    code = str(row.get("Code") or "").strip()
    market = str(row.get("MktNum") or "").strip()
    quote_id = row.get("QuoteID")
    if isinstance(quote_id, str) and "." in quote_id:
        qid_market, _, qid_code = quote_id.partition(".")
        market = market or qid_market.strip()
        code = code or qid_code.strip()
    if market not in ("0", "1") or not (len(code) == 6 and code.isdigit()):
        return None
    if market == "1":
        suffix = "SH"
        if _suffix_for_code(code) != "SH":
            return None
    else:
        suffix = _suffix_for_code(code)
        if suffix not in ("SZ", "BJ"):
            return None
    name = str(row.get("Name") or "").strip()
    return {"symbol": f"{code}.{suffix}", "name": name, "industry": ""}


def search_a_shares(
    query: str,
    *,
    limit: int = _SEARCH_LIMIT,
    fetcher: JsonFetcher | None = None,
) -> list[dict[str, str]]:
    """Fuzzy-search A-share instruments by code or name.

    Returns de-duplicated ``{"symbol", "name", "industry"}`` candidates
    (industry is empty at search time — it is enriched by the first quote
    refresh). A network/parse failure raises :class:`WatchlistDataError`.
    """
    keyword = (query or "").strip()
    if not keyword:
        return []
    fetch = fetcher or _default_json_fetcher
    try:
        payload = fetch(
            _SUGGEST_URL,
            {"input": keyword, "type": "14", "count": str(_SEARCH_LIMIT)},
        )
    except Exception as exc:  # noqa: BLE001 - normalize to a typed error
        raise WatchlistDataError(f"搜索接口请求失败: {exc}") from exc

    table = payload.get("QuotationCodeTable") if isinstance(payload, dict) else None
    raw_rows = table.get("Data") if isinstance(table, dict) else None
    if not isinstance(raw_rows, list):
        return []

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        candidate = _candidate_from_suggest_row(row)
        if candidate is None or candidate["symbol"] in seen:
            continue
        seen.add(candidate["symbol"])
        results.append(candidate)
        if len(results) >= limit:
            break
    return results


# ----------------------------------------------------------------------
# Quote snapshot batch
# ----------------------------------------------------------------------
def _snapshot_from_row(row: dict[str, Any]) -> tuple[str, QuoteSnapshot] | None:
    code = str(row.get("f12") or "").strip()
    if not (len(code) == 6 and code.isdigit()):
        return None
    suffix = _suffix_for_code(code)
    if suffix is None:
        return None
    raw_industry = row.get("f100")
    industry = "" if raw_industry in (None, "-") else str(raw_industry).strip()
    return (
        f"{code}.{suffix}",
        QuoteSnapshot(
            price=_num(row.get("f2")),
            total_market_cap=_num(row.get("f20")),
            pe=_num(row.get("f9")),
            pb=_num(row.get("f23")),
            industry=industry or None,
        ),
    )


def fetch_quote_snapshots(
    symbols: Sequence[str],
    *,
    fetcher: JsonFetcher | None = None,
) -> dict[str, QuoteSnapshot]:
    """Fetch latest quote/valuation snapshots for many symbols in ONE request.

    Returns a mapping ``symbol -> QuoteSnapshot`` for every row the API
    returned; symbols absent from the response are simply missing from the
    map (callers show “暂无数据”). Timestamps are stamped by the caller when
    the snapshot is persisted.
    """
    normalized = [normalize_a_share_symbol(symbol) for symbol in symbols]
    if not normalized:
        return {}
    secids = ",".join(to_eastmoney_secid(symbol) for symbol in normalized)
    fetch = fetcher or _default_json_fetcher
    try:
        payload = fetch(
            _ULIST_URL,
            {
                "fltt": "2",
                "invt": "2",
                "fields": _QUOTE_FIELDS,
                "secids": secids,
            },
        )
    except Exception as exc:  # noqa: BLE001 - normalize to a typed error
        raise WatchlistDataError(f"行情接口请求失败: {exc}") from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    diff = data.get("diff") if isinstance(data, dict) else None
    if isinstance(diff, dict):  # some hosts key diff by index
        diff = list(diff.values())
    if not isinstance(diff, list):
        return {}

    snapshots: dict[str, QuoteSnapshot] = {}
    for row in diff:
        if not isinstance(row, dict):
            continue
        shaped = _snapshot_from_row(row)
        if shaped is not None:
            snapshots[shaped[0]] = shaped[1]
    return snapshots


# ----------------------------------------------------------------------
# Company profile (F10)
# ----------------------------------------------------------------------
def _default_profile_fetcher(code: str) -> Sequence[tuple[str, Any]]:
    """Fetch F10 basic-info rows from Eastmoney ``stock/get`` (with headers).

    Returned under the Chinese item labels that :func:`profile_from_rows`
    understands, keeping the row-based parsing contract identical to the
    previous akshare backend.
    """
    from backtest.loaders.eastmoney_client import get_json

    market = "1" if code.startswith("6") else "0"
    payload = get_json(
        _STOCK_GET_URL,
        params={
            "fltt": "2",
            "invt": "2",
            "fields": _PROFILE_FIELDS,
            "secid": f"{market}.{code}",
        },
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    return [
        ("股票简称", data.get("f58")),
        ("行业", data.get("f127")),
        ("上市时间", data.get("f189")),
        ("总股本", data.get("f84")),
    ]


def _parse_list_date(value: Any) -> str | None:
    """Normalize akshare's 上市时间 cell ("20010827") to an ISO date."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value).strip()
    if not text or text == "-":
        return None
    if "-" in text or "/" in text:
        text = text[:10]
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def profile_from_rows(
    symbol: str,
    rows: Sequence[tuple[str, Any]],
) -> CompanyProfile:
    """Map raw F10 item/value rows to a :class:`CompanyProfile`."""
    normalized = normalize_a_share_symbol(symbol)
    fields: dict[str, Any] = {}
    for item, value in rows:
        fields[str(item).strip()] = value

    def _as_float(value: Any) -> float | None:
        try:
            result = float(value)
        except (ValueError, TypeError):
            return None
        return result if result == result else None  # NaN guard

    return CompanyProfile(
        symbol=normalized,
        name=str(fields.get("股票简称") or "").strip() or None,
        industry=str(fields.get("行业") or "").strip() or None,
        list_date=_parse_list_date(fields.get("上市时间")),
        registered_capital=None,  # not provided by stock_individual_info_em
        total_shares=_as_float(fields.get("总股本")),
        updated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def fetch_company_profile(
    symbol: str,
    *,
    fetcher: ProfileFetcher | None = None,
) -> CompanyProfile:
    """Fetch basic F10 information (name/industry/list date/share capital)."""
    normalized = normalize_a_share_symbol(symbol)
    code = normalized.split(".", 1)[0]
    fetch = fetcher or _default_profile_fetcher
    try:
        rows = fetch(code)
    except WatchlistDataError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize to a typed error
        raise WatchlistDataError(f"基本信息接口请求失败: {exc}") from exc
    profile = profile_from_rows(normalized, list(rows))
    if not profile.name and not profile.industry:
        raise WatchlistDataError("基本信息接口未返回有效数据")
    return profile
