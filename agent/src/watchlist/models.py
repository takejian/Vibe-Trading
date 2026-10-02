"""Pydantic models for the watchlist module."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

#: Engineering-form A-share symbol: 6 digits + .SH / .SZ / .BJ.
A_SHARE_SYMBOL_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")

#: Analysis tab categories.
AnalysisCategory = Literal["fundamental", "technical", "general"]


class QuoteSnapshot(BaseModel):
    """Latest quote/valuation snapshot for one symbol."""

    price: float | None = None
    total_market_cap: float | None = None
    pe: float | None = None
    pb: float | None = None
    industry: str | None = None
    quote_updated_at: str | None = None


class WatchEntry(BaseModel):
    """One watched A-share instrument (personal, local-profile private)."""

    symbol: str
    name: str = ""
    industry: str | None = None
    added_at: str
    updated_at: str
    quote: QuoteSnapshot = Field(default_factory=QuoteSnapshot)


class CompanyProfile(BaseModel):
    """Basic instrument profile shown on the overview tab."""

    symbol: str
    name: str | None = None
    industry: str | None = None
    list_date: str | None = None  # ISO date
    registered_capital: float | None = None
    total_shares: float | None = None
    updated_at: str | None = None
