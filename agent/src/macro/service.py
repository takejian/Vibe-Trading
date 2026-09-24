"""Macro cycle judgment service: readiness, one-shot LLM call, validation.

The service orchestrates the prompt-``a`` flow without any agent loop:

  economy validation -> readiness assessment -> same-month dedupe ->
  per-key in-process lock -> one-shot LLM call (exactly one retry on invalid
  output) -> strict structural validation -> MySQL persistence.

LLM, readiness probe and repository are constructor-injected so the whole
service is unit-testable without sockets or a live MySQL server.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Callable, Optional

from src.config.accessor import get_env_config
from src.macro.models import DataReadiness, JudgeResult, MacroJudgment, PromptDef
from src.macro.prompts import (
    CONFIDENCE_LEVELS,
    CYCLE_STAGES,
    EDITABLE_CODES,
    ENABLED_CODES,
    JUDGMENT_FIELDS,
    OPTIONAL_TEXT_FIELDS,
    PROMPT_A,
    PROMPT_CODES,
)
from src.macro.readiness import (
    PRESET_ECONOMIES,
    ReadinessAssessor,
    canonicalize_economy,
)
from src.macro.repository import MacroRepository, MySQLMacroRepository

logger = logging.getLogger(__name__)

_MONTH_INPUT_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")

# Process-wide judgment slots: f"{economy}|{YYYY-MM}" -> busy. FastAPI runs
# sync endpoints in a threadpool, so an in-process set is sufficient for the
# single-server deployment described by the loopback contract.
_JUDGE_SLOTS: set[str] = set()
_JUDGE_SLOTS_GUARD = threading.Lock()
_SCHEMA_ONCE = threading.Lock()
_SCHEMA_INITIALIZED = False


# ---------------------------------------------------------------------------
# Errors (mapped to HTTP status codes by the API layer)
# ---------------------------------------------------------------------------


class MacroServiceError(RuntimeError):
    """Base class; ``status_code`` / ``code`` are consumed by the API route."""

    status_code = 400
    code = "macro_error"


class UnsupportedEconomyError(MacroServiceError):
    status_code = 400
    code = "unsupported_economy"


class InvalidMonthError(MacroServiceError):
    status_code = 400
    code = "invalid_statistics_date"


class MacroDataInsufficientError(MacroServiceError):
    status_code = 422
    code = "data_insufficient"

    def __init__(self, readiness: DataReadiness) -> None:
        super().__init__(readiness.reason or "当前宏观数据不足，暂无法分析。")
        self.readiness = readiness


class MacroGenerationInProgressError(MacroServiceError):
    status_code = 409
    code = "generation_in_progress"


class PromptNotFoundError(MacroServiceError):
    status_code = 404
    code = "prompt_not_found"


class PromptNotEditableError(MacroServiceError):
    status_code = 409
    code = "prompt_not_editable"


class MacroLLMTimeoutError(MacroServiceError):
    status_code = 504
    code = "llm_timeout"


class MacroAnalysisFailedError(MacroServiceError):
    status_code = 502
    code = "analysis_failed"


# ---------------------------------------------------------------------------
# Pure validation helpers
# ---------------------------------------------------------------------------


def parse_judgment_payload(raw: object) -> tuple[Optional[dict], Optional[str]]:
    """Strictly parse and validate the model's JSON output.

    Returns ``(payload, None)`` on success and ``(None, reason)`` on failure.
    No lenient markdown-fence extraction is performed: pure JSON is part of
    the contract and a violation triggers the one-shot retry.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None, "模型输出为空。"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"模型输出不是合法 JSON：{exc.msg}"
    if not isinstance(data, dict):
        return None, "JSON 顶层结构必须是对象。"
    for key in JUDGMENT_FIELDS:
        if key not in data:
            return None, f"缺少必需字段：{key}"
        value = data[key]
        if not isinstance(value, str):
            return None, f"字段 {key} 必须是字符串。"
        if key not in OPTIONAL_TEXT_FIELDS and not value.strip():
            return None, f"字段 {key} 不允许为空。"
    if not any(stage in data["current_cycle"] for stage in CYCLE_STAGES):
        return (
            None,
            "current_cycle 未使用标准周期阶段表述（衰退期/复苏期/过热期/滞胀期）。",
        )
    if not any(level in data["judgment_confidence"] for level in CONFIDENCE_LEVELS):
        return None, "judgment_confidence 未包含标准置信度评级（高/中/低）。"
    return data, None


