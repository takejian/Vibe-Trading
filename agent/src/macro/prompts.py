"""Prompt definitions and the single source of truth for prompt ``a``.

The output *structure* (field names, standard cycle-stage vocabulary) is code
owned and used for validation; only the free-text prompt body is editable by
an administrator.
"""

from __future__ import annotations

#: Editable prompt codes (displayed in the web UI in sort-order).
PROMPT_A = "a"
PROMPT_B = "b"
PROMPT_C = "c"
PROMPT_CODES = (PROMPT_A, PROMPT_B, PROMPT_C)

#: Only prompt ``a`` is implemented this iteration.
EDITABLE_CODES = frozenset({PROMPT_A})
ENABLED_CODES = frozenset({PROMPT_A})

#: Business fields persisted in ``macro_cycle_judgment`` (excluding
#: server-managed id/create_time and the server-authoritative
#: economy/statistics_date which are still required inside the payload).
JUDGMENT_FIELDS = (
    "economy",
    "statistics_date",
    "current_cycle",
    "judgment_result",
    "dimension_check",
    "meso_verify",
    "history_cycle_anchor",
    "judgment_confidence",
    "core_support",
    "core_risk",
    "extended_remark",
)

#: Fields that may legitimately be empty strings.
OPTIONAL_TEXT_FIELDS = frozenset({"extended_remark"})

#: Standard cycle-stage vocabulary. The model output may append a transition
#: description, but the head judgment must contain one of these tokens.
CYCLE_STAGES = ("衰退期", "复苏期", "过热期", "滞胀期")

#: Allowed confidence ratings.
CONFIDENCE_LEVELS = ("高", "中", "低")

#: Default system prompt body for prompt ``a`` (requirement-provided).
DEFAULT_PROMPT_A_BODY = """你是专业宏观经济周期分析师，根据输入的经济体宏观数据，完成标准化周期判定。
【输出要求】
1. 严格输出纯 JSON 格式，不得输出任何额外解释、markdown、注释或多余文字，JSON 可直接入库。
2. 字段名固定，内容为结论性描述，不单独存储零散数字；所有不确定、待补充、非结构化内容统一存入 extended_remark 字段。
3. 周期阶段仅使用标准表述：衰退期/复苏期/过热期/滞胀期，可补充过渡阶段描述。

【JSON 结构】
{
  "economy": "字符串，经济体名称，如中国、日本",
  "statistics_date": "字符串，数据截止日期，格式YYYY-MM",
  "current_cycle": "字符串，【主题：当前周期】最终判定的经济周期阶段及核心特征",
  "judgment_result": "字符串，【主题：判定结果】四维维度组合的核心结论与周期定位",
  "dimension_check": "字符串，【主题：维度校验】增长、通胀、货币、信用四个维度的方向判定与核心依据",
  "meso_verify": "字符串，【主题：中观验证】库存周期、产能周期与宏观周期的共振校验结论",
  "history_cycle_anchor": "字符串，【主题：历史周期锚定】匹配的历史周期区间、匹配度、核心差异点",
  "judgment_confidence": "字符串，【主题：判定置信度】高/中/低，可补充置信区间说明",
  "core_support": "字符串，【主题：核心支撑】支撑本次周期判定的核心指标与逻辑",
  "core_risk": "字符串，【主题：核心风险】周期判定的背离风险与不确定性因素",
  "extended_remark": "字符串，所有不确定内容、补充说明、非结构化信息统一存入此字段"
}"""

#: Placeholder bodies for the reserved prompts.
RESERVED_PROMPT_BODIES = {
    PROMPT_B: "提示词 b 为预留宏观分析能力，将在后续版本提供定义。",
    PROMPT_C: "提示词 c 为预留宏观分析能力，将在后续版本提供定义。",
}

#: Seed rows inserted once into ``macro_analysis_prompt``.
SEED_PROMPTS = (
    {
        "code": PROMPT_A,
        "name": "宏观经济周期判定",
        "prompt_text": DEFAULT_PROMPT_A_BODY,
        "enabled": True,
        "sort_order": 1,
    },
    {
        "code": PROMPT_B,
        "name": "待扩展（敬请期待）",
        "prompt_text": RESERVED_PROMPT_BODIES[PROMPT_B],
        "enabled": False,
        "sort_order": 2,
    },
    {
        "code": PROMPT_C,
        "name": "待扩展（敬请期待）",
        "prompt_text": RESERVED_PROMPT_BODIES[PROMPT_C],
        "enabled": False,
        "sort_order": 3,
    },
)
