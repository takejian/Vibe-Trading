"""Concrete failure reasons must survive retries/timeouts to task.error.

Regression for the run where attempt 1 died on an LLM provider timeout and
attempt 2 hit the worker timeout: the web UI only saw the generic
worker-did-not-complete message because the final timeout result carried
an empty error.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.swarm.models import SwarmAgentSpec, SwarmTask, WorkerResult
from src.swarm.runtime import SwarmRuntime
from src.swarm.store import SwarmStore

LLM_ERROR = (
    "LLM call failed at iteration 1: provider_stream_error provider=glm "
    "model=glm-5.3-flash: OpenAITimeoutError: Request timed out."
)
TIMEOUT_REASON = "Worker timed out after 1967s (timeout=1800s, 0 iterations)"


def _runtime(tmp_path: Path) -> SwarmRuntime:
    return SwarmRuntime(SwarmStore(base_dir=tmp_path / "runs"))


def _spec() -> SwarmAgentSpec:
    return SwarmAgentSpec(
        id="analyst",
        role="Chanlun Analyst",
        system_prompt="Analyze",
        max_retries=1,
    )


def _task() -> SwarmTask:
    return SwarmTask(id="task-1", agent_id="analyst", prompt_template="Analyze")


def _run(runtime: SwarmRuntime, tmp_path: Path) -> WorkerResult:
    return runtime._run_worker_with_retries(
        agent_spec=_spec(),
        task=_task(),
        upstream_summaries={},
        user_vars={},
        run_dir=tmp_path / "run-1",
        event_callback=None,
        run_id="run-1",
    )


def test_timeout_after_failed_attempt_keeps_concrete_llm_error(tmp_path: Path):
    runtime = _runtime(tmp_path)
    failed = WorkerResult(
        status="failed", summary="", error=LLM_ERROR,
        input_tokens=10, output_tokens=20,
    )
    # The worker timeout branch now carries its own reason, but the earlier
    # LLM failure is the actionable root cause the user must see.
    timed_out = WorkerResult(
        status="timeout", summary="partial", error=TIMEOUT_REASON,
        input_tokens=30, output_tokens=40,
    )
    with patch("src.swarm.runtime.run_worker", side_effect=[failed, timed_out]), \
            patch("src.swarm.runtime.clear_agent_artifacts"):
        result = _run(runtime, tmp_path)

    assert result.status == "timeout"
    assert TIMEOUT_REASON in result.error
    assert LLM_ERROR in result.error
    assert result.input_tokens == 40
    assert result.output_tokens == 60


def test_timeout_without_prior_failure_reports_timeout_reason(tmp_path: Path):
    runtime = _runtime(tmp_path)
    timed_out = WorkerResult(
        status="timeout", summary="partial", error=TIMEOUT_REASON,
        input_tokens=30, output_tokens=40,
    )
    with patch("src.swarm.runtime.run_worker", side_effect=[timed_out]), \
            patch("src.swarm.runtime.clear_agent_artifacts"):
        result = _run(runtime, tmp_path)

    assert result.status == "timeout"
    assert result.error == TIMEOUT_REASON


def test_failed_retries_exhausted_keep_last_concrete_error(tmp_path: Path):
    runtime = _runtime(tmp_path)
    first = WorkerResult(
        status="failed", summary="", error="first attempt boom",
        input_tokens=1, output_tokens=2,
    )
    last = WorkerResult(
        status="failed", summary="", error=LLM_ERROR,
        input_tokens=3, output_tokens=4,
    )
    with patch("src.swarm.runtime.run_worker", side_effect=[first, last]), \
            patch("src.swarm.runtime.clear_agent_artifacts"):
        result = _run(runtime, tmp_path)

    assert result.status == "failed"
    # Every concrete attempt reason is preserved, newest first.
    assert result.error.startswith(LLM_ERROR)
    assert "first attempt boom" in result.error

