from __future__ import annotations

from schemas.storyboard import Shot
from tools.scene_checker import check_scene_coverage


def _shot(number: int, scene: str) -> Shot:
    return Shot(
        shot_number=number,
        start_seconds=0,
        end_seconds=1,
        scene=scene,
    )


def test_all_required_scenes_are_covered() -> None:
    shots = [
        _shot(1, "森林"),
        _shot(2, "草原"),
        _shot(3, "沙漠"),
        _shot(4, "雪地"),
        _shot(5, "城市"),
    ]
    required = ["森林", "草原", "沙漠", "雪地", "城市"]

    report = check_scene_coverage(shots, required)

    assert report.passed is True
    assert report.missing_scenes == []
    assert report.coverage_ratio == 1.0


def test_missing_scene_is_detected() -> None:
    shots = [
        _shot(1, "森林"),
        _shot(2, "草原"),
        _shot(3, "沙漠"),
        _shot(4, "城市"),
    ]
    required = ["森林", "草原", "沙漠", "雪地", "城市"]

    report = check_scene_coverage(shots, required)

    assert report.passed is False
    assert report.missing_scenes == ["雪地"]
    assert any("缺少必需场景：雪地" in error for error in report.errors)


def test_duplicate_scene_warns_but_does_not_fail() -> None:
    shots = [
        _shot(1, "森林"),
        _shot(2, "城市"),
        _shot(3, "城市"),
    ]
    required = ["森林", "城市"]

    report = check_scene_coverage(shots, required)

    assert report.passed is True
    assert report.duplicate_scenes
    assert any("出现 2 次" in warning for warning in report.warnings)


def test_substring_scene_name_matches() -> None:
    shots = [_shot(1, "城市街道")]
    required = ["城市"]

    report = check_scene_coverage(shots, required)

    assert report.passed is True
    assert report.covered_scenes == ["城市"]


def test_empty_storyboard_fails() -> None:
    report = check_scene_coverage([], ["森林"])

    assert report.passed is False
    assert any("分镜为空" in error for error in report.errors)
