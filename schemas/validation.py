"""Structured validation results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DurationCheckResult(BaseModel):
    check_type: Literal["duration"] = "duration"
    passed: bool
    target_duration_seconds: float
    tolerance_seconds: float
    shot_count: int
    sum_of_shot_durations_seconds: float
    timeline_end_seconds: float
    intervals: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PromptConflict(BaseModel):
    """A deterministic keyword-level conflict found in a prompt.

    These checks catch contradictory instructions such as ``film grain`` plus
    ``ultra sharp 4K``. They are not a semantic quality judgment.
    """

    severity: Literal["error", "warning"]
    reason: str
    matched_terms: list[str] = Field(default_factory=list)


class SceneCheckResult(BaseModel):
    check_type: Literal["scene_coverage"] = "scene_coverage"
    passed: bool
    required_scenes: list[str] = Field(default_factory=list)
    covered_scenes: list[str] = Field(default_factory=list)
    missing_scenes: list[str] = Field(default_factory=list)
    duplicate_scenes: list[str] = Field(default_factory=list)
    coverage_ratio: float = 0.0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ConsistencyCheckResult(BaseModel):
    check_type: Literal["consistency"] = "consistency"
    passed: bool
    checks: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    semantic_notes: list[str] = Field(default_factory=list)


class PromptCheckResult(BaseModel):
    check_type: Literal["prompt_quality"] = "prompt_quality"
    passed: bool
    per_shot: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[PromptConflict] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AggregateValidationReport(BaseModel):
    check_type: Literal["aggregate"] = "aggregate"
    passed: bool
    duration: DurationCheckResult
    scene: SceneCheckResult
    consistency: ConsistencyCheckResult
    prompt: PromptCheckResult
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
