"""Tests for the objective_kline tool: local archive first, online fallback."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.tools.objective_kline_tool import ObjectiveKlineTool
from src.watchlist import db as watch_db
from src.watchlist import kline as watch_kline
import src.watchlist.kline as kline_mod


def _state(status: str, *, fetch_failed: bool = False, last_error=None):
    return {
        "interval": "1d",
        "status": status,
        "fetch_failed": fetch_failed,
        "last_error": last_error,
        "source": "eastmoney",
    }


def _bars(n: int):
    return [
        {
            "trade_date": f"2026-09-{i + 1:02d}",
            "open": 1.0,
            "high": 1.5,
            "low": 0.9,
            "close": 1.2,
            "volume": 100 + i,
            "amount": 1000 + i,
        }
        for i in range(n)
    ]


@pytest.fixture()
def patched(monkeypatch: pytest.MonkeyPatch):
    conn = SimpleNamespace(closed=False)

    def _close():
        conn.closed = True

    conn.close = _close
    monkeypatch.setattr(
        "src.tools.objective_kline_tool.watch_db.watchlist_connection",
        lambda: conn,
    )
    monkeypatch.setattr(
        "src.tools.objective_kline_tool.watch_db.initialize_schema",
        lambda c: None,
    )

    box = SimpleNamespace(states=[], bars=_bars(130), updates=[])

    def fake_states(symbol, c, *, today=None):
        return {"items": list(box.states), "market_ref": {}}

    def fake_update(symbol, intervals, c, *, source=watch_kline.DEFAULT_SOURCE):
        box.updates.append((symbol, list(intervals), source))
        return list(intervals)

    def fake_bars(symbol, interval, start=None, end=None, *, conn):
        return list(box.bars)

    monkeypatch.setattr(watch_kline, "list_level_states", fake_states)
    monkeypatch.setattr(watch_kline, "update_levels", fake_update)
    monkeypatch.setattr(watch_db, "list_kline_bars", fake_bars)
    return box, conn


def test_ready_archive_is_served_locally_without_online_fetch(patched):
    box, conn = patched
    box.states = [_state(watch_kline.READY)]

    payload = json.loads(ObjectiveKlineTool().execute(symbol="600519.SH"))

    assert payload["status"] == "ok"
    assert payload["fresh"] is True
    assert payload["refreshed"] is False
    assert payload["refresh_error"] is None
    assert payload["source"] == "eastmoney"
    assert payload["bars_count"] == 130
    assert payload["returned_bars"] == 130
    assert box.updates == []  # ready → never goes online
    assert conn.closed is True  # connection lifecycle respected


def test_stale_archive_triggers_one_online_refresh_then_readback(patched):
    box, _ = patched
    seen = {"n": 0}

    def states_then_ready(symbol, c, *, today=None):
        seen["n"] += 1
        status = watch_kline.INSUFFICIENT if seen["n"] == 1 else watch_kline.READY
        return {"items": [_state(status)], "market_ref": {}}

    original = kline_mod.list_level_states
    kline_mod.list_level_states = states_then_ready
    try:
        payload = json.loads(ObjectiveKlineTool().execute(symbol="600519.SH"))
    finally:
        kline_mod.list_level_states = original

    assert payload["status"] == "ok"
    assert payload["refreshed"] is True
    assert payload["fresh"] is True
    assert box.updates == [("600519.SH", ["1d"], watch_kline.DEFAULT_SOURCE)]


def test_refresh_never_uses_archive_even_when_stale(patched):
    box, _ = patched
    box.states = [_state(watch_kline.INSUFFICIENT)]

    payload = json.loads(
        ObjectiveKlineTool().execute(symbol="600519", interval="1d", refresh="never")
    )

    assert payload["status"] == "ok"
    assert payload["refreshed"] is False
    assert payload["fresh"] is False
    assert payload["level_status"] == watch_kline.INSUFFICIENT
    assert box.updates == []
    # Bare 6-digit code normalized to exchange suffix.
    assert payload["symbol"] == "600519.SH"


def test_refresh_always_forces_online_call_when_ready(patched):
    box, _ = patched
    box.states = [_state(watch_kline.READY)]

    payload = json.loads(
        ObjectiveKlineTool().execute(symbol="600519.SH", refresh="always")
    )

    assert payload["status"] == "ok"
    assert payload["refreshed"] is True
    assert len(box.updates) == 1


def test_no_bars_after_failed_refresh_is_explicit_error_not_fake_data(patched):
    box, _ = patched
    box.states = [
        _state(
            watch_kline.FAILED,
            fetch_failed=True,
            last_error="ConnectionError: reset by peer",
        )
    ]
    box.bars = []

    payload = json.loads(ObjectiveKlineTool().execute(symbol="600519.SH"))

    assert payload["status"] == "error"
    assert payload["bars"] == []
    assert "reset by peer" in payload["error"]
    assert payload["refreshed"] is True
    assert len(box.updates) == 1


def test_failed_refresh_keeps_old_bars_and_surfaces_refresh_error(patched):
    box, _ = patched
    box.bars = _bars(130)
    seen = {"n": 0}

    def states(symbol, c, *, today=None):
        seen["n"] += 1
        if seen["n"] == 1:
            return {"items": [_state(watch_kline.INSUFFICIENT)], "market_ref": {}}
        # Refresh failed but old bars survive: still insufficient with a
        # fetch_failed marker.
        return {
            "items": [
                _state(
                    watch_kline.INSUFFICIENT,
                    fetch_failed=True,
                    last_error="timeout",
                )
            ],
            "market_ref": {},
        }

    original = kline_mod.list_level_states
    kline_mod.list_level_states = states
    try:
        payload = json.loads(ObjectiveKlineTool().execute(symbol="600519.SH"))
    finally:
        kline_mod.list_level_states = original

    assert payload["status"] == "ok"
    assert payload["bars_count"] == 130  # old bars served, never fabricated
    assert payload["fresh"] is False
    assert payload["refresh_error"] == "timeout"


def test_limit_caps_returned_bars_in_ascending_order(patched):
    box, _ = patched
    box.states = [_state(watch_kline.READY)]
    box.bars = _bars(10)

    payload = json.loads(
        ObjectiveKlineTool().execute(symbol="600519.SH", limit=3)
    )

    assert payload["bars_count"] == 10
    assert payload["returned_bars"] == 3
    # Most recent 3 bars, still ascending.
    assert [b["trade_date"] for b in payload["bars"]] == [
        "2026-09-08",
        "2026-09-09",
        "2026-09-10",
    ]
    assert payload["earliest_bar_time"] == "2026-09-08"
    assert payload["latest_bar_time"] == "2026-09-10"


def test_invalid_interval_and_symbol_are_validation_errors(patched):
    box, _ = patched
    box.states = [_state(watch_kline.NOT_FETCHED)]

    bad_interval = json.loads(
        ObjectiveKlineTool().execute(symbol="600519.SH", interval="5m")
    )
    assert bad_interval["status"] == "error"
    assert "5m" in bad_interval["error"]
    assert box.updates == []

    bad_symbol = json.loads(ObjectiveKlineTool().execute(symbol="AAPL.US"))
    assert bad_symbol["status"] == "error"


def test_tool_is_registered_in_swarm_registry_for_chanlun_whitelist():
    from src.tools import build_swarm_registry

    registry = build_swarm_registry(
        [
            "bash",
            "read_file",
            "write_file",
            "load_skill",
            "objective_kline",
            "technical_indicators",
            "pattern",
        ]
    )
    assert registry.get("objective_kline") is not None
