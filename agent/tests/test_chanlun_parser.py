"""Tests for the fixed 7-dimension Chanlun report parser."""

from __future__ import annotations

import pytest

from src.watchlist.chanlun_parser import DIMENSION_KEYS, parse_chanlun_report

_SECTIONS = {
    1: ("**1. Structure read 结构读取**",
        "日线处于上升趋势，存在两个同向中枢；最近 6 笔端点如下……"),
    2: ("**2. Active pivots 活跃支点**",
        "ZG=10.50 / ZD=10.10 / ZZ=10.30，状态为中枢震荡。"),
    3: ("**3. Divergence 背驰**",
        "离开段 MACD 红绿柱面积小于前同向段，盘整背驰成立。"),
    4: ("**4. Buy/sell points 买卖点**",
        "三买成立：触发价 10.52，失效价 10.05；其余类别 none。"),
    5: ("**5. Multi-level plan 多级别计划**",
        "周线定方向、30m 择时，止损 9.90，目标看下一中枢上沿。"),
    6: ("**6. Elliott corroboration 艾略特验证**",
        "映射 1-2-3-4-5 推动结构，三铁律通过，与缠论共振。"),
}


def _report(score_line: str, confidence_line: str) -> str:
    lines = [text for idx in range(1, 7) for text in _SECTIONS[idx]]
    lines.append("**7. Chanlun score 缠论打分**")
    lines.append(score_line)
    lines.append(confidence_line)
    return "\n".join(lines)


def test_full_report_percent_confidence() -> None:
    parsed = parse_chanlun_report(_report("Score: +3", "Confidence: 78%"))
    assert parsed is not None
    assert list(parsed["dims"].keys()) == list(DIMENSION_KEYS)
    assert parsed["score"] == 3
    assert parsed["confidence"] == pytest.approx(0.78)
    assert "ZG=10.50" in parsed["dims"]["active_pivots"]
    assert "Score: +3" in parsed["dims"]["chanlun_score"]


def test_full_report_fraction_confidence_and_cn_headings() -> None:
    lines = [
        "### 1、结构读取 Structure read",
        "内容一",
        "### 2、活跃支点 Active pivots",
        "内容二",
        "### 3、背驰 Divergence",
        "内容三",
        "### 4、买卖点 Buy/sell points",
        "内容四",
        "### 5、多级别计划 Multi-level plan",
        "内容五",
        "### 6、艾略特验证 Elliott corroboration",
        "内容六",
        "### 7、缠论打分 Chanlun score",
        "打分：+2",
        "置信度：0.65",
    ]
    parsed = parse_chanlun_report("\n".join(lines))
    assert parsed is not None
    assert parsed["score"] == 2
    assert parsed["confidence"] == pytest.approx(0.65)


def test_real_world_cn_numeral_headings_with_inner_subsections() -> None:
    # Shape of an actual chanlun_analyst run (600519.SH, 2026-10-01):
    # top-level sections use Chinese numerals while per-level detail inside
    # section 1 uses Arabic-numbered subheadings that must NOT be consumed.
    lines = [
        "# 贵州茅台（600519.SH）缠论多级别技术分析报告",
        "前言",
        "## 一、结构解读（分级别）",
        "### 1. 周线（高级别）",
        "周线笔 W9 下 1363.35 → 进行中。",
        "### 2. 日线（本级别，31 根完整）",
        "日线 D2 下 1338.86 → 1228.10。",
        "### 3. 30 分钟（低级别）",
        "数据为空，不给结构。",
        "## 二、活跃中枢（详细参数）",
        "周线中枢 W-A：ZG = 1451.91 / ZD = 1355.18，延伸状态。",
        "## 三、背驰研判",
        "日线 D2 幅度收缩、斜率放缓，存在底背驰迹象，未经 MACD 面积验证。",
        "## 四、买卖点（三类）",
        "无已确认一买/二买/三买；1228.10 跌破则反抽失败。",
        "## 五、多级别联动操作计划",
        "周线偏空、日线反弹尝试，级别不对齐，以观望为主，≤2 成短线仓。",
        "## 六、艾略特波浪交叉验证（辅助，缠论为主）",
        "1539.98→1355.18=A、1355.18→1470.05=B（0.618）、1470.05→1151.01=C。",
        "## 七、缠论评分与结论",
        "**缠论结构评分：−1（5 分制，−5~+5）**：周线中枢下方 -2，日线底分型 +1。",
        "**结构置信度：55%**（30 分钟数据缺失、MACD 面积未量化）。",
        "## 风险提示",
        "假日跳空风险；未完成笔可能延伸。",
    ]
    parsed = parse_chanlun_report("\n".join(lines))
    assert parsed is not None
    assert parsed["score"] == -1
    assert parsed["confidence"] == pytest.approx(0.55)
    assert "W9" in parsed["dims"]["structure_read"]
    assert "1451.91" in parsed["dims"]["active_pivots"]
    # Inner Arabic subsections stayed inside dimension 1.
    assert "31 根完整" in parsed["dims"]["structure_read"]
    assert parsed["dims"]["active_pivots"].startswith("周线中枢")


def test_unicode_minus_and_equals_form() -> None:
    parsed = parse_chanlun_report(_report("缠论打分 = −4", "结构置信度 = 100%"))
    assert parsed is not None
    assert parsed["score"] == -4
    assert parsed["confidence"] == 1.0


def test_missing_section_returns_none() -> None:
    text = _report("Score: +3", "Confidence: 78%")
    text = text.replace(
        "**6. Elliott corroboration 艾略特验证**\n"
        "映射 1-2-3-4-5 推动结构，三铁律通过，与缠论共振。\n",
        "",
    )
    assert parse_chanlun_report(text) is None


def test_score_out_of_range_returns_none() -> None:
    assert parse_chanlun_report(_report("Score: +6", "Confidence: 78%")) is None
    assert parse_chanlun_report(_report("Score: -6", "Confidence: 78%")) is None


def test_confidence_out_of_range_returns_none() -> None:
    assert parse_chanlun_report(_report("Score: 2", "Confidence: 120%")) is None
    assert parse_chanlun_report(_report("Score: 2", "Confidence: 1.5")) is None


def test_boundary_values_legal() -> None:
    parsed = parse_chanlun_report(_report("Score: -5", "Confidence: 0%"))
    assert parsed is not None
    assert parsed["score"] == -5 and parsed["confidence"] == 0.0

    parsed = parse_chanlun_report(_report("Score: 5", "Confidence: 100%"))
    assert parsed is not None
    assert parsed["score"] == 5 and parsed["confidence"] == 1.0


def test_template_heading_is_not_a_value() -> None:
    """A copied 'score range' line must not be parsed as actual values."""
    report = _report(
        "Chanlun score range: −5..+5",
        "structural confidence 0–100%",
    )
    assert parse_chanlun_report(report) is None


@pytest.mark.parametrize("text", ["", "   ", "no structure here at all"])
def test_garbage_input_returns_none(text: str) -> None:
    assert parse_chanlun_report(text) is None
