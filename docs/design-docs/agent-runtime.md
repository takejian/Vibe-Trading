# Agent Runtime Design

> How a chat message becomes model/tool iterations in Vibe-Trading: SessionService, the SSE event bus, the AgentLoop ReAct engine with its retries/compaction/accounting, the Swarm runtime's hand-written worker loop, and the governance hash chain.

## 1. Sessions: One AgentLoop per Session

`SessionService` (`agent/src/session/service.py:56`) owns session lifecycle and enforces a strict concurrency rule — at most one in-flight run per session. A second concurrent send raises `SessionBusyError` (`agent/src/session/service.py:46-53`), surfaced to callers as HTTP 409, rather than being queued: two loops on one session would interleave messages and attempts.

For each attempt the service constructs the runtime stack lazily inside the run (`agent/src/session/service.py:483-499`):

1. `build_registry(...)` — tools, with session id, config overrides and event callback injected (`:483`);
2. `ChatLLM()` — provider-agnostic streaming chat (`:484`, `:489`);
3. `PersistentMemory()` — shared cross-session memory (`:486`, `:490`);
4. `AgentLoop(registry, llm, ...)` — the ReAct engine (`:485`).

Attempts persist checkpoints (`ResponseCheckpoint`) and session-scoped MCP server definitions are merged over the global config via `load_runtime_agent_config` (`:475-478`, `:498-499`).

## 2. SSE Event Bus

The web client subscribes to `GET /sessions/{session_id}/events` (`agent/src/api/sessions_routes.py:787-852`), an SSE `StreamingResponse` guarded by `require_event_stream_auth`. The loop emits lifecycle events (message deltas, tool calls/results, heartbeats, completion) through the `event_callback` injected at registry construction; events are fanned out through an in-process ring-buffer event bus, supporting `Last-Event-ID` resume and replay (`:791-809`). A 501 is returned when the session runtime is disabled (`ENABLE_SESSION_RUNTIME`).

## 3. AgentLoop: the ReAct Engine

`AgentLoop` (`agent/src/agent/loop.py:1071`) runs the classic model↔tools cycle, iterating until the model stops or the iteration budget is exhausted. Key machinery:

- **Tool execution** — `self.registry.execute(tool_name, args)` on the watchdog path (`agent/src/agent/loop.py:2892`) and inside a bounded worker thread for read-only tools (`agent/src/agent/loop.py:2906`); a hung read-only tool becomes a bounded timeout instead of wedging the turn.
- **Timeouts** — `_tool_timeout_seconds()` (`agent/src/agent/loop.py:161-166`, default `VIBE_TRADING_TOOL_TIMEOUT_SECONDS=1800`) and LLM/SSE/stall timeouts from the tuning config group.
- **Streaming retries** — `ProviderStreamError` (`agent/src/providers/chat.py:162-163`) triggers capped exponential backoff doubling from 1.0s: `_stream_retry_backoff_s` (`agent/src/agent/loop.py:138-158`), honoring provider `Retry-After` (`agent/src/providers/chat.py:146-159`); consecutive content-filter skips are bounded.
- **Context management** — five-layer compression plus micro-compaction keep the window within `TOKEN_THRESHOLD`; exact successful read-only tool results may be replayed after compaction when the tool opts in (`replay_after_compaction`).
- **Heartbeats** — a heartbeat timer (`_heartbeat_timer`, used around tool calls at `agent/src/agent/loop.py:2891`) proves liveness during long calls; `VT_HEARTBEAT_INTERVAL_S` sets cadence.
- **Accounting** — real provider token usage is recorded per iteration (`LLMResponse.usage_metadata`, `agent/src/providers/chat.py:119-123`) into LLM-usage artifacts and the run manifest; deterministic cached tool calls are distinguished from real data calls.
- **Governance hooks** — the loop seals each run into a manifest and records grounding evidence (see §5).

### Supporting components

- `ContextBuilder` (`agent/src/agent/context.py:261`) assembles the system prompt, auto-recalled memory (`agent/src/agent/context.py:16`), strategy-discovery context (`:314`), and identity constraints.
- `SkillsLoader` (`agent/src/agent/skills.py:100`) loads bundled and user-created finance skills; the `load_skill` tool and `agent/mcp_server.py:319-325` expose them with skeleton/section pagination for oversized docs.
- `ChatLLM` (`agent/src/providers/chat.py:324`) is the provider facade over the LangChain-based providers (`agent/src/providers/llm.py`), returning `LLMResponse` (`agent/src/providers/chat.py:110-143`) with tool-call requests, reasoning trace, finish reason, and content-filter flags.

