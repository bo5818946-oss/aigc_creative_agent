"""Deterministic checks for cinematography prompt quality.

These checks are keyword-based and intentionally conservative. They catch
contradictory instructions that are known to hurt video generation, but they
cannot judge whether a shot is artistically good. Semantic review remains a
separate, explicitly labelled step.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from config.cinematography import (
    CAMERA_MOVEMENT_KEYWORDS,
    CONFLICT_RULES,
    PROFESSIONAL_SHOT_FIELDS,
)
from schemas.cinematography import CameraMovement
from schemas.validation import PromptConflict


def find_prompt_conflicts(text: str) -> list[PromptConflict]:
    """Return deterministic term-level conflicts found in a prompt."""

    normalized = text.casefold()
    if not normalized.strip():
        return []

    conflicts: list[PromptConflict] = []
    for rule in CONFLICT_RULES:
        left_hits = [
            term for term in rule.left_terms if term.casefold() in normalized
        ]
        right_hits = [
            term for term in rule.right_terms if term.casefold() in normalized
        ]
        if left_hits and right_hits:
            conflicts.append(
                PromptConflict(
                    severity=rule.severity,
                    reason=rule.reason,
                    matched_terms=[*left_hits, *right_hits],
                )
            )
    return conflicts


def find_camera_movement_mentions(text: str) -> list[CameraMovement]:
    """Find camera-movement vocabulary mentioned in one shot description.

    This is a heuristic. It is useful for catching ``push in + pan`` in a
    single shot, but a multi-shot prompt should be checked shot by shot.
    """

    normalized = text.casefold()
    mentions: list[CameraMovement] = []
    for movement, keywords in CAMERA_MOVEMENT_KEYWORDS.items():
        if any(keyword.casefold() in normalized for keyword in keywords):
            mentions.append(movement)
    return mentions


def check_camera_movement_conflict(text: str) -> list[PromptConflict]:
    """Warn when one shot description names more than one camera movement."""

    movements = find_camera_movement_mentions(text)
    if len(movements) <= 1:
        return []
    return [
        PromptConflict(
            severity="warning",
            reason=(
                "单个镜头中检测到多种运镜；建议一个镜头只保留一个主要运镜，"
                "否则生成稳定性会下降。"
            ),
            matched_terms=[movement.value for movement in movements],
        )
    ]


def missing_professional_fields(
    shot: Mapping[str, Any] | Any,
) -> list[str]:
    """Return professional shot fields that are missing or empty.

    The deterministic duration check can run on a minimal Phase 1 storyboard.
    This check is stricter and is meant for storyboards that claim to be
    production-ready.
    """

    if hasattr(shot, "model_dump"):
        data: dict[str, Any] = shot.model_dump(mode="json")
    elif isinstance(shot, Mapping):
        data = dict(shot)
    else:
        raise TypeError("shot must be a Pydantic model or a mapping")

    missing: list[str] = []
    for field_name in PROFESSIONAL_SHOT_FIELDS:
        value = data.get(field_name)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(field_name)
    return missing
