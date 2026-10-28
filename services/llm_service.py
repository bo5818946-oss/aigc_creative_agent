"""DeepSeek LLM service with validation, limited retries, and usage tracking.

The service uses the OpenAI-compatible DeepSeek endpoint. It never logs the
API key, validates every structured response with Pydantic, and keeps token
usage so the workflow can report actual model consumption.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from config import settings
from schemas.project import CreativeRequirement, RequirementDraft

T = TypeVar("T", bound=BaseModel)

_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]+")

REQUIREMENT_SYSTEM_PROMPT = """你是一名严谨的 AIGC 商业广告与短视频创作需求分析师。
你的任务是把用户的自然语言创作需求转换为严格的 JSON 对象。

规则：
1. 只输出 JSON 对象，不要输出 Markdown 代码块、解释或前后缀文字。
2. 不要编造用户没有提供、也无法从需求中安全推断的关键信息。
3. 无法确定的内容写入 pending_confirmations；非关键字段可以使用合理默认值，但要在 pending_confirmations 中说明。
4. duration_seconds 必须是数字，单位秒；不要写“30秒”这样的字符串。
5. scene_requirements、consistency_constraints、output_formats、pending_confirmations 必须是字符串数组。
6. 主体一致性约束要具体，并结合内容类型：人物写外观、服装、发型和识别特征；产品写材质、结构和颜色；汽车写车型、颜色、灯组和车头车尾方向。不要只写“保持一致”。
7. 保留用户明确提出的限制条件，不要擅自删除。
8. 不要输出 API 密钥、密码或其他敏感信息。
9. prompt_dialect 必须从下面这些值里选一个最贴合需求的，只写英文键名：
   ecommerce 电商视觉 / brand_ad 品牌广告 / film_scifi 科幻影视 /
   film_human 人文剧情 / film_action 动作追逐 / anime 动画动漫 /
   experimental 创意实验 / documentary 纪实。
   判断依据是这支片子要怎么被看：卖货选 ecommerce，讲品牌记忆点选 brand_ad，
   世界观与技术设定是主角选 film_scifi，人物与情绪是主角选 film_human，
   速度与追逃是主角选 film_action，二次元作画选 anime，形式即内容选 experimental，
   真实观察选 documentary。
