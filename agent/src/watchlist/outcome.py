"""Deterministic post-hoc verification of Chanlun action cards.

Every archived card (section 8) states a direction, trigger/stop/target
prices and a horizon in trading days. Once enough trading days have
passed, the call can be judged mechanically from the SAME archived bars
the analyst was supposed to read -- no LLM, no network, no hindsight
rewriting:

* trigger filled? target T1 touched? stop touched? which came first?
* maximum favourable / adverse excursion (MFE/MAE) over the window;
* window-end return against the cost basis;
* final label: win / partial / loss / timeout_correct / timeout_wrong /
  neutral.

The fill convention is deliberately simple and documented in the UI:
intraday touch counts as a fill, and a bar touching both target and stop
is conservatively booked as the stop (A-share limit-up/down lock is not
modelled yet). Cards that never triggered are judged on direction vs the
window-end close, with ``first_event='neither'`` distinguishing them.

L2 module: imports only :mod:`src.watchlist.db` (DuckDB) and stdlib.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import duckdb

from src.watchlist import db as watch_db

#: Evaluation lifecycle states persisted on ``chanlun_outcome``.
EVAL_PENDING = "pending"
EVAL_INSUFFICIENT = "insufficient_data"
EVAL_VERIFIED = "verified"

#: Outcome labels.
WIN = "win"
LOSS = "loss"
PARTIAL = "partial"
TIMEOUT_CORRECT = "timeout_correct"
TIMEOUT_WRONG = "timeout_wrong"
NEUTRAL = "neutral"

#: Live card statuses (not persisted; computed on read).
LIVE_WAITING = "waiting"        # plan exists, trigger not touched yet
LIVE_ACTIVE = "active"          # triggered, neither T1 nor stop yet
LIVE_TARGET = "target_hit"      # T1 touched at some point
LIVE_STOPPED = "stopped"        # stop touched
LIVE_EXPIRED = "expired"        # horizon elapsed without a trigger fill
LIVE_NEUTRAL = "neutral"        # wait/neutral card
LIVE_DATA = "insufficient_data"

_DECIDED_LABELS = (WIN, LOSS, PARTIAL, TIMEOUT_CORRECT, TIMEOUT_WRONG)
_DIRECTIONAL_LABELS = (WIN, PARTIAL, TIMEOUT_CORRECT)
_WRONG_LABELS = (LOSS, TIMEOUT_WRONG)


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _pct(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return round((numerator - denominator) / denominator * 100.0, 2)


def _horizon_end_estimate(base: date, horizon_days: int) -> date:
    """Calendar-day upper bound for N trading days (weekends + buffer)."""
    return base + timedelta(days=int(horizon_days * 1.6) + 15)


def _scan_events(
    *,
    direction: str,
    trigger: float,
    stop: float,
    target: float | None,
    bars: list[dict[str, Any]],
) -> dict[str, Any]:
    """Walk bars chronologically; decide fills purely from price touches.

    ``bars`` begin the session AFTER the base date. Returns trigger index,
    first-event classification (target-first wins; same-bar ambiguity is
    booked as the stop), MFE/MAE vs the trigger fill price and the exit
    close.
    """
    bullish = direction == "bullish"
    trigger_idx: int | None = None
    for idx, bar in enumerate(bars):
        high = bar.get("high")
        low = bar.get("low")
        touched = (
            (bullish and high is not None and float(high) >= trigger)
            or (not bullish and low is not None and float(low) <= trigger)
        )
        if touched:
            trigger_idx = idx
            break

    result: dict[str, Any] = {
        "trigger_idx": trigger_idx,
        "target_hit": False,
        "stop_hit": False,
        "first_event": "neither",
        "mfe_pct": None,
        "mae_pct": None,
        "exit_close": bars[-1]["close"] if bars else None,
        "target_after_stop": False,
    }
    if trigger_idx is None:
        return result

    # Excursion is measured for a holder filled at the trigger price.
    mfe = mae = 0.0
    for offset, bar in enumerate(bars[trigger_idx:]):
        high = bar.get("high")
        low = bar.get("low")
        if high is not None:
            move = (float(high) - trigger) / trigger
            if bullish:
                mfe = max(mfe, move)
            else:
                mae = min(mae, -move)
        if low is not None:
            move = (float(low) - trigger) / trigger
            if bullish:
                mae = min(mae, move)
            else:
                mfe = max(mfe, -move)

        target_touched = (
            target is not None
            and (
                (bullish and high is not None and float(high) >= target)
                or (not bullish and low is not None and float(low) <= target)
            )
        )
        stop_touched = (
            (bullish and low is not None and float(low) <= stop)
            or (not bullish and high is not None and float(high) >= stop)
        )
        # Same-bar double touch -> conservative stop booking.
        if stop_touched:
            result["stop_hit"] = True
            result["first_event"] = "stop_first"
            if result["target_hit"]:
                result["target_after_stop"] = True
            break
        if target_touched:
            result["target_hit"] = True
            result["first_event"] = "target_first"
            break

    result["mfe_pct"] = round(mfe * 100.0, 2)
    result["mae_pct"] = round(mae * 100.0, 2)
    # When stopped early the window-end close for stats is still the last
    # bar close of the evaluated window (caller truncates to horizon).
    return result


def _reference_close(conn: duckdb.DuckDBPyConnection, symbol: str, base: date) -> float | None:
    bars = watch_db.daily_bars_between(symbol, base, base, conn)
    if bars and bars[0].get("close") is not None:
        return float(bars[0]["close"])
    fallback = watch_db.latest_close_on(symbol, base, conn)
    return float(fallback["close"]) if fallback and fallback.get("close") else None


def evaluate_card_row(
    row: dict[str, Any],
    conn: duckdb.DuckDBPyConnection,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Evaluate one archived card row against archived daily bars.

    Returns a dict suitable for :func:`db.upsert_chanlun_outcome` plus
    ``eval_status``. ``pending`` means the horizon has not elapsed yet;
    ``insufficient_data`` means it elapsed but local bars cannot judge it.
    """
    today = today or date.today()
    run_id = str(row["run_id"])
    symbol = str(row["symbol"])
    base = _as_date(row.get("base_date")) or _as_date(row.get("analyzed_at"))
    horizon = int(row.get("horizon_days") or 20)

    if row.get("direction") == "neutral" or row.get("action") == "wait":
        return {
            "run_id": run_id,
            "symbol": symbol,
            "eval_status": EVAL_VERIFIED,
            "base_date": base,
            "window_end_date": base,
            "target_hit": None,
            "stop_hit": None,
            "first_event": None,
            "mfe_pct": None,
            "mae_pct": None,
            "exit_return_pct": None,
            "direction_correct": None,
            "outcome_label": NEUTRAL,
            "error_note": None,
        }

    if base is None:
        return {
            "run_id": run_id, "symbol": symbol, "eval_status": EVAL_INSUFFICIENT,
            "base_date": None, "window_end_date": None,
            "target_hit": None, "stop_hit": None, "first_event": None,
            "mfe_pct": None, "mae_pct": None, "exit_return_pct": None,
            "direction_correct": None, "outcome_label": None,
            "error_note": "missing base_date",
        }

    ref_close = _reference_close(conn, symbol, base)
    if ref_close is None:
        return {
            "run_id": run_id, "symbol": symbol, "eval_status": EVAL_INSUFFICIENT,
            "base_date": base, "window_end_date": None,
            "target_hit": None, "stop_hit": None, "first_event": None,
            "mfe_pct": None, "mae_pct": None, "exit_return_pct": None,
            "direction_correct": None, "outcome_label": None,
            "error_note": "no daily bar on/around base date",
        }

    range_end = _horizon_end_estimate(base, horizon)
    after = watch_db.daily_bars_between(symbol, base + timedelta(days=1), range_end, conn)
    if len(after) < horizon:
        # Still inside (or near) the plan window -- wait for more bars.
        if today < range_end:
            status = EVAL_PENDING
            note = None
        else:
            status = EVAL_INSUFFICIENT
            note = f"only {len(after)} bars after base, need {horizon}"
        return {
            "run_id": run_id, "symbol": symbol, "eval_status": status,
            "base_date": base, "window_end_date": None,
            "target_hit": None, "stop_hit": None, "first_event": None,
            "mfe_pct": None, "mae_pct": None, "exit_return_pct": None,
            "direction_correct": None, "outcome_label": None,
            "error_note": note,
        }

    window = after[:horizon]
    window_end = _as_date(window[-1].get("trade_date"))
    trigger = row.get("trigger_price")
    stop = row.get("stop_price")
    targets = row.get("target_prices") or []
    target = float(targets[0]) if targets else None

    # Cards without a concrete plan (e.g. hold w/o levels) are judged only
    # on direction vs the window-end close.
    if trigger is None or stop is None:
        exit_close = float(window[-1]["close"])
        ret = _pct(exit_close, ref_close)
        correct = (ret or 0) > 0 if row.get("direction") == "bullish" else (ret or 0) < 0
        return {
            "run_id": run_id, "symbol": symbol, "eval_status": EVAL_VERIFIED,
            "base_date": base, "window_end_date": window_end,
            "target_hit": None, "stop_hit": None, "first_event": None,
            "mfe_pct": None, "mae_pct": None, "exit_return_pct": ret,
            "direction_correct": correct,
            "outcome_label": TIMEOUT_CORRECT if correct else TIMEOUT_WRONG,
            "error_note": None,
        }

    scan = _scan_events(
        direction=str(row.get("direction")),
        trigger=float(trigger),
        stop=float(stop),
        target=target,
        bars=window,
    )
    exit_close = float(window[-1]["close"])
    cost_basis = float(trigger) if scan["trigger_idx"] is not None else ref_close
    ret = _pct(exit_close, cost_basis)
    direction_up = row.get("direction") == "bullish"

    if scan["first_event"] == "target_first":
        label = PARTIAL if scan["target_after_stop"] else WIN
        correct = True
    elif scan["first_event"] == "stop_first":
        label = LOSS
        correct = False
    else:
        correct = (ret or 0) > 0 if direction_up else (ret or 0) < 0
        label = TIMEOUT_CORRECT if correct else TIMEOUT_WRONG

    return {
        "run_id": run_id,
        "symbol": symbol,
        "eval_status": EVAL_VERIFIED,
        "base_date": base,
        "window_end_date": window_end,
        "target_hit": bool(scan["target_hit"]),
        "stop_hit": bool(scan["stop_hit"]),
        "first_event": scan["first_event"],
        "mfe_pct": scan["mfe_pct"] if scan["trigger_idx"] is not None else None,
        "mae_pct": scan["mae_pct"] if scan["trigger_idx"] is not None else None,
        "exit_return_pct": ret,
        "direction_correct": correct,
        "outcome_label": label,
        "error_note": None,
    }


