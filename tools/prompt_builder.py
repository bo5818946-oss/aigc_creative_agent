"""Deterministic image/video prompt assembly from structured shot fields.

The LLM supplies structured creative decisions. This module turns those
decisions into consistent prompts with Python, so prompt wording is traceable
and does not depend on a second free-form model call.
"""

from __future__ import annotations

from config.cinematography import (
    CAMERA_ANGLE_LABELS,
    CAMERA_MOVEMENT_LABELS,
    COLOR_GRADE_LABELS,
    LIGHTING_LABELS,
    MODEL_PROFILES,
    SHOT_SIZE_LABELS,
    TRANSITION_LABELS,
    VFX_LABELS,
)
from schemas.cinematography import ScreenDirection
from schemas.project import CreativeRequirement
from schemas.storyboard import Shot, Storyboard

COMPOSITION_LABELS: dict[str, str] = {
    "rule_of_thirds": "三分法构图",
    "rule_of_thirds_composition": "三分法构图",
    "centered_composition": "中心构图",
    "center_composition": "中心构图",
    "center_framing": "中心构图",
    "center_framed": "中心构图",
    "centered_framing": "中心构图",
    "center": "中心构图",
    "centered": "中心构图",
    "symmetrical_composition": "对称构图",
    "symmetry": "对称构图",
    "leading_lines": "引导线构图",
    "negative_space": "留白构图",
    "foreground_framing": "前景框架构图",
}

SCREEN_DIRECTION_LABELS: dict[ScreenDirection, str] = {
    ScreenDirection.LEFT_TO_RIGHT: "主体从左向右运动",
    ScreenDirection.RIGHT_TO_LEFT: "主体从右向左运动",
    ScreenDirection.TOWARD_CAMERA: "主体朝向镜头运动",
    ScreenDirection.AWAY_FROM_CAMERA: "主体背离镜头运动",
    ScreenDirection.STATIC: "主体位置保持稳定",
}

DEFAULT_NEGATIVE_PROMPT = (
    "无字幕，无水印，无 Logo，主体不重复，不形变，无闪烁"
)


def _join(parts: list[str]) -> str:
    return "；".join(part for part in parts if part)


def _cinematography_text(shot: Shot) -> str:
    cin = shot.cinematography
    if cin is None:
        return _join(
            [
                shot.framing,
                shot.camera_position,
                shot.camera_movement,
                shot.lighting_color,
            ]
        )

    parts = [
        SHOT_SIZE_LABELS.get(cin.shot_size, cin.shot_size.value),
        CAMERA_ANGLE_LABELS.get(cin.camera_angle, cin.camera_angle.value),
        CAMERA_MOVEMENT_LABELS.get(
            cin.camera_movement,
            cin.camera_movement.value,
        ),
        f"{cin.lens} 镜头",
        COMPOSITION_LABELS.get(cin.composition, cin.composition),
    ]
    return "，".join(part for part in parts if part)


def _lighting_text(shot: Shot, requirement: CreativeRequirement) -> str:
    cin = shot.cinematography
    if cin is None:
        return shot.lighting_color or requirement.visual_style
    return "，".join(
        [
            LIGHTING_LABELS.get(
                cin.lighting_style,
                cin.lighting_style.value,
            ),
            COLOR_GRADE_LABELS.get(
                cin.color_grade,
                cin.color_grade.value,
            ),
        ]
    )


def _transition_text(shot: Shot) -> str:
    cin = shot.cinematography
    if cin is None:
        return shot.transition
    return TRANSITION_LABELS.get(cin.transition, cin.transition.value)


def build_image_prompt(
    shot: Shot,
    requirement: CreativeRequirement,
) -> str:
    subject = shot.subject_state or requirement.subject
    locks = "；".join(
        shot.continuity_locks or requirement.consistency_constraints
    )
    action_parts = []
    if shot.action_start:
        action_parts.append(f"起始状态：{shot.action_start}")
    if shot.action_end:
        action_parts.append(f"结束状态：{shot.action_end}")
    if not action_parts and shot.action:
        action_parts.append(shot.action)
    negative = shot.negative_prompt or DEFAULT_NEGATIVE_PROMPT

    return (
        f"{subject}。场景：{shot.scene}。"
        f"{'；'.join(action_parts)}。"
        f"摄影：{_cinematography_text(shot)}。"
        f"光线与色彩：{_lighting_text(shot, requirement)}。"
        f"风格：{requirement.visual_style}。"
        f"一致性要求：{locks}。"
        f"避免：{negative}。"
    )


def build_video_prompt(
    shot: Shot,
    requirement: CreativeRequirement,
    model_profile_key: str = "generic",
) -> str:
    profile = MODEL_PROFILES.get(
        model_profile_key,
        MODEL_PROFILES["generic"],
    )
    subject = shot.subject_state or requirement.subject
    locks = "；".join(
        shot.continuity_locks or requirement.consistency_constraints
    )
    if shot.action:
        action_text = f"动作链：{shot.action}"
    else:
        action_parts = []
        if shot.action_start:
            action_parts.append(f"起点：{shot.action_start}")
        if shot.action_end:
            action_parts.append(f"终点：{shot.action_end}")
        action_text = "；".join(action_parts) or "主体保持稳定"

    sound_text = f"声音：{shot.sound}。" if shot.sound else ""
    transition_text = f"转场：{_transition_text(shot)}。"
    screen_direction = ""
    if shot.cinematography and shot.cinematography.screen_direction:
        screen_direction = (
            "屏幕方向："
            + SCREEN_DIRECTION_LABELS.get(
                shot.cinematography.screen_direction,
                shot.cinematography.screen_direction.value,
            )
            + "。"
        )

    vfx_text = ""
    if shot.cinematography and shot.cinematography.vfx:
        labels = [
            VFX_LABELS.get(vfx, vfx.value)
            for vfx in shot.cinematography.vfx
        ]
        vfx_text = "特效：" + "、".join(labels) + "。"

    negative = shot.negative_prompt or DEFAULT_NEGATIVE_PROMPT
    if profile.negative_prompt_support == "none":
        negative_text = "画面保持干净、稳定、主体清晰。"
    else:
        negative_text = f"负向约束：{negative}。"

    return (
        f"{subject}。"
        f"场景：{shot.scene}。"
        f"{action_text}。"
        f"摄影：{_cinematography_text(shot)}。"
        f"光线与色彩：{_lighting_text(shot, requirement)}。"
        f"风格：{requirement.visual_style}。"
        f"画幅：{requirement.aspect_ratio}；"
        f"镜头时长：{shot.duration_seconds:g} 秒。"
        f"{sound_text}{transition_text}{screen_direction}{vfx_text}"
        f"一致性要求：{locks}。"
        f"{negative_text}"
    )


def build_prompts_for_storyboard(
    storyboard: Storyboard,
    requirement: CreativeRequirement,
    model_profile_key: str = "generic",
) -> Storyboard:
    if not storyboard.shots:
        raise ValueError("分镜为空，无法生成提示词。")

    updated_shots: list[Shot] = []
    for shot in storyboard.shots:
        negative = shot.negative_prompt or DEFAULT_NEGATIVE_PROMPT
        updated_shots.append(
            shot.model_copy(
                update={
                    "image_prompt": build_image_prompt(shot, requirement),
                    "video_prompt": build_video_prompt(
                        shot,
                        requirement,
                        model_profile_key,
                    ),
                    "negative_prompt": negative,
                }
            )
        )

    return Storyboard(
        generation_method=storyboard.generation_method,
        prompt_generation_method="deterministic_builder",
        shots=updated_shots,
    )
