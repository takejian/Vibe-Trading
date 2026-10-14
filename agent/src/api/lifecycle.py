"""API server lifespan: startup preflight and reverse-order shutdown.

Extracted from ``api_server`` to keep the assembler module thin. Runtime
collaborators are resolved through the ``_compat`` host-attribute shim, so
tests that monkeypatch names (``_start_channel_runtime`` etc.) on the
``api_server`` host module continue to take effect here.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from rich.console import Console

from src.api import _compat
from src.api.channels_routes import (
    _start_channel_runtime,
    _stop_channel_runtime,
)
from src.api.scheduled_routes import (
    _start_scheduled_research_executor,
    _stop_scheduled_research_executor,
)

logger = logging.getLogger(__name__)


async def _run_startup_preflight() -> None:
    """Run preflight checks on server startup."""
    from src.config import migrate as _migrate
    from src.config.accessor import get_env_config
    from src.preflight import run_preflight

    start_scheduled = _compat.host_attr(
        "_start_scheduled_research_executor", _start_scheduled_research_executor
    )
    start_channels = _compat.host_attr("_start_channel_runtime", _start_channel_runtime)

    try:
        # one-time pre-#904 state move; must never block startup
        _migrate.migrate_legacy_state()
    except Exception:  # pragma: no cover - best-effort
        logger.warning("Legacy state migration failed", exc_info=True)
    run_preflight(Console())
    start_scheduled()

    if get_env_config().agent_tuning.vibe_trading_channels_auto_start:
        await start_channels()


async def _stop_scheduled_research_on_shutdown() -> None:
    """Stop background runtimes on server shutdown."""
    stop_channels = _compat.host_attr("_stop_channel_runtime", _stop_channel_runtime)
    stop_scheduled = _compat.host_attr(
        "_stop_scheduled_research_executor", _stop_scheduled_research_executor
    )
    try:
        await stop_channels()
    finally:
        await stop_scheduled()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run API startup and guaranteed reverse-order shutdown."""
    from src.paper.scheduler import (
        start_paper_scheduler,
        stop_paper_scheduler,
    )

    startup = _compat.host_attr("_run_startup_preflight", _run_startup_preflight)
    shutdown = _compat.host_attr(
        "_stop_scheduled_research_on_shutdown", _stop_scheduled_research_on_shutdown
    )
    try:
        await startup()
        start_paper_scheduler(app)
        yield
    finally:
        await stop_paper_scheduler(app)
        await shutdown()
