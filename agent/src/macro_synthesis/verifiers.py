"""Claims 到期判定：预测条件解析 + 实际值取数 + 结果判定。

取数器按 ``verify_source`` 注册：
* ``daily_bar`` —— 本地行情库日线（指数等），``metric`` 为工程规范代码；
* ``fx_rate``   —— 参考汇率，``metric`` 如 ``USDCNY``；
* 其余来源（``cn_macro_monthly`` 等宏观源）当前本地库无表，取数器返回
  ``None``，命题标记 ``data_missing``；未来接入宏观数据只需注册新取数器。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

import duckdb

from .models import (
    CLAIM_STATUS_DATA_MISSING,
    CLAIM_STATUS_HIT,
    CLAIM_STATUS_MISS,
    CLAIM_STATUS_PARTIAL,
    SynthesisClaim,
)

# -- 实际值观测 ------------------------------------------------------------


@dataclass(frozen=True)
class ActualObservation:
    value: float
    observed_date: str
    baseline: Optional[float] = None  # 窗口前最近观测，方向/相对变化判定用


# -- 预测条件解析 ----------------------------------------------------------

_OPS = (">=", "<=", "≥", "≤", ">", "<", "=", "≈", "~")
_THRESHOLD_RE = re.compile(
    r"^(>=|<=|≥|≤|=|≈|~|>|<)?\s*(-?\d+(?:\.\d+)?)\s*(%?)$"
)
_INTERVAL_RE = re.compile(
    r"^(-?\d+(?:\.\d+)?)\s*(?:~|至|到|-|—)\s*(-?\d+(?:\.\d+)?)\s*(%?)$"
)
_REL_RE = re.compile(r"(>=|<=|≥|≤|>|<|=)?\s*(-?\d+(?:\.\d+)?)\s*%")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def parse_predicate(text: str):
    """解析 predicted_value 为结构化判定规则。

    返回 ``{"kind": ...}``：threshold / interval / rel_change / direction。
    """
    raw = (text or "").strip()
    percentage_hint = "%" in raw

    interval = _INTERVAL_RE.match(raw.replace(" ", ""))
    if interval:
        low, high, pct = interval.groups()
        low_f, high_f = float(low), float(high)
        if low_f > high_f:
            low_f, high_f = high_f, low_f
        return {
            "kind": "interval",
            "low": low_f,
            "high": high_f,
            "pct": bool(pct),
        }

    threshold = _THRESHOLD_RE.match(raw.replace(" ", ""))
    if threshold:
        op, value, pct = threshold.groups()
        op = {"≥": ">=", "≤": "<=", "≈": "=", "~": "="}.get(op, op or "=")
        kind = "rel_change" if (pct or percentage_hint) else "threshold"
        return {"kind": kind, "op": op, "value": float(value)}

    rel = _REL_RE.search(raw.replace(" ", ""))
    if rel:
        op, value = rel.groups()
        return {"kind": "rel_change", "op": op or ">=", "value": float(value)}

    if _NUMBER_RE.search(raw):
        # 含数字但无法匹配结构（如复杂文字），保守退回方向判定
        return {"kind": "direction"}
    return {"kind": "direction"}


# -- 判定 ------------------------------------------------------------------

#: 阈值附近视为 partial 的相对容差。
_TOLERANCE = 0.005
#: 方向判定 flat/边界的相对容差（0.5%）。
_DIRECTION_TOLERANCE = 0.005


def _relative_gap(actual: float, target: float) -> float:
    if target == 0:
        return abs(actual - target)
    return abs(actual - target) / abs(target)


def judge(rule: dict, observation: ActualObservation) -> str:
    """依据规则与实际观测返回 hit/miss/partial。"""
    actual = observation.value

    if rule["kind"] == "threshold":
        target = rule["value"]
        op = rule["op"]
        satisfied = _compare(actual, op, target)
        near = _relative_gap(actual, target) <= _TOLERANCE
        if satisfied:
            return CLAIM_STATUS_HIT
        return CLAIM_STATUS_PARTIAL if near else CLAIM_STATUS_MISS

    if rule["kind"] == "interval":
        low, high = rule["low"], rule["high"]
        if low <= actual <= high:
            return CLAIM_STATUS_HIT
        near_low = _relative_gap(actual, low) <= _TOLERANCE
        near_high = _relative_gap(actual, high) <= _TOLERANCE
        if actual < low and near_low:
            return CLAIM_STATUS_PARTIAL
        if actual > high and near_high:
            return CLAIM_STATUS_PARTIAL
        return CLAIM_STATUS_MISS

    # rel_change / direction 均依赖基准
    baseline = observation.baseline
    if baseline is None or baseline == 0:
        # 无基准则无法机械判定，按缺失处理
        return CLAIM_STATUS_DATA_MISSING
    change = (actual - baseline) / abs(baseline)
    if rule["kind"] == "rel_change":
        target = rule["value"] / 100.0
        satisfied = _compare(change, rule["op"], target)
        near = abs(change - target) <= _TOLERANCE
        if satisfied:
            return CLAIM_STATUS_HIT
        return CLAIM_STATUS_PARTIAL if near else CLAIM_STATUS_MISS

    # direction
    direction = rule["direction"]
    if direction == "flat":
        return (
            CLAIM_STATUS_HIT
            if abs(change) <= _DIRECTION_TOLERANCE
            else CLAIM_STATUS_PARTIAL
            if abs(change) <= _DIRECTION_TOLERANCE * 3
            else CLAIM_STATUS_MISS
        )
    expected = 1 if direction == "up" else -1
    observed_sign = 1 if change > _DIRECTION_TOLERANCE else (
        -1 if change < -_DIRECTION_TOLERANCE else 0
    )
    if observed_sign == expected:
        return CLAIM_STATUS_HIT
    if observed_sign == 0:
        return CLAIM_STATUS_PARTIAL
    return CLAIM_STATUS_MISS


def _compare(left: float, op: str, right: float) -> bool:
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    return left == right


# -- 取数器注册表 ----------------------------------------------------------

#: 指数代码别名 -> 工程规范代码（daily_bar.symbol）。
SYMBOL_ALIASES = {
    "CSI300": "000300.SH",
    "HS300": "000300.SH",
    "沪深300": "000300.SH",
}


def _daily_bar_resolver(
    conn: duckdb.DuckDBPyConnection, claim: SynthesisClaim
) -> Optional[ActualObservation]:
    metric = claim.metric.strip()
    symbol = SYMBOL_ALIASES.get(metric.upper(), SYMBOL_ALIASES.get(metric, metric))
    row = conn.execute(
        "SELECT close, trade_date FROM daily_bar "
        "WHERE symbol = ? AND trade_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) "
        "ORDER BY trade_date DESC LIMIT 1",
        [symbol, claim.window_start, claim.window_end],
    ).fetchone()
    if row is None:
        return None
    base = conn.execute(
        "SELECT close FROM daily_bar WHERE symbol = ? AND trade_date < CAST(? AS DATE) "
        "ORDER BY trade_date DESC LIMIT 1",
        [symbol, claim.window_start],
    ).fetchone()
    return ActualObservation(
        value=float(row[0]),
        observed_date=str(row[1]),
        baseline=float(base[0]) if base else None,
    )


def _fx_rate_resolver(
    conn: duckdb.DuckDBPyConnection, claim: SynthesisClaim
) -> Optional[ActualObservation]:
    metric = claim.metric.strip().upper().replace("/", "").replace("-", "")
    if len(metric) != 6:
        return None
    base_ccy, quote_ccy = metric[:3], metric[3:]
    row = conn.execute(
        "SELECT rate, rate_date FROM fx_rate "
        "WHERE base = ? AND quote = ? AND rate_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) "
        "AND rate_type = 'reference' ORDER BY rate_date DESC LIMIT 1",
        [base_ccy, quote_ccy, claim.window_start, claim.window_end],
    ).fetchone()
    if row is None:
        return None
    base = conn.execute(
        "SELECT rate FROM fx_rate WHERE base = ? AND quote = ? AND rate_date < CAST(? AS DATE) "
        "AND rate_type = 'reference' ORDER BY rate_date DESC LIMIT 1",
        [base_ccy, quote_ccy, claim.window_start],
    ).fetchone()
    return ActualObservation(
        value=float(row[0]),
        observed_date=str(row[1]),
        baseline=float(base[0]) if base else None,
    )


#: verify_source -> 取数器；未注册来源返回 None（data_missing）。
RESOLVERS: dict[str, Callable] = {
    "daily_bar": _daily_bar_resolver,
    "fx_rate": _fx_rate_resolver,
}


def verify_claim(
    conn: duckdb.DuckDBPyConnection, claim: SynthesisClaim
) -> tuple[str, Optional[float], Optional[str]]:
    """验证单条命题，返回 (status, actual_value, observed_date)。"""
    resolver = RESOLVERS.get((claim.verify_source or "").strip().lower())
    if resolver is None:
        return CLAIM_STATUS_DATA_MISSING, None, None
    try:
        observation = resolver(conn, claim)
    except duckdb.Error:
        # 取数表尚未初始化等情况，按数据缺失处理而非 500
        return CLAIM_STATUS_DATA_MISSING, None, None
    if observation is None:
        return CLAIM_STATUS_DATA_MISSING, None, None
    rule = parse_predicate(claim.predicted_value)
    if rule["kind"] == "direction":
        rule["direction"] = claim.direction
    status = judge(rule, observation)
    return status, observation.value, observation.observed_date
