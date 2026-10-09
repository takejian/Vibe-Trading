"""Tests for deterministic post-hoc verification of Chanlun action cards."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from src.watchlist import db as watch_db
from src.watchlist import outcome

_DIMS = {
    "structure_read": "s1",
    "active_pivots": "s2",
    "divergence": "s3",
    "buy_sell_points": "s4",
    "multi_level_plan": "s5",
    "elliott_corroboration": "s6",
    "chanlun_score": "打分：+3",
}

_BASE = date(2026, 9, 1)
_DATES = [
    "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-07",
    "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
    "2026-09-14", "2026-09-15", "2026-09-16",
]


def _card(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "base_price": 10.0,
        "base_date": "2026-09-01",
        "direction": "bullish",
        "action": "buy",
        "confidence_pct": 60.0,
        "setup_class": "3买",
        "horizon_days": 10,
        "trigger_price": 10.2,
        "stop_price": 9.8,
        "target_prices": [10.8],
        "rr_at_t1": 1.5,
        "invalidation": "破9.8",
        "key_risks": "",
        "one_liner": "三买",
    }
    base.update(overrides)
    return base


def _bar(day: str, close: float, *, high: float | None = None,
         low: float | None = None, open_: float | None = None) -> dict:
    return {
        "trade_date": day,
        "open": open_ if open_ is not None else close,
        "high": high if high is not None else close,
        "low": low if low is not None else close,
        "close": close,
        "volume": 100.0,
    }


@pytest.fixture()
def conn(tmp_path):
    connection = watch_db.watchlist_connection(tmp_path / "o.duckdb")
    watch_db.initialize_schema(connection)
    # Base-day bar plus flat filler bars.
    bars = [_bar("2026-09-01", 10.0)]
    watch_db.upsert_kline_bars(
        "600519.SH", "1d", bars, source="test", conn=connection
    )
    yield connection
    connection.close()


def _seed(conn, run_id: str, card: dict) -> dict:
    watch_db.insert_chanlun_record(
        run_id=run_id, symbol="600519.SH", conn=conn,
        dims=_DIMS, score=3, confidence=0.6, structured=True,
        raw_report="report", analyzed_at=datetime(2026, 9, 1, 6, 0, 0),
        card=card, card_parse="ok",
    )
    return next(
        r for r in watch_db.list_chanlun_records("600519.SH", conn)
        if r["run_id"] == run_id
    )


def _joined(conn) -> list[dict]:
    outcomes = {o["run_id"]: o for o in watch_db.list_chanlun_outcomes("600519.SH", conn)}
    rows = []
    for row in watch_db.list_chanlun_records("600519.SH", conn):
        merged = dict(row)
        merged.update(outcomes.get(row["run_id"], {}))
        rows.append(merged)
    return rows


def test_bullish_target_first_is_win(conn) -> None:
    bars = [_bar(_DATES[0], 10.1, high=10.3, low=10.0)]
    for day in _DATES[1:4]:
        bars.append(_bar(day, 10.2))
    bars.append(_bar(_DATES[4], 10.9, high=10.95, low=10.15))
    for day in _DATES[5:]:
        bars.append(_bar(day, 10.9))
    watch_db.upsert_kline_bars("600519.SH", "1d", bars, source="test", conn=conn)

    row = _seed(conn, "r-win", _card())
    result = outcome.evaluate_card_row(row, conn, today=date(2026, 9, 20))
    assert result["eval_status"] == outcome.EVAL_VERIFIED
    assert result["outcome_label"] == outcome.WIN
    assert result["first_event"] == "target_first"
    assert result["target_hit"] is True
    assert result["stop_hit"] is False
    assert result["mfe_pct"] > 5
    assert result["direction_correct"] is True


def test_stop_first_is_loss_with_same_bar_conservative_booking(conn) -> None:
    # Trigger and stop touched on the same post-base bar -> stop booked.
    bars = [_bar(_DATES[0], 10.0, open_=10.25, high=10.3, low=9.7)]
    for day in _DATES[1:]:
        bars.append(_bar(day, 9.9))
    watch_db.upsert_kline_bars("600519.SH", "1d", bars, source="test", conn=conn)

    row = _seed(conn, "r-loss", _card())
    result = outcome.evaluate_card_row(row, conn, today=date(2026, 9, 20))
    assert result["outcome_label"] == outcome.LOSS
    assert result["first_event"] == "stop_first"


def test_timeout_wrong_when_end_close_below_trigger(conn) -> None:
    bars = [_bar(_DATES[0], 10.25, high=10.3, low=10.1)]
    for day in _DATES[1:]:
        bars.append(_bar(day, 10.1, high=10.25, low=9.95))
    watch_db.upsert_kline_bars("600519.SH", "1d", bars, source="test", conn=conn)

    row = _seed(conn, "r-to", _card())
    result = outcome.evaluate_card_row(row, conn, today=date(2026, 9, 20))
    assert result["outcome_label"] == outcome.TIMEOUT_WRONG
    assert result["direction_correct"] is False
    assert result["exit_return_pct"] < 0


def test_bearish_target_first_is_win(conn) -> None:
    card = _card(
        direction="bearish", action="sell", setup_class="1卖",
        trigger_price=9.8, stop_price=10.2, target_prices=[9.2],
    )
    bars = [_bar(_DATES[0], 9.9, high=10.0, low=9.7)]
    for day in _DATES[1:4]:
        bars.append(_bar(day, 9.8))
    bars.append(_bar(_DATES[4], 9.1, high=9.8, low=9.05))
    for day in _DATES[5:]:
        bars.append(_bar(day, 9.1))
    watch_db.upsert_kline_bars("600519.SH", "1d", bars, source="test", conn=conn)

    row = _seed(conn, "r-short", card)
    result = outcome.evaluate_card_row(row, conn, today=date(2026, 9, 20))
    assert result["outcome_label"] == outcome.WIN
    assert result["mfe_pct"] > 5


def test_neutral_card_verified_without_bars(conn) -> None:
    row = _seed(
        conn, "r-neutral",
        _card(direction="neutral", action="wait", setup_class="none",
              trigger_price=None, stop_price=None, target_prices=None,
              rr_at_t1=None),
    )
    result = outcome.evaluate_card_row(row, conn, today=date(2026, 9, 20))
    assert result["eval_status"] == outcome.EVAL_VERIFIED
    assert result["outcome_label"] == outcome.NEUTRAL


def test_pending_then_verified_after_more_bars(conn) -> None:
    # Only 3 post-base bars; still early -> pending.
    watch_db.upsert_kline_bars(
        "600519.SH", "1d", [_bar(d, 10.1) for d in _DATES[:3]],
        source="test", conn=conn,
    )
    row = _seed(conn, "r-pend", _card())
    early = outcome.evaluate_card_row(row, conn, today=_BASE + timedelta(days=5))
    assert early["eval_status"] == outcome.EVAL_PENDING

    # Well past the window but still only 3 bars -> insufficient data.
    late = outcome.evaluate_card_row(row, conn, today=_BASE + timedelta(days=40))
    assert late["eval_status"] == outcome.EVAL_INSUFFICIENT


def test_refresh_due_and_summarize(conn) -> None:
    # Win + neutral together -> one decided win, stats aggregate.
    win_bars = [_bar(_DATES[0], 10.1, high=10.3, low=10.0)]
    for day in _DATES[1:4]:
        win_bars.append(_bar(day, 10.2))
    win_bars.append(_bar(_DATES[4], 10.9, high=10.95, low=10.15))
    for day in _DATES[5:]:
        win_bars.append(_bar(day, 10.9))
    watch_db.upsert_kline_bars("600519.SH", "1d", win_bars, source="test", conn=conn)
    _seed(conn, "r1", _card())
    _seed(conn, "r2", _card(direction="neutral", action="wait", setup_class="none",
                            trigger_price=None, stop_price=None,
                            target_prices=None, rr_at_t1=None))

    written = outcome.refresh_due("600519.SH", conn, today=date(2026, 9, 20))
    assert written == 2
    # Idempotent: second sweep writes nothing.
    assert outcome.refresh_due("600519.SH", conn, today=date(2026, 9, 20)) == 0

    stats = outcome.summarize(_joined(conn))
    assert stats["cards_total"] == 2
    assert stats["verified_decided"] == 1
    assert stats["wins"] == 1
    assert stats["win_rate"] == 100.0
    assert stats["neutral"] == 1


def test_user_rating_counts_separately_from_machine_outcome(conn) -> None:
    win_bars = [_bar(_DATES[0], 10.1, high=10.3, low=10.0)]
    for day in _DATES[1:4]:
        win_bars.append(_bar(day, 10.2))
    win_bars.append(_bar(_DATES[4], 10.9, high=10.95, low=10.15))
    for day in _DATES[5:]:
        win_bars.append(_bar(day, 10.9))
    watch_db.upsert_kline_bars("600519.SH", "1d", win_bars, source="test", conn=conn)
    _seed(conn, "r1", _card())
    outcome.refresh_due("600519.SH", conn, today=date(2026, 9, 20))
    # Investor disagrees with the machine win.
    watch_db.set_user_rating(
        run_id="r1", symbol="600519.SH", verdict="wrong",
        note="走势犹豫", conn=conn,
    )
    stats = outcome.summarize(_joined(conn))
    assert stats["ratings"]["wrong"] == 1
    assert stats["wins"] == 1


def test_current_status_transitions(conn) -> None:
    # Before trigger, horizon not elapsed.
    watch_db.upsert_kline_bars(
        "600519.SH", "1d", [_bar(d, 10.0, high=10.1) for d in _DATES[:3]],
        source="test", conn=conn,
    )
    row = _seed(conn, "r-s1", _card(trigger_price=10.9))
    assert outcome.current_status(row, conn, today=_BASE + timedelta(days=5)) == outcome.LIVE_WAITING

    # Triggered (bar 1 high 10.3) but no target/stop yet -> active.
    watch_db.upsert_kline_bars(
        "600519.SH", "1d",
        [_bar(_DATES[0], 10.1, high=10.3, low=10.0)]
        + [_bar(d, 10.15, high=10.35, low=9.95) for d in _DATES[1:3]],
        source="test", conn=conn,
    )
    row = _seed(conn, "r-s2", _card())
    assert outcome.current_status(row, conn, today=_BASE + timedelta(days=5)) == outcome.LIVE_ACTIVE

    # Full path that reaches T1 -> target_hit.
    win_bars = [_bar(_DATES[0], 10.1, high=10.3, low=10.0)]
    for day in _DATES[1:4]:
        win_bars.append(_bar(day, 10.2))
    win_bars.append(_bar(_DATES[4], 10.9, high=10.95, low=10.15))
    for day in _DATES[5:]:
        win_bars.append(_bar(day, 10.9))
    watch_db.upsert_kline_bars("600519.SH", "1d", win_bars, source="test", conn=conn)
    row = _seed(conn, "r-s3", _card())
    assert outcome.current_status(row, conn, today=date(2026, 9, 20)) == outcome.LIVE_TARGET
