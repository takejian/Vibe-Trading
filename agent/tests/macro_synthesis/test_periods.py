"""期次解析与归属判定测试。"""

from __future__ import annotations

from datetime import date

import pytest

from src.macro_synthesis.models import PERIOD_MONTH, PERIOD_QUARTER
from src.macro_synthesis.periods import (
    InvalidPeriodError,
    current_period,
    period_label,
    run_belongs,
    validate,
)


def test_current_month() -> None:
    assert current_period(PERIOD_MONTH, today=date(2026, 10, 9)) == "2026-10"


def test_current_quarter() -> None:
    assert current_period(PERIOD_QUARTER, today=date(2026, 1, 9)) == "2026-Q1"
    assert current_period(PERIOD_QUARTER, today=date(2026, 12, 9)) == "2026-Q4"


def test_period_label() -> None:
    assert period_label(PERIOD_MONTH, "2026-10") == "2026年10月"
    assert period_label(PERIOD_QUARTER, "2026-Q4") == "2026年第四季度"


@pytest.mark.parametrize(
    "period_type,period",
    [
        (PERIOD_MONTH, "2026-13"),
        (PERIOD_MONTH, "202610"),
        (PERIOD_QUARTER, "2026-Q5"),
        ("year", "2026"),
    ],
)
def test_invalid_period(period_type: str, period: str) -> None:
    with pytest.raises(InvalidPeriodError):
        validate(period_type, period)


def test_run_belongs_month() -> None:
    assert run_belongs("2026-10-08T10:00:00+00:00", PERIOD_MONTH, "2026-10")
    assert not run_belongs("2026-09-30T23:59:00+00:00", PERIOD_MONTH, "2026-10")


def test_run_belongs_quarter() -> None:
    assert run_belongs("2026-11-08T10:00:00Z", PERIOD_QUARTER, "2026-Q4")
    assert not run_belongs("2026-09-08T10:00:00Z", PERIOD_QUARTER, "2026-Q4")


def test_run_belongs_bad_input() -> None:
    assert not run_belongs(None, PERIOD_MONTH, "2026-10")
    assert not run_belongs("", PERIOD_MONTH, "2026-10")
