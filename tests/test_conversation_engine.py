"""Conversation engine tests.

The engine no longer contains a fallback question policy, so every test drives
it with a ``ScriptedDirector``. What is under test here is the engine's job:
validating the model's answer, expanding an option click into a brief value,
refusing to invent missing decisions, and persisting all of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from database.repository import ProjectRepository
from schemas.conversation import (
    ConversationState,
    ConversationStatus,
    FieldSource,
    VehicleAsset,
)
from services.agent_director import (
    DirectorDecision,
    DirectorOption,
    DirectorQuestion,
)
from services.conversation_service import (
    AgentContractError,
    AgentUnavailableError,
    ConversationEngine,
)
from tests.fakes import ScriptedDirector, ask, propose


def _engine(decisions: list[DirectorDecision], tmp_path: Path | None = None):
    repository = (
        ProjectRepository(tmp_path / "conversation.sqlite3")
        if tmp_path is not None
        else None
    )
    director = ScriptedDirector(decisions)
    return ConversationEngine(repository, director=director), director


def _car_decisions() -> list[DirectorDecision]:
    """A short but complete car conversation."""

    return [
        ask(
            "creative_direction",
            prompt="用哪种结构承载电影感？",
            labels=("多地貌穿越", "未来都市"),
            understood={"vehicle_type": "超级跑车", "visual_style": "电影感"},
        ),
        ask(
            "scenes",
            prompt="穿越经过哪些地貌？",
            labels=("森林林间公路", "沙漠戈壁公路", "雪山盘山道路"),
            understood={"creative_direction": "多地貌穿越"},
            multi_select=True,
        ),
        ask(
            "duration_seconds",
            prompt="这支片多长？",
            labels=("15 秒", "30 秒"),
            understood={"duration_seconds": 30},
        ),
        ask(
            "camera_language",
            prompt="镜头偏速度还是质感？",
            labels=("节奏平衡", "速度冲击"),
            understood={"camera_language": "航拍建立、侧向跟拍、细节特写"},
        ),
        propose({}),
    ]


# ----------------------------------------------------------------------
# the model drives every turn
# ----------------------------------------------------------------------
def test_start_uses_the_model_question_and_understanding() -> None:
    engine, _ = _engine(
        [
            ask(
                "creative_direction",
                prompt="用哪种结构承载电影感？",
                labels=("多地貌穿越", "未来都市"),
                understood={"vehicle_type": "超级跑车"},
            )
        ]
    )

    state = engine.start("我想做一个未来超跑广告")

    question = state.pending_question
    assert question is not None
    assert question.policy_source == "llm"
    assert question.prompt == "用哪种结构承载电影感？"
    assert [option.label for option in question.options] == ["多地貌穿越", "未来都市"]
    assert state.brief.get("vehicle_type") == "超级跑车"
    assert state.messages[-1].kind == "question"


def test_free_text_answer_advances_through_the_model() -> None:
    engine, director = _engine(_car_decisions())
    state = engine.start("做一个超跑广告")

    state = engine.handle(state, "多地貌穿越")

    assert state.pending_question is not None
    assert state.pending_question.field == "scenes"
    assert state.pending_question.policy_source == "llm"
    assert director.calls[-1]["user_text"] == "多地貌穿越"


def test_clicking_an_option_asks_the_model_again() -> None:
    """Regression: a click used to drop straight into the rule table."""

    engine, director = _engine(_car_decisions())
    state = engine.start("做一个超跑广告")

    first = state.pending_question.options[0]
    state = engine.choose(state, first.option_id)

    assert state.brief.get("creative_direction") == "多地貌穿越"
    assert state.pending_question is not None
    assert state.pending_question.field == "scenes"
    assert state.pending_question.policy_source == "llm"
    assert sum(1 for call in director.calls if "我选择" in call["user_text"]) == 1
    assert any(message.content.startswith("我选：") for message in state.messages)


def test_multi_select_keeps_every_chosen_label() -> None:
    engine, _ = _engine(_car_decisions())
    state = engine.start("做一个超跑广告")
    state = engine.choose(state, state.pending_question.options[0].option_id)

    question = state.pending_question
    ids = [option.option_id for option in question.options[:2]]
    state = engine.choose(state, ids[0], selected_ids=ids)

    assert state.brief.get("scenes") == ["森林林间公路", "沙漠戈壁公路"]
    assert state.pending_question.field == "duration_seconds"


def test_agent_choice_uses_the_recommended_option() -> None:
    engine, _ = _engine(_car_decisions())
    state = engine.start("做一个超跑广告")

    state = engine.choose(state, "__agent__")

    assert state.brief.get("creative_direction") == "多地貌穿越"
    assert state.brief.source("creative_direction") == FieldSource.USER_SELECTED


def test_autonomy_turn_proposes_with_model_values() -> None:
    engine, _ = _engine(
        [
            ask(
                "subject",
                prompt="主角是谁？",
                labels=("产品", "人物"),
            ),
            propose(
                {
                    "subject": "一款高端护肤产品",
                    "creative_direction": "以光和材质呈现产品",
                    "scenes": ["纯色背景棚"],
                    "duration_seconds": 15,
                    "camera_language": "微距推移",
                },
                reply="行，剩下的我来定。",
            ),
        ]
    )
    state = engine.start("做一支护肤品广告")
    state = engine.handle(state, "你决定")

    assert state.proposal is not None
    last = state.messages[-1]
    assert last.kind == "director"
    assert last.payload["reasoning"]
    assert "行，剩下的我来定。" in last.content


def test_propose_with_missing_decisions_asks_again() -> None:
    engine, director = _engine(
        [
            ask("creative_direction", prompt="用哪种结构？", labels=("A", "B")),
            propose({"creative_direction": "A"}),  # missing scenes/duration/camera
            ask("scenes", prompt="在哪些空间？", labels=("棚拍", "户外"), multi_select=True),
        ]
    )

    state = engine.start("做一个广告")
    state = engine.handle(state, "你决定")

    assert state.proposal is None
    assert state.pending_question is not None
    assert state.pending_question.field == "scenes"
    assert director.calls[-1]["force_action"] == "ask"


# ----------------------------------------------------------------------
# no fallback: failures are explicit
# ----------------------------------------------------------------------
def test_missing_decision_layer_is_an_explicit_error() -> None:
    engine = ConversationEngine(None)

    with pytest.raises(AgentUnavailableError) as excinfo:
        engine.start("做一个广告")

    assert "DEEPSEEK_API_KEY" in str(excinfo.value)


def test_model_failure_is_an_explicit_error() -> None:
    class Broken:
        model = "broken"

        def decide(self, **_kwargs):
            raise RuntimeError("network down")

    engine = ConversationEngine(None, director=Broken())

    with pytest.raises(AgentUnavailableError) as excinfo:
        engine.start("做一个广告")

    assert "network down" in str(excinfo.value)
    assert "network down" in engine.last_director_error


def test_unusable_question_raises_a_contract_error() -> None:
    class BadQuestion:
        model = "bad"

        def decide(self, **_kwargs):
            return DirectorDecision(
                reasoning="想问天气。",
                action="ask",
                question=DirectorQuestion(
                    field="weather",
                    prompt="那天天气如何？",
                    options=[
                        DirectorOption(label="晴"),
                        DirectorOption(label="雨"),
                    ],
                ),
            )

    engine = ConversationEngine(None, director=BadQuestion())

    with pytest.raises(AgentContractError):
        engine.start("做一个广告")


def test_choose_without_a_pending_question_is_rejected() -> None:
    engine, _ = _engine([propose({})])
    state = ConversationState()

    with pytest.raises(ValueError):
        engine.choose(state, "anything")


# ----------------------------------------------------------------------
# persistence, assets, requirement
# ----------------------------------------------------------------------
def test_conversation_round_trip_persistence(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "round_trip.sqlite3")
    engine = ConversationEngine(repository, director=ScriptedDirector(_car_decisions()))
    state = engine.start("我想做一个汽车广告。")

    record = repository.get_conversation(state.session_id)
    assert record is not None
    restored = ConversationState.model_validate(record["state"])

    assert restored.pending_question is not None
    assert restored.pending_question.field == "creative_direction"
    assert restored.brief.get("vehicle_type") == "超级跑车"
    assert repository.list_conversations()[0]["session_id"] == state.session_id


def test_asset_can_be_applied_to_the_brief(tmp_path: Path) -> None:
    engine, _ = _engine(_car_decisions(), tmp_path)
    state = engine.start("我想做一个汽车广告。")
    asset = VehicleAsset(
        name="钢铁掠食者",
        description="一辆银灰色宽体未来超跑，贯穿式灯带",
        attributes={
            "vehicle_type": "超级跑车",
            "vehicle_design": "原创未来概念车",
        },
        rules=["全片锁定银灰色车漆与宽体套件。"],
    )

    state = engine.apply_asset(state, asset)

    assert state.brief.get("vehicle_description") == asset.description
    assert state.brief.get("vehicle_type") == "超级跑车"
    assert state.brief.get("vehicle_reference") == "创作资产：钢铁掠食者"
    assert state.brief.field("vehicle_description").source == FieldSource.ASSET
    assert state.pending_question is not None


def test_full_flow_builds_a_valid_requirement() -> None:
    engine, _ = _engine(_car_decisions())
    state = engine.start("我想做一个 30 秒汽车广告")
    for _ in range(4):
        question = state.pending_question
        assert question is not None
        if question.multi_select:
            ids = [option.option_id for option in question.options[:3]]
            state = engine.choose(state, ids[0], selected_ids=ids)
        elif question.field == "duration_seconds":
            option = next(o for o in question.options if "30" in o.label)
            state = engine.choose(state, option.option_id)
        else:
            state = engine.choose(state, question.options[0].option_id)

    assert state.proposal is not None
    requirement = engine.build_requirement(state)

    assert requirement.subject
    assert requirement.duration_seconds == 30
    assert requirement.clip_seconds == 5.0
    assert requirement.clip_count == 6
    assert state.proposal.clip_count == 6
    assert state.proposal.clip_seconds == 5.0
    assert requirement.scene_requirements == [
        "森林林间公路",
        "沙漠戈壁公路",
        "雪山盘山道路",
    ]
    assert requirement.content_type == "商业广告"


def test_build_requirement_refuses_incomplete_brief() -> None:
    engine, _ = _engine([ask("creative_direction", prompt="方向？", labels=("A", "B"))])
    state = engine.start("做一个广告")

    with pytest.raises(AgentContractError):
        engine.build_requirement(state)


def test_confirm_requires_a_proposal() -> None:
    engine, _ = _engine([ask("creative_direction", prompt="方向？", labels=("A", "B"))])
    state = engine.start("做一个广告")

    with pytest.raises(ValueError):
        engine.confirm(state)


def test_confirm_marks_generation_requested() -> None:
    engine, _ = _engine(_car_decisions())
    state = engine.start("做一个超跑广告")
    for _ in range(4):
        question = state.pending_question
        if question.multi_select:
            ids = [option.option_id for option in question.options[:2]]
            state = engine.choose(state, ids[0], selected_ids=ids)
        else:
            state = engine.choose(state, question.options[0].option_id)

    state = engine.confirm(state)

    assert state.generation_requested is True
    assert state.status == ConversationStatus.READY


# ----------------------------------------------------------------------
# the duration is a number of generation calls, not a free-form wish
# ----------------------------------------------------------------------
def test_impossible_duration_is_refused_and_explained(tmp_path: Path) -> None:
    """90 seconds was accepted before; no backend returns 90 seconds."""

    engine, _ = _engine(
        [
            ask(
                "creative_direction",
                prompt="方向？",
                labels=("A", "B"),
                understood={"vehicle_type": "超级跑车"},
            ),
            ask(
                "scenes",
                prompt="场景？",
                labels=("森林", "沙漠", "雪山"),
                multi_select=True,
            ),
            ask(
                "duration_seconds",
                prompt="多长？",
                labels=("30 秒",),
                understood={
                    "scenes": ["森林", "沙漠", "雪山"],
                    "duration_seconds": 90,
                },
            ),
        ],
        tmp_path,
    )
    state = engine.start("做一个超跑广告")
    state = engine.handle(state, "A")
    state = engine.handle(state, "森林、沙漠、雪山，90 秒吧")

    assert state.brief.get("duration_seconds") is None
    notices = [message for message in state.messages if message.kind == "notice"]
    assert notices and "90 秒做不到" in notices[-1].content
    assert "18 条" in notices[-1].content
    assert state.pending_question is not None
    assert state.pending_question.field == "duration_seconds"
    assert state.pending_question.options[0].label == "30 秒（6 条 × 5 秒）"


def test_duration_options_the_backend_cannot_produce_are_dropped() -> None:
    engine, _ = _engine(
        [
            ask(
                "creative_direction",
                prompt="方向？",
                labels=("A", "B"),
                understood={"vehicle_type": "超级跑车"},
            ),
            ask("scenes", prompt="场景？", labels=("森林",), multi_select=True),
            ask(
                "duration_seconds",
                prompt="多长？",
                labels=("5 秒", "90 秒", "30 秒"),
            ),
        ]
    )
    state = engine.start("做一个超跑广告")
    state = engine.handle(state, "A")
    state = engine.handle(state, "森林")

    question = state.pending_question
    assert question is not None
    assert [option.label for option in question.options] == [
        "5 秒（1 条 × 5 秒）",
        "30 秒（6 条 × 5 秒）",
    ]
    assert "生成能力" in question.helper


def test_a_five_second_backend_plans_six_clips() -> None:
    """The user's local workflow returns five seconds per call."""

    from services.clip_plan import capability_for

    director = ScriptedDirector(_car_decisions())
    engine = ConversationEngine(
        None,
        director=director,
        capability=capability_for(clip_seconds=(5,), source="backend"),
    )
    state = engine.start("我想做一个 30 秒汽车广告")
    for _ in range(4):
        question = state.pending_question
        if question.multi_select:
            ids = [option.option_id for option in question.options[:3]]
            state = engine.choose(state, ids[0], selected_ids=ids)
        elif question.field == "duration_seconds":
            option = next(o for o in question.options if "30" in o.label)
            state = engine.choose(state, option.option_id)
        else:
            state = engine.choose(state, question.options[0].option_id)

    requirement = engine.build_requirement(state)
    assert requirement.clip_seconds == 5.0
    assert requirement.clip_count == 6
    assert "6 条" in state.proposal.one_liner
    assert any("6 条 × 5 秒" in line for line in state.proposal.shot_strategy)
