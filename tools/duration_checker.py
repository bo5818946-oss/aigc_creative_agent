"""Deterministic duration validation.

This module intentionally uses plain Python arithmetic. It does not ask a model
to judge timing. It checks:

- invalid or non-finite time values;
- negative start times and non-positive shot durations;
- overlaps and unexpected gaps between consecutive shots;
- the total timeline against the target duration within a tolerance.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from schemas.storyboard import Shot
from schemas.validation import DurationCheckResult


def _number(
    value: Any,
    *,
    field_name: str,
    shot_label: str,
    errors: list[str],
) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{shot_label}的 {field_name} 不是有效数字。")
        return None
    if not math.isfinite(number):
        errors.append(f"{shot_label}的 {field_name} 不是有限数字。")
        return None
    return number


def check_duration(
    shots: Sequence[Shot | Mapping[str, Any]],
    target_duration_seconds: float,
    tolerance_seconds: float = 0.5,
) -> DurationCheckResult:
    """Validate a storyboard timeline.

    ``timeline_end_seconds`` is used for the target-duration comparison because
    it represents the time position where the final shot ends. The sum of shot
    durations is also reported separately, which makes gaps visible.
    """

    target = float(target_duration_seconds)
    tolerance = float(tolerance_seconds)
    if not math.isfinite(target) or target <= 0:
        raise ValueError("target_duration_seconds must be a positive finite number")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance_seconds must be a non-negative finite number")

    errors: list[str] = []
    warnings: list[str] = []
    intervals: list[dict[str, Any]] = []
    total_shot_duration = 0.0
    timeline_end = 0.0
    previous_end: float | None = None
    first_start: float | None = None

    if not shots:
        errors.append("分镜列表为空，无法校验时长。")
        return DurationCheckResult(
            passed=False,
            target_duration_seconds=target,
            tolerance_seconds=tolerance,
            shot_count=0,
            sum_of_shot_durations_seconds=0.0,
            timeline_end_seconds=0.0,
            intervals=[],
            errors=errors,
            warnings=warnings,
        )

    for index, raw_shot in enumerate(shots, start=1):
        if isinstance(raw_shot, Shot):
            shot_number = raw_shot.shot_number
            scene = raw_shot.scene
            start_value: Any = raw_shot.start_seconds
            end_value: Any = raw_shot.end_seconds
        elif isinstance(raw_shot, Mapping):
            try:
                shot_number = int(raw_shot.get("shot_number", index))
            except (TypeError, ValueError):
                shot_number = index
            scene = str(raw_shot.get("scene", ""))
            start_value = raw_shot.get("start_seconds")
            end_value = raw_shot.get("end_seconds")
        else:
            errors.append(f"第 {index} 个镜头格式无效，无法读取时间信息。")
            continue

        label = f"镜头 {shot_number}"
        start = _number(
            start_value,
            field_name="start_seconds",
            shot_label=label,
            errors=errors,
        )
        end = _number(
            end_value,
            field_name="end_seconds",
            shot_label=label,
            errors=errors,
        )
        if start is None or end is None:
            continue

        duration = end - start
        if start < 0:
            errors.append(f"{label}开始时间为 {start:.2f} 秒，不能为负数。")
        if duration <= 0:
            errors.append(f"{label}时长为 {duration:.2f} 秒，必须大于 0。")

        if first_start is None:
            first_start = start
        else:
            if previous_end is not None:
                gap_or_overlap = start - previous_end
                if gap_or_overlap < -tolerance:
                    errors.append(
                        f"{label}与前一个镜头重叠 {-gap_or_overlap:.2f} 秒。"
                    )
                elif gap_or_overlap > tolerance:
                    errors.append(
                        f"{label}之前存在 {gap_or_overlap:.2f} 秒空档。"
                    )

        previous_end = end
        total_shot_duration += duration
        timeline_end = max(timeline_end, end)
        intervals.append(
            {
                "shot_number": shot_number,
                "scene": scene,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "duration_seconds": round(duration, 3),
            }
        )

    if not intervals:
        errors.append("没有可解析的分镜时间信息。")
    elif first_start is not None and first_start > tolerance:
        errors.append(f"首个镜头从 {first_start:.2f} 秒开始，存在前导空档。")

    difference = timeline_end - target
    if abs(difference) > tolerance:
        errors.append(
            f"总时长 {timeline_end:.2f} 秒，与目标 {target:.2f} 秒"
            f"相差 {abs(difference):.2f} 秒，超出容差 {tolerance:.2f} 秒。"
        )

    return DurationCheckResult(
        passed=not errors,
        target_duration_seconds=round(target, 3),
        tolerance_seconds=round(tolerance, 3),
        shot_count=len(shots),
        sum_of_shot_durations_seconds=round(total_shot_duration, 3),
        timeline_end_seconds=round(timeline_end, 3),
        intervals=intervals,
        errors=errors,
        warnings=warnings,
    )
