"""Watchlist analysis orchestration (start / guard / history / archive).

L2 service: it never imports the L3 swarm package. The runtime (duck-typed
``SwarmRuntime``) and the approved-role catalog (plain entry dicts) are
provided by the L4 route layer, so all dependency edges point downward.

Responsibilities:

* Build default research questions (user brief optional; symbol/name are
  always attached automatically).
* Validate category/role, enforce one-running-run per symbol+role (409),
  and start role runs via the injected runtime.
* Filter role-run history by symbol / category / role / date.
* Lazily persist finished artifacts into DuckDB: Chanlun reports parse
  into 7 dimensions (or get a ``structured=false`` raw row), system data
  fetches archive as objective records. Idempotent by ``run_id``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any

import duckdb

from src.watchlist import db as watch_db
from src.watchlist.action_card import parse_action_card
from src.watchlist.chanlun_parser import parse_chanlun_report
from src.watchlist.market import normalize_a_share_symbol
from src.watchlist.role_catalog_filter import (
    CHANLUN_ROLE_REF,
    get_analyst_role,
    is_chanlun_role,
    list_analyst_roles,
)

_SYMBOL_RE = re.compile(r"(?<!\d)\d{6}\.(?:SH|SZ|BJ)(?!\d)")

#: System-designated built-in role for objective-data supplemental fetches.
OBJECTIVE_FETCH_ROLE = "equity_research_team:stock_picker"

_IN_PROGRESS_STATUSES = frozenset({"pending", "running"})
_ROLE_RUN_KIND = "role_run"
_HISTORY_SCAN_LIMIT = 10_000
_MAX_HISTORY_LIMIT = 100


class AnalysisInProgress(Exception):
    """A run for the same symbol+role is already pending/running (HTTP 409)."""


class AnalysisServiceError(RuntimeError):
    """Server-side analysis configuration failure (HTTP 502)."""


# ----------------------------------------------------------------------
# Question / target builders
# ----------------------------------------------------------------------
def _display_name(symbol: str, name: str | None) -> str:
    return f"{name.strip()}（{symbol}）" if name and name.strip() else symbol


def default_question(
    category: str,
    symbol: str,
    name: str = "",
    brief: str = "",
) -> str:
    """Build the research question.

    A non-empty *brief* is preserved verbatim with a symbol/name context
    line prepended; an empty brief uses the category's default template.
    """
    normalized = normalize_a_share_symbol(symbol)
    display = _display_name(normalized, name)
    context = f"标的：{display}"
    user_text = (brief or "").strip()
    if user_text:
        return f"{context}\n\n{user_text}"

    templates = {
        "fundamental": (
            f"请对{display}进行基本面深度分析：行业格局与竞争优势、财务质量、"
            "盈利能力、估值水平与主要风险，并给出明确的研究结论。"
        ),
        "technical": (
            f"请对{display}进行技术面分析：当前趋势结构、关键支点（中枢）、"
            "背驰与买卖点、多级别共振情况，并给出明确的操作参考与风险提示。"
        ),
        "general": (
            f"请对{display}进行综合分析，结合行业、基本面、市场情绪与技术面，"
            "给出客观的研究结论。"
        ),
    }
    return templates.get(category, templates["general"])


def _objective_question(symbol: str, name: str | None, note: str) -> str:
    display = _display_name(symbol, name)
    return (
        f"标的：{display}\n\n"
        f"请通过可用的数据工具补充抓取以下客观数据并原样整理归档（不得编造、"
        f"无法获取的项需明确说明）：\n{note.strip()}"
    )


# ----------------------------------------------------------------------
# Run inspection helpers (duck-typed SwarmRuntime / SwarmRun)
# ----------------------------------------------------------------------
def _status(run: Any) -> str:
    status = getattr(run, "status", "")
    value = getattr(status, "value", status)
    return str(value or "")


def _field(run: Any, key: str) -> Any:
    return getattr(run, key, None)


def _run_succeeded(run: Any) -> bool:
    """Local mirror of role_run_succeeded (avoids an L3 import)."""
    if _status(run) != "completed":
        return False
    if (getattr(run, "final_report", "") or "").strip():
        return True
    for task in getattr(run, "tasks", []) or []:
        task_status = getattr(getattr(task, "status", ""), "value", getattr(task, "status", ""))
        if str(task_status) == "completed" and (getattr(task, "summary", "") or "").strip():
            return True
    return False


def _symbol_matches(run: Any, symbol: str) -> bool:
    target = str(_field(run, "research_target") or "").upper()
    wanted = symbol.upper()
    return wanted in _SYMBOL_RE.findall(target)


def _role_runs(runtime: Any) -> list[Any]:
    store = getattr(runtime, "_store", runtime)  # tolerate store-only fakes
    return [
        run
        for run in store.list_runs(limit=_HISTORY_SCAN_LIMIT)
        if (getattr(run, "kind", "team") or "team") == _ROLE_RUN_KIND
    ]


def _reconcile(runtime: Any, run: Any) -> Any:
    store = getattr(runtime, "_store", None)
    if store is not None and hasattr(store, "reconcile_run"):
        return store.reconcile_run(run, write=True)
    return run


def _has_in_progress(runtime: Any, symbol: str, role_ref: str) -> bool:
    for run in _role_runs(runtime):
        if getattr(run, "trial_role", None) != role_ref:
            continue
        if not _symbol_matches(run, symbol):
            continue
        if _status(_reconcile(runtime, run)) in _IN_PROGRESS_STATUSES:
            return True
    return False


def _created_date(run: Any) -> date | None:
    raw = str(getattr(run, "created_at", "") or "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _run_datetime(run: Any, attr: str) -> datetime:
    raw = str(getattr(run, attr, "") or "")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    return datetime.now()


# ----------------------------------------------------------------------
# Start runs
# ----------------------------------------------------------------------
def _entry_name(watch_store: Any, symbol: str) -> str:
    if watch_store is None:
        return ""
    entry = watch_store.get_entry(symbol)  # FileNotFoundError -> route 404
    return str(getattr(entry, "name", "") or "")


def start_analysis(
    *,
    symbol: str,
    category: str,
    role_ref: str,
    brief: str = "",
    entries: Sequence[dict[str, Any]],
    runtime: Any,
    watch_store: Any = None,
) -> Any:
    """Validate, de-duplicate, and start one analyst role run.

    Market data is never carried in the research question: roles read the
    platform's archived objective data through the ``objective_kline``
    tool (local archive first, online fallback when stale — BDD rule 21).
    """
    normalized = normalize_a_share_symbol(symbol)
    name = _entry_name(watch_store, normalized)

    role = get_analyst_role(role_ref, list(entries))
    if role is None:
        raise ValueError("该智能体不存在或尚未发布，无法发起分析")
    if role["category"] != category:
        raise ValueError(
            f"该智能体不属于「{category}」分类，请重新选择"
        )

    if _has_in_progress(runtime, normalized, role_ref):
        raise AnalysisInProgress("该智能体对这一标的的分析正在进行中")

    target = _display_name(normalized, name)
    question = default_question(category, normalized, name, brief)
    return runtime.start_run(
        "",
        {},
        role_run={"role_ref": role_ref, "target": target, "question": question},
    )


def start_objective_fetch(
    *,
    symbol: str,
    note: str,
    entries: Sequence[dict[str, Any]],
    runtime: Any,
    watch_store: Any = None,
) -> Any:
    """Start a system-designated data-researcher fetch role run."""
    normalized = normalize_a_share_symbol(symbol)
    user_note = (note or "").strip()
    if not user_note:
        raise ValueError("补充抓取需求不能为空")
    name = _entry_name(watch_store, normalized)

    role = get_analyst_role(OBJECTIVE_FETCH_ROLE, list(entries))
    if role is None:
        raise AnalysisServiceError(
            "系统指定的数据研究角色不可用，无法发起补充抓取"
        )

    if _has_in_progress(runtime, normalized, OBJECTIVE_FETCH_ROLE):
        raise AnalysisInProgress("该标的的客观数据补充抓取正在进行中")

    question = _objective_question(normalized, name, user_note)
    return runtime.start_run(
        "",
        {},
        role_run={
            "role_ref": OBJECTIVE_FETCH_ROLE,
            "target": normalized,
            "question": question,
        },
    )


# ----------------------------------------------------------------------
# History
# ----------------------------------------------------------------------
def list_analyses(
    *,
    symbol: str,
    entries: Sequence[dict[str, Any]],
    runtime: Any,
    category: str | None = None,
    role_ref: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List role-run summaries for one symbol with the standard filters."""
    normalized = normalize_a_share_symbol(symbol)
    catalog = {role["ref"]: role for role in classify_entries(entries)}

    matched: list[Any] = []
    for run in _role_runs(runtime):
        run_role = getattr(run, "trial_role", None)
        if run_role not in catalog:
            continue
        if not _symbol_matches(run, normalized):
            continue
        if category is not None and catalog[run_role]["category"] != category:
            continue
        if role_ref and run_role != role_ref:
            continue
        created = _created_date(run)
        if created is None:
            continue
        if date_from is not None and created < date_from:
            continue
        if date_to is not None and created > date_to:
            continue
        matched.append(_reconcile(runtime, run))

    matched.sort(key=lambda run: str(getattr(run, "created_at", "") or ""), reverse=True)
    matched = matched[: max(1, min(int(limit), _MAX_HISTORY_LIMIT))]

    items: list[dict[str, Any]] = []
    for run in matched:
        run_role = getattr(run, "trial_role", None)
        role = catalog.get(run_role, {})
        report = str(getattr(run, "final_report", "") or "")
        items.append(
            {
                "id": getattr(run, "id", ""),
                "status": _status(run),
                "role_ref": run_role,
                "role_name": role.get("name", run_role),
                "category": role.get("category"),
                "is_chanlun": bool(role.get("is_chanlun")),
                "research_target": getattr(run, "research_target", None),
                "research_question": getattr(run, "research_question", None),
                "created_at": getattr(run, "created_at", None),
                "completed_at": getattr(run, "completed_at", None),
                "final_report_excerpt": report[:280] or None,
                "final_report": report or None,
                "qualified": _run_succeeded(run),
            }
        )
    return items


