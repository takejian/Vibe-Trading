"""Custom exceptions for the gold monitor module."""

from __future__ import annotations


class GoldMonitorError(Exception):
    """Base exception for gold monitor module errors."""


class GoldDataError(GoldMonitorError):
    """Raised when data is missing, malformed, or inconsistent."""


class GoldLLMError(GoldMonitorError):
    """Raised when the LLM data-fetch call fails or returns incomplete data."""


class GoldCycleDetectError(GoldMonitorError):
    """Raised when cycle auto-detection cannot run (insufficient history, etc.)."""


class GoldValidationError(GoldMonitorError):
    """Raised when LLM-returned data fails local field validation."""
