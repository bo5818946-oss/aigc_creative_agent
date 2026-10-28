"""Deterministic fakes for LLM tests. No real API calls are made."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from services.agent_director import (
    DirectorDecision,
    DirectorOption,
    DirectorQuestion,
)


def ask(
    field: str,
    *,
    prompt: str,
    labels: tuple[str, ...],
    understood: dict[str, Any] | None = None,
    multi_select: bool = False,
    reasoning: str = "这是当前最影响成片的一项。",
) -> DirectorDecision:
    """Build a scripted ``ask`` decision."""

    return DirectorDecision(
        reasoning=reasoning,
        reply="",
        understood=understood or {},
        action="ask",
        question=DirectorQuestion(
            field=field,
            prompt=prompt,
            options=[
                DirectorOption(
                    label=label,
                    technique="85mm 长焦 · 侧逆光 · 滑轨横移 · f/2.8",
                    reference="测试参考",
                    description=f"{label} 的画面",
                    tradeoff="置景与调试成本较高",
                    recommended=index == 0,
                )
                for index, label in enumerate(labels)
            ],
            multi_select=multi_select,
        ),
    )


def propose(understood: dict[str, Any], *, reply: str = "其余我按专业判断补齐。") -> DirectorDecision:
    return DirectorDecision(
        reasoning="信息已经足够出方案。",
        reply=reply,
        understood=understood,
        action="propose",
    )


class ScriptedDirector:
    """A director that plays back a fixed list of decisions.

    The list is consumed across engine instances because the UI builds a fresh
    ``ConversationEngine`` per turn; tests need the same script to keep advancing.
    """

    model = "scripted-director"

    def __init__(self, decisions: list[DirectorDecision]):
        self._decisions = list(decisions)
        self.calls: list[dict[str, Any]] = []

    def decide(self, **kwargs: Any) -> DirectorDecision:
        self.calls.append(kwargs)
        if not self._decisions:
            raise RuntimeError("scripted director has no decision left")
        return self._decisions.pop(0)


def car_flow_decisions() -> list[DirectorDecision]:
    """The scripted car conversation used by the Streamlit flow tests."""

    return [
        ask(
            "creative_direction",
            prompt="这支未来超跑广告，你想用哪种结构承载电影感？",
            labels=("多地貌穿越", "未来都市", "极速公路"),
            understood={
                "vehicle_type": "超级跑车",
                "visual_style": "电影感",
            },
        ),
        ask(
            "scenes",
            prompt="穿越经过哪些地貌？可以多选。",
            labels=(
                "森林林间公路",
                "沙漠戈壁公路",
                "雪山盘山道路",
                "城市隧道",
            ),
            understood={"creative_direction": "多地貌穿越"},
            multi_select=True,
        ),
        ask(
            "duration_seconds",
            prompt="这支片多长？",
            labels=("15 秒", "30 秒", "60 秒"),
            understood={"duration_seconds": 30},
        ),
        ask(
            "camera_language",
            prompt="镜头语言偏速度还是质感？",
            labels=("节奏平衡", "速度冲击"),
            understood={
                "camera_language": "航拍建立、侧向跟拍、细节特写、结尾英雄展示"
            },
        ),
        ask(
            "transition_requirements",
            prompt="场景之间怎么衔接？",
            labels=("动作匹配", "硬切"),
            understood={"transition_requirements": "以动作匹配转场为主"},
        ),
        propose({}),
        DirectorDecision(
            reasoning="只改场景，其他决策不动。",
            reply="只把沙漠换成海岸公路。",
            action="revise",
            understood={
                "scenes": [
                    "森林林间公路",
                    "海岸公路",
                    "雪山盘山道路",
                    "城市隧道",
                ]
            },
            revision_summary="场景：沙漠改为海岸公路",
        ),
    ]


class FakeChatClient:
    """Mimics the small part of the OpenAI client used by LLMService."""

    def __init__(
        self,
        responses: list[Any],
        usage: dict[str, int] | None = None,
    ):
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
            raise AssertionError("No fake responses left")

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
