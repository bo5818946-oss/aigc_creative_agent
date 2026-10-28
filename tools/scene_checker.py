"""Deterministic scene-coverage checks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from schemas.storyboard import Shot
from schemas.validation import SceneCheckResult


def _normalize(value: str) -> str:
    return " ".join(str(value).strip().casefold().split())


def _scene_matches(required: str, actual: str) -> bool:
    required_text = _normalize(required)
    actual_text = _normalize(actual)
    if not required_text or not actual_text:
        return False
    return required_text in actual_text or actual_text in required_text


def _shot_scene(shot: Shot | Mapping[str, Any]) -> str:
    if isinstance(shot, Shot):
        return shot.scene
    return str(shot.get("scene", ""))


def check_scene_coverage(
    shots: Sequence[Shot | Mapping[str, Any]],
    required_scenes: Sequence[str],
) -> SceneCheckResult:
    required = []
    seen_required: set[str] = set()
    for scene in required_scenes:
        text = str(scene).strip()
        key = _normalize(text)
        if text and key not in seen_required:
            seen_required.add(key)
            required.append(text)

    errors: list[str] = []
    warnings: list[str] = []
    if not shots:
        errors.append("分镜为空，无法检查场景覆盖。")

    actual_scenes = [_shot_scene(shot) for shot in shots]
    for index, scene in enumerate(actual_scenes, start=1):
        if not scene.strip():
            errors.append(f"镜头 {index} 缺少场景描述。")

    covered: list[str] = []
    missing: list[str] = []
    for scene in required:
        if any(_scene_matches(scene, actual) for actual in actual_scenes):
            covered.append(scene)
        else:
            missing.append(scene)

    for scene in missing:
        errors.append(f"缺少必需场景：{scene}。")

    counts = Counter(
        _normalize(scene) for scene in actual_scenes if scene.strip()
    )
    duplicate_scenes: list[str] = []
    for scene, count in counts.items():
        if count > 1:
            duplicate_scenes.append(scene)
            warnings.append(
                f"场景“{scene}”出现 {count} 次，请确认是否为必要重复。"
            )

    if not required:
        warnings.append("未提供场景要求，无法判断场景覆盖是否完整。")

    coverage_ratio = (
        len(covered) / len(required) if required else 0.0
    )
    return SceneCheckResult(
        passed=not errors,
        required_scenes=required,
        covered_scenes=covered,
        missing_scenes=missing,
        duplicate_scenes=duplicate_scenes,
        coverage_ratio=round(coverage_ratio, 4),
        errors=errors,
        warnings=warnings,
    )
