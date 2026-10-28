from __future__ import annotations

from ui.pages.validation import _checks, _suggestions


def test_old_duration_report_marks_other_checks_not_executed() -> None:
    old_report = {
        "check_type": "duration",
        "passed": True,
        "target_duration_seconds": 30,
        "timeline_end_seconds": 30,
        "errors": [],
    }

    checks = _checks(old_report)
    suggestions = _suggestions(checks)

    assert checks["duration"] is old_report
    assert checks["scene"] is None
    assert checks["consistency"] is None
    assert checks["prompt"] is None
    assert any("场景检查未执行" in item for item in suggestions)


def test_missing_report_marks_all_checks_not_executed() -> None:
    checks = _checks(None)
    suggestions = _suggestions(checks)

    assert all(value is None for value in checks.values())
    assert len(suggestions) == 4
    assert all("未执行" in item for item in suggestions)


def test_aggregate_report_maps_four_checks() -> None:
    duration = {"passed": True, "errors": [], "warnings": []}
    scene = {"passed": True, "errors": [], "warnings": []}
    consistency = {"passed": True, "errors": [], "warnings": []}
    prompt = {"passed": True, "errors": [], "warnings": []}
    report = {
        "check_type": "aggregate",
        "passed": True,
        "duration": duration,
        "scene": scene,
        "consistency": consistency,
        "prompt": prompt,
        "errors": [],
        "warnings": [],
    }

    checks = _checks(report)

    assert checks == {
        "duration": duration,
        "scene": scene,
        "consistency": consistency,
        "prompt": prompt,
    }
    assert _suggestions(checks) == []
