"""Aggregate deterministic validation for a generated storyboard."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from schemas.project import CreativeRequirement
from schemas.storyboard import Shot
from schemas.validation import AggregateValidationReport
from tools.consistency_checker import check_consistency
from tools.duration_checker import check_duration
from tools.prompt_checker import check_prompt_quality
from tools.scene_checker import check_scene_coverage


def run_validation(
    shots: Sequence[Shot | Mapping[str, Any]],
    requirement: CreativeRequirement,
    tolerance_seconds: float,
    model_profile_key: str = "generic",
) -> AggregateValidationReport:
    duration = check_duration(
        shots=shots,
        target_duration_seconds=requirement.duration_seconds,
        tolerance_seconds=tolerance_seconds,
    )
    scene = check_scene_coverage(
        shots,
        requirement.scene_requirements,
    )
    consistency = check_consistency(shots, requirement)
    prompt = check_prompt_quality(
        shots,
        requirement,
        model_profile_key,
    )

    errors: list[str] = []
    warnings: list[str] = []
    for check in (duration, scene, consistency, prompt):
        errors.extend(check.errors)
        warnings.extend(check.warnings)

    return AggregateValidationReport(
        passed=(
            duration.passed
            and scene.passed
            and consistency.passed
            and prompt.passed
        ),
        duration=duration,
        scene=scene,
        consistency=consistency,
        prompt=prompt,
        errors=errors,
        warnings=warnings,
    )
