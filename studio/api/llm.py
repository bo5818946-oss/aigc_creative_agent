"""DeepSeek client for the planning layer.

Every failure is raised with a readable message. There is deliberately no
rules-based fallback plan: a made-up storyboard is worse than an honest error.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from studio.api import config

_SECRET = re.compile(r"sk-[A-Za-z0-9_-]+")
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMError(RuntimeError):
    """Base class for planning failures."""


class LLMUnavailable(LLMError):
    """No key, or the provider cannot be reached."""


class LLMContractError(LLMError):
    """The provider answered, but not with the JSON contract we asked for."""


@dataclass
class Usage:
    calls: int = 0
    retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.calls += other.calls
        self.retries += other.retries
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "retries": self.retries,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


def _redact(value: str) -> str:
    return _SECRET.sub("sk-***", value)


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise LLMContractError("模型返回了空内容。")
    candidates: list[str] = [text]
    fence = _FENCE.search(text)
    if fence:
        candidates.insert(0, fence.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise LLMContractError(
        "模型没有返回可解析的 JSON。"
        f" 原始内容前 240 字：{_redact(text[:240])}"
    )


class DeepSeekClient:
    def __init__(self) -> None:
        if not config.DEEPSEEK_API_KEY:
            raise LLMUnavailable(
                "DEEPSEEK_API_KEY 未配置。请在项目根目录的 .env 中填写密钥。"
            )
        self.client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            timeout=config.DEEPSEEK_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self.model = config.DEEPSEEK_MODEL

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.65,
        max_tokens: int = 8192,
    ) -> tuple[dict[str, Any], Usage]:
        usage = Usage()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_error: Exception | None = None
        for attempt in range(config.DEEPSEEK_MAX_RETRIES + 1):
            if attempt:
                usage.retries += 1
                time.sleep(min(1.5 * attempt, 4.0))
            try:
                usage.calls += 1
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                raw_usage = getattr(response, "usage", None)
                if raw_usage is not None:
                    usage.prompt_tokens += int(
                        getattr(raw_usage, "prompt_tokens", 0) or 0
                    )
                    usage.completion_tokens += int(
                        getattr(raw_usage, "completion_tokens", 0) or 0
                    )
                    usage.total_tokens += int(
                        getattr(raw_usage, "total_tokens", 0) or 0
                    )
                text = response.choices[0].message.content or ""
                return _extract_json(text), usage
            except (
                APITimeoutError,
                APIConnectionError,
                RateLimitError,
            ) as exc:
                last_error = exc
                continue
            except APIStatusError as exc:
                last_error = exc
                if exc.status_code >= 500 or exc.status_code == 429:
                    continue
                raise LLMUnavailable(
                    _redact(f"DeepSeek HTTP {exc.status_code}：{exc.message}")
                ) from exc
            except LLMContractError:
                raise
            except Exception as exc:  # provider/SDK edge cases
                last_error = exc
                break
        detail = _redact(str(last_error) if last_error else "未知错误")
        raise LLMUnavailable(f"DeepSeek 调用失败：{detail}")
