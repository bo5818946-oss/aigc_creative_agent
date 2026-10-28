"""Deterministic prompt-quality checks for storyboard shots."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from config.cinematography import MODEL_PROFILES
from schemas.project import CreativeRequirement
from schemas.storyboard import Shot
from schemas.validation import PromptCheckResult, PromptConflict
from tools.cinematography_checker import (
    check_camera_movement_conflict,
    find_prompt_conflicts,
)

def _has_chinese(text: str) -> bool:
    return any("一" <= character <= "鿿" for character in text)


def _field(shot: Shot | Mapping[str, Any], name: str, default: Any) -> Any:
    if isinstance(shot, Shot):
        return getattr(shot, name, default)
    return shot.get(name, default)


def _cinematography(shot: Shot | Mapping[str, Any]) -> dict[str, Any]:
    value = _field(shot, "cinematography", None)
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def check_prompt_quality(
    shots: Sequence[Shot | Mapping[str, Any]],
    requirement: CreativeRequirement,
    model_profile_key: str = "generic",
) -> PromptCheckResult:
    profile = MODEL_PROFILES.get(
        model_profile_key,
        MODEL_PROFILES["generic"],
    )
    errors: list[str] = []
    warnings: list[str] = []
    per_shot: list[dict[str, Any]] = []
    all_conflicts: list[PromptConflict] = []

    if not shots:
        return PromptCheckResult(
            passed=False,
            per_shot=[],
            conflicts=[],
            errors=["分镜为空，无法检查提示词质量。"],
            warnings=[],
        )

    for index, shot in enumerate(shots, start=1):
        shot_errors: list[str] = []
        shot_warnings: list[str] = []
        missing_fields: list[str] = []

        image_prompt = str(_field(shot, "image_prompt", "") or "")
        video_prompt = str(_field(shot, "video_prompt", "") or "")
        negative_prompt = str(_field(shot, "negative_prompt", "") or "")
        scene = str(_field(shot, "scene", "") or "")
        action = str(_field(shot, "action", "") or "")
        action_start = str(_field(shot, "action_start", "") or "")
        action_end = str(_field(shot, "action_end", "") or "")
        cinematography = _cinematography(shot)

        for field_name, value in (
            ("image_prompt", image_prompt),
            ("video_prompt", video_prompt),
            ("negative_prompt", negative_prompt),
            ("scene", scene),
        ):
            if not value.strip():
                missing_fields.append(field_name)
                shot_errors.append(f"镜头 {index} 缺少 {field_name}。")

        if not any(
            value.strip() for value in (action, action_start, action_end)
        ):
            missing_fields.append("action")
            shot_errors.append(f"镜头 {index} 缺少动作描述。")

        if scene and scene not in video_prompt:
            shot_errors.append(f"镜头 {index} 的视频提示词未包含场景。")

        action_terms = [
            value for value in (action, action_start, action_end) if value
        ]
        if action_terms and not any(
            term in video_prompt for term in action_terms
        ):
            shot_errors.append(
                f"镜头 {index} 的视频提示词未包含动作链。"
            )

        if not cinematography and not str(
            _field(shot, "framing", "") or ""
        ).strip():
            missing_fields.append("cinematography")
            shot_errors.append(f"镜头 {index} 缺少摄影参数。")

        if video_prompt and "摄影" not in video_prompt:
            shot_warnings.append(
                f"镜头 {index} 的视频提示词未显式标注摄影信息。"
            )
        if video_prompt and "光线" not in video_prompt:
            shot_warnings.append(
                f"镜头 {index} 的视频提示词未显式标注光线信息。"
            )
        if video_prompt and "一致性" not in video_prompt:
            shot_warnings.append(
                f"镜头 {index} 的视频提示词未显式标注一致性要求。"
            )

        combined = image_prompt + "\n" + video_prompt
        conflicts = find_prompt_conflicts(combined)
        all_conflicts.extend(conflicts)
        for conflict in conflicts:
            message = f"镜头 {index}：{conflict.reason}"
            if conflict.severity == "error":
                shot_errors.append(message)
            else:
                shot_warnings.append(message)

        movement_conflicts = check_camera_movement_conflict(video_prompt)
        for conflict in movement_conflicts:
            shot_warnings.append(f"镜头 {index}：{conflict.reason}")
            all_conflicts.append(conflict)

        if (
            profile.negative_prompt_support == "none"
            and (
                "负向约束" in video_prompt
                or re.search(r"\b(no|avoid)\b", video_prompt, re.IGNORECASE)
            )
        ):
            shot_warnings.append(
                f"目标模型 {profile.display_name} 不支持负向提示词，"
                "建议改用正向描述。"
            )

        if profile.preferred_language == "en" and _has_chinese(combined):
            shot_warnings.append(
                f"目标模型 {profile.display_name} 偏好英文，"
                "当前提示词包含中文；后续需要模型方言转换。"
            )

        shot_duration = float(_field(shot, "end_seconds", 0)) - float(
            _field(shot, "start_seconds", 0)
        )
        if shot_duration > profile.max_single_shot_seconds:
            shot_warnings.append(
                f"镜头时长 {shot_duration:g} 秒超过 "
                f"{profile.display_name} 单镜头建议上限 "
                f"{profile.max_single_shot_seconds:g} 秒。"
            )

        passed = not shot_errors
        per_shot.append(
            {
                "shot_number": index,
                "passed": passed,
                "missing_fields": missing_fields,
                "conflicts": [
                    conflict.model_dump(mode="json")
                    for conflict in conflicts + movement_conflicts
                ],
                "warnings": shot_warnings,
            }
        )
        errors.extend(shot_errors)
        warnings.extend(shot_warnings)

    return PromptCheckResult(
        passed=not errors,
        per_shot=per_shot,
        conflicts=all_conflicts,
        errors=errors,
        warnings=warnings,
    )
