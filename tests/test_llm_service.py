from __future__ import annotations

import json

import pytest

from schemas.project import RequirementDraft
from services.llm_service import (
    LLMCallError,
    LLMConfigurationError,
    LLMResponseError,
    LLMService,
)
from tests.fakes import FakeChatClient


class FakeRateLimitError(Exception):
    status_code = 429


def _payload(**overrides) -> dict:
    payload = {
        "project_name": "LLM 汽车广告",
        "content_type": "汽车商业广告",
        "subject": "一辆哑光黑色纯电 SUV",
        "target_audience": "年轻消费者",
        "duration_seconds": 30,
        "aspect_ratio": "16:9",
        "visual_style": "电影感商业广告",
        "scene_requirements": ["森林", "雪地", "城市"],
        "camera_language": "航拍与低机位跟拍结合",
        "consistency_constraints": [
            "全片同一辆哑光黑色纯电 SUV，车头始终朝右"
        ],
        "transition_requirements": "自然动势转场",
        "output_formats": ["markdown", "json"],
        "pending_confirmations": [],
    }
    payload.update(overrides)
    return payload


def _service(
    responses: list,
    *,
    max_retries: int = 2,
    usage: dict[str, int] | None = None,
    json_mode: bool = True,
) -> tuple[LLMService, FakeChatClient]:
    client = FakeChatClient(responses, usage=usage)
    service = LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        max_retries=max_retries,
        json_mode=json_mode,
        client=client,
        retry_backoff_seconds=0,
    )
    return service, client


def _chat(service: LLMService) -> RequirementDraft:
    return service.chat_json(
        system_prompt="只输出 JSON。",
        user_prompt="解析需求",
        response_model=RequirementDraft,
    )


def test_parse_requirement_uses_valid_json_and_tracks_usage() -> None:
    service, client = _service([_payload()])

    requirement = service.parse_requirement(
        "30 秒汽车广告，五个场景。",
        fallback={
            "project_name": "兜底项目",
            "subject": "兜底主体",
            "duration_seconds": 15,
        },
    )

    assert requirement.subject == "一辆哑光黑色纯电 SUV"
    assert requirement.duration_seconds == 30
    assert requirement.scene_requirements == ["森林", "雪地", "城市"]
    assert service.usage.calls == 1
    assert service.usage.errors == 0
    assert service.usage.total_tokens == 30
    assert client.calls[0]["response_format"] == {"type": "json_object"}


def test_missing_fields_use_structured_fallback() -> None:
    service, _ = _service([{"subject": "LLM 主体"}])

    requirement = service.parse_requirement(
        "需求",
        fallback={
            "project_name": "兜底项目",
            "content_type": "商业广告",
            "subject": "兜底主体",
            "duration_seconds": 15,
            "scene_requirements": ["城市"],
            "consistency_constraints": ["保持主体一致"],
            "output_formats": ["markdown", "json"],
        },
    )

    assert requirement.subject == "LLM 主体"
    assert requirement.project_name == "兜底项目"
    assert requirement.duration_seconds == 15
    assert requirement.scene_requirements == ["城市"]
    assert any("目标受众" in item for item in requirement.pending_confirmations)


def test_missing_subject_raises_clear_error() -> None:
    service, _ = _service([{"project_name": "只有名称"}])

    with pytest.raises(ValueError) as exc_info:
        service.parse_requirement("需求")

    assert "主体描述" in str(exc_info.value)


def test_missing_duration_raises_clear_error() -> None:
    service, _ = _service([{"subject": "一辆车"}])

    with pytest.raises(ValueError) as exc_info:
        service.parse_requirement("需求")

    assert "视频时长" in str(exc_info.value)


def test_invalid_json_raises_response_error() -> None:
    service, _ = _service(["这不是 JSON"])

    with pytest.raises(LLMResponseError) as exc_info:
        _chat(service)

    assert "有效 JSON" in str(exc_info.value)
    assert service.usage.calls == 1
    assert service.usage.errors == 1


