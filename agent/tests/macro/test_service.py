"""MacroAnalysisService orchestration tests (fakes only, no I/O)."""

from __future__ import annotations

import threading

import pytest

from src.macro.service import (
    MacroAnalysisFailedError,
    MacroAnalysisService,
    MacroDataInsufficientError,
    MacroGenerationInProgressError,
    MacroLLMTimeoutError,
    PromptNotEditableError,
    UnsupportedEconomyError,
)

from .conftest import make_judgment, valid_payload


def _service(repo, assessor, llm):
    return MacroAnalysisService(
        repository=repo,
        assessor=assessor,
        llm_factory=lambda: llm,
    )


def test_successful_judgment_persists_all_fields_with_server_keys(
    fake_repo, ready_assessor
):
    from .conftest import FakeLLM

    llm = FakeLLM([valid_payload(economy="日本", statistics_date="2099-01")])
    service = _service(fake_repo, ready_assessor, llm)

    result = service.judge("china")

    assert result.cached is False
    assert llm.calls and llm.calls[0][0]["role"] == "system"
    assert len(llm.calls) == 1
    assert fake_repo.insert_count == 1
    stored = result.judgment
    # Server-authoritative dedupe keys override whatever the model reported.
    assert stored.economy == "中国"
    assert stored.statistics_date == "2026-08"
    assert "复苏期" in stored.current_cycle
    assert stored.judgment_confidence.startswith("中")
    assert stored.extended_remark
    # User message carries the canonical economy and effective month.
    user_msg = llm.calls[0][1]["content"]
    assert "经济体：中国" in user_msg and "2026-08" in user_msg


def test_existing_month_returns_cached_without_llm(fake_repo, ready_assessor):
    from .conftest import FakeLLM

    fake_repo.insert_judgment(make_judgment("中国", "2026-08"))
    llm = FakeLLM([valid_payload()])
    service = _service(fake_repo, ready_assessor, llm)

    result = service.judge("中国")

    assert result.cached is True
    assert result.judgment.statistics_date == "2026-08"
    assert llm.calls == []


def test_invalid_then_valid_retries_exactly_once(fake_repo, ready_assessor):
    from .conftest import FakeLLM

    llm = FakeLLM(["抱歉，结果如下：", valid_payload()])
    service = _service(fake_repo, ready_assessor, llm)

    result = service.judge("中国")

    assert len(llm.calls) == 2
    assert result.cached is False
    assert fake_repo.insert_count == 1
    # The retry instruction was sent as the second user turn.
    assert llm.calls[-1][-1]["role"] == "user"
    assert "重新输出" in llm.calls[-1][-1]["content"]


def test_two_invalid_outputs_fail_without_persisting(fake_repo, ready_assessor):
    from .conftest import FakeLLM

    llm = FakeLLM(["not json", "```json\n{}```"])
    service = _service(fake_repo, ready_assessor, llm)

    with pytest.raises(MacroAnalysisFailedError):
        service.judge("中国")
    assert len(llm.calls) == 2
    assert fake_repo.insert_count == 0


def test_long_confidence_fits_column_with_overflow_preserved(fake_repo, ready_assessor):
    from .conftest import FakeLLM

    long_confidence = "高（定性判断置信度较高，但" + "部分高频指标仍待回填，" * 9 + "）"
    assert len(long_confidence) > 100
    llm = FakeLLM([valid_payload(judgment_confidence=long_confidence)])
    service = _service(fake_repo, ready_assessor, llm)

    result = service.judge("中国")
    stored = result.judgment

    assert len(stored.judgment_confidence) <= 100
    assert stored.judgment_confidence.startswith("高")
    assert stored.judgment_confidence.endswith("…")
    # The full model narrative is preserved in extended_remark, together with
    # the original remark content (no information loss from the column cap).
    assert long_confidence in stored.extended_remark
    assert "【置信度补充说明】" in stored.extended_remark
    assert "部分月度数据口径待统一。" in stored.extended_remark
    assert fake_repo.insert_count == 1


def test_fit_confidence_column_helper():
    from src.macro.service import (
        _fit_confidence_column,
        _merge_confidence_overflow,
    )

    assert _fit_confidence_column("中（区间有限）") == ("中（区间有限）", "")

    no_punctuation = "高" + "据" * 150
    column, overflow = _fit_confidence_column(no_punctuation)
    assert len(column) == 100
    assert column.endswith("…")
    assert overflow == no_punctuation

    assert _merge_confidence_overflow("备注", "") == "备注"
    merged = _merge_confidence_overflow("备注", "全文")
    assert merged.startswith("备注")
    assert "【置信度补充说明】全文" in merged


