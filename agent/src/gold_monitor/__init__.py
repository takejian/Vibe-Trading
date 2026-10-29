"""Gold policy-cycle monitor module.

Tables live in the shared market DuckDB under ``~/.vibe-trading/data/market.duckdb``
with the ``gold_`` prefix. Short-lived connections follow the same pattern
as ``src.watchlist.db`` and ``src.paper.db``.
"""

from src.gold_monitor.exceptions import (
    GoldCycleDetectError,
    GoldDataError,
    GoldLLMError,
    GoldMonitorError,
    GoldValidationError,
)

__all__ = [
    "GoldMonitorError",
    "GoldDataError",
    "GoldLLMError",
    "GoldCycleDetectError",
    "GoldValidationError",
]