def refresh_due(
    symbol: str | None,
    conn: duckdb.DuckDBPyConnection,
    *,
    today: date | None = None,
) -> int:
    """Evaluate every due card (missing/pending/insufficient outcome).

    Returns the number of rows written. Re-evaluating ``insufficient_data``
    rows lets a later bar backfill flip them to verified.
    """
    today = today or date.today()
    written = 0
    for row in watch_db.cards_pending_outcome(symbol, conn):
        result = evaluate_card_row(row, conn, today=today)
        if result["eval_status"] == EVAL_PENDING:
            existing = watch_db.get_chanlun_outcome(str(row["run_id"]), conn)
            if existing and existing.get("eval_status") == EVAL_PENDING:
                continue
        watch_db.upsert_chanlun_outcome(conn=conn, **result)
        written += 1
    return written


def current_status(
    row: dict[str, Any],
    conn: duckdb.DuckDBPyConnection,
    *,
    today: date | None = None,
) -> str:
    """Live status of a card using every bar available up to ``today``."""
    today = today or date.today()
    if row.get("direction") == "neutral" or row.get("action") == "wait":
        return LIVE_NEUTRAL
    base = _as_date(row.get("base_date")) or _as_date(row.get("analyzed_at"))
    if base is None:
        return LIVE_DATA
    trigger = row.get("trigger_price")
    stop = row.get("stop_price")
    targets = row.get("target_prices") or []
    if trigger is None or stop is None:
        return LIVE_ACTIVE
    bars = watch_db.daily_bars_between(
        str(row["symbol"]), base + timedelta(days=1), today, conn
    )
    if not bars:
        return LIVE_DATA if today > _horizon_end_estimate(base, int(row.get("horizon_days") or 20)) else LIVE_WAITING
    horizon = int(row.get("horizon_days") or 20)
    scan = _scan_events(
        direction=str(row.get("direction")),
        trigger=float(trigger),
        stop=float(stop),
        target=float(targets[0]) if targets else None,
        bars=bars,
    )
    if scan["first_event"] == "target_first":
        return LIVE_TARGET
    if scan["first_event"] == "stop_first":
        return LIVE_STOPPED
    if scan["trigger_idx"] is not None:
        return LIVE_ACTIVE
    if len(bars) >= horizon:
        return LIVE_EXPIRED
    return LIVE_WAITING


