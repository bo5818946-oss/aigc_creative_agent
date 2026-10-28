"""Storyboard revision tools for the validation/revision loop."""

from __future__ import annotations

import json
from typing import Any

from config.cinematography import MODEL_PROFILES
from schemas.project import CreativeRequirement
from schemas.storyboard import Shot, Storyboard, StoryboardDraft
from schemas.validation import AggregateValidationReport
from services.llm_service import LLMService
from tools.storyboard_tool import allowed_enum_text, draft_to_storyboard


class RevisionError(RuntimeError):
    """Raised when a revision cannot be performed safely."""


def report_errors(report: AggregateValidationReport) -> list[str]:
    return list(report.errors)


def has_only_duration_errors(report: AggregateValidationReport) -> bool:
    return (
        not report.duration.passed
        and report.scene.passed
        and report.consistency.passed
        and report.prompt.passed
    )


def summarize_storyboard(storyboard: Storyboard) -> dict[str, Any]:
    return {
        "shot_count": len(storyboard.shots),
        "timeline_end_seconds": (
            storyboard.shots[-1].end_seconds if storyboard.shots else 0.0
        ),
        "scenes": [shot.scene for shot in storyboard.shots],
    }


def _direction_audit(storyboard: Storyboard) -> str:
    lines: list[str] = []
    for shot in storyboard.shots:
        screen_direction = (
            shot.cinematography.screen_direction.value
            if shot.cinematography
            and shot.cinematography.screen_direction
            else "None"
        )
        lines.append(
            f"镜头 {shot.shot_number}: "
            f"screen_direction={screen_direction}; "
            f"subject={shot.subject_state[:80]}; "
            f"start={shot.action_start[:80]}; "
            f"end={shot.action_end[:80]}"
        )
    return "\n".join(lines)


def revise_storyboard_deterministically(
    requirement: CreativeRequirement,
    storyboard: Storyboard,
    report: AggregateValidationReport,
) -> Storyboard:
    """Repair timing without a model when timing is the only failure."""

    if not storyboard.shots:
        raise RevisionError("分镜为空，无法修正。")
    if not has_only_duration_errors(report):
        raise RevisionError(
            "确定性修正只能处理时长问题；场景、主体一致性或提示词问题"
            "需要模型修正。"
        )

    durations: list[float] = []
    for shot in storyboard.shots:
        duration = shot.end_seconds - shot.start_seconds
        durations.append(duration if duration > 0 else 0.1)

    total = sum(durations)
    target = requirement.duration_seconds
    scaled = [duration * target / total for duration in durations]
    if any(value <= 0 for value in scaled):
        raise RevisionError("镜头时长缩放失败，存在非正时长。")

    updated: list[Shot] = []
    cursor = 0.0
    for index, (shot, duration) in enumerate(
        zip(storyboard.shots, scaled)
    ):
        start = round(cursor, 3)
        if index == len(storyboard.shots) - 1:
            end = round(target, 3)
        else:
            end = round(cursor + duration, 3)
        cursor = end
        updated.append(
            shot.model_copy(
                update={
                    "start_seconds": start,
                    "end_seconds": end,
                }
            )
        )

    return Storyboard(
        generation_method=storyboard.generation_method,
        prompt_generation_method="",
        shots=updated,
    )


def revise_storyboard_with_llm(
    llm_service: LLMService,
    requirement: CreativeRequirement,
    storyboard: Storyboard,
    report: AggregateValidationReport,
    model_profile_key: str = "generic",
) -> Storyboard:
    profile = MODEL_PROFILES.get(
        model_profile_key,
        MODEL_PROFILES["generic"],
    )
    errors = report_errors(report)
    if not errors:
        raise RevisionError("校验报告没有错误，不需要修正。")

    requirement_json = json.dumps(
        requirement.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
    storyboard_json = json.dumps(
        storyboard.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
    errors_text = "\n".join(f"- {error}" for error in errors[:20])
    user_prompt = (
        "下面是一份未通过校验的分镜。请只修正列出的问题，"
        "保持其他内容稳定。\n\n"
        f"创作需求：\n{requirement_json}\n\n"
        f"当前分镜：\n{storyboard_json}\n\n"
        f"方向审计：\n{_direction_audit(storyboard)}\n\n"
        f"校验错误：\n{errors_text}\n\n"
        f"目标视频模型：{profile.display_name}\n"
        f"模型提示：{profile.notes}\n"
        f"单镜头建议上限：{profile.max_single_shot_seconds:g} 秒\n\n"
        f"可用枚举值：\n{allowed_enum_text()}\n\n"
        "修正要求：\n"
        "1. 总时间线必须等于目标时长，无重叠、无空档。\n"
        "2. 必须覆盖用户要求的每个场景。\n"
        "3. 保持同一主体、同一车型/颜色/设计特征和一致的车辆前进方向。\n"
        "4. 如果错误包含“方向相反/方向不一致”：\n"
        "   - 以多数镜头的 screen_direction 为基准，把少数反向镜头改为相同值；\n"
        "   - 同时把该镜头 subject_state/action_start/action_end 中的"
        "“左/右”描述改为与基准一致；\n"
        "   - 不要只改 screen_direction 而保留相反的文字描述。\n"
        "5. 只输出与输入相同结构的 JSON 对象，不要输出 Markdown 或解释。\n"
        "6. 不要输出 image_prompt 或 video_prompt；Python 会重新生成提示词。\n"
    )

    draft = llm_service.chat_json(
        system_prompt=(
            "你是一名严谨的电影分镜修订师。你只修正用户指出的问题，"
            "不改变没有被指出问题的创作决定。只输出 JSON。"
        ),
        user_prompt=user_prompt,
        response_model=StoryboardDraft,
        temperature=0.2,
    )
    return draft_to_storyboard(
        draft,
        requirement,
        generation_method="llm_revision",
    )
