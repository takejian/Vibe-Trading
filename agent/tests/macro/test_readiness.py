"""Economy list, month derivation and readiness assessment tests."""

from __future__ import annotations

import datetime as dt

import pytest

from src.macro.models import DataReadiness
from src.macro.readiness import (
    CONFIRMED,
    INSUFFICIENT,
    UNKNOWN,
    DefaultMacroProbe,
    PRESET_ECONOMIES,
    ReadinessAssessor,
    canonicalize_economy,
    latest_available_month,
)

from .conftest import FIXED_TODAY, ScriptedProbe, build_assessor


def test_preset_economies():
    assert PRESET_ECONOMIES == ("中国", "美国", "日本", "欧元区")


def test_latest_available_month_uses_previous_calendar_month():
    assert latest_available_month(dt.date(2026, 9, 24)) == "2026-08"
    assert latest_available_month(dt.date(2026, 1, 5)) == "2025-12"
    assert latest_available_month(dt.date(2026, 3, 31)) == "2026-02"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("中国", "中国"),
        ("china", "中国"),
        ("CN", "中国"),
        ("美国", "美国"),
        ("Japan", "日本"),
        ("Eurozone", "欧元区"),
        ("巴西", None),
        ("", None),
    ],
)
def test_canonicalize(raw, expected):
    assert canonicalize_economy(raw) == expected


def test_confirmed_probe_readies_with_calendar_month():
    readiness = build_assessor(ScriptedProbe(CONFIRMED)).assess("中国")
    assert readiness.ready is True
    assert readiness.latest_month == "2026-08"
    assert readiness.reason is None


def test_unknown_probe_degrades_to_ready():
    readiness = build_assessor(ScriptedProbe(UNKNOWN)).assess("美国")
    assert readiness.ready is True
    assert readiness.latest_month == "2026-08"


def test_insufficient_probe_blocks():
    readiness = build_assessor(ScriptedProbe(INSUFFICIENT)).assess("日本")
    assert readiness.ready is False
    assert "数据不足" in readiness.reason
    assert readiness.latest_month == "2026-08"


def test_unsupported_economy_is_insufficient():
    readiness = build_assessor().assess("巴西")
    assert isinstance(readiness, DataReadiness)
    assert readiness.ready is False


def test_default_probe_swallows_failures_to_unknown():
    def raising_provider(_economy: str):
        raise RuntimeError("network down")

    # A raising injected China provider degrades to UNKNOWN -> ready.
    probe = DefaultMacroProbe(akshare_provider=raising_provider)
    assessor = ReadinessAssessor(probe, today_provider=lambda: FIXED_TODAY)
    assert probe.probe("中国") == UNKNOWN
    assert assessor.assess("中国").ready is True

    # FRED path with no API key short-circuits to UNKNOWN without sockets.
    probe_us = DefaultMacroProbe()
    assert probe_us.probe("美国") == UNKNOWN


def test_freshness_threshold():
    from src.macro.readiness import _is_fresh_enough

    today = dt.date(2026, 9, 24)
    assert _is_fresh_enough("2026-08", today=today)
    assert _is_fresh_enough("2026-07", today=today)
    assert not _is_fresh_enough("2026-06", today=today)
