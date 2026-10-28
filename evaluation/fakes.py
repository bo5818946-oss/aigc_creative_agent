"""Scripted LLM client used by the evaluation suite.

The evaluation never calls a real provider by default. The fake mirrors the
small part of the OpenAI client used by ``LLMService`` and records every call
so the suite can assert exact call counts.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any


class FakeChatClient:
    def __init__(
        self,
        responses: list[Any],
        usage: dict[str, int] | None = None,
    ) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.usage = usage or {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        }
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("No scripted fake responses left")

        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response

        content = (
            response
            if isinstance(response, str)
            else json.dumps(response, ensure_ascii=False)
        )
        usage = SimpleNamespace(
            prompt_tokens=self.usage.get("prompt_tokens", 0),
            completion_tokens=self.usage.get("completion_tokens", 0),
            total_tokens=self.usage.get("total_tokens", 0),
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=content))
            ],
            usage=usage,
        )
