"""Paper portfolio error types (mapped to HTTP statuses by the route layer)."""

from __future__ import annotations


class PaperError(ValueError):
    """Business-rule violation (bad qty, insufficient cash, T+1) -> HTTP 400."""


class PaperDataError(RuntimeError):
    """Market price unavailable from every source -> HTTP 502."""
