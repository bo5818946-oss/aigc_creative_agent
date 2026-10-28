from __future__ import annotations

from tools.prompt_builder import build_prompts_for_storyboard
from tools.prompt_checker import check_prompt_quality
from tools.storyboard_tool import generate_deterministic_storyboard


def _good_storyboard(demo_requirement):
    storyboard = generate_deterministic_storyboard(demo_requirement)
    return build_prompts_for_storyboard(storyboard, demo_requirement)


def test_clean_prompts_pass(demo_requirement) -> None:
    storyboard = _good_storyboard(demo_requirement)

    report = check_prompt_quality(storyboard.shots, demo_requirement)

    assert report.passed is True
    assert report.errors == []
    assert len(report.per_shot) == len(storyboard.shots)


def test_missing_image_prompt_is_rejected(demo_requirement) -> None:
    storyboard = _good_storyboard(demo_requirement)
    shots = list(storyboard.shots)
    shots[0] = shots[0].model_copy(update={"image_prompt": ""})

    report = check_prompt_quality(shots, demo_requirement)

    assert report.passed is False
    assert any("image_prompt" in error for error in report.errors)


def test_missing_negative_prompt_is_rejected(demo_requirement) -> None:
    storyboard = _good_storyboard(demo_requirement)
    shots = list(storyboard.shots)
    shots[0] = shots[0].model_copy(update={"negative_prompt": ""})

    report = check_prompt_quality(shots, demo_requirement)

    assert report.passed is False
    assert any("negative_prompt" in error for error in report.errors)


def test_conflicting_prompt_terms_are_rejected(
    demo_requirement,
) -> None:
    storyboard = _good_storyboard(demo_requirement)
    shots = list(storyboard.shots)
    shots[0] = shots[0].model_copy(
        update={
            "video_prompt": (
                shots[0].video_prompt
                + " 8mm film grain, ultra sharp 4K"
            )
        }
    )

    report = check_prompt_quality(shots, demo_requirement)

    assert report.passed is False
    assert any("胶片颗粒" in error for error in report.errors)


def test_multiple_camera_movements_produce_warning(
    demo_requirement,
) -> None:
    storyboard = _good_storyboard(demo_requirement)
    shots = list(storyboard.shots)
    shots[0] = shots[0].model_copy(
        update={"video_prompt": shots[0].video_prompt + " 并向左横摇"}
    )

    report = check_prompt_quality(shots, demo_requirement)

    assert report.passed is True
    assert any("多种运镜" in warning for warning in report.warnings)


def test_runway_negative_style_warns(demo_requirement) -> None:
    storyboard = _good_storyboard(demo_requirement)

    report = check_prompt_quality(
        storyboard.shots,
        demo_requirement,
        "runway",
    )

    assert report.passed is True
    assert any(
        "不支持负向提示词" in warning for warning in report.warnings
    )


def test_veo_language_warns(demo_requirement) -> None:
    storyboard = _good_storyboard(demo_requirement)

    report = check_prompt_quality(
        storyboard.shots,
        demo_requirement,
        "veo",
    )

    assert report.passed is True
    assert any("偏好英文" in warning for warning in report.warnings)
