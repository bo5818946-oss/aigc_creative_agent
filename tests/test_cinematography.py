from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from config.cinematography import MODEL_PROFILES
from schemas.cinematography import (
    CameraAngle,
    CameraMovement,
    CinematographySpec,
    ColorGrade,
    LightingStyle,
    ScreenDirection,
    ShotSize,
    TransitionType,
    VfxType,
    take_normalisations,
)
from schemas.storyboard import Shot
from tools.cinematography_checker import (
    check_camera_movement_conflict,
    find_camera_movement_mentions,
    find_prompt_conflicts,
    missing_professional_fields,
)


def _base_shot(**overrides) -> Shot:
    payload = {
        "shot_number": 1,
        "start_seconds": 0.0,
        "end_seconds": 3.0,
        "scene": "城市街道",
    }
    payload.update(overrides)
    return Shot(**payload)


def _professional_shot() -> Shot:
    return _base_shot(
        shot_id="SHOT-001",
        narrative_purpose="建立产品与城市环境的关系",
        cinematography=CinematographySpec(
            shot_size=ShotSize.WS,
            camera_angle=CameraAngle.LOW_ANGLE,
            camera_movement=CameraMovement.PUSH_IN,
            lens="35mm",
            composition="centered_composition",
            lighting_style=LightingStyle.GOLDEN_HOUR,
            color_grade=ColorGrade.TEAL_ORANGE,
            transition=TransitionType.MATCH_CUT,
            vfx=[VfxType.LENS_FLARE],
            screen_direction=ScreenDirection.LEFT_TO_RIGHT,
        ),
        action_start="车辆从画面左侧进入，车头朝右",
        action_end="车辆停在画面中央，车头仍朝右",
        image_prompt="银灰色纯电轿车，城市街道，低角度，黄金时刻",
        video_prompt="车辆缓慢驶入画面，镜头缓慢推近，保持车头朝右",
        negative_prompt="无字幕，无水印，无 Logo",
        continuity_locks=["银灰色流线型纯电轿车，贯穿式 LED 日行灯"],
    )


def test_shot_remains_backward_compatible_without_new_fields() -> None:
    shot = _base_shot(camera_movement="当前阶段未接入模型，待生成。")

    assert shot.cinematography is None
    assert shot.continuity_locks == []
    assert shot.image_prompt == ""
    assert shot.camera_movement == "当前阶段未接入模型，待生成。"


def test_shot_accepts_structured_cinematography_and_serializes() -> None:
    shot = _professional_shot()

    assert shot.cinematography is not None
    assert shot.cinematography.shot_size == ShotSize.WS
    assert shot.cinematography.camera_movement == CameraMovement.PUSH_IN
    assert shot.cinematography.vfx == [VfxType.LENS_FLARE]

    payload = json.loads(shot.model_dump_json())
    assert payload["cinematography"]["shot_size"] == "wide_shot"
    assert payload["cinematography"]["screen_direction"] == "left_to_right"
    assert payload["continuity_locks"] == [
        "银灰色流线型纯电轿车，贯穿式 LED 日行灯"
    ]


def test_unknown_shot_size_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CinematographySpec(shot_size="banana_shot")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("medium_wide_shot", "medium_wide_shot"),
        ("Medium Wide Shot", "medium_wide_shot"),
        ("中远景", "medium_wide_shot"),
        ("全景", "full_shot"),
        ("特写", "close_up"),
        ("MCU", "medium_close_up"),
    ],
)
def test_shot_size_spellings_are_normalised(raw: str, expected: str) -> None:
    """Models return synonyms; a synonym must not kill the whole storyboard."""

    assert CinematographySpec(shot_size=raw).shot_size.value == expected


def test_unknown_enum_member_still_fails_loudly() -> None:
    with pytest.raises(ValidationError):
        CinematographySpec(camera_movement="dolly_zoom_banana")


def test_normalisation_log_records_what_the_model_wrote() -> None:
    """The log is how the vocabulary grows from real usage, not guesswork."""

    take_normalisations()  # drain anything left by earlier tests

    CinematographySpec(shot_size="中远景", camera_movement="dolly in")

    log = take_normalisations()
    pairs = {
        (item["field"], item["raw"], item["canonical"])
        for item in log["normalised"]
    }

    assert ("ShotSize", "中远景", "medium_wide_shot") in pairs
    assert ("CameraMovement", "dolly in", "push_in") in pairs
    # Draining twice yields nothing, so one generation cannot see another's log.
    assert take_normalisations()["normalised"] == []


def test_unknown_values_are_logged_not_normalised() -> None:
    take_normalisations()

    with pytest.raises(ValidationError):
        CinematographySpec(shot_size="banana_shot")

    log = take_normalisations()
    assert log["normalised"] == []
    assert ("ShotSize", "banana_shot") in {
        (item["field"], item["raw"]) for item in log["unknown"]
    }


def test_prompt_conflict_film_grain_vs_4k() -> None:
    conflicts = find_prompt_conflicts(
        "8mm film grain, vintage look, ultra sharp 4K"
    )

    assert any(conflict.severity == "error" for conflict in conflicts)
    assert any("胶片颗粒" in conflict.reason for conflict in conflicts)


def test_prompt_conflict_slow_motion_vs_fast_action() -> None:
    conflicts = find_prompt_conflicts(
        "slow motion bullet time with high-speed action"
    )

    assert any("速度矛盾" in conflict.reason for conflict in conflicts)


def test_clean_prompt_has_no_conflicts() -> None:
    assert find_prompt_conflicts(
        "中景，缓慢推镜，黄金时刻，青橙调，无字幕无水印"
    ) == []


def test_single_camera_movement_is_detected() -> None:
    movements = find_camera_movement_mentions("中景缓慢推镜，主体保持清晰")

    assert movements == [CameraMovement.PUSH_IN]
    assert check_camera_movement_conflict("中景缓慢推镜，主体保持清晰") == []


def test_multiple_camera_movements_produce_warning() -> None:
    conflicts = check_camera_movement_conflict("缓慢推镜并向左横摇")

    assert len(conflicts) == 1
    assert conflicts[0].severity == "warning"
    assert "push_in" in conflicts[0].matched_terms
    assert "pan_left" in conflicts[0].matched_terms


def test_model_profiles_have_reference_capabilities() -> None:
    assert MODEL_PROFILES["generic"].max_single_shot_seconds == 10
    assert MODEL_PROFILES["seedance"].max_single_shot_seconds == 15
    assert MODEL_PROFILES["runway"].negative_prompt_support == "none"
    assert MODEL_PROFILES["veo"].preferred_language == "en"
    assert MODEL_PROFILES["wan"].preferred_language == "zh"


def test_minimal_shot_reports_missing_professional_fields() -> None:
    missing = missing_professional_fields(_base_shot())

    assert "cinematography" in missing
    assert "shot_id" in missing
    assert "action_start" in missing
    assert "image_prompt" in missing
    assert "continuity_locks" in missing


def test_professional_shot_has_all_required_fields() -> None:
    shot = _professional_shot()

    assert missing_professional_fields(shot) == []
    assert missing_professional_fields(shot.model_dump(mode="json")) == []
