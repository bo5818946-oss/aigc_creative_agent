from __future__ import annotations

from tools.duration_checker import check_duration


def _shot(number: int, start: float, end: float, scene: str = "测试场景") -> dict:
    return {
        "shot_number": number,
        "start_seconds": start,
        "end_seconds": end,
        "scene": scene,
    }


def test_valid_30_second_storyboard_passes() -> None:
    shots = [
        _shot(1, 0, 10, "森林"),
        _shot(2, 10, 20, "雪地"),
        _shot(3, 20, 30, "城市"),
    ]

    report = check_duration(shots, 30, tolerance_seconds=0.01)

    assert report.passed is True
    assert report.timeline_end_seconds == 30.0
    assert report.sum_of_shot_durations_seconds == 30.0
    assert report.errors == []


def test_short_storyboard_reports_three_second_gap() -> None:
    shots = [
        _shot(1, 0, 9),
        _shot(2, 9, 18),
        _shot(3, 18, 27),
    ]

    report = check_duration(shots, 30, tolerance_seconds=0.01)

    assert report.passed is False
    assert report.timeline_end_seconds == 27.0
    assert any("相差 3.00 秒" in error for error in report.errors)


def test_overlap_is_rejected() -> None:
    shots = [
        _shot(1, 0, 10),
        _shot(2, 9, 20),
        _shot(3, 20, 30),
    ]

    report = check_duration(shots, 30, tolerance_seconds=0.01)

    assert report.passed is False
    assert any("重叠" in error for error in report.errors)


def test_unexpected_gap_is_rejected() -> None:
    shots = [
        _shot(1, 0, 10),
        _shot(2, 11, 20),
        _shot(3, 20, 30),
    ]

    report = check_duration(shots, 30, tolerance_seconds=0.01)

    assert report.passed is False
    assert any("空档" in error for error in report.errors)


def test_negative_duration_is_rejected() -> None:
    shots = [_shot(1, 10, 5)]

    report = check_duration(shots, 10, tolerance_seconds=0.01)

    assert report.passed is False
    assert any("必须大于 0" in error for error in report.errors)
