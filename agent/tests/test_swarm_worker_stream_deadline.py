"""Wall-clock deadline enforcement on in-flight swarm LLM streams.

Regression for runs (e.g. swarm-20261004-063815) where a slow glm stream ran
15+ minutes on a single turn: the worker's timeout was only checked between
iterations and the HTTP read timeout does not bound total stream duration, so
a trickling/stalling stream overran the configured worker budget by minutes.

Fix: every stream receives a cooperative should_cancel predicate combining
user-cancel with the worker deadline, plus an idle_timeout_s ceiling on
silence between deltas.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.config.env_schema import SwarmConfig
from src.providers.chat import LLMResponse, ProviderStreamError
from src.swarm.models import SwarmAgentSpec, SwarmTask
import src.swarm.worker as worker_mod

FINAL_TEXT = "# 301606.SZ chanlun view: local archive daily level ready; invalidation below the prior swing low."


class _EmptyRegistry:
    def get_definitions(self) -> list[dict]:
        return []

    def execute(self, name: str, args: dict) -> str:
        return "ok"

    def get(self, name: str):
        return None


class _SlowStreamLLM:
    """Streams tiny chunks until the should_cancel predicate fires.

    Natural lifetime is long (8s) to prove the predicate stops the stream at
    the 1s worker budget instead of running to completion.
    """

    def __init__(self, natural_s: float = 8.0, step_s: float = 0.02) -> None:
        self.natural_s = natural_s
        self.step_s = step_s
        self.seen_should_cancel: list[Any] = []
        self.seen_idle: list[Any] = []
        self.predicate_fired = False

    def __call__(self, *args: Any, **kwargs: Any) -> "_SlowStreamLLM":
        return self

    def close(self) -> None:
        return None

    def stream_chat(
        self, messages, tools=None, on_text_chunk=None, timeout=None,
        should_cancel=None, idle_timeout_s=None,
    ) -> LLMResponse:
        self.seen_should_cancel.append(should_cancel)
        self.seen_idle.append(idle_timeout_s)
        deadline_t = time.monotonic() + self.natural_s
        while time.monotonic() < deadline_t:
            if should_cancel is not None and should_cancel():
                self.predicate_fired = True
                break
            time.sleep(self.step_s)
            if on_text_chunk:
                on_text_chunk("x")
        # Mirrors ChatLLM returning whatever partial response accumulated.
        return LLMResponse(content=FINAL_TEXT)


class _StallingLLM:
    """Every call fails the way a provider that stays silent past the idle
    ceiling surfaces after ChatLLM wraps it: a retryable ProviderStreamError."""

    def __init__(self) -> None:
        self.calls = 0
        self.seen_should_cancel: list[Any] = []
        self.seen_idle: list[Any] = []

    def __call__(self, *args: Any, **kwargs: Any) -> "_StallingLLM":
        return self

    def close(self) -> None:
        return None

    def stream_chat(
        self, messages, tools=None, on_text_chunk=None, timeout=None,
        should_cancel=None, idle_timeout_s=None,
    ) -> LLMResponse:
        self.calls += 1
        self.seen_should_cancel.append(should_cancel)
        self.seen_idle.append(idle_timeout_s)
        raise ProviderStreamError(
            provider="glm",
            model="glm-5.3-flash",
            original=TimeoutError("no stream delta for 180s"),
        )


def _agent(timeout_seconds: int = 1) -> SwarmAgentSpec:
    return SwarmAgentSpec(
        id="chanlun_analyst",
        role="Chanlun Analyst",
        system_prompt="Analyse with local kline first.",
        tools=[],
        skills=[],
        max_iterations=3,
        timeout_seconds=timeout_seconds,
    )


def _run_worker(tmp_path: Path, llm: Any, monkeypatch, collect_events=False):
    task = SwarmTask(id="t1", agent_id="chanlun_analyst", prompt_template="Analyse 301606.")
    events: list[str] = []
    monkeypatch.setattr(worker_mod, "_LLM_IDLE_TIMEOUT_S", 180.0)
    with (
        patch.object(worker_mod, "build_swarm_registry", lambda *a, **k: _EmptyRegistry()),
        patch.object(worker_mod, "ChatLLM", llm),
    ):
        result = worker_mod.run_worker(
            agent_spec=_agent(),
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path,
            event_callback=(lambda ev: events.append(ev.type)) if collect_events else None,
        )
    return result, events


def test_inflight_stream_stops_at_worker_deadline(tmp_path, monkeypatch):
    llm = _SlowStreamLLM(natural_s=8.0, step_s=0.02)
    t0 = time.monotonic()
    result, events = _run_worker(tmp_path, llm, monkeypatch, collect_events=True)
    elapsed = time.monotonic() - t0

    assert result.status == "timeout"
    assert "Worker timed out after" in (result.error or "")
    assert "timeout=1s" in (result.error or "")
    assert "worker_timeout" in events
    # The hard guarantee: prompt stop at ~1s, never the stream's natural 8s.
    assert elapsed < 3.0, f"deadline did not bound the in-flight stream: {elapsed:.1f}s"
    assert llm.predicate_fired, "should_cancel predicate never fired during streaming"
    assert llm.seen_should_cancel and all(callable(p) for p in llm.seen_should_cancel)
    assert llm.seen_idle and all(v == 180.0 for v in llm.seen_idle)


def test_idle_ceiling_failure_is_retried_then_fails_with_reason(tmp_path, monkeypatch):
    llm = _StallingLLM()
    monkeypatch.setattr(worker_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(worker_mod, "_STREAM_RETRY_DELAY_S", 0.0)

    result, _ = _run_worker(tmp_path, llm, monkeypatch)

    assert result.status == "failed"
    assert "no stream delta for 180s" in (result.error or "")
    # Exactly one retry per the stream-retry contract.
    assert llm.calls == 2
    assert llm.seen_idle and all(v == 180.0 for v in llm.seen_idle)
    assert llm.seen_should_cancel and all(callable(p) for p in llm.seen_should_cancel)


def test_zero_idle_timeout_disables_the_ceiling_kwarg(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_mod, "_LLM_IDLE_TIMEOUT_S", 0.0)
    llm = _SlowStreamLLM(natural_s=0.05, step_s=0.01)
    task = SwarmTask(id="t1", agent_id="chanlun_analyst", prompt_template="Analyse.")
    with (
        patch.object(worker_mod, "build_swarm_registry", lambda *a, **k: _EmptyRegistry()),
        patch.object(worker_mod, "ChatLLM", llm),
    ):
        worker_mod.run_worker(
            agent_spec=_agent(timeout_seconds=30),
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path,
        )
    assert llm.seen_idle and all(v is None for v in llm.seen_idle)


def test_idle_timeout_config_default_and_validation():
    cfg = SwarmConfig()
    assert cfg.swarm_llm_idle_timeout_s == 180.0
    assert SwarmConfig(SWARM_LLM_IDLE_TIMEOUT_S=0).swarm_llm_idle_timeout_s == 0.0
    with pytest.raises(ValidationError):
        SwarmConfig(SWARM_LLM_IDLE_TIMEOUT_S=-1)
