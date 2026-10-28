"""Duration arithmetic: a film is whole generation clips, not one long video."""

from __future__ import annotations

import pytest

from services.clip_plan import (
    ClipPlan,
    DurationNotPlannable,
    capability_for,
    check_duration,
    duration_choices,
    plan_for,
)


def test_capability_reads_the_model_table() -> None:
    capability = capability_for("hailuo")
    assert capability.clip_seconds == (5.0, 10.0)
    assert capability.max_clip_seconds == 10.0
    assert capability.max_total_seconds == 60.0
    assert "单次生成 5/10 秒" in capability.quote()


def test_unknown_model_fails_loudly() -> None:
    with pytest.raises(ValueError, match="未知的目标视频模型"):
        capability_for("no-such-model")


def test_ninety_seconds_is_refused_not_planned() -> None:
    """The reported bug: a 90-second clip on a five-second backend."""

    capability = capability_for(clip_seconds=(5,), source="backend", display_name="本地 5 秒工作流")
    check = check_duration(90, capability)
    assert check.ok is False
    assert "90 秒做不到" in check.message
    assert "18 条" in check.message
    assert "超过单支片 12 条" in check.message
    with pytest.raises(DurationNotPlannable):
        plan_for(90, capability)


def test_local_five_second_backend_plans_six_clips() -> None:
    capability = capability_for(clip_seconds=(5,), source="backend")
    plan = plan_for(30, capability)
    assert isinstance(plan, ClipPlan)
    assert (plan.clip_count, plan.clip_seconds) == (6, 5.0)
    assert plan.exact is True
    assert plan.brief_line() == "成片 30 秒，共 6 条，每条 5 秒（素材合计 30 秒）"


def test_single_clip_is_labelled_as_one_generation() -> None:
    capability = capability_for(clip_seconds=(5,), source="backend")
    plan = plan_for(5, capability)
    assert plan.single_generation is True
    assert plan.describe() == "5 秒 · 1 条（单次生成）"


def test_min_clips_refuses_to_merge_scenes() -> None:
    capability = capability_for("veo")  # 4 / 6 / 8 seconds
    assert plan_for(9, capability).clip_count == 3
    # Four scenes cannot live in three 4-second clips of a 9-second film.
    with pytest.raises(DurationNotPlannable, match="装不下 4 个场景"):
        plan_for(9, capability, min_clips=4)
    # Give the film more time and the same four scenes fit.
    assert plan_for(16, capability, min_clips=4).clip_count == 4


def test_scenes_that_cannot_fit_raise_with_advice() -> None:
    capability = capability_for(clip_seconds=(5,), source="backend")
    with pytest.raises(DurationNotPlannable, match="装不下"):
        plan_for(5, capability, min_clips=3)


def test_unrepresentable_duration_says_the_nearest_values() -> None:
    capability = capability_for("veo")  # 4 / 6 / 8 seconds
    check = check_duration(15, capability)
    assert check.ok is False
    assert "15 秒不能用 4/6/8 秒的片段拼出来" in check.message
    assert "16" in check.message


def test_duration_choices_are_all_whole_clips() -> None:
    capability = capability_for(clip_seconds=(5,), source="backend")
    choices = duration_choices(capability)
    assert [plan.total_seconds for plan in choices] == [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60]
    assert all(plan.exact for plan in choices)


def test_planner_prefers_more_shots_over_longer_clips() -> None:
    """Measured: 5 s costs 235 s of compute, 10 s costs 582 s (2.5×, not 2×)."""

    capability = capability_for("generic")
    assert plan_for(20, capability).clip_count == 4  # 4 × 5, not 2 × 10
    assert plan_for(20, capability).clip_seconds == 5.0
    assert plan_for(25, capability).clip_count == 5  # 25 is not a multiple of 10
