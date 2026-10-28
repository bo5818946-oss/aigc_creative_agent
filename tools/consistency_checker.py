"""Deterministic subject-consistency and screen-direction checks.

These checks operate on declared text and structured fields. They cannot prove
that a generated video will look consistent; they only prove that the plan
contains the required locks and does not contain obvious contradictions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from schemas.project import CreativeRequirement
from schemas.storyboard import Shot
from schemas.validation import ConsistencyCheckResult

_DIRECTION_WORDS = (
    "车头",
    "车尾",
    "朝左",
    "朝右",
    "向左",
    "向右",
    "前进",
    "向前",
    "向后",
    "后退",
    "方向",
)

_SCREEN_DIRECTION_MAP = {
    "left_to_right": "right",
    "right_to_left": "left",
    "toward_camera": "forward",
    "away_from_camera": "backward",
}


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


def _shot_text(shot: Shot | Mapping[str, Any]) -> str:
    parts = [
        str(_field(shot, "subject_state", "")),
        str(_field(shot, "action", "")),
        str(_field(shot, "action_start", "")),
        str(_field(shot, "action_end", "")),
        str(_field(shot, "camera_movement", "")),
        str(_field(shot, "framing", "")),
    ]
    for name in ("continuity_locks", "constraints"):
        value = _field(shot, name, [])
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(part for part in parts if part)


def _direction_terms(text: str) -> set[str]:
    text = text.casefold()
    # "画面左侧/右侧" describes screen position, not travel direction.
    text = (
        text.replace("画面左侧", "")
        .replace("画面右侧", "")
        .replace("画面左", "")
        .replace("画面右", "")
        .replace("从左向右", "向右")
        .replace("从右向左", "向左")
        .replace("从左到右", "向右")
        .replace("从右到左", "向左")
        .replace("由左至右", "向右")
        .replace("由右至左", "向左")
        .replace("left to right", "right")
        .replace("right to left", "left")
    )
    terms: set[str] = set()
    if "左" in text or "left" in text:
        terms.add("left")
    if "右" in text or "right" in text:
        terms.add("right")
    if "前进" in text or "向前" in text or "forward" in text:
        terms.add("forward")
    if "后退" in text or "向后" in text or "backward" in text:
        terms.add("backward")
    return terms


def _screen_direction(shot: Shot | Mapping[str, Any]) -> str | None:
    value = _cinematography(shot).get("screen_direction")
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    return _SCREEN_DIRECTION_MAP.get(str(value))


def _locks(shot: Shot | Mapping[str, Any]) -> list[str]:
    value = _field(shot, "continuity_locks", [])
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _is_vehicle(requirement: CreativeRequirement) -> bool:
    text = " ".join(
        [
            requirement.content_type,
            requirement.subject,
            *requirement.consistency_constraints,
        ]
    ).casefold()
    return any(
        keyword in text
        for keyword in (
            "汽车",
            "轿车",
            "suv",
            "跑车",
            "卡车",
            "车辆",
            "车头",
            "车尾",
        )
    )


def _requires_direction(requirement: CreativeRequirement) -> bool:
    return any(
        any(word in constraint for word in ("方向", "车头", "车尾", "前进"))
        for constraint in requirement.consistency_constraints
    )


def _requires_exact_subject(requirement: CreativeRequirement) -> bool:
    return any(
        any(
            word in constraint
            for word in ("车型", "同一辆", "主体", "外观", "设计特征")
        )
        for constraint in requirement.consistency_constraints
    )


def check_consistency(
    shots: Sequence[Shot | Mapping[str, Any]],
    requirement: CreativeRequirement,
) -> ConsistencyCheckResult:
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []
    semantic_notes: list[str] = [
        "确定性文本检查不能保证最终视频中的主体外观完全一致；"
        "仍需在生成后做人工或模型语义复核。"
    ]

    if not shots:
        errors.append("分镜为空，无法进行一致性检查。")
        return ConsistencyCheckResult(
            passed=False,
            checks=[],
            errors=errors,
            warnings=warnings,
            semantic_notes=semantic_notes,
        )

    vehicle = _is_vehicle(requirement)
    direction_required = _requires_direction(requirement)
    exact_subject_required = _requires_exact_subject(requirement)
    subject_text = requirement.subject.casefold()
    all_text_directions: set[str] = set()
    all_screen_directions: set[str] = set()
    screen_by_shot: dict[int, str] = {}
    text_dirs_by_shot: dict[int, set[str]] = {}

    for index, shot in enumerate(shots, start=1):
        locks = _locks(shot)
        subject_state = str(_field(shot, "subject_state", ""))
        combined = (subject_state + " " + " ".join(locks)).casefold()

        has_lock = bool(locks) or bool(subject_state.strip())
        checks.append(
            {
                "name": "continuity_lock",
                "shot_number": index,
                "passed": has_lock,
                "detail": "存在主体状态或连续性锁" if has_lock else "缺少",
            }
        )
        if not has_lock:
            if exact_subject_required:
                errors.append(
                    f"镜头 {index} 缺少主体状态或连续性锁，"
                    "无法保证主体一致。"
                )
            else:
                warnings.append(
                    f"镜头 {index} 未声明主体状态或连续性锁。"
                )

        if subject_text and subject_text not in combined:
            message = (
                f"镜头 {index} 未原样包含主体描述“{requirement.subject}”，"
                "请确认是否仍是同一主体。"
            )
            if exact_subject_required:
                errors.append(message)
            else:
                warnings.append(message)

        text_directions = _direction_terms(_shot_text(shot))
        screen_direction = _screen_direction(shot)
        all_text_directions.update(text_directions)
        if screen_direction:
            all_screen_directions.add(screen_direction)
            if screen_direction in {"left", "right"}:
                screen_by_shot[index] = screen_direction
        horizontal_text = text_directions & {"left", "right"}
        if horizontal_text:
            text_dirs_by_shot[index] = horizontal_text

        if vehicle:
            has_direction_info = bool(screen_direction) or any(
                word in _shot_text(shot) for word in _DIRECTION_WORDS
            )
            checks.append(
                {
                    "name": "vehicle_direction",
                    "shot_number": index,
                    "passed": has_direction_info,
                    "detail": (
                        "已声明车辆方向"
                        if has_direction_info
                        else "未声明车头/前进方向"
                    ),
                }
            )
            if not has_direction_info:
                message = (
                    f"镜头 {index} 未声明车头方向或车辆前进方向。"
                )
                if direction_required:
                    errors.append(message)
                else:
                    warnings.append(message)

            if screen_direction and text_directions:
                horizontal_text = text_directions & {"left", "right"}
                if horizontal_text and screen_direction in {"left", "right"}:
                    if screen_direction not in horizontal_text:
                        errors.append(
                            f"镜头 {index} 文本中的车辆方向与"
                            "screen_direction 矛盾。"
                        )

    if direction_required:
        horizontal = all_text_directions & {"left", "right"}
        if {"left", "right"}.issubset(horizontal):
            groups: dict[str, list[int]] = {}
            for shot_number, directions in text_dirs_by_shot.items():
                for direction in directions:
                    groups.setdefault(direction, []).append(shot_number)
            detail = "；".join(
                f"{direction}: 镜头 {sorted(set(numbers))}"
                for direction, numbers in groups.items()
            )
            errors.append(
                f"文本中的车辆水平运动方向出现相反（{detail}），"
                "与“前进方向一致”的约束冲突。"
            )
        horizontal_screen = all_screen_directions & {"left", "right"}
        if {"left", "right"}.issubset(horizontal_screen):
            groups = {}
            for shot_number, direction in screen_by_shot.items():
                groups.setdefault(direction, []).append(shot_number)
            detail = "；".join(
                f"{direction}: 镜头 {sorted(set(numbers))}"
                for direction, numbers in groups.items()
            )
            errors.append(
                f"screen_direction 出现相反（{detail}），"
                "与“前进方向一致”的约束冲突。"
            )

    if vehicle:
        semantic_notes.append(
            "车型、车漆、灯组、轮毂等细粒度一致性属于语义问题；"
            "当前工具只能核对声明是否存在。"
        )

    return ConsistencyCheckResult(
        passed=not errors,
        checks=checks,
        errors=errors,
        warnings=warnings,
        semantic_notes=semantic_notes,
    )