def test_generation_in_progress_blocks_duplicate_requests(fake_repo, ready_assessor):
    from src.macro import service as service_module

    entered = threading.Event()
    release = threading.Event()

    class BlockingLLM:
        def chat(self, messages, tools=None, timeout=None):
            entered.set()
            release.wait(timeout=5)
            return type("Response", (), {"content": valid_payload()})()

    service = _service(fake_repo, ready_assessor, BlockingLLM())
    errors: list[Exception] = []

    def worker():
        try:
            service.judge("美国")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(timeout=2)

    # Duplicate while the first call is still running.
    with pytest.raises(MacroGenerationInProgressError):
        service.judge("美国")

    release.set()
    thread.join(timeout=5)
    assert errors == []
    assert fake_repo.insert_count == 1

    # Slot released afterwards: a second request finds the cached row.
    result = service.judge("美国")
    assert result.cached is True
    assert service_module._JUDGE_SLOTS == set()


def test_data_insufficient_blocks_until_supplement_or_month(
    fake_repo, insufficient_assessor
):
    from .conftest import FakeLLM

    llm = FakeLLM([valid_payload()])
    service = _service(fake_repo, insufficient_assessor, llm)

    with pytest.raises(MacroDataInsufficientError) as exc_info:
        service.judge("日本")
    assert llm.calls == []
    assert "数据不足" in str(exc_info.value)

    # Supplement bypasses the probe gate.
    result = service.judge("日本", supplement="请结合日方最新短观报告补充判断。")
    assert result.judgment.economy == "日本"
    assert llm.calls and len(llm.calls) == 1

    # Explicit month also bypasses (fresh LLM script).
    llm2 = FakeLLM([valid_payload()])
    service2 = _service(fake_repo, insufficient_assessor, llm2)
    result2 = service2.judge("欧元区", statistics_date="2026-05")
    assert result2.judgment.statistics_date == "2026-05"
    assert len(llm2.calls) == 1


def test_unsupported_economy_rejected(fake_repo, ready_assessor):
    from .conftest import FakeLLM

    service = _service(fake_repo, ready_assessor, FakeLLM([valid_payload()]))
    with pytest.raises(UnsupportedEconomyError):
        service.judge("巴西")
    assert fake_repo.insert_count == 0


def test_timeout_does_not_persist_and_releases_slot(fake_repo, ready_assessor):
    from .conftest import FakeLLM

    service = _service(fake_repo, ready_assessor, FakeLLM([TimeoutError("timed out")]))

    with pytest.raises(MacroLLMTimeoutError):
        service.judge("中国")
    assert fake_repo.insert_count == 0

    # Slot released: a follow-up request is allowed to run.
    service2 = _service(
        fake_repo,
        ready_assessor,
        FakeLLM([valid_payload()]),
    )
    result = service2.judge("中国")
    assert result.cached is False
    assert fake_repo.insert_count == 1


def test_prompt_edit_only_allowed_for_a_and_takes_effect(fake_repo, ready_assessor):
    from .conftest import FakeLLM

    with pytest.raises(PromptNotEditableError):
        _service(fake_repo, ready_assessor, None).update_prompt_text("b", "新正文")

    service = _service(fake_repo, ready_assessor, None)
    updated = service.update_prompt_text("a", "全新的系统提示词正文")
    assert updated.prompt_text == "全新的系统提示词正文"

    llm = FakeLLM([valid_payload()])
    judged = _service(fake_repo, ready_assessor, llm).judge("中国", statistics_date="2026-04")
    assert judged is not None
    assert llm.calls[0][0]["content"] == "全新的系统提示词正文"


def test_invalid_month_format_rejected(fake_repo, ready_assessor):
    from .conftest import FakeLLM

    service = _service(fake_repo, ready_assessor, FakeLLM([valid_payload()]))
    with pytest.raises(Exception, match="YYYY-MM"):
        service.judge("中国", statistics_date="2026/08")


def test_history_listing_is_descending(fake_repo, ready_assessor):
    service = _service(fake_repo, ready_assessor, None)
    fake_repo.insert_judgment(make_judgment("中国", "2026-05"))
    fake_repo.insert_judgment(make_judgment("中国", "2026-08"))
    fake_repo.insert_judgment(make_judgment("中国", "2026-07"))

    months = [j.statistics_date for j in service.list_judgments("中国")]
    assert months == ["2026-08", "2026-07", "2026-05"]
