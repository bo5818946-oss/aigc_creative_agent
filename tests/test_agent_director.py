"""Tests for the model-driven decision layer.

The director is exercised with a stub that returns a ``DirectorDecision``
directly, so the suite never touches the network. Parsing robustness (aliased
keys, unknown fields) is tested separately against the Pydantic contract.
"""

from __future__ import annotations

from typing import Any

import pytest

from schemas.conversation import ConversationStage, QuestionOption
from services.agent_director import (
    AgentDirector,
    DirectorDecision,
    DirectorOption,
    DirectorQuestion,
    allowed_fields,
    build_user_prompt,
    coerce_field_value,
    is_automotive_brief,
    system_prompt,
)
from services.conversation_service import AgentUnavailableError, ConversationEngine


class FakeDirector:
    """Minimal stand-in for ``AgentDirector``."""

    model = "fake-director"

    def __init__(self, decisions: list[DirectorDecision]):
        self._decisions = list(decisions)
        self.calls: list[dict[str, Any]] = []

    def decide(self, **kwargs: Any) -> DirectorDecision:
        self.calls.append(kwargs)
        if not self._decisions:
            raise RuntimeError("no scripted decision left")
        return self._decisions.pop(0)


def _ask(
    field: str = "creative_direction",
    *,
    prompt: str = "这支片的创意结构走哪条路？",
    labels: tuple[str, ...] = ("夜色独行者", "追捕开场"),
) -> DirectorDecision:
    return DirectorDecision(
        reasoning="用户只给了车型和调性，创意结构决定后面所有镜头怎么排。",
        reply="先把结构定下来。",
        understood={},
        action="ask",
        question=DirectorQuestion(
            field=field,
            prompt=prompt,
            why_it_matters="结构决定场景和镜头。",
            options=[
                DirectorOption(
                    label=label,
                    description=f"{label} 的具体画面",
                    best_for="适合这类片子",
                    tradeoff="有代价",
                    recommended=index == 0,
                )
                for index, label in enumerate(labels)
            ],
            recommendation_reason="第一个最贴合当前信息。",
        ),
    )


# ----------------------------------------------------------------------
# contract robustness
# ----------------------------------------------------------------------
def test_decision_accepts_aliased_keys_and_maps_unknown_fields() -> None:
    raw = {
        "reasoning": "只给了调性。",
        "action": "ask",
        "understood": {"tone": "霓虹冷调", "product": "一台超跑", "天气": "晴"},
        "question": {
            "text": "电影感想落在哪种影像语言上？",
            "options": [{"label": "雨夜霓虹", "desc": "湿地反光"}],
        },
    }
    decision = DirectorDecision.model_validate(raw)

    assert decision.reply == ""
    assert decision.question is not None
    assert decision.question.prompt == "电影感想落在哪种影像语言上？"
    assert decision.question.options[0].description == "湿地反光"
    # Known aliases are mapped, unknown keys are dropped instead of invented.
    assert decision.understood == {
        "visual_style": "霓虹冷调",
        "subject": "一台超跑",
    }
    assert decision.question.resolved_field() == "visual_style"


def test_unresolvable_question_field_is_rejected() -> None:
    decision = DirectorDecision(
        reasoning="想知道天气。",
        action="ask",
        question=DirectorQuestion(
            field="weather",
            prompt="那天天气如何？",
            options=[DirectorOption(label="晴天"), DirectorOption(label="雨天")],
        ),
    )
    assert AgentDirector.to_question(decision) is None


def test_director_question_keeps_model_wording_and_tradeoffs() -> None:
    decision = _ask(labels=("夜色独行者", "追捕开场"))

    question = AgentDirector.to_question(decision)

    assert question is not None
    assert question.policy_source == "llm"
    assert question.reasoning.startswith("用户只给了车型")
    assert [option.label for option in question.options] == [
        "夜色独行者",
        "追捕开场",
    ]
    assert question.options[0].recommended is True
    assert question.options[0].challenge == "有代价"
    assert question.recommended_option_id == question.options[0].option_id


def test_production_parameters_survive_the_contract() -> None:
    decision = DirectorDecision(
        reasoning="需要定镜头方案。",
        action="ask",
        question=DirectorQuestion(
            field="camera_language",
            prompt="产品第一次出现用哪种镜头？",
            options=[
                DirectorOption(
                    label="单灯硬光·静止雕塑",
                    technique="100mm 微距 · 单灯裸光 45° 侧逆 · f/8 全清晰",
                    reference="Aesop 产品静物",
                    description="瓶身只被一道硬光切出轮廓。",
                    tradeoff="置景 4 小时以上，需彻底除尘。",
                    recommended=True,
                )
            ],
        ),
    )

    question = AgentDirector.to_question(decision)

    assert question is not None
    option = question.options[0]
    assert option.technique.startswith("100mm 微距")
    assert option.reference == "Aesop 产品静物"
    assert "置景" in option.challenge


def test_director_option_accepts_aliased_production_keys() -> None:
    decision = DirectorDecision.model_validate(
        {
            "reasoning": "定镜头。",
            "action": "ask",
            "question": {
                "field": "camera_language",
                "prompt": "怎么拍？",
                "options": [
                    {
                        "label": "滑轨横移",
                        "setup": "35mm · 滑轨横移 · f/4",
                        "ref": "某汽车广告",
                        "cost": "需要轨道与场地",
                    }
                ],
            },
        }
    )

    assert decision.question is not None
    assert decision.question.options[0].technique == "35mm · 滑轨横移 · f/4"
    assert decision.question.options[0].reference == "某汽车广告"


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("duration_seconds", "15 秒", 15.0),
        ("duration_seconds", 30, 30.0),
        ("scenes", "沙漠、雪山", ["沙漠", "雪山"]),
        ("scenes", ["沙漠", "雪山"], ["沙漠", "雪山"]),
        ("creative_direction", None, None),
        ("vehicle_type", " 纯电 SUV ", "纯电 SUV"),
    ],
)
def test_coerce_field_value(field: str, raw: Any, expected: Any) -> None:
    assert coerce_field_value(field, raw) == expected


