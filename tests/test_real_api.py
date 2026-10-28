from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from config import settings
from services.llm_service import LLMService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REAL_API_TESTS") != "1"
    or not settings.DEEPSEEK_API_KEY,
    reason=(
        "Real DeepSeek test is opt-in. Set RUN_REAL_API_TESTS=1 and "
        "configure DEEPSEEK_API_KEY to run it."
    ),
)


class Ping(BaseModel):
    ok: bool
    message: str


def test_real_deepseek_json_roundtrip() -> None:
    service = LLMService.from_env()
    try:
        result = service.chat_json(
            system_prompt="只输出一个 JSON 对象，不要输出 Markdown 或解释。",
            user_prompt='输出 {"ok": true, "message": "pong"}',
            response_model=Ping,
            temperature=0,
        )
    finally:
        service.close()

    assert result.ok is True
    assert result.message
    assert service.usage.calls == 1
    assert service.usage.total_tokens > 0