def classify_entries(entries: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify a raw approved-catalog list (helper used by history/archive)."""
    return list_analyst_roles(None, list(entries))


# ----------------------------------------------------------------------
# Lazy artifact persistence
# ----------------------------------------------------------------------
def _is_chanlun_run(run: Any, entries: Sequence[dict[str, Any]] | None) -> bool:
    role_ref = getattr(run, "trial_role", None)
    if role_ref == CHANLUN_ROLE_REF:
        return True
    if entries:
        for role in classify_entries(entries):
            if role["ref"] == role_ref:
                return bool(role["is_chanlun"])
    # Last resort: exact ref/name match without a catalog (name unknown here,
    # so this only succeeds for the built-in ref).
    return is_chanlun_role({"ref": role_ref, "name": ""})


def persist_run_artifacts(
    runs: Iterable[Any],
    *,
    entries: Sequence[dict[str, Any]] | None = None,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, int]:
    """Archive finished Chanlun/objective runs into DuckDB (idempotent).

    Opens/initializes a warehouse connection when one isn't supplied and
    closes it afterwards. Safe to call repeatedly; ``run_id`` uniqueness
    guarantees no duplicate archive rows.
    """
    own_connection = connection is None
    if own_connection:
        connection = watch_db.watchlist_connection()
    assert connection is not None
    watch_db.initialize_schema(connection)
    counts = {
        "chanlun": 0,
        "objective": 0,
        "unstructured": 0,
        "card_ok": 0,
        "card_violation": 0,
    }
    try:
        for run in runs:
            if (getattr(run, "kind", "team") or "team") != _ROLE_RUN_KIND:
                continue
            if not _run_succeeded(run):
                continue
            run_id = str(getattr(run, "id", "") or "")
            report = str(getattr(run, "final_report", "") or "").strip()
            if not run_id or not report:
                continue
            target = str(getattr(run, "research_target", "") or "")
            symbol = _symbol_from_target(target)
            if symbol is None:
                continue
            analyzed_at = _run_datetime(
                run, "completed_at"
            ) if getattr(run, "completed_at", None) else _run_datetime(run, "created_at")

            role_ref = getattr(run, "trial_role", None)
            if _is_chanlun_run(run, entries):
                if watch_db.chanlun_record_exists(run_id, connection):
                    continue
                parsed = parse_chanlun_report(report)
                card_result = parse_action_card(report)
                card = card_result["card"] if card_result["parse"] == "ok" else None
                if card_result["parse"] == "ok":
                    counts["card_ok"] += 1
                elif card_result["parse"] == "contract_violation":
                    counts["card_violation"] += 1
                if parsed is not None:
                    watch_db.insert_chanlun_record(
                        run_id=run_id,
                        symbol=symbol,
                        conn=connection,
                        dims=parsed["dims"],
                        score=parsed["score"],
                        confidence=parsed["confidence"],
                        structured=True,
                        raw_report=report,
                        analyzed_at=analyzed_at,
                        card=card,
                        card_parse=card_result["parse"],
                    )
                    counts["chanlun"] += 1
                else:
                    watch_db.insert_chanlun_record(
                        run_id=run_id,
                        symbol=symbol,
                        conn=connection,
                        dims={},
                        score=None,
                        confidence=None,
                        structured=False,
                        raw_report=report,
                        analyzed_at=analyzed_at,
                        card=card,
                        card_parse=card_result["parse"],
                    )
                    counts["unstructured"] += 1
            elif role_ref == OBJECTIVE_FETCH_ROLE:
                if watch_db.objective_record_exists(run_id, connection):
                    continue
                watch_db.insert_objective_record(
                    symbol=symbol,
                    payload=report,
                    source=role_ref,
                    run_id=run_id,
                    request_note=getattr(run, "research_question", None),
                    conn=connection,
                    created_at=analyzed_at,
                )
                counts["objective"] += 1
    finally:
        if own_connection:
            connection.close()
    return counts


def _symbol_from_target(target: str) -> str | None:
    """Extract the engineering A-share symbol embedded in a run target."""
    match = _SYMBOL_RE.search(target.upper())
    return match.group(0) if match else None