def _is_timeout_exception(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    name = exc.__class__.__name__.lower()
    return "timeout" in name or "timedout" in name or "timed out" in str(exc).lower()


def _build_user_message(economy: str, statistics_date: str, supplement: str) -> str:
    lines = [
        f"经济体：{economy}",
        f"数据截止月份：{statistics_date}（格式 YYYY-MM）",
    ]
    if supplement:
        lines.append(f"使用者补充说明：{supplement}")
    lines.append("请严格按系统要求输出纯 JSON，不要输出任何额外文字。")
    return "\n".join(lines)


_RETRY_INSTRUCTION = (
    "上一次输出不符合约定（不是可直接解析的纯 JSON、字段不完整，或周期阶段/"
    "置信度未使用标准表述）。请重新输出，且只输出符合约定结构的纯 JSON 对象，"
    "不要包含任何解释、markdown 代码块或多余文字。"
)

#: Width of macro_cycle_judgment.judgment_confidence (varchar(100) in the
#: user-owned DDL). The rating column stores the concise 高/中/低 conclusion;
#: any longer rationale is preserved in extended_remark instead of dropped.
_CONFIDENCE_COLUMN_LIMIT = 100
_CONFIDENCE_CUT_PUNCTUATION = ("；", "。", "，", ";", ",")
_CONFIDENCE_OVERFLOW_PREFIX = "【置信度补充说明】"


def _fit_confidence_column(raw: str) -> tuple[str, str]:
    """Split an over-long confidence string into (column value, overflow).

    Models sometimes append a long confidence-interval narrative to the
    高/中/低 rating. The leading clause is shortened on punctuation to fit
    ``varchar(100)``; the original full text is returned for extended_remark
    so no model content is lost. Returns ``(value, "")`` when already short.
    """
    value = (raw or "").strip()
    if len(value) <= _CONFIDENCE_COLUMN_LIMIT:
        return value, ""
    budget = _CONFIDENCE_COLUMN_LIMIT - 1  # reserve one char for "…"
    head = value[:budget]
    for sep in _CONFIDENCE_CUT_PUNCTUATION:
        idx = head.rfind(sep)
        if idx >= 1:
            head = head[:idx]
            break
    return head.strip()[:budget].rstrip() + "…", value


def _merge_confidence_overflow(remark: str, overflow: str) -> str:
    if not overflow:
        return remark
    suffix = f"{_CONFIDENCE_OVERFLOW_PREFIX}{overflow}"
    return f"{remark}\n{suffix}" if remark else suffix


class MacroAnalysisService:
    """Application service for macro prompts and cycle judgments."""

    def __init__(
        self,
        repository: Optional[MacroRepository] = None,
        assessor: Optional[ReadinessAssessor] = None,
        llm_factory: Optional[Callable[[], object]] = None,
    ) -> None:
        self._repo = repository or MySQLMacroRepository()
        self._assessor = assessor or ReadinessAssessor()
        self._llm_factory = llm_factory  # None -> lazy ChatLLM

    # -- infrastructure --------------------------------------------------

    def _ensure_schema(self) -> None:
        global _SCHEMA_INITIALIZED
        if not isinstance(self._repo, MySQLMacroRepository) or _SCHEMA_INITIALIZED:
            return
        with _SCHEMA_ONCE:
            if _SCHEMA_INITIALIZED:
                return
            from src.macro.db import initialize_schema

            initialize_schema()
            _SCHEMA_INITIALIZED = True

    def _build_llm(self) -> object:
        if self._llm_factory is not None:
            return self._llm_factory()
        from src.providers.chat import ChatLLM

        return ChatLLM()

    # -- prompts ---------------------------------------------------------

    def list_prompts(self) -> list[PromptDef]:
        self._ensure_schema()
        return self._repo.list_prompts()

    def get_prompt(self, code: str) -> PromptDef:
        self._ensure_schema()
        if code not in PROMPT_CODES:
            raise PromptNotFoundError(f"未知提示词：{code}")
        prompt = self._repo.get_prompt(code)
        if prompt is None:
            raise PromptNotFoundError(f"提示词 {code} 尚未初始化。")
        return prompt

    def update_prompt_text(self, code: str, prompt_text: str) -> PromptDef:
        self._ensure_schema()
        if code not in PROMPT_CODES:
            raise PromptNotFoundError(f"未知提示词：{code}")
        if code not in EDITABLE_CODES:
            raise PromptNotEditableError(f"提示词 {code} 为预留提示词，本期不可编辑。")
        if not prompt_text or not prompt_text.strip():
            raise MacroServiceError("提示词正文不能为空。")
        updated = self._repo.update_prompt_text(code, prompt_text.strip())
        if updated is None:
            raise PromptNotFoundError(f"提示词 {code} 尚未初始化。")
        return updated

    # -- history ---------------------------------------------------------

    def list_judgments(self, economy: str) -> list[MacroJudgment]:
        self._ensure_schema()
        canonical = canonicalize_economy(economy)
        if canonical is None:
            raise UnsupportedEconomyError(
                f"暂不支持的经济体：{economy}；当前仅支持 {'、'.join(PRESET_ECONOMIES)}"
            )
        return self._repo.list_judgments(canonical)

    def get_judgment(self, economy: str, statistics_date: str) -> MacroJudgment:
        self._ensure_schema()
        canonical = canonicalize_economy(economy)
        if canonical is None:
            raise UnsupportedEconomyError(f"暂不支持的经济体：{economy}")
        if not _MONTH_INPUT_RE.match(statistics_date or ""):
            raise InvalidMonthError("statistics_date 必须为 YYYY-MM 格式。")
        judgment = self._repo.get_judgment(canonical, statistics_date)
        if judgment is None:
            raise PromptNotFoundError(
                f"未找到 {canonical} 在 {statistics_date} 的判定结果。"
            )
        return judgment

    def list_economies(self) -> list[str]:
        return list(PRESET_ECONOMIES)

    def assess_readiness(self, economy: str) -> DataReadiness:
        canonical = canonicalize_economy(economy)
        if canonical is None:
            raise UnsupportedEconomyError(
                f"暂不支持的经济体：{economy}；当前仅支持 {'、'.join(PRESET_ECONOMIES)}"
            )
        return self._assessor.assess(canonical)

    # -- judgment flow ---------------------------------------------------

    def judge(
        self,
        economy: str,
        statistics_date: Optional[str] = None,
        supplement: Optional[str] = None,
    ) -> JudgeResult:
        """Run (or reuse) a cycle judgment for one economy/month."""
        self._ensure_schema()

        canonical = canonicalize_economy(economy)
        if canonical is None:
            raise UnsupportedEconomyError(
                f"暂不支持的经济体：{economy}；当前仅支持 {'、'.join(PRESET_ECONOMIES)}"
            )
        if statistics_date and not _MONTH_INPUT_RE.match(statistics_date):
            raise InvalidMonthError("statistics_date 必须为 YYYY-MM 格式。")

        supplement = (supplement or "").strip()
        forced = bool(statistics_date or supplement)

        readiness: Optional[DataReadiness] = None
        if statistics_date:
            effective_month = statistics_date
        else:
            readiness = self._assessor.assess(canonical)
            effective_month = readiness.latest_month
            if not readiness.ready and not forced:
                raise MacroDataInsufficientError(readiness)

        # Dedupe: same economy + month reuses the stored judgment.
        existing = self._repo.get_judgment(canonical, effective_month)
        if existing is not None:
            return JudgeResult(judgment=existing, cached=True, readiness=readiness)

        slot = f"{canonical}|{effective_month}"
        if not self._acquire_slot(slot):
            raise MacroGenerationInProgressError(
                f"{canonical} {effective_month} 的宏观分析正在生成中，请稍候。"
            )
        try:
            # Re-check under the slot: a peer may have finished meanwhile.
            existing = self._repo.get_judgment(canonical, effective_month)
            if existing is not None:
                return JudgeResult(judgment=existing, cached=True, readiness=readiness)

            prompt = self._repo.get_prompt(PROMPT_A)
            if prompt is None:
                raise MacroAnalysisFailedError("提示词 a 未初始化，无法发起分析。")

            llm = self._build_llm()
            timeout = self._llm_timeout_seconds()
            messages: list[dict[str, str]] = [
                {"role": "system", "content": prompt.prompt_text},
                {
                    "role": "user",
                    "content": _build_user_message(canonical, effective_month, supplement),
                },
            ]

            payload: Optional[dict] = None
            last_reason = "未知原因。"
            for attempt in range(2):  # initial attempt + exactly one retry
                raw = self._invoke_llm(llm, messages, timeout)
                payload, last_reason = parse_judgment_payload(raw)
                if payload is not None:
                    break
                logger.info(
                    "macro judgment invalid output (attempt %d/2): %s",
                    attempt + 1,
                    last_reason,
                )
                if attempt == 0:
                    messages = [
                        *messages,
                        {"role": "assistant", "content": str(raw or "")},
                        {"role": "user", "content": _RETRY_INSTRUCTION},
                    ]
            if payload is None:
                raise MacroAnalysisFailedError(
                    f"模型输出连续两次不符合约定（{last_reason}），分析失败，请稍后重试。"
                )

            # Server owns the dedupe keys: never trust the model's month/name.
            confidence, confidence_overflow = _fit_confidence_column(
                payload["judgment_confidence"]
            )
            judgment = MacroJudgment(
                economy=canonical,
                statistics_date=effective_month,
                current_cycle=payload["current_cycle"].strip(),
                judgment_result=payload["judgment_result"].strip(),
                dimension_check=payload["dimension_check"].strip(),
                meso_verify=payload["meso_verify"].strip(),
                history_cycle_anchor=payload["history_cycle_anchor"].strip(),
                judgment_confidence=confidence,
                core_support=payload["core_support"].strip(),
                core_risk=payload["core_risk"].strip(),
                extended_remark=_merge_confidence_overflow(
                    payload["extended_remark"].strip(), confidence_overflow
                ),
            )
            stored = self._repo.insert_judgment(judgment)
            return JudgeResult(judgment=stored, cached=False, readiness=readiness)
        finally:
            self._release_slot(slot)

    def _invoke_llm(self, llm: object, messages: list[dict], timeout: int) -> str:
        try:
            response = llm.chat(messages, timeout=timeout)
        except Exception as exc:
            if _is_timeout_exception(exc):
                raise MacroLLMTimeoutError("宏观分析请求超时，请稍后重试。") from exc
            raise MacroAnalysisFailedError(f"模型调用失败：{exc}") from exc
        content = getattr(response, "content", None)
        return content if isinstance(content, str) else ""

    @staticmethod
    def _llm_timeout_seconds() -> int:
        cfg = get_env_config()
        override = cfg.macro.macro_llm_timeout
        return int(override) if override and override > 0 else int(cfg.llm.timeout_seconds)

    @staticmethod
    def _acquire_slot(slot: str) -> bool:
        with _JUDGE_SLOTS_GUARD:
            if slot in _JUDGE_SLOTS:
                return False
            _JUDGE_SLOTS.add(slot)
            return True

    @staticmethod
    def _release_slot(slot: str) -> None:
        with _JUDGE_SLOTS_GUARD:
            _JUDGE_SLOTS.discard(slot)

    # -- helpers exposed for future b/c enablement ----------------------

    @staticmethod
    def is_enabled(code: str) -> bool:
        return code in ENABLED_CODES
