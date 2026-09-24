"""HTTP contract tests for /api/macro/* routes (service fakes injected)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import macro_routes
from src.macro.models import DataReadiness
from src.macro.service import (
    MacroAnalysisFailedError,
    MacroAnalysisService,
    MacroDataInsufficientError,
    MacroGenerationInProgressError,
    MacroLLMTimeoutError,
    UnsupportedEconomyError,
)

from tests.macro.conftest import (
    FakeLLM,
    FakeRepository,
    build_assessor,
    make_judgment,
    valid_payload,
)


# The routes captured this exact function object at registration time, so it
# must remain the dependency-override key even when tests monkeypatch the
# module attribute.
_ORIGINAL_GET_SERVICE = macro_routes.get_macro_service


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    repo = FakeRepository()

    def fresh_service():
        return MacroAnalysisService(repository=repo, assessor=build_assessor())

    api_server.app.dependency_overrides[_ORIGINAL_GET_SERVICE] = fresh_service
    tc = TestClient(api_server.app, client=("127.0.0.1", 50001))
    tc.repo = repo  # type: ignore[attr-defined]
    try:
        yield tc
    finally:
        api_server.app.dependency_overrides.pop(_ORIGINAL_GET_SERVICE, None)


def _service_with(monkeypatch, repo, **judge_behavior):
    """Override the service factory with a small scripted stub."""

    class StubService:
        def list_prompts(self_inner):
            return FakeRepository().list_prompts()

        def get_prompt(self_inner, code):
            return FakeRepository().get_prompt(code)

        def update_prompt_text(self_inner, code, text):
            if code == "b":
                from src.macro.service import PromptNotEditableError

                raise PromptNotEditableError("reserved")
            return FakeRepository().update_prompt_text(code, text)

        def list_economies(self_inner):
            return ["中国", "美国", "日本", "欧元区"]

        def assess_readiness(self_inner, economy):
            if economy == "巴西":
                raise UnsupportedEconomyError("unsupported")
            return DataReadiness(ready=True, latest_month="2026-08")

        def list_judgments(self_inner, economy):
            return [
                make_judgment("中国", "2026-08", current_cycle="复苏期"),
                make_judgment("中国", "2026-07", current_cycle="复苏期"),
            ]

        def get_judgment(self_inner, economy, month):
            if month == "2026-09":
                from src.macro.service import PromptNotFoundError

                raise PromptNotFoundError("missing")
            return make_judgment(economy, month)

        def judge(self_inner, economy, statistics_date=None, supplement=None):
            if economy not in ("中国", "美国", "日本", "欧元区"):
                raise UnsupportedEconomyError("unsupported")
            kind = judge_behavior.get("kind", "ok")
            if kind == "insufficient":
                raise MacroDataInsufficientError(
                    DataReadiness(ready=False, latest_month="2026-08", reason="数据不足")
                )
            if kind == "progress":
                raise MacroGenerationInProgressError("生成中")
            if kind == "timeout":
                raise MacroLLMTimeoutError("超时")
            if kind == "failed":
                raise MacroAnalysisFailedError("失败")
            from src.macro.models import JudgeResult
            return JudgeResult(judgment=make_judgment("中国", "2026-08"), cached=(kind == "cached"))

    def factory():
        return StubService()

    api_server.app.dependency_overrides[_ORIGINAL_GET_SERVICE] = factory
    return factory


def test_prompts_list_shape(client: TestClient):
    resp = client.get("/api/macro/prompts")
    assert resp.status_code == 200
    prompts = resp.json()["prompts"]
    assert [p["code"] for p in prompts] == ["a", "b", "c"]
    a_prompt = prompts[0]
    assert a_prompt["enabled"] is True and a_prompt["editable"] is True
    assert a_prompt["can_edit"] is True
    assert prompts[1]["enabled"] is False


def test_run_judgment_success(client: TestClient):
    # Real service wired to the fake repository and a scripted LLM.
    llm = FakeLLM([valid_payload()])
    service = MacroAnalysisService(
        repository=client.repo,  # type: ignore[attr-defined]
        assessor=build_assessor(),
        llm_factory=lambda: llm,
    )
    def factory():
        return service

    api_server.app.dependency_overrides[_ORIGINAL_GET_SERVICE] = factory

    resp = client.post("/api/macro/cycle/judgments", json={"economy": "中国"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cached"] is False
    assert body["judgment"]["economy"] == "中国"
    assert body["judgment"]["statistics_date"] == "2026-08"


def test_run_judgment_cached(monkeypatch, client: TestClient):
    _service_with(monkeypatch, client.repo, kind="cached")
    resp = client.post("/api/macro/cycle/judgments", json={"economy": "中国"})
    assert resp.status_code == 200
    assert resp.json()["cached"] is True


def test_run_judgment_status_mappings(monkeypatch, client: TestClient):
    for kind, status in [
        ("insufficient", 422),
        ("progress", 409),
        ("timeout", 504),
        ("failed", 502),
    ]:
        _service_with(monkeypatch, client.repo, kind=kind)
        resp = client.post("/api/macro/cycle/judgments", json={"economy": "中国"})
        assert resp.status_code == status, (kind, resp.status_code, resp.text)
        assert resp.json()["detail"]["code"]


def test_unsupported_economy_rejected(monkeypatch, client: TestClient):
    _service_with(monkeypatch, client.repo)
    resp = client.post("/api/macro/cycle/judgments", json={"economy": "巴西"})
    assert resp.status_code == 400


def test_history_and_detail(monkeypatch, client: TestClient):
    _service_with(monkeypatch, client.repo)
    history = client.get("/api/macro/cycle/judgments", params={"economy": "中国"})
    assert history.status_code == 200
    months = [j["statistics_date"] for j in history.json()["judgments"]]
    assert months == ["2026-08", "2026-07"]

    detail = client.get("/api/macro/cycle/judgments/中国/2026-08")
    assert detail.status_code == 200
    assert detail.json()["judgment"]["statistics_date"] == "2026-08"

    missing = client.get("/api/macro/cycle/judgments/中国/2026-09")
    assert missing.status_code == 404


def test_economies_and_readiness(monkeypatch, client: TestClient):
    _service_with(monkeypatch, client.repo)
    assert client.get("/api/macro/economies").json()["economies"] == [
        "中国", "美国", "日本", "欧元区"
    ]
    readiness = client.get("/api/macro/readiness", params={"economy": "美国"})
    assert readiness.status_code == 200
    assert readiness.json()["readiness"]["latest_month"] == "2026-08"


def test_prompt_update_requires_settings_write_auth(monkeypatch, client: TestClient):
    # With an API key configured, a keyless write is rejected even loopback.
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")
    _service_with(monkeypatch, client.repo)

    unauthorized = client.put("/api/macro/prompts/a", json={"prompt_text": "新正文"})
    assert unauthorized.status_code == 401

    authorized = client.put(
        "/api/macro/prompts/a",
        json={"prompt_text": "新正文"},
        headers={"Authorization": "Bearer secret"},
    )
    assert authorized.status_code == 200

    reserved = client.put(
        "/api/macro/prompts/b",
        json={"prompt_text": "x"},
        headers={"Authorization": "Bearer secret"},
    )
    assert reserved.status_code == 409
