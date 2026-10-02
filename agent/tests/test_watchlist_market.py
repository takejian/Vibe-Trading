"""Offline unit tests for the direct A-share market data services."""

from __future__ import annotations

import pytest

from src.watchlist.market import (
    WatchlistDataError,
    fetch_company_profile,
    fetch_quote_snapshots,
    normalize_a_share_symbol,
    profile_from_rows,
    search_a_shares,
    to_eastmoney_secid,
)
from src.watchlist.store import WatchlistError


# ----------------------------------------------------------------------
# Symbol normalization
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("600519", "600519.SH"),
        ("sh600519", "600519.SH"),
        ("600519.sh", "600519.SH"),
        ("000001", "000001.SZ"),
        ("300750", "300750.SZ"),
        ("920819", "920819.BJ"),
        ("430047", "430047.BJ"),
        ("835185", "835185.BJ"),
    ],
)
def test_normalize_accepted_forms(raw: str, expected: str) -> None:
    assert normalize_a_share_symbol(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "ABC", "12345", "AAPL.US", "600519.XX", "500519", "200002", "900901"],
)
def test_normalize_rejected_forms(raw: str) -> None:
    with pytest.raises(WatchlistError):
        normalize_a_share_symbol(raw)


def test_to_eastmoney_secid() -> None:
    assert to_eastmoney_secid("600519.SH") == "1.600519"
    assert to_eastmoney_secid("000001.SZ") == "0.000001"
    assert to_eastmoney_secid("835185.BJ") == "0.835185"


# ----------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------
def _suggest_payload() -> dict:
    return {
        "QuotationCodeTable": {
            "Data": [
                {"Code": "600519", "Name": "贵州茅台", "MktNum": "1"},
                {"Code": "000001", "Name": "平安银行", "MktNum": "0"},
                {"Code": "430047", "Name": "诺思兰德", "MktNum": "0"},
                {"Code": "600519", "Name": "贵州茅台-dup", "MktNum": "1"},
                {"Code": "00700", "Name": "腾讯控股", "MktNum": "116"},
                {"Code": "AAPL", "Name": "Apple", "MktNum": "105"},
            ]
        }
    }


def test_search_filters_to_a_share_and_dedups() -> None:
    calls: list[tuple[str, dict]] = []

    def fake_fetch(url: str, params: dict) -> dict:
        calls.append((url, params))
        return _suggest_payload()

    results = search_a_shares("茅台", fetcher=fake_fetch)
    assert [r["symbol"] for r in results] == [
        "600519.SH",
        "000001.SZ",
        "430047.BJ",
    ]
    assert all(r["industry"] == "" for r in results)
    assert calls[0][1]["input"] == "茅台"


def test_search_empty_keyword_skips_network() -> None:
    def boom(url: str, params: dict) -> dict:
        raise AssertionError("network must not be touched")

    assert search_a_shares("  ", fetcher=boom) == []


def test_search_handles_empty_payload_and_network_error() -> None:
    assert search_a_shares("xx", fetcher=lambda u, p: {"QuotationCodeTable": None}) == []

    def failing(url: str, params: dict) -> dict:
        raise ConnectionError("boom")

    with pytest.raises(WatchlistDataError):
        search_a_shares("xx", fetcher=failing)


# ----------------------------------------------------------------------
# Quote snapshots
# ----------------------------------------------------------------------
def test_fetch_quote_snapshots_one_batch_with_sentinels() -> None:
    captured: list[dict] = []

    def fake_fetch(url: str, params: dict) -> dict:
        captured.append(params)
        return {
            "data": {
                "diff": [
                    {"f12": "600519", "f14": "贵州茅台", "f2": 1500.0,
                     "f9": 25.6, "f20": 1.88e12, "f23": 8.1, "f100": "白酒"},
                    {"f12": "000001", "f14": "平安银行", "f2": "-",
                     "f9": "-", "f20": "-", "f23": "-", "f100": "-"},
                ]
            }
        }

    result = fetch_quote_snapshots(["600519.SH", "000001.SZ"], fetcher=fake_fetch)
    moutai = result["600519.SH"]
    assert moutai.price == 1500.0
    assert moutai.pe == 25.6
    assert moutai.pb == 8.1
    assert moutai.total_market_cap == 1.88e12
    assert moutai.industry == "白酒"
    halted = result["000001.SZ"]
    assert halted.price is None and halted.pe is None and halted.industry is None

    assert len(captured) == 1  # single batched request
    assert captured[0]["secids"] == "1.600519,0.000001"


