"""宏观量化汇总应用服务。

流程：覆盖归集 -> 构建团队材料 -> LLM 输出强约束 JSON -> 严格校验 ->
服务端重算 MCS / 归一化周期概率 -> 持久化。模型只提供结构化判断，
权重、指数与标识均由服务端确定。
"""

from __future__ import annotations

import json
import re
import threading
from datetime import date
from typing import Optional

from src.config.accessor import get_env_config

from . import coverage, periods, verifiers
from .db import MacroSynthesisRepository, SynthesisDBError
from .models import (
    ASSET_KEYS,
    CLAIM_STATUS_DATA_MISSING,
    CLAIM_STATUS_HIT,
    CLAIM_STATUS_MISS,
    CLAIM_STATUS_PARTIAL,
    CLAIM_STATUS_PENDING,
    CLAIM_TERMINAL_STATUSES,
    CYCLE_KEYS,
    DIMENSIONS,
    DIMENSION_TEAMS,
    DIMENSION_WEIGHTS,
    DIRECTIONS,
    REVIEW_TYPE_AI,
    REVIEW_TYPE_MANUAL,
    TRENDS,
    DimensionSignal,
    SynthesisClaim,
    SynthesisReport,
    SynthesisReview,
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
  verify_source 取值约定：指数/行情点位用 daily_bar（metric 填工程代码，如沪深300填 000300.SH）；
  汇率用 fx_rate（metric 填六位货币对，如 USDCNY）；宏观月度指标用 cn_macro_monthly 等。
- 5~10 条命题中，至少包含 2 条 verify_source 为 daily_bar 或 fx_rate 的行情/汇率类可机判命题。
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


REVIEW_SYSTEM_PROMPT = """你是严谨的宏观研究质检主管。请依据一份宏观汇总报告的可验证命题（claims）
及其到期后的实际数据判定结果，给出客观、尖锐、有建设性的结构化复盘。只输出纯 JSON。

输出结构：
{
  "comment": "总体点评：原结论是否成立、对节奏与拐点的把握如何，100~300字",
  "attribution": "偏差归因：区分数据问题、逻辑问题、突发外生事件或模型倾向；并明确指出是否存在系统性偏多或偏空",
  "lessons": "改进建议：下期应加强/弱化哪些信号、关注哪些指标或触发条件，具体可执行"
}
不要回避问题，也不要在缺乏证据时过度批评；以判定明细为唯一依据。"""


def parse_review_payload(raw: object) -> tuple[Optional[dict], Optional[str]]:
    """解析 AI 复盘 JSON。"""
    if not isinstance(raw, str) or not raw.strip():
        return None, "复盘输出为空。"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"复盘输出不是合法 JSON：{exc.msg}"
    if not isinstance(data, dict):
        return None, "复盘 JSON 顶层必须是对象。"
    try:
        for key in ("comment", "attribution", "lessons"):
            value = data.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"复盘字段 {key} 必须是非空字符串。")
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

    # -- 二期：判定与复盘 -------------------------------------------------

    def verify_report(self, report_id: int) -> SynthesisReport:
        """扫描报告中已到期命题并取数判定。

        * pending：仅当 window_end <= 今天才判定，未到期保持 pending；
        * data_missing：允许重试（数据可能在窗口后补灌）；
        * hit/miss/partial：终态不重判。
        """
        repo = self._get_repo()
        report = repo.get_report_by_id(report_id)
        if report is None:
            raise SynthesisServiceError("汇总报告不存在。")
        today = date.today().isoformat()
        for claim in report.claims:
            if claim.id is None:
                continue
            if claim.status in CLAIM_TERMINAL_STATUSES:
                continue
            if claim.status == CLAIM_STATUS_PENDING and claim.window_end > today:
                continue
            status, actual_value, observed_date = verifiers.verify_claim(
                repo._conn, claim
            )
            repo.update_claim_verification(
                claim.id, status, actual_value, observed_date
            )
        return repo.get_report_by_id(report_id)

    @staticmethod
    def _review_stats(report: SynthesisReport) -> dict:
        """统计判定结果、方向命中率与 Brier 分数（仅已判定命题）。"""
        counts = {
            CLAIM_STATUS_PENDING: 0,
            CLAIM_STATUS_HIT: 0,
            CLAIM_STATUS_MISS: 0,
            CLAIM_STATUS_PARTIAL: 0,
            CLAIM_STATUS_DATA_MISSING: 0,
        }
        brier_terms: list[float] = []
        weighted_hits = 0.0
        resolved = 0
        for claim in report.claims:
            counts[claim.status] = counts.get(claim.status, 0) + 1
            if claim.status == CLAIM_STATUS_HIT:
                outcome = 1.0
            elif claim.status == CLAIM_STATUS_MISS:
                outcome = 0.0
            elif claim.status == CLAIM_STATUS_PARTIAL:
                outcome = 0.5
            else:
                continue
            resolved += 1
            weighted_hits += outcome
            brier_terms.append((float(claim.probability) - outcome) ** 2)
        hit_rate = round(weighted_hits / resolved, 3) if resolved else None
        brier = (
            round(sum(brier_terms) / len(brier_terms), 3) if brier_terms else None
        )
        return {
            "counts": counts,
            "resolved": resolved,
            "hit_rate": hit_rate,
            "brier_score": brier,
        }

    def ai_review(self, report_id: int) -> tuple[SynthesisReport, SynthesisReview]:
        """先确保到期命题已判定，再由 AI 生成结构化复盘点评。"""
        report = self.verify_report(report_id)
        stats = self._review_stats(report)
        if stats["resolved"] == 0:
            raise SynthesisServiceError(
                "当前没有任何可判定的命题（验证窗口可能未到期或实际数据缺失），"
                "暂无法生成有依据的 AI 复盘。"
            )
        messages = [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_review_message(report, stats)},
        ]
        llm = self._build_llm()
        payload: Optional[dict] = None
        last_reason = "未知原因。"
        for attempt in range(2):
            raw = self._invoke_llm(llm, messages)
            payload, last_reason = parse_review_payload(raw)
            if payload is not None:
                break
            messages = [
                *messages,
                {"role": "assistant", "content": str(raw or "")},
                {"role": "user", "content": _RETRY_INSTRUCTION},
            ]
        if payload is None:
            raise SynthesisFailedError(f"复盘输出不符合约定：{last_reason}")

        repo = self._get_repo()
        review = SynthesisReview(
            report_id=report_id,
            review_type=REVIEW_TYPE_AI,
            hit_rate=stats["hit_rate"],
            brier_score=stats["brier_score"],
            counts=stats["counts"],
            comment=payload["comment"].strip(),
            attribution=payload["attribution"].strip(),
            lessons=payload["lessons"].strip(),
            reviewer="ai",
        )
        stored_review = repo.insert_review(review)
        refreshed = repo.get_report_by_id(report_id)
        return refreshed, stored_review

    def add_comment(
        self,
        report_id: int,
        comment: str,
        hit_rate: Optional[float] = None,
        reviewer: Optional[str] = None,
    ) -> SynthesisReport:
        """追加一条人工点评。"""
        text = (comment or "").strip()
        if not text:
            raise SynthesisServiceError("点评内容不能为空。")
        if hit_rate is not None and not 0 <= hit_rate <= 1:
            raise SynthesisServiceError("人工评分必须在 0~1 之间。")
        repo = self._get_repo()
        if repo.get_report_by_id(report_id) is None:
            raise SynthesisServiceError("汇总报告不存在。")
        review = SynthesisReview(
            report_id=report_id,
            review_type=REVIEW_TYPE_MANUAL,
            hit_rate=round(hit_rate, 3) if hit_rate is not None else None,
            comment=text,
            reviewer=reviewer or "user",
        )
        repo.insert_review(review)
        return repo.get_report_by_id(report_id)

    @staticmethod
    def _build_review_message(report: SynthesisReport, stats: dict) -> str:
        lines = [
            f"报告期次：{report.period_label}",
            f"总体结论：{report.summary}",
            "",
            f"判定统计：{stats['counts']}",
            f"方向命中率：{stats['hit_rate']}",
            f"Brier 概率精度：{stats['brier_score']}"
            "（0~2，越低越准；0.25 为无技巧基准）",
            "",
            "各命题判定明细（预测 / 概率 / 实际值 / 结果）：",
        ]
        for claim in report.claims:
            lines.append(
                f"- [{claim.status}] {claim.text}｜预测 {claim.predicted_value}"
                f"（概率 {claim.probability}）｜实际 {claim.actual_value or '无数据'}"
            )
        lines.extend(
            [
                "",
                "请基于以上事实输出复盘 JSON：comment 总体点评（结论是否成立、"
                "节奏与拐点把握）、attribution 偏差归因（数据/逻辑/突发事件/模型倾向，"
                "并指出是否存在系统性偏多或偏空）、lessons 对下期分析的具体改进建议。"
                "只输出纯 JSON。",
            ]
        )
        return "\n".join(lines)
