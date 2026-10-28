from __future__ import annotations

from schemas.storyboard import Storyboard
from tools.prompt_builder import build_prompts_for_storyboard
from tools.storyboard_tool import generate_deterministic_storyboard


def test_generated_prompts_contain_required_elements(
    demo_requirement,
) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)
    updated = build_prompts_for_storyboard(
        storyboard,
        demo_requirement,
        "generic",
    )

    assert updated.prompt_generation_method == "deterministic_builder"
    assert len(updated.shots) == len(storyboard.shots)
    assert all(
        shot.image_prompt and shot.video_prompt
        for shot in updated.shots
    )
    assert all(
        shot.negative_prompt for shot in updated.shots
    )
    assert all(
        demo_requirement.subject in shot.image_prompt
        for shot in updated.shots
    )
    assert all(
        shot.scene in shot.image_prompt
        and shot.scene in shot.video_prompt
        for shot in updated.shots
    )
    assert all(
        "负向约束" in shot.video_prompt
        for shot in updated.shots
    )

    first_video = updated.shots[0].video_prompt
    assert "广角 / 远景" in first_video
    assert "推镜" in first_video
    assert "黄金时刻" in first_video
    assert "青橙调" in first_video
    assert "16:9" in first_video
    assert "主体从左向右运动" in first_video


def test_prompt_generation_is_deterministic(demo_requirement) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)
    first = build_prompts_for_storyboard(storyboard, demo_requirement)
    second = build_prompts_for_storyboard(storyboard, demo_requirement)

    assert [shot.image_prompt for shot in first.shots] == [
        shot.image_prompt for shot in second.shots
    ]
    assert [shot.video_prompt for shot in first.shots] == [
        shot.video_prompt for shot in second.shots
    ]


def test_unknown_composition_alias_is_localized(demo_requirement) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)
    shot = storyboard.shots[0].model_copy(deep=True)
    assert shot.cinematography is not None
    shot.cinematography.composition = "center_framing"
    custom = Storyboard(
        generation_method="test",
        shots=[shot],
    )

    updated = build_prompts_for_storyboard(custom, demo_requirement)

    assert "中心构图" in updated.shots[0].image_prompt
    assert "center_framing" not in updated.shots[0].image_prompt


def test_runway_profile_avoids_negative_command_style(
    demo_requirement,
) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)
    updated = build_prompts_for_storyboard(
        storyboard,
        demo_requirement,
        "runway",
    )

    video_prompt = updated.shots[0].video_prompt
    assert "负向约束" not in video_prompt
    assert "画面保持干净" in video_prompt
