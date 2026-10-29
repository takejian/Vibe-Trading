"""Pydantic models for the watchlist module."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

#: Engineering-form A-share symbol: 6 digits + .SH / .SZ / .BJ.
A_SHARE_SYMBOL_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")

#: Analysis tab categories.
AnalysisCategory = Literal["fundamental", "technical", "general"]

#: System-reserved group ids — these cannot be renamed or deleted.
SYSTEM_GROUP_IDS = ("default", "canceled")

#: System-reserved group display names.
SYSTEM_GROUP_NAMES = {"default": "自选", "canceled": "取消"}

#: Default group for newly added entries.
DEFAULT_GROUP_ID = "default"

#: Group where canceled entries land.
CANCELED_GROUP_ID = "canceled"


class QuoteSnapshot(BaseModel):
    """Latest quote/valuation snapshot for one symbol."""

    price: float | None = None
    total_market_cap: float | None = None
    pe: float | None = None
    pb: float | None = None
    industry: str | None = None
    quote_updated_at: str | None = None


class WatchGroup(BaseModel):
    """One watchlist group — either system-reserved or user-defined."""

    id: str
    name: str
    system: bool = False  # True for "default" / "canceled"


class WatchEntry(BaseModel):
    """One watched A-share instrument (personal, local-profile private)."""

    symbol: str
    name: str = ""
    industry: str | None = None
    group_id: str = DEFAULT_GROUP_ID
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