## 4. Swarm: a Deliberately Separate Loop

Multi-agent runs do **not** reuse AgentLoop. `SwarmRuntime` (`agent/src/swarm/runtime.py:251`) orchestrates a DAG of agent tasks: each run executes in a background daemon thread, tasks within a layer run in parallel via `ThreadPoolExecutor`, with retries, grounding and artifact management. Workers are driven by `run_worker` (`agent/src/swarm/worker.py:449`), and the module's own docstring states why (`agent/src/swarm/worker.py:1-5`):

> Uses ChatLLM.chat + manual for-loop directly (without instantiating AgentLoop), keeping the worker self-contained and the agent core unchanged.

The worker imports `build_swarm_registry` (`agent/src/swarm/worker.py:36`) and executes tool calls itself at `agent/src/swarm/worker.py:1009`, with the same redaction, heartbeat (`:1000-1002`), content-filter accounting, and error-JSON contract as the main loop, but with swarm-specific iteration/timeouts (`SWARM_WORKER_MAX_ITER`, `SWARM_WORKER_TIMEOUT`) and upstream-summary/variable injection. Swarm runs are observable over their own SSE stream (`agent/src/api/swarm_routes.py:170-211`). Broker write tools reachable from swarm go through the same mandate gate as every other surface (`agent/src/live/registry.py:184-238`).

## 5. Governance: Manifest Hash Chain

Every run can be sealed into a tamper-evident record:

- `RunManifest.verify_hash()` (`agent/src/governance/manifest.py:251`) and `build_run_manifest` (`agent/src/governance/manifest.py:356`) anchor an individual run's artifacts; producers include the agent loop (`agent/src/agent/loop.py:1201`) and the grounding ledger.
- Append-only audit chains (e.g. live order decisions) live in `agent/src/governance/ledger.py`: `compute_record_hash(seq, prev_record_hash, payload)` chains SHA-256 hashes (`:133`), `append_record` (`:368`) fsyncs and locks each write, and `verify_chain` (`:309`) walks records. A broken chain raises `LedgerCorruptionError` (`:208-221`) — the chain refuses to self-heal, because healing would defeat tamper evidence. The offline eval harness uses `verify_hash()` to attest manifests before scoring runs.

## 6. End-to-End Sequence

```mermaid
sequenceDiagram
    participant UI as "Web / MCP client"
    participant API as "sessions_routes (FastAPI)"
    participant Svc as SessionService
    participant Loop as AgentLoop
    participant LLM as ChatLLM
    participant Reg as ToolRegistry
    participant Bus as "SSE event bus"

    UI->>API: POST send to /sessions/{id}
    API->>Svc: start attempt (409 SessionBusyError if one is active)
    Svc->>Reg: build_registry(session_id, event_callback, mcp overrides)
    Svc->>Loop: AgentLoop(registry, llm).run(prompt)
    Loop->>Bus: run started / heartbeat
    Bus-->>UI: SSE frame on GET /sessions/{id}/events
    loop ReAct iterations until stop or budget
        Loop->>LLM: chat stream (retry w/ exp backoff on ProviderStreamError)
        LLM-->>Loop: LLMResponse (content + tool calls)
        loop each tool call
            Loop->>Bus: tool_call event
            Loop->>Reg: execute(name, args) (watchdog / bounded worker)
            Reg-->>Loop: JSON result (or JSON error — never raises)
            Loop->>Bus: tool_result event
        end
        Bus-->>UI: streamed message/tool frames
    end
    Loop->>Bus: completion + LLM usage + manifest
    Svc->>Svc: persist attempt/checkpoint
    Bus-->>UI: terminal SSE event
```

## 7. Design Invariants

- One loop per session, no implicit queueing — concurrency conflicts are explicit 409s.
- Every tool boundary speaks JSON strings, including failures; the loop and swarm worker never special-case exceptions from tools.
- The main loop and swarm loop are separate on purpose: shared abstractions stop at ChatLLM / BaseTool / ContextBuilder / SkillsLoader.
- Provider instability is retried with bounded backoff; missing instrumentation and content filtering never masquerade as answers.
- Run and order audit records are hash-chained and fail closed on corruption; tests run entirely against a sandboxed runtime root so the real ledgers in `~/.vibe-trading/live/` cannot move during validation.
