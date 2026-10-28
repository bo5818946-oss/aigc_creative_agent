from __future__ import annotations

from schemas.cinematography import CinematographySpec, ScreenDirection
from schemas.storyboard import Shot
from tools.consistency_checker import check_consistency
from tools.storyboard_tool import generate_deterministic_storyboard


def _shot(
    demo_requirement,
    *,
    screen_direction: ScreenDirection,
    subject_state: str | None = None,
    action_start: str = "",
) -> Shot:
    return Shot(
        shot_number=1,
        start_seconds=0,
        end_seconds=30,
        scene="森林",
        subject_state=(
            subject_state
            if subject_state is not None
            else f"{demo_requirement.subject}保持统一外观"
        ),
        action_start=action_start,
        continuity_locks=list(demo_requirement.consistency_constraints),
        cinematography=CinematographySpec(
            screen_direction=screen_direction,
        ),
    )


def test_consistent_deterministic_storyboard_passes(
    demo_requirement,
) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)

    report = check_consistency(storyboard.shots, demo_requirement)

    assert report.passed is True
    assert report.semantic_notes


def test_screen_position_is_not_travel_direction(
    demo_requirement,
) -> None:
    shot = _shot(
        demo_requirement,
        screen_direction=ScreenDirection.LEFT_TO_RIGHT,
        subject_state=(
            f"{demo_requirement.subject}，"
            "车辆从画面左侧进入，车头朝右"
        ),
        action_start="车辆从画面左侧进入，车头朝右",
    )

    report = check_consistency([shot], demo_requirement)

    assert report.passed is True


def test_left_to_right_phrase_is_one_direction(
    demo_requirement,
) -> None:
    shot = _shot(
        demo_requirement,
        screen_direction=ScreenDirection.LEFT_TO_RIGHT,
        subject_state=(
            f"{demo_requirement.subject}，车头朝右，"
            "前进方向从左到右"
        ),
        action_start="车辆从画面左侧进入，前进方向从左到右",
    )

    report = check_consistency([shot], demo_requirement)

    assert report.passed is True


def test_opposite_screen_directions_are_rejected(
    demo_requirement,
) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)
    shots = list(storyboard.shots)
    second = shots[1]
    shots[1] = second.model_copy(
        update={
            "cinematography": second.cinematography.model_copy(
                update={
                    "screen_direction": ScreenDirection.RIGHT_TO_LEFT,
                }
            )
        }
    )

    report = check_consistency(shots, demo_requirement)

    assert report.passed is False
    assert any("相反" in error for error in report.errors)


def test_text_direction_conflicts_with_screen_direction(
    demo_requirement,
) -> None:
    shot = _shot(
        demo_requirement,
        screen_direction=ScreenDirection.LEFT_TO_RIGHT,
        subject_state=f"{demo_requirement.subject}，车辆向左行驶",
        action_start="车辆向左行驶",
    )

    report = check_consistency([shot], demo_requirement)

    assert report.passed is False
    assert any(
        "文本中的车辆方向" in error for error in report.errors
    )


def test_missing_continuity_lock_is_rejected(
    demo_requirement,
) -> None:
    shot = _shot(
        demo_requirement,
        screen_direction=ScreenDirection.LEFT_TO_RIGHT,
        subject_state="",
    )
    shot = shot.model_copy(update={"continuity_locks": []})

    report = check_consistency([shot], demo_requirement)

    assert report.passed is False
    assert any(
        "缺少主体状态或连续性锁" in error for error in report.errors
    )