def test_json_code_fence_is_accepted() -> None:
    content = "```json\n" + json.dumps(_payload(), ensure_ascii=False) + "\n```"
    service, _ = _service([content])

    draft = _chat(service)

    assert draft.subject == "一辆哑光黑色纯电 SUV"


def test_json_with_surrounding_text_is_accepted() -> None:
    content = "结果如下：" + json.dumps(_payload(), ensure_ascii=False) + " 完成"
    service, _ = _service([content])

    draft = _chat(service)

    assert draft.duration_seconds == 30


def test_invalid_field_type_raises_response_error() -> None:
    service, _ = _service([{"duration_seconds": -1}])

    with pytest.raises(LLMResponseError) as exc_info:
        _chat(service)

    assert "不符合要求" in str(exc_info.value)


def test_timeout_is_retried() -> None:
    service, client = _service([TimeoutError("timeout"), _payload()])

    draft = _chat(service)

    assert draft.subject == "一辆哑光黑色纯电 SUV"
    assert service.usage.calls == 2
    assert service.usage.retries == 1
    assert service.usage.errors == 1
    assert len(client.calls) == 2


def test_rate_limit_is_retried() -> None:
    service, _ = _service([FakeRateLimitError("429"), _payload()])

    draft = _chat(service)

    assert draft.subject == "一辆哑光黑色纯电 SUV"
    assert service.usage.calls == 2
    assert service.usage.retries == 1


def test_retry_limit_is_enforced() -> None:
    service, _ = _service(
        [TimeoutError("1"), TimeoutError("2"), TimeoutError("3")],
        max_retries=2,
    )

    with pytest.raises(LLMCallError):
        _chat(service)

    assert service.usage.calls == 3
    assert service.usage.retries == 2
    assert service.usage.errors == 3


def test_non_retryable_error_fails_immediately() -> None:
    service, _ = _service([RuntimeError("bad request")], max_retries=2)

    with pytest.raises(LLMCallError):
        _chat(service)

    assert service.usage.calls == 1
    assert service.usage.retries == 0


def test_error_message_redacts_secret() -> None:
    secret = "sk-super-secret-value"
    service, _ = _service([RuntimeError(f"invalid key {secret}")])

    with pytest.raises(LLMCallError) as exc_info:
        _chat(service)

    message = str(exc_info.value)
    assert secret not in message
    assert "sk-***" in message


def test_empty_api_key_is_rejected() -> None:
    with pytest.raises(LLMConfigurationError):
        LLMService(
            api_key="",
            base_url="https://example.invalid",
            model="deepseek-chat",
            client=FakeChatClient([]),
        )


def test_json_mode_can_be_disabled() -> None:
    service, client = _service([_payload()], json_mode=False)

    _chat(service)

    assert "response_format" not in client.calls[0]


class FakeBadRequestError(Exception):
    status_code = 400


def test_json_mode_is_dropped_when_a_local_backend_rejects_it() -> None:
    """llama.cpp / Ollama style servers may answer 400 to response_format."""

    service, client = _service(
        [FakeBadRequestError("response_format is not supported"), _payload()]
    )

    _chat(service)

    assert "response_format" in client.calls[0]
    assert "response_format" not in client.calls[1]
    assert service.json_mode is False
    assert len(client.calls) == 2


def test_a_plain_bad_request_is_not_retried_forever() -> None:
    service, client = _service([FakeBadRequestError("bad request"), _payload()])

    _chat(service)

    # One degradation attempt, then the answer succeeds: no third call.
    assert len(client.calls) == 2


def test_empty_content_raises_response_error() -> None:
    service, _ = _service([""])

    with pytest.raises(LLMResponseError) as exc_info:
        _chat(service)

    assert "空内容" in str(exc_info.value)


def test_top_level_json_array_is_rejected() -> None:
    service, _ = _service(["[1, 2, 3]"])

    with pytest.raises(LLMResponseError) as exc_info:
        _chat(service)

    assert "顶层必须是对象" in str(exc_info.value)


def test_empty_raw_text_is_rejected() -> None:
    service, _ = _service([_payload()])

    with pytest.raises(LLMResponseError):
        service.parse_requirement("   ")