# ----------------------------------------------------------------------
# engine wiring
# ----------------------------------------------------------------------
def test_engine_uses_model_question_and_dynamic_options() -> None:
    director = FakeDirector([_ask(labels=("夜色独行者", "追捕开场"))])
    engine = ConversationEngine(None, director=director)

    state = engine.start("做个未来超跑广告，要电影感")

    question = state.pending_question
    assert question is not None
    assert question.policy_source == "llm"
    assert [option.label for option in question.options] == [
        "夜色独行者",
        "追捕开场",
    ]
    assert [option.label for option in question.options] != [
        option.label for option in []
    ]
    assert state.stage == ConversationStage.CONCEPT
    assert engine.last_policy_source == "llm"
    assert director.calls[0]["idea"] == "做个未来超跑广告，要电影感"


def test_engine_applies_model_understanding_and_builds_proposal() -> None:
    decision = DirectorDecision(
        reasoning="用户授权我补齐，15 秒只够两个场景。",
        reply="行，剩下的我来定。",
        action="propose",
        understood={
            "vehicle_type": "纯电 SUV",
            "vehicle_design": "原创未来概念车",
            "vehicle_description": "一台银灰色纯电 SUV",
            "creative_direction": "沙脊与雪脊之间的一次硬切对撞",
            "scenes": ["沙漠", "雪山"],
            "duration_seconds": "15 秒",
            "camera_language": "低机位贴地跟车与航拍拉升交替",
        },
    )
    engine = ConversationEngine(None, director=FakeDirector([decision]))

    state = engine.start("做个银灰纯电 SUV 广告，穿沙漠和雪山，15 秒")

    assert state.brief.get("vehicle_type") == "纯电 SUV"
    assert state.brief.get("duration_seconds") == 15.0
    assert state.proposal is not None
    assert state.proposal.scene_order == ["沙漠", "雪山"]


def test_engine_raises_instead_of_falling_back_when_director_fails() -> None:
    class Broken:
        model = "broken"

        def decide(self, **_: Any) -> DirectorDecision:
            raise RuntimeError("boom")

    engine = ConversationEngine(None, director=Broken())

    with pytest.raises(AgentUnavailableError):
        engine.start("做个校园短片，讲毕业前的一晚")

    assert "boom" in engine.last_director_error


def test_engine_asks_again_with_the_model_when_it_proposes_too_early() -> None:
    early = DirectorDecision(
        reasoning="以为够了。",
        action="propose",
        understood={"vehicle_type": "纯电 SUV"},
    )
    follow_up = _ask(field="scenes", prompt="沙漠和雪山怎么排？")
    director = FakeDirector([early, follow_up])
    engine = ConversationEngine(None, director=director)

    state = engine.start("做个纯电 SUV 广告")

    assert state.proposal is None
    assert state.pending_question is not None
    assert state.pending_question.prompt == "沙漠和雪山怎么排？"
    assert state.pending_question.policy_source == "llm"
    assert len(director.calls) == 2



# ----------------------------------------------------------------------
# vehicle fields exist only for automotive briefs
# ----------------------------------------------------------------------
def test_non_automotive_prompt_contains_no_vehicle_vocabulary() -> None:
    prompt = system_prompt(automotive=False)

    for word in ("车型", "车头", "车灯", "轮胎", "道路", "vehicle_"):
        assert word not in prompt, word


def test_automotive_prompt_keeps_vehicle_fields() -> None:
    prompt = system_prompt(automotive=True)

    assert "vehicle_type" in prompt
    assert "vehicle_description" in prompt
    assert "车型" in prompt


def test_campus_brief_does_not_list_vehicle_fields_as_missing() -> None:
    from schemas.conversation import ConversationState

    idea = "我想制作一支有电影感的校园短片，讲一个毕业前的夜晚。"
    state = ConversationState(original_idea=idea)
    prompt = build_user_prompt(
        idea=idea,
        brief_snapshot=state.brief.snapshot(),
        pending_field="",
        pending_prompt="",
        user_text=idea,
        tail=[],
        rejected_fields=[],
        fields=allowed_fields(False),
    )
    missing = prompt.split("【当前还缺的字段】")[1].split("【用户此刻")[0]

    assert "车型" not in missing
    assert "外观方向" not in missing


def test_is_automotive_brief_classification() -> None:
    assert is_automotive_brief("做一支汽车广告，银灰色轿车") is True
    assert is_automotive_brief("做一支校园短片，毕业前夜") is False
    # A campus film mentioning a car in passing is still not a car project.
    assert is_automotive_brief("校园短片里有一辆车开过", "剧情短片") is False


def test_engine_drops_vehicle_fields_from_a_campus_decision() -> None:
    decision = DirectorDecision(
        reasoning="先定人物。",
        action="ask",
        understood={
            "vehicle_type": "超级跑车",
            "vehicle_design": "原创未来概念车",
            "subject": "两个即将毕业的学生",
        },
        question=DirectorQuestion(
            field="creative_direction",
            prompt="这份情绪怎么放？",
            options=[DirectorOption(label="长镜头", recommended=True)],
        ),
    )
    engine = ConversationEngine(None, director=FakeDirector([decision]))

    state = engine.start("做一支校园短片，毕业前夜")

    assert state.brief.get("subject") == "两个即将毕业的学生"
    assert not state.brief.has("vehicle_type")
    assert not state.brief.has("vehicle_design")
