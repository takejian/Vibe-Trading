"""宏观量化汇总应用服务。

流程：覆盖归集 -> 构建团队材料 -> LLM 输出强约束 JSON -> 严格校验 ->
服务端重算 MCS / 归一化周期概率 -> 持久化。模型只提供结构化判断，
权重、指数与标识均由服务端确定。
"""

from __future__ import annotations

import json
import re
import threading
from typing import Optional

from src.config.accessor import get_env_config

from . import coverage, periods
from .db import MacroSynthesisRepository, SynthesisDBError
from .models import (
    ASSET_KEYS,
    CYCLE_KEYS,
    DIMENSIONS,
    DIMENSION_TEAMS,
    DIMENSION_WEIGHTS,
    DIRECTIONS,
    TRENDS,
    DimensionSignal,
    SynthesisClaim,
    SynthesisReport,
    TeamCoverage,
)

# -- 错误 ------------------------------------------------------------------


class SynthesisServiceError(RuntimeError):
    status_code = 400
    code = "synthesis_failed"


class SynthesisInProgressError(SynthesisServiceError):
    status_code = 409
    code = "in_progress"


class SynthesisLLMTimeoutError(SynthesisServiceError):
    status_code = 504
    code = "llm_timeout"


class SynthesisFailedError(SynthesisServiceError):
    status_code = 502
    code = "analysis_failed"


# -- 并发槽位（同 economy+period 串行）-------------------------------------

_SLOTS: set[str] = set()
_SLOTS_GUARD = threading.Lock()


def _acquire_slot(slot: str) -> bool:
    with _SLOTS_GUARD:
        if slot in _SLOTS:
            return False
        _SLOTS.add(slot)
        return True


def _release_slot(slot: str) -> None:
    with _SLOTS_GUARD:
        _SLOTS.discard(slot)


# -- Prompt ----------------------------------------------------------------

SYSTEM_PROMPT = """你是顶级资产管理公司的宏观研究主管。你的任务是综合各智能体团队的当期分析结论，
产出一份结构化、可量化、可事后验证的宏观总体研判。只输出纯 JSON，不要输出任何解释或 markdown 代码块。

【五维信号】每个维度给出：
- signal：整数，-2 显著利空 / -1 偏利空 / 0 中性 / 1 偏利好 / 2 显著利好。方向语义统一为"对宏观环境与风险资产的利多强度"：
  * growth（增长）：经济扩张越强越利好；
  * inflation（通胀）：语义相反——通胀压力缓解为利好（+2），通胀加剧为利空（-2）；通缩风险由 growth 维度捕捉；
  * money（货币流动性）：政策宽松、流动性充裕、利率下行利好；
  * external（对外均衡）：本币走强、外需改善、地缘与供应链风险缓和利好；
  * synthesis（综合配置）：基于前述四维的总体资产配置视角。
- confidence：0~1 浮点数，你对该判断的置信度；材料缺失时必须给低分（<=0.4）。
- trend：up / down / flat，该维度相较上一期的变化方向。
- rationale：一句话理由（<=80字）。

【周期概率 cycle_probs】按美林时钟给出四档概率（0~1，合计为1）：
recovery 复苏（增长向上、通胀温和）、overheat 过热（增长强、通胀高）、
stagflation 滞胀（增长弱、通胀高）、recession 衰退（增长弱、通胀低）。

【资产建议 allocation】equity 股票 / bond 债券 / commodity 商品 / cash 现金，
各给 -2 强低配 … 0 标配 … +2 强超配。

【风险触发器 risk_triggers】2~4 条可客观跟踪的条件，写明指标、阈值与后果。

【可验证命题 claims】给出 5~10 条结构化预测，每条必须具体、可在未来用公开数据判定：
- dimension：所属维度；text：命题完整表述；metric：关联指标代码（如 CN_PMI、CN_CPI、US_CPI、CN10Y、USDCNY、CSI300）；
- direction：up/down/flat；predicted_value：预测值或区间或阈值表述；probability：0~1 实现概率；
- window_start / window_end：YYYY-MM-DD，验证窗口（数据发布/观察起止日期）；verify_source：验证数据源标识。
不要给出无法证伪的模糊表述。

【输出格式】严格按以下结构（示例值需替换）：
{
  "summary": "总体结论，100~300字，包含现状、核心矛盾与短期展望",
  "action_advice": "可执行的操作建议，含资产方向、仓位倾向与关键观察时点",
  "dimensions": [
    {"dimension": "growth", "signal": 1, "confidence": 0.7, "trend": "up", "rationale": "理由"}
  ],
  "cycle_probs": {"recovery": 0.5, "overheat": 0.2, "stagflation": 0.1, "recession": 0.2},
  "allocation": {"equity": 1, "bond": 0, "commodity": -1, "cash": 0},
  "risk_triggers": ["若官方PMI连续2月低于49，则切换至衰退对冲"],
  "claims": [
    {"dimension": "growth", "text": "11月官方制造业PMI较10月回升至49.5以上", "metric": "CN_PMI",
     "direction": "up", "predicted_value": ">=49.5", "probability": 0.65,
     "window_start": "2026-12-01", "window_end": "2026-12-10", "verify_source": "cn_macro_monthly"}
  ]
}
dimensions 必须包含全部五个维度且各出现一次。"""

