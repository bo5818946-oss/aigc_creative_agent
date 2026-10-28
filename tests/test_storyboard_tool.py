from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.storyboard import ShotDraft, StoryboardDraft
from services.llm_service import LLMService
from tests.fakes import FakeChatClient
from tools.storyboard_tool import (
    draft_to_storyboard,
    generate_deterministic_storyboard,
    generate_storyboard_with_llm,
)


def test_deterministic_storyboard_covers_all_scenes(
    demo_requirement,
) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)

    assert storyboard.generation_method == "deterministic_placeholder"
    assert len(storyboard.shots) == len(
        demo_requirement.scene_requirements
    )
    assert [shot.scene for shot in storyboard.shots] == (
        demo_requirement.scene_requirements
    )
    assert storyboard.shots[0].start_seconds == 0
    assert storyboard.shots[-1].end_seconds == (
        demo_requirement.duration_seconds
    )
    assert all(
        shot.cinematography is not None for shot in storyboard.shots
    )
    assert all(shot.continuity_locks for shot in storyboard.shots)
    assert all(shot.negative_prompt for shot in storyboard.shots)
    assert all(shot.image_prompt == "" for shot in storyboard.shots)


def test_draft_conversion_fills_defaults(demo_requirement) -> None:
    draft = StoryboardDraft(
        shots=[
            ShotDraft(
                start_seconds="0s",
                end_seconds="6s",
                scene="森林",
                action_start="进入画面",
                action_end="离开画面",
            )
        ]
    )

    storyboard = draft_to_storyboard(draft, demo_requirement, "llm")
    shot = storyboard.shots[0]

    assert shot.shot_id == "SHOT-001"
    assert shot.start_seconds == 0.0
    assert shot.end_seconds == 6.0
    assert shot.subject_state == (
        f"{demo_requirement.subject}保持统一外观"
    )
    assert shot.continuity_locks == (
        demo_requirement.consistency_constraints
    )
    assert shot.negative_prompt
    assert shot.cinematography is not None
    assert storyboard.generation_method == "llm"


def test_missing_time_raises_value_error(demo_requirement) -> None:
    draft = StoryboardDraft(shots=[ShotDraft(scene="森林")])

    with pytest.raises(ValueError) as exc_info:
        draft_to_storyboard(draft, demo_requirement, "llm")

    assert "缺少 start_seconds" in str(exc_info.value)


def test_draft_rejects_unknown_cinematography_enum() -> None:
    with pytest.raises(ValidationError):
        ShotDraft(cinematography={"shot_size": "banana_shot"})


def test_draft_accepts_model_spellings_of_shot_size() -> None:
    # This is the value that used to abort a whole storyboard generation.
    draft = ShotDraft(cinematography={"shot_size": "medium_wide_shot"})

    assert draft.cinematography is not None
    assert draft.cinematography.shot_size.value == "medium_wide_shot"


def test_llm_storyboard_generation_uses_fake_client(
    demo_requirement,
) -> None:
    payload = {
        "generation_method": "llm",
        "shots": [
            {
                "shot_number": 1,
                "shot_id": "SHOT-001",
                "start_seconds": 0,
                "end_seconds": 30,
                "scene": "森林",
                "narrative_purpose": "建立环境与主体",
                "action_start": "车辆从左侧进入",
                "action_end": "车辆到达画面中央",
                "subject_state": "同一辆银灰色纯电轿车，车头朝右",
                "continuity_locks": ["保持同一辆车，车头始终朝右"],
                "cinematography": {
                    "shot_size": "wide_shot",
                    "camera_angle": "low_angle",
                    "camera_movement": "push_in",
                    "lens": "35mm",
                    "lighting_style": "golden_hour",
                    "color_grade": "teal_orange",
                    "transition": "hard_cut",
                    "screen_direction": "left_to_right",
                },
                "sound": "环境声",
                "negative_prompt": "无字幕，无水印",
            }
        ],
    }
    client = FakeChatClient([payload])
    service = LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        client=client,
        retry_backoff_seconds=0,
    )

    storyboard = generate_storyboard_with_llm(service, demo_requirement)

    assert storyboard.generation_method == "llm"
    assert len(storyboard.shots) == 1
    prompt_text = client.calls[0]["messages"][1]["content"]
    assert "请为下面的创作需求生成分镜" in prompt_text
    assert "可用枚举值" in prompt_text