"""


class LLMError(RuntimeError):
    """Base class for LLM integration failures."""


class LLMConfigurationError(LLMError):
    """Raised when the LLM cannot be configured safely."""


class LLMCallError(LLMError):
    """Raised when the provider cannot be reached after limited retries."""


class LLMResponseError(LLMError):
    """Raised when the provider returns invalid or incomplete data."""


@dataclass
class LLMUsage:
    calls: int = 0
    retries: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "retries": self.retries,
            "errors": self.errors,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def _merge_list(primary: list[str], fallback: Any) -> list[str]:
    if primary:
        return [str(item).strip() for item in primary if str(item).strip()]
    if isinstance(fallback, list):
        return [str(item).strip() for item in fallback if str(item).strip()]
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _pick(
    draft_value: Any,
    fallback_value: Any,
    default: Any,
    label: str,
    pending: list[str],
) -> Any:
    if _has_value(draft_value):
        return draft_value
    if _has_value(fallback_value):
        return fallback_value
    if default is not None:
        pending.append(
            f"{label}未提供，已使用默认值“{default}”，需用户确认。"
        )
        return default
    raise ValueError(f"缺少关键信息：{label}。请补充后再生成分镜。")


def merge_requirement_draft(
    draft: RequirementDraft,
    fallback: dict[str, Any] | None = None,
) -> CreativeRequirement:
    """Merge an LLM draft with the user's structured fallback.

    Critical fields (subject and duration) must come from one of the two
    sources. Non-critical fields receive explicit defaults and are recorded in
    ``pending_confirmations`` rather than being silently treated as confirmed.
    """

    fallback = fallback or {}
    pending = [
        str(item).strip()
        for item in draft.pending_confirmations
        if str(item).strip()
    ]

    project_name = _pick(
        draft.project_name,
        fallback.get("project_name"),
        "未命名创作项目",
        "项目名称",
        pending,
    )
    content_type = _pick(
        draft.content_type,
        fallback.get("content_type"),
        "商业广告",
        "内容类型",
        pending,
    )
    subject = _pick(
        draft.subject,
        fallback.get("subject"),
        None,
        "主体描述",
        pending,
    )
    duration_seconds = _pick(
        draft.duration_seconds,
        fallback.get("duration_seconds"),
        None,
        "视频时长",
        pending,
    )
    target_audience = _pick(
        draft.target_audience,
        fallback.get("target_audience"),
        "大众消费者",
        "目标受众",
        pending,
    )
    aspect_ratio = _pick(
        draft.aspect_ratio,
        fallback.get("aspect_ratio"),
        "16:9",
        "画面比例",
        pending,
    )
    visual_style = _pick(
        draft.visual_style,
        fallback.get("visual_style"),
        "电影感商业广告",
        "视觉风格",
        pending,
    )
    camera_language = _pick(
        draft.camera_language,
        fallback.get("camera_language"),
        "稳定运镜，主体清晰",
        "镜头语言",
        pending,
    )
    transition_requirements = _pick(
        draft.transition_requirements,
        fallback.get("transition_requirements"),
        "自然连贯",
        "转场要求",
        pending,
    )

    scenes = _merge_list(
        draft.scene_requirements,
        fallback.get("scene_requirements"),
    )
    constraints = _merge_list(
        draft.consistency_constraints,
        fallback.get("consistency_constraints"),
    )
    output_formats = _merge_list(
        draft.output_formats,
        fallback.get("output_formats") or ["markdown", "json"],
    )
    notes = draft.notes if _has_value(draft.notes) else fallback.get("notes", "")

    from config.prompt_dialects import DIALECTS

    dialect = str(draft.prompt_dialect or fallback.get("prompt_dialect") or "").strip().lower()
    if dialect not in DIALECTS:
        dialect = ""

    return CreativeRequirement(
        project_name=str(project_name),
        content_type=str(content_type),
        subject=str(subject),
        prompt_dialect=dialect,
        target_audience=str(target_audience),
        duration_seconds=float(duration_seconds),
        aspect_ratio=str(aspect_ratio),
        visual_style=str(visual_style),
        scene_requirements=scenes,
        camera_language=str(camera_language),
        consistency_constraints=constraints,
        transition_requirements=str(transition_requirements),
        output_formats=output_formats,
        notes=str(notes or ""),
        pending_confirmations=_dedupe(pending),
    )


def _build_requirement_user_prompt(
    raw_text: str,
    fallback: dict[str, Any],
) -> str:
    schema = json.dumps(
        RequirementDraft.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )
    fallback_text = json.dumps(fallback, ensure_ascii=False, indent=2)
    return (
        "请从下面的原始创作需求中提取字段。\n\n"
        f"字段结构（JSON Schema）：\n{schema}\n\n"
        f"原始需求：\n{raw_text[:6000]}\n\n"
        "已有结构化字段（仅用于补全空白，不要用空值覆盖）：\n"
        f"{fallback_text[:2000]}\n\n"
        "再次强调：只输出一个 JSON 对象。"
    )


def _preview(text: str) -> str:
    return " ".join(text.split())[:200]


class LLMService:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        json_mode: bool = True,
        client: Any | None = None,
        retry_backoff_seconds: float = 1.0,
    ):
        api_key = (api_key or "").strip()
        if not api_key:
            raise LLMConfigurationError(
                "DEEPSEEK_API_KEY 未配置。请写入项目根目录 .env，"
                "或设置同名环境变量。"
            )
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")

        self._api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.json_mode = json_mode
        self.retry_backoff_seconds = retry_backoff_seconds
        self.usage = LLMUsage()
        self._client = client or self._build_client()

    @classmethod
    def from_env(cls) -> "LLMService":
        return cls(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            model=settings.DEEPSEEK_MODEL,
            timeout_seconds=settings.DEEPSEEK_TIMEOUT_SECONDS,
            max_retries=settings.DEEPSEEK_MAX_RETRIES,
            json_mode=settings.DEEPSEEK_JSON_MODE,
        )

    def _build_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMConfigurationError(
                "未安装 openai SDK。请运行："
                ".venv\\Scripts\\python.exe -m pip install -r requirements.txt"
            ) from exc
        return OpenAI(
            api_key=self._api_key,
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            max_retries=0,
        )

    def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> T:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if self.json_mode:
            request["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            if max_tokens <= 0:
                raise ValueError("max_tokens must be > 0")
            request["max_tokens"] = max_tokens

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self.usage.calls += 1
            try:
                response = self._create(request)
                self._record_usage(response)
                content = self._extract_message_content(response)
                data = self._parse_json_object(content)
                try:
                    return response_model.model_validate(data)
                except ValidationError as exc:
                    raise LLMResponseError(
                        "模型返回的数据结构不符合要求："
                        + self._format_validation_error(exc)
                    ) from exc
            except LLMResponseError:
                self.usage.errors += 1
                raise
            except Exception as exc:
                self.usage.errors += 1
                last_error = exc
                if not self._is_retryable(exc) or attempt >= self.max_retries:
                    break
                self.usage.retries += 1
                time.sleep(self.retry_backoff_seconds * (2**attempt))

        raise LLMCallError(
            "DeepSeek 调用失败：" + self._safe_error_message(last_error)
        ) from last_error

    def _create(self, request: dict[str, Any]) -> Any:
        """One HTTP call, degrading if the backend has no JSON mode.

        Local OpenAI-compatible servers (llama.cpp, Ollama, LM Studio) vary:
        some implement ``response_format``, some answer 400. Failing the whole
        turn over an optional field would make a working local model look
        broken, so the field is dropped once and the call is repeated.
        """

        try:
            return self._client.chat.completions.create(**request)
        except Exception as exc:
            if "response_format" not in request or not self._rejects_json_mode(exc):
                raise
            fallback = dict(request)
            fallback.pop("response_format", None)
            self.json_mode = False
            self.usage.retries += 1
            return self._client.chat.completions.create(**fallback)

    @staticmethod
    def _rejects_json_mode(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        text = str(exc).lower()
        return status == 400 or "response_format" in text or "json mode" in text

    def reset_usage(self) -> None:
        self.usage = LLMUsage()

    def parse_requirement(
        self,
        raw_text: str,
        fallback: dict[str, Any] | None = None,
    ) -> CreativeRequirement:
        raw_text = (raw_text or "").strip()
        if not raw_text:
            raise LLMResponseError("原始需求为空，无法调用模型解析。")

        fallback = fallback or {}
        draft = self.chat_json(
            system_prompt=REQUIREMENT_SYSTEM_PROMPT,
            user_prompt=_build_requirement_user_prompt(raw_text, fallback),
            response_model=RequirementDraft,
            temperature=0.1,
        )
        return merge_requirement_draft(draft, fallback)

    @staticmethod
    def _extract_message_content(response: Any) -> str:
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise LLMResponseError(
                "模型响应缺少 choices[0].message.content。"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("模型返回了空内容。")
        return content

    @staticmethod
    def _parse_json_object(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end <= start:
                raise LLMResponseError(
                    "模型返回的不是有效 JSON 对象。响应摘要："
                    + _preview(text)
                )
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise LLMResponseError(
                    "模型返回的不是有效 JSON 对象。响应摘要："
                    + _preview(text)
                ) from exc

        if not isinstance(data, dict):
            raise LLMResponseError("模型返回的 JSON 顶层必须是对象。")
        return data

    def _record_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens
        self.usage.prompt_tokens += prompt_tokens
        self.usage.completion_tokens += completion_tokens
        self.usage.total_tokens += total_tokens

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return True
        name = type(exc).__name__
        if name in {
            "APITimeoutError",
            "APIConnectionError",
            "RateLimitError",
            "InternalServerError",
        }:
            return True
        status = getattr(exc, "status_code", None)
        if isinstance(status, int) and (status == 429 or status >= 500):
            return True
        return False

    def _safe_error_message(self, exc: Exception | None) -> str:
        if exc is None:
            return "未知错误"
        message = f"{type(exc).__name__}: {exc}"
        if self._api_key:
            message = message.replace(self._api_key, "sk-***")
        message = _SECRET_PATTERN.sub("sk-***", message)
        return message[:500]

    @staticmethod
    def _format_validation_error(exc: ValidationError) -> str:
        parts: list[str] = []
        for item in exc.errors(include_url=False, include_input=True):
            location = ".".join(str(part) for part in item.get("loc", ()))
            prefix = f"{location}: " if location else ""
            actual = item.get("input")
            actual_text = ""
            if isinstance(actual, (str, int, float)):
                actual_text = f"；实际值：{str(actual)[:80]}"
            parts.append(
                f"{prefix}{item.get('msg', '字段校验失败')}{actual_text}"
            )
        return "; ".join(parts)

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()