_RETRY_INSTRUCTION = (
    "上一次输出不符合约定：不是可直接解析的纯 JSON，或结构/字段/取值不合法。"
    "请只输出符合约定结构的纯 JSON 对象，不要包含任何解释或 markdown 标记。"
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# -- JSON 校验 -------------------------------------------------------------


def _require_non_empty_str(value: object, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"字段 {key} 必须是非空字符串。")
    return value.strip()


def parse_synthesis_payload(raw: object) -> tuple[Optional[dict], Optional[str]]:
    """严格解析模型 JSON。成功返回 (payload, None)，否则 (None, reason)。"""
    if not isinstance(raw, str) or not raw.strip():
        return None, "模型输出为空。"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"模型输出不是合法 JSON：{exc.msg}"
    if not isinstance(data, dict):
        return None, "JSON 顶层必须是对象。"
    try:
        _require_non_empty_str(data.get("summary"), "summary")
        _require_non_empty_str(data.get("action_advice"), "action_advice")

        raw_dims = data.get("dimensions")
        if not isinstance(raw_dims, list):
            raise ValueError("dimensions 必须是数组。")
        seen: set[str] = set()
        for item in raw_dims:
            if not isinstance(item, dict):
                raise ValueError("dimensions 元素必须是对象。")
            dim = item.get("dimension")
            if dim not in DIMENSIONS:
                raise ValueError(f"dimension 非法：{dim}")
            if dim in seen:
                raise ValueError(f"dimension 重复：{dim}")
            seen.add(dim)
            signal = item.get("signal")
            if not isinstance(signal, int) or not -2 <= signal <= 2:
                raise ValueError(f"{dim}.signal 必须是 -2..2 整数。")
            conf = item.get("confidence")
            if not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
                raise ValueError(f"{dim}.confidence 必须是 0..1。")
            if item.get("trend") not in TRENDS:
                raise ValueError(f"{dim}.trend 必须是 up/down/flat。")
            rationale = item.get("rationale", "")
            if not isinstance(rationale, str):
                raise ValueError(f"{dim}.rationale 必须是字符串。")
        if seen != set(DIMENSIONS):
            raise ValueError("dimensions 必须且只能包含五个维度。")

        probs = data.get("cycle_probs")
        if not isinstance(probs, dict):
            raise ValueError("cycle_probs 必须是对象。")
        for key in CYCLE_KEYS:
            value = probs.get(key)
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError(f"cycle_probs.{key} 必须是 0..1。")
        if not 0.9 <= sum(probs[k] for k in CYCLE_KEYS) <= 1.1:
            raise ValueError("cycle_probs 合计应接近 1。")

        allocation = data.get("allocation")
        if not isinstance(allocation, dict):
            raise ValueError("allocation 必须是对象。")
        for key in ASSET_KEYS:
            value = allocation.get(key)
            if not isinstance(value, int) or not -2 <= value <= 2:
                raise ValueError(f"allocation.{key} 必须是 -2..2 整数。")

        triggers = data.get("risk_triggers")
        if not isinstance(triggers, list) or not 1 <= len(triggers) <= 5:
            raise ValueError("risk_triggers 必须是 1~5 条。")
        for trigger in triggers:
            if not isinstance(trigger, str) or not trigger.strip():
                raise ValueError("risk_triggers 条目必须是非空字符串。")

        claims = data.get("claims")
        if not isinstance(claims, list) or not 5 <= len(claims) <= 10:
            raise ValueError("claims 必须是 5~10 条。")
        for index, claim in enumerate(claims):
            if not isinstance(claim, dict):
                raise ValueError(f"claims[{index}] 必须是对象。")
            if claim.get("dimension") not in DIMENSIONS:
                raise ValueError(f"claims[{index}].dimension 非法。")
            _require_non_empty_str(claim.get("text"), f"claims[{index}].text")
            _require_non_empty_str(claim.get("metric"), f"claims[{index}].metric")
            if claim.get("direction") not in DIRECTIONS:
                raise ValueError(f"claims[{index}].direction 必须是 up/down/flat。")
            _require_non_empty_str(
                claim.get("predicted_value"), f"claims[{index}].predicted_value"
            )
            probability = claim.get("probability")
            if not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
                raise ValueError(f"claims[{index}].probability 必须是 0..1。")
            for date_key in ("window_start", "window_end"):
                date_value = claim.get(date_key)
                if not isinstance(date_value, str) or not _DATE_RE.match(date_value):
                    raise ValueError(f"claims[{index}].{date_key} 必须是 YYYY-MM-DD。")
            _require_non_empty_str(
                claim.get("verify_source"), f"claims[{index}].verify_source"
            )
            if claim["window_start"] > claim["window_end"]:
                raise ValueError(f"claims[{index}] 验证窗口起止颠倒。")
    except ValueError as exc:
        return None, str(exc)
    return data, None


# -- 组装 ------------------------------------------------------------------


def _build_dimensions(
    payload: dict, teams: list[TeamCoverage]
) -> list[DimensionSignal]:
    run_by_team = {item.team: item.run_id for item in teams if item.present}
    raw_by_dim = {item["dimension"]: item for item in payload["dimensions"]}
    signals: list[DimensionSignal] = []
    for dim in DIMENSIONS:
        raw = raw_by_dim[dim]
        source_run_ids = [
            run_id
            for team in DIMENSION_TEAMS[dim]
            if (run_id := run_by_team.get(team))
        ]
        signals.append(
            DimensionSignal(
                dimension=dim,
                signal=int(raw["signal"]),
                confidence=float(raw["confidence"]),
                trend=raw["trend"],
                weight=DIMENSION_WEIGHTS[dim],
                source_run_ids=source_run_ids,
                rationale=raw.get("rationale", "").strip()[:80],
            )
        )
    return signals


def _normalize_cycle_probs(payload: dict) -> dict[str, float]:
    probs = {key: float(payload["cycle_probs"][key]) for key in CYCLE_KEYS}
    total = sum(probs.values())
    return {key: round(probs[key] / total, 2) for key in CYCLE_KEYS}


def _build_claims(payload: dict) -> list[SynthesisClaim]:
    return [
        SynthesisClaim(
            dimension=claim["dimension"],
            text=claim["text"].strip(),
            metric=claim["metric"].strip(),
            direction=claim["direction"],
            predicted_value=claim["predicted_value"].strip(),
            probability=float(claim["probability"]),
            window_start=claim["window_start"],
            window_end=claim["window_end"],
            verify_source=claim["verify_source"].strip(),
        )
        for claim in payload["claims"]
    ]


def _compute_mcs(dimensions: list[DimensionSignal]) -> float:
    """计算宏观综合指数：50 中性，signal 加权 × 置信度折算。"""
    total_weight = sum(dim.weight for dim in dimensions)
    weighted_conf = (
        sum(dim.weight * dim.confidence for dim in dimensions) / total_weight
    )
    confidence_factor = 0.5 + 0.5 * weighted_conf
    raw = sum(dim.weight * dim.signal for dim in dimensions)
    return round(50 + raw * 25 * confidence_factor, 1)


# -- 服务 ------------------------------------------------------------------


class MacroSynthesisService:
    """宏观量化汇总应用服务。"""

    def __init__(
        self,
        repository: Optional[MacroSynthesisRepository] = None,
        llm_factory: Optional[object] = None,
        store: Optional[object] = None,
    ) -> None:
        self._repo = repository
        self._llm_factory = llm_factory
        self._store = store

    def _get_repo(self) -> MacroSynthesisRepository:
        if self._repo is None:
            self._repo = MacroSynthesisRepository()
        return self._repo

    def _build_llm(self) -> object:
        if self._llm_factory is not None:
            return self._llm_factory()
        from src.providers.chat import ChatLLM

        return ChatLLM()

    def coverage(self, economy: str, period_type: str, period: Optional[str] = None):
        """返回 (period, teams) 覆盖情况。"""
        period = period or periods.current_period(period_type)
        periods.validate(period_type, period)
        teams = coverage.collect(period_type, period, self._store)
        return period, teams

    def synthesize(
        self,
        economy: str,
        period_type: str = "month",
        period: Optional[str] = None,
        allow_partial: bool = True,
    ) -> tuple[SynthesisReport, bool]:
        """产出（或复用）一期量化汇总报告。allow_partial 一期恒允许。"""
        period = period or periods.current_period(period_type)
        periods.validate(period_type, period)

        repo = self._get_repo()
        existing = repo.get_report(economy, period_type, period)
        if existing is not None:
            return existing, True

        slot = f"{economy}|{period_type}|{period}"
        if not _acquire_slot(slot):
            raise SynthesisInProgressError("该期汇总分析正在生成中，请稍候。")
        try:
            existing = repo.get_report(economy, period_type, period)
            if existing is not None:
                return existing, True

            teams = coverage.collect(period_type, period, self._store)
            materials = coverage.load_materials(teams, self._store)

            label = periods.period_label(period_type, period)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": self._build_user_message(
                        economy, label, materials
                    ),
                },
            ]

            llm = self._build_llm()
            payload: Optional[dict] = None
            last_reason = "未知原因。"
            for attempt in range(2):
                raw = self._invoke_llm(llm, messages)
                payload, last_reason = parse_synthesis_payload(raw)
                if payload is not None:
                    break
                if attempt == 0:
                    messages = [
                        *messages,
                        {"role": "assistant", "content": str(raw or "")},
                        {"role": "user", "content": _RETRY_INSTRUCTION},
                    ]
            if payload is None:
                raise SynthesisFailedError(
                    f"模型输出连续两次不符合约定（{last_reason}），请稍后重试。"
                )

            dimensions = _build_dimensions(payload, teams)
            mcs = _compute_mcs(dimensions)

            previous = repo.list_reports(economy, limit=1)
            mcs_delta = (
                round(mcs - previous[0].mcs, 1) if previous else None
            )

            report = SynthesisReport(
                economy=economy,
                period_type=period_type,
                period=period,
                period_label=label,
                mcs=mcs,
                mcs_delta=mcs_delta,
                cycle_probs=_normalize_cycle_probs(payload),
                allocation={
                    key: int(payload["allocation"][key]) for key in ASSET_KEYS
                },
                summary=payload["summary"].strip(),
                action_advice=payload["action_advice"].strip(),
                risk_triggers=[item.strip() for item in payload["risk_triggers"]],
                teams=teams,
                dimensions=dimensions,
                claims=_build_claims(payload),
            )
            try:
                stored = repo.insert_report(report)
            except SynthesisDBError as exc:
                raise SynthesisFailedError(str(exc)) from exc
            return stored, False
        finally:
            _release_slot(slot)

    @staticmethod
    def _build_user_message(economy: str, label: str, materials: list) -> str:
        lines = [
            f"经济体：{economy}",
            f"分析期次：{label}",
            "",
        ]
        if materials:
            lines.append("以下是各智能体团队在该期的分析结论：")
            for material in materials:
                lines.extend(
                    [
                        "",
                        f"===== {material.title}（{material.team}）日期：{material.date} =====",
                        material.report,
                    ]
                )
        else:
            lines.extend(
                [
                    "本期没有任何智能体团队的分析结论。",
                    "请基于你掌握的公开宏观信息，以低置信度（各维度 confidence <= 0.4）给出谨慎判断，",
                    "并在 claims 中给出可验证预测。",
                ]
            )
        lines.extend(["", "请严格按系统要求只输出纯 JSON。"])
        return "\n".join(lines)

    @staticmethod
    def _invoke_llm(llm: object, messages: list[dict]) -> str:
        timeout = int(get_env_config().llm.timeout_seconds)
        try:
            response = llm.chat(messages, timeout=timeout)
        except Exception as exc:
            name = exc.__class__.__name__.lower()
            if "timeout" in name or "timed out" in str(exc).lower():
                raise SynthesisLLMTimeoutError("汇总分析请求超时，请稍后重试。") from exc
            raise SynthesisFailedError(f"模型调用失败：{exc}") from exc
        content = getattr(response, "content", None)
        return content if isinstance(content, str) else ""