def test_fetch_quote_snapshots_dict_diff_and_missing_rows() -> None:
    payload = {"data": {"diff": {"0": {"f12": "430047", "f2": 12.3, "f9": 40.0,
                                      "f20": 2e9, "f23": 2.0, "f100": "生物"}}}}
    result = fetch_quote_snapshots(["430047.BJ", "835185.BJ"], fetcher=lambda u, p: payload)
    assert "430047.BJ" in result
    assert "835185.BJ" not in result  # API simply omitted it


def test_fetch_quote_snapshots_empty_input_and_failure() -> None:
    assert fetch_quote_snapshots([], fetcher=lambda u, p: {}) == {}
    with pytest.raises(WatchlistDataError):
        fetch_quote_snapshots(["600519.SH"], fetcher=lambda u, p: (_ for _ in ()).throw(TimeoutError()))


# ----------------------------------------------------------------------
# Company profile
# ----------------------------------------------------------------------
def _profile_rows():
    return [
        ("股票简称", "贵州茅台"),
        ("股票代码", "600519"),
        ("上市时间", "20010827"),
        ("行业", "白酒"),
        ("总股本", 1.256e9),
    ]


def test_profile_from_rows_mapping() -> None:
    profile = profile_from_rows("600519", _profile_rows())
    assert profile.symbol == "600519.SH"
    assert profile.name == "贵州茅台"
    assert profile.industry == "白酒"
    assert profile.list_date == "2001-08-27"
    assert profile.total_shares == 1.256e9
    assert profile.registered_capital is None
    assert profile.updated_at is not None


def test_fetch_company_profile_success_and_empty_payload() -> None:
    profile = fetch_company_profile(
        "sh600519",
        fetcher=lambda code: _profile_rows() if code == "600519" else [],
    )
    assert profile.name == "贵州茅台"

    with pytest.raises(WatchlistDataError):
        fetch_company_profile("600519.SH", fetcher=lambda code: [("无关项", "x")])


def test_fetch_company_profile_network_failure() -> None:
    def failing(code: str):
        raise RuntimeError("akshare down")

    with pytest.raises(WatchlistDataError):
        fetch_company_profile("600519.SH", fetcher=failing)


def test_default_profile_fetcher_uses_stock_get_payload(monkeypatch) -> None:
    """The default fetcher maps the real stock/get field shape end to end."""
    import backtest.loaders.eastmoney_client as em_client

    calls: list[tuple[str, dict]] = []

    def fake_get_json(url: str, params: dict):
        calls.append((url, params))
        assert url.endswith("/api/qt/stock/get")
        return {"data": {"f57": "600519", "f58": "贵州茅台", "f84": 1.2500816e9,
                         "f127": "白酒Ⅱ", "f189": 20010827}}

    monkeypatch.setattr(em_client, "get_json", fake_get_json)
    profile = fetch_company_profile("600519")
    assert profile.symbol == "600519.SH"
    assert profile.name == "贵州茅台"
    assert profile.industry == "白酒Ⅱ"
    assert profile.list_date == "2001-08-27"
    assert profile.total_shares == 1.2500816e9
    assert calls[0][1]["secid"] == "1.600519"


def test_default_profile_fetcher_empty_data_raises(monkeypatch) -> None:
    import backtest.loaders.eastmoney_client as em_client

    monkeypatch.setattr(
        em_client, "get_json", lambda url, params: {"data": None}
    )
    with pytest.raises(WatchlistDataError):
        fetch_company_profile("600519.SH")