def summarize(joined: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate card rows joined with their outcome/user rating.

    Only ``card_parse='ok'`` rows count; machine labels and user verdicts
    are tallied separately so they can disagree.
    """
    cards = [r for r in joined if r.get("card_parse") == "ok"]
    outcomes = [
        r for r in cards
        if r.get("eval_status") == EVAL_VERIFIED and r.get("outcome_label")
    ]
    decided = [r for r in outcomes if r["outcome_label"] in _DECIDED_LABELS]
    wins = sum(1 for r in decided if r["outcome_label"] == WIN)
    losses = sum(1 for r in decided if r["outcome_label"] == LOSS)
    partials = sum(1 for r in decided if r["outcome_label"] == PARTIAL)
    correct = sum(
        1 for r in decided
        if r.get("direction_correct") is True or r["outcome_label"] in (WIN, PARTIAL)
    )
    target_hits = sum(1 for r in decided if r.get("target_hit"))
    stop_hits = sum(1 for r in decided if r.get("stop_hit"))
    rated = [r for r in cards if r.get("user_verdict")]
    ratings = {
        verdict: sum(1 for r in rated if r.get("user_verdict") == verdict)
        for verdict in ("accurate", "partial", "wrong")
    }

    by_setup: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "win": 0, "loss": 0, "partial": 0}
    )
    for r in decided:
        bucket = by_setup[str(r.get("setup_class") or "none")]
        bucket["total"] += 1
        label = r["outcome_label"]
        if label in (WIN, LOSS, PARTIAL):
            bucket[label] += 1

    mfe = [r["mfe_pct"] for r in decided if r.get("mfe_pct") is not None]
    mae = [r["mae_pct"] for r in decided if r.get("mae_pct") is not None]

    def _avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    return {
        "cards_total": len(cards),
        "pending": sum(1 for r in cards if r.get("eval_status") == EVAL_PENDING),
        "insufficient_data": sum(
            1 for r in cards if r.get("eval_status") == EVAL_INSUFFICIENT
        ),
        "neutral": sum(1 for r in outcomes if r["outcome_label"] == NEUTRAL),
        "verified_decided": len(decided),
        "wins": wins,
        "losses": losses,
        "partials": partials,
        "win_rate": round((wins + 0.5 * partials) / len(decided) * 100, 1) if decided else None,
        "direction_accuracy": round(correct / len(decided) * 100, 1) if decided else None,
        "target_hit_rate": round(target_hits / len(decided) * 100, 1) if decided else None,
        "stop_rate": round(stop_hits / len(decided) * 100, 1) if decided else None,
        "avg_mfe_pct": _avg(mfe),
        "avg_mae_pct": _avg(mae),
        "ratings": ratings,
        "rated_total": len(rated),
        "by_setup": dict(by_setup),
    }
