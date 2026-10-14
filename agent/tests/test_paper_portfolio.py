"""Tests for the simulated paper portfolio (service, calendar, routes).

All market data is faked; no network is used.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import paper_routes
from src.paper import calendar as cal
from src.paper import db as paper_db
from src.paper import prices, service
from src.paper.errors import PaperDataError, PaperError
from src.paper.service import FeePolicy

CN = ZoneInfo("Asia/Shanghai")

WED = datetime(2026, 10, 14, 10, 0, tzinfo=CN)   # 10:00 live
WED_PM = datetime(2026, 10, 14, 14, 0, tzinfo=CN)
THU = datetime(2026, 10, 15, 10, 0, tzinfo=CN)
FRI = datetime(2026, 10, 16, 10, 0, tzinfo=CN)
SUN_NIGHT = datetime(2026, 10, 18, 20, 0, tzinfo=CN)
MON_MORNING = datetime(2026, 10, 19, 8, 0, tzinfo=CN)
MON_LIVE = datetime(2026, 10, 19, 10, 0, tzinfo=CN)

SYMBOL = "600519.SH"


@pytest.fixture()
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "paper.duckdb"))
    paper_db.initialize_schema(c)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def policy(monkeypatch):
    p = FeePolicy(
        initial_capital=Decimal("100000"),
        commission_rate=Decimal("0.00025"),
        commission_min=Decimal("5"),
        stamp_tax_rate=Decimal("0.0005"),
        transfer_fee_rate=Decimal("0.00001"),
        refresh_enabled=True,
    )
    return p


class FakeStore:
    def __init__(self, watched=True):
        self._watched = watched

    def contains(self, symbol):
        return self._watched

    def get_entry(self, symbol):
        class _Entry:
            name = "贵州茅台"
        return _Entry()


def make_fetcher(prices_map):
    """Fake Eastmoney ulist JSON fetcher keyed by 6-digit code."""
    def _fetch(url, params):
        diff = [
            {"f2": px, "f12": code, "f14": f"股票{code}"}
            for code, px in prices_map.items()
        ]
        return {"data": {"diff": diff}}
    return _fetch


def fetcher_with(px):
    return make_fetcher({"600519": px})


def add_chanlun_row(c, *, score=3, confidence=0.8, text="三维买点共振"):
    c.execute(
        """
        CREATE TABLE chanlun_analysis (
            id VARCHAR, run_id VARCHAR, symbol VARCHAR, analyzed_at TIMESTAMP,
            dim7_chanlun_score VARCHAR, score INTEGER, confidence DOUBLE
        )
        """
    )
    c.execute(
        "INSERT INTO chanlun_analysis VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["id-1", "run-1", SYMBOL, datetime(2026, 10, 13, 9, 0), text,
         score, confidence],
    )


# ----------------------------------------------------------------------
# Fees
# ----------------------------------------------------------------------
def test_fees_commission_floor_and_stamp_only_on_sell(policy):
    comm, stamp, tf = service.calc_fees(policy, "buy", Decimal("1000"))
    assert (comm, stamp, tf) == (Decimal("5.00"), Decimal("0.00"),
                                 Decimal("0.01"))
    comm, stamp, tf = service.calc_fees(policy, "sell", Decimal("100000"))
    # 100000*0.025% = 25 (above floor); stamp 50; transfer 1
    assert (comm, stamp, tf) == (Decimal("25.00"), Decimal("50.00"),
                                 Decimal("1.00"))


@pytest.mark.parametrize("bad_qty", [0, -100, 150, 12.0, "100", True])
def test_validate_qty_rejects(policy, bad_qty):
    with pytest.raises(PaperError):
        service.validate_qty(bad_qty)


# ----------------------------------------------------------------------
# Buy
# ----------------------------------------------------------------------
def test_buy_after_hours_uses_close_price_and_dates_lot(conn, policy):
    res = service.buy(conn, SYMBOL, 100, now=SUN_NIGHT,
                      fetcher=fetcher_with(10.0),
                      watch_store=FakeStore(), policy=policy)
    order = res["order"]
    # Sunday night -> previous Friday close via weekday fallback.
    assert res["price_session"] == "close"
    assert res["price_trade_date"] == date(2026, 10, 16)
    assert order["price"] == 10.0
    assert (order["commission"], order["stamp_tax"],
            order["transfer_fee"]) == (5.0, 0.0, 0.01)

    acc = paper_db.get_account(conn)
    assert acc["cash_balance"] == pytest.approx(100000 - 1005.01)
    lots = paper_db.list_open_lots(conn)
    assert len(lots) == 1
    assert lots[0]["bought_on"] == date(2026, 10, 16)
    assert lots[0]["qty_remaining"] == 100


def test_buy_snapshots_latest_chanlun_score(conn, policy):
    add_chanlun_row(conn, score=4, confidence=0.9)
    res = service.buy(conn, SYMBOL, 100, now=WED, fetcher=fetcher_with(10.0),
                      watch_store=FakeStore(), policy=policy)
    order = res["order"]
    assert order["chanlun_run_id"] == "run-1"
    assert order["chanlun_score"] == 4
    assert order["chanlun_confidence"] == pytest.approx(0.9)
    assert order["chanlun_score_text"] == "三维买点共振"


def test_buy_without_chanlun_history_still_fills(conn, policy):
    res = service.buy(conn, SYMBOL, 100, now=WED, fetcher=fetcher_with(10.0),
                      watch_store=FakeStore(), policy=policy)
    assert res["order"]["chanlun_score"] is None


def test_buy_rejects_unwatched_symbol(conn, policy):
    with pytest.raises(PaperError, match="不在关注列表"):
        service.buy(conn, SYMBOL, 100, now=WED, fetcher=fetcher_with(10.0),
                    watch_store=FakeStore(watched=False), policy=policy)


def test_buy_rejects_insufficient_cash(conn, policy):
    with pytest.raises(PaperError, match="资金不足"):
        service.buy(conn, SYMBOL, 10000, now=WED,
                    fetcher=fetcher_with(50.0),
                    watch_store=FakeStore(), policy=policy)


def test_buy_raises_when_no_price_anywhere(conn, policy):
    with pytest.raises(PaperDataError):
        service.buy(conn, SYMBOL, 100, now=WED,
                    fetcher=make_fetcher({}),
                    watch_store=FakeStore(), policy=policy)


# ----------------------------------------------------------------------
# T+1 / FIFO sell
# ----------------------------------------------------------------------
def test_tplus_blocks_same_day_sell(conn, policy):
    service.buy(conn, SYMBOL, 100, now=WED, fetcher=fetcher_with(10.0),
                watch_store=FakeStore(), policy=policy)
    with pytest.raises(PaperError, match=r"T\+1"):
        service.sell(conn, SYMBOL, 100, now=WED_PM,
                     fetcher=fetcher_with(10.5), policy=policy)


def test_monday_preopen_buy_is_t1_sellable_monday_open(conn, policy):
    # Bought Monday 08:00 at Friday close -> lot dated Friday -> sellable Mon.
    service.buy(conn, SYMBOL, 100, now=MON_MORNING,
                fetcher=fetcher_with(10.0),
                watch_store=FakeStore(), policy=policy)
    res = service.sell(conn, SYMBOL, 100, now=MON_LIVE,
                       fetcher=fetcher_with(11.0), policy=policy)
    assert res["price_session"] == "live"
    assert res["order"]["stamp_tax"] == pytest.approx(0.55)
    assert res["closes"][0]["realized_pnl"] == pytest.approx(89.43)


def test_fifo_partial_sell_across_two_lots(conn, policy):
    service.buy(conn, SYMBOL, 100, now=WED, fetcher=fetcher_with(10.0),
                watch_store=FakeStore(), policy=policy)
    service.buy(conn, SYMBOL, 100, now=THU, fetcher=fetcher_with(11.0),
                watch_store=FakeStore(), policy=policy)
    # Sell 100 on Friday: FIFO must consume Wednesday's lot.
    res = service.sell(conn, SYMBOL, 100, now=FRI,
                       fetcher=fetcher_with(12.0), policy=policy)
    assert len(res["closes"]) == 1
    close = res["closes"][0]
    # proceeds = 1200 - (5 + 0.6 + 0.01) = 1194.39; cost = 1005.01
    assert close["realized_pnl"] == pytest.approx(189.38)

    remaining = paper_db.list_open_lots(conn)
    assert len(remaining) == 1
    assert remaining[0]["qty_remaining"] == 100
    assert remaining[0]["bought_on"] == date(2026, 10, 15)

    pos = service.positions(conn, now=FRI, policy=policy)
    assert pos["items"][0]["qty"] == 100
    assert pos["items"][0]["avg_cost"] == pytest.approx(11.05)


def test_sell_cannot_exceed_sellable_quantity(conn, policy):
    service.buy(conn, SYMBOL, 100, now=WED, fetcher=fetcher_with(10.0),
                watch_store=FakeStore(), policy=policy)
    with pytest.raises(PaperError, match="可卖"):
        service.sell(conn, SYMBOL, 200, now=THU,
                     fetcher=fetcher_with(11.0), policy=policy)


# ----------------------------------------------------------------------
# Aggregation / reset / refresh
# ----------------------------------------------------------------------
def test_account_identity_and_positions_return(conn, policy):
    service.buy(conn, SYMBOL, 100, now=SUN_NIGHT, fetcher=fetcher_with(10.0),
                watch_store=FakeStore(), policy=policy)
    # Monday live price 11 -> refresh marks to market.
    count = service.refresh_quotes(conn, now=MON_LIVE,
                                   fetcher=fetcher_with(11.0), policy=policy)
    assert count == 1
    acc = service.account(conn, now=MON_LIVE, policy=policy)
    assert acc["cash"] + acc["market_value"] == pytest.approx(
        acc["total_asset"], abs=0.001)
    assert acc["market_value"] == pytest.approx(1100.0)
    item = service.positions(conn, now=MON_LIVE, policy=policy)["items"][0]
    assert item["return_pct"] == pytest.approx(0.09452, abs=1e-4)
    assert item["unrealized_pnl"] == pytest.approx(94.99)


def test_reset_restores_initial_cash(conn, policy):
    service.buy(conn, SYMBOL, 100, now=WED, fetcher=fetcher_with(10.0),
                watch_store=FakeStore(), policy=policy)
    service.reset(conn, now=WED_PM, policy=policy)
    acc = paper_db.get_account(conn)
    assert acc["cash_balance"] == 100000
    assert paper_db.open_position_symbols(conn) == []
    assert paper_db.list_orders(conn) == []


# ----------------------------------------------------------------------
# Calendar
# ----------------------------------------------------------------------
def cal_conn(tmp_path, rows):
    c = duckdb.connect(str(tmp_path / "cal.duckdb"))
    c.execute(
        "CREATE TABLE trading_calendar "
        "(market VARCHAR, cal_date DATE, is_open BOOLEAN)"
    )
    c.executemany("INSERT INTO trading_calendar VALUES ('a_share', ?, ?)",
                  rows)
    return c


def test_market_clock_sessions(tmp_path):
    # No calendar table -> weekday heuristic.
    c = duckdb.connect(str(tmp_path / "empty.duckdb"))
    clock = cal.market_clock(c, now=WED)
    assert clock.is_live and clock.trade_date == date(2026, 10, 14)
    assert cal.market_clock(c, now=datetime(2026, 10, 14, 11, 45,
                                            tzinfo=CN)).is_live is False
    assert cal.market_clock(c, now=datetime(2026, 10, 14, 9, 0,
                                            tzinfo=CN)).trade_date == \
        date(2026, 10, 13)
    assert cal.market_clock(c, now=SUN_NIGHT).trade_date == date(2026, 10, 16)
    c.close()


def test_calendar_holiday_and_due_anchors(tmp_path):
    tue, wed = date(2026, 10, 13), date(2026, 10, 14)
    c = cal_conn(tmp_path, [(tue, True), (wed, False)])  # Wed holiday
    clock = cal.market_clock(c, now=datetime(2026, 10, 14, 10, 0,
                                             tzinfo=CN))
    assert clock.is_trading_day is False and clock.is_live is False
    assert clock.trade_date == tue

    executed: set = set()
    due = cal.due_anchors(
        c, now=datetime(2026, 10, 13, 11, 31, tzinfo=CN),
        executed=executed)
    assert due == [time(11, 30)]
    # Beyond the 5-minute grace -> treated as already executed, no backfill.
    late = cal.due_anchors(
        c, now=datetime(2026, 10, 13, 11, 36, tzinfo=CN))
    assert late == []
    # Holiday -> nothing due even at anchor time.
    assert cal.due_anchors(
        c, now=datetime(2026, 10, 14, 15, 1, tzinfo=CN)) == []
    c.close()


# ----------------------------------------------------------------------
# Routes (TestClient, no auth key configured)
# ----------------------------------------------------------------------
def test_paper_routes_end_to_end(tmp_path, monkeypatch):
    db_file = str(tmp_path / "route.duckdb")

    def _connect(*_args, **_kwargs):
        c = duckdb.connect(db_file)
        paper_db.initialize_schema(c)
        return c

    monkeypatch.setattr(paper_routes.paper_db, "paper_connection", _connect)
    monkeypatch.setattr(service, "_default_membership", lambda: FakeStore())
    monkeypatch.setattr(
        prices.watch_market, "fetch_quote_snapshots",
        lambda symbols, fetcher=None: {
            "600519.SH": _quote(10.0),
        },
    )

    app = FastAPI()
    paper_routes.register_paper_routes(app)
    client = TestClient(app)

    assert client.get("/api/paper/account").json()["cash"] == 100000
    r = client.post("/api/paper/buy", json={"symbol": SYMBOL, "qty": 100})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order"]["side"] == "buy"

    # Bad qty maps to 400.
    bad = client.post("/api/paper/buy", json={"symbol": SYMBOL, "qty": 150})
    assert bad.status_code == 400

    positions = client.get("/api/paper/positions").json()
    assert positions["items"][0]["symbol"] == SYMBOL
    nav = client.get("/api/paper/nav?range=all").json()
    assert len(nav["items"]) >= 1


def _quote(px):
    from src.watchlist.models import QuoteSnapshot
    return QuoteSnapshot(price=px)


# ----------------------------------------------------------------------
# K-line sync at the 11:30 / 15:00 anchors (Chanlun bars)
# ----------------------------------------------------------------------
def _kline_fetcher(daily_rows, minute_rows=None, fail_klt=()):
    """Fake Eastmoney push2his fetcher keyed by klt (101 day / 30 30m)."""
    minute_rows = minute_rows or []

    def _fetch(secid, klt, beg, end):
        if klt in fail_klt:
            from src.watchlist.market import WatchlistDataError
            raise WatchlistDataError(f"klt {klt} unavailable")
        if klt == 101:
            return list(daily_rows)
        if klt == 30:
            return list(minute_rows)
        return []

    return _fetch


def _open_one_lot(conn, pol):
    service.buy(conn, SYMBOL, 100, now=SUN_NIGHT,
                fetcher=fetcher_with(10.0),
                watch_store=FakeStore(), policy=pol)


def test_sync_klines_no_positions_makes_no_calls(conn, policy):
    calls = []

    def _fetcher(*args):
        calls.append(args)
        return []

    assert service.sync_position_klines(conn, fetcher=_fetcher) == {}
    assert calls == []


def test_sync_klines_replaces_same_day_half_session_bar(conn, policy):
    _open_one_lot(conn, policy)
    day = date(2026, 10, 16)

    # 11:30 anchor: today's daily bar only covers the morning session.
    morning = [
        {"trade_date": "2026-10-15", "open": 9.8, "high": 10.1,
         "low": 9.7, "close": 10.0, "volume": 1000, "amount": 10000.0},
        {"trade_date": "2026-10-16", "open": 10.0, "high": 10.4,
         "low": 9.95, "close": 10.3, "volume": 400, "amount": 4120.0},
    ]
    minutes = [
        {"trade_date": "2026-10-16 10:00", "open": 10.0, "high": 10.2,
         "low": 9.95, "close": 10.1, "volume": 200, "amount": 2020.0},
        {"trade_date": "2026-10-16 10:30", "open": 10.1, "high": 10.4,
         "low": 10.05, "close": 10.3, "volume": 200, "amount": 2100.0},
    ]
    done = service.sync_position_klines(
        conn, intervals=("1d", "30m"),
        fetcher=_kline_fetcher(morning, minutes), today=day,
    )
    assert set(done[SYMBOL]) == {"1d", "30m"}

    rows = conn.execute(
        "SELECT interval, bar_time, close FROM watch_kline_bar "
        "ORDER BY interval, bar_time"
    ).fetchall()
    assert ("1d", "2026-10-16", 10.3) in rows
    assert ("30m", "2026-10-16 10:30", 10.3) in rows

    # 15:00 anchor: full-session daily bar replaces the 11:30 bar in place.
    full_day = [
        {"trade_date": "2026-10-15", "open": 9.8, "high": 10.1,
         "low": 9.7, "close": 10.0, "volume": 1000, "amount": 10000.0},
        {"trade_date": "2026-10-16", "open": 10.0, "high": 10.6,
         "low": 9.95, "close": 10.5, "volume": 900, "amount": 9450.0},
    ]
    service.sync_position_klines(
        conn, intervals=("1d",),
        fetcher=_kline_fetcher(full_day), today=day,
    )
    daily = conn.execute(
        "SELECT bar_time, close, high, volume FROM watch_kline_bar "
        "WHERE interval = '1d' ORDER BY bar_time"
    ).fetchall()
    # No duplicate row for the same day; half-session values replaced.
    assert daily == [
        ("2026-10-15", 10.0, 10.1, 1000.0),
        ("2026-10-16", 10.5, 10.6, 900.0),
    ]


def test_sync_klines_one_level_failure_keeps_others(conn, policy):
    _open_one_lot(conn, policy)
    daily = [
        {"trade_date": "2026-10-16", "open": 10.0, "high": 10.4,
         "low": 9.95, "close": 10.3, "volume": 400, "amount": 4120.0},
    ]
    service.sync_position_klines(
        conn, intervals=("1d", "30m"),
        fetcher=_kline_fetcher(daily, fail_klt=(30,)),
        today=date(2026, 10, 16),
    )
    # Daily bars persisted despite 30m failure...
    daily_count = conn.execute(
        "SELECT count(*) FROM watch_kline_bar WHERE interval = '1d'"
    ).fetchone()[0]
    assert daily_count == 1
    # ...and the failed level is recorded without deleting anything.
    status = conn.execute(
        "SELECT last_error IS NOT NULL FROM watch_kline_fetch_status "
        "WHERE interval = '30m'"
    ).fetchone()
    assert status == (True,)
