"""Build a user-facing, copyable prompt package from a storyboard.

When the director prompt writer has run, the package leads with the cohesive
director prompt and continuity bible. When it has not (demo mode or a writer
failure), the package falls back to the deterministic per-shot assembly and
says so explicitly.
"""

from __future__ import annotations

from typing import Any, Mapping

from config.cinematography import MODEL_PROFILES


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _profile_name(target_model: str) -> str:
    profile = MODEL_PROFILES.get(target_model)
    return profile.display_name if profile else target_model


def _director_dict(
    storyboard: Mapping[str, Any],
) -> dict[str, Any] | None:
    value = storyboard.get("director_package")
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        data = dict(value)
        if _text(data.get("global_prompt")):
            return data
    return None


def _shot_number(shot: Mapping[str, Any], fallback: int) -> int:
    try:
        return int(shot.get("shot_number") or fallback)
    except (TypeError, ValueError):
        return fallback


def _header_lines(
    project_name: str,
    requirement: Mapping[str, Any],
    storyboard: Mapping[str, Any],
    target_model: str,
) -> list[str]:
    duration = _number(requirement.get("duration_seconds"), 0.0)
    aspect_ratio = _text(requirement.get("aspect_ratio")) or "未指定"
    visual_style = _text(requirement.get("visual_style")) or "未指定"
    shots = storyboard.get("shots") or []
    return [
        f"- 目标时长：{duration:g} 秒" if duration else "- 目标时长：未指定",
        f"- 画面比例：{aspect_ratio}",
        f"- 视觉风格：{visual_style}",
        f"- 目标视频模型：{_profile_name(target_model)}",
        f"- 镜头数量：{len(shots)}",
    ]


def _director_package(
    project_name: str,
    requirement: Mapping[str, Any],
    storyboard: Mapping[str, Any],
    target_model: str,
    director: Mapping[str, Any],
) -> str:
    shots = storyboard.get("shots") or []
    title = _text(director.get("title")) or project_name
    director_shots = {
        _shot_number(item, index + 1): item
        for index, item in enumerate(director.get("shot_prompts") or [])
    }
    lines: list[str] = [
        f"# {title}",
        "",
        *_header_lines(
            project_name,
            requirement,
            storyboard,
            target_model,
        ),
        "- 提示词层级：导演提示词 + 逐镜头提示词",
        "",
        "## 整片导演提示词",
        "",
        _text(director.get("global_prompt")),
        "",
    ]

    continuity = director.get("continuity_bible") or []
    if continuity:
        lines.extend(["## 连续性圣经", ""])
        for item in continuity:
            lines.append(f"- {_text(item)}")
        lines.append("")

    negative = _text(director.get("negative_prompt"))
    if negative:
        lines.extend(
            [
                "## 全片负向提示词",
                "",
                negative,
                "",
            ]
        )

    lines.extend(["## 逐镜头提示词", ""])
    for index, shot in enumerate(shots, start=1):
        number = _shot_number(shot, index)
        scene = _text(shot.get("scene")) or "未命名场景"
        start = _number(shot.get("start_seconds"), 0.0)
        end = _number(shot.get("end_seconds"), 0.0)
        director_shot = director_shots.get(number) or {}
        image_prompt = (
            _text(director_shot.get("image_prompt"))
            or _text(shot.get("image_prompt"))
        )
        video_prompt = (
            _text(director_shot.get("video_prompt"))
            or _text(shot.get("video_prompt"))
        )
        shot_negative = (
            _text(director_shot.get("negative_prompt"))
            or _text(shot.get("negative_prompt"))
        )
        lines.extend(
            [
                f"### 镜头 {number} · {scene} · {start:g}–{end:g} 秒",
                "",
                "**图片提示词**",
                "",
                image_prompt or "（未生成）",
                "",
                "**视频提示词**",
                "",
                video_prompt or "（未生成）",
                "",
                "**负向提示词**",
                "",
                shot_negative or "（无）",
                "",
                "---",
                "",
            ]
        )

    notes = _text(director.get("model_notes"))
    if notes:
        lines.extend(["## 模型适配提示", "", notes, ""])
    return "\n".join(lines).rstrip() + "\n"


def _fallback_package(
    project_name: str,
    requirement: Mapping[str, Any],
    storyboard: Mapping[str, Any],
    target_model: str,
) -> str:
    shots = storyboard.get("shots") or []
    lines: list[str] = [
        f"# {project_name or '未命名项目'} · AI 视频提示词包",
        "",
        *_header_lines(
            project_name,
            requirement,
            storyboard,
            target_model,
        ),
        "",
        "> 当前项目没有导演级提示词；以下为 Python 规则拼装结果，"
        "仅用于演示模式或模型不可用时的兜底。",
        "",
        "> 图片提示词用于首帧/参考图；视频提示词用于图生视频或文生视频；",
        "> 负向提示词用于支持独立负向字段的模型。",
        "",
    ]

    if not shots:
        lines.extend(
            [
                "> 当前项目没有可用分镜，因此没有提示词包。",
                "> 请查看执行过程或校验报告，确认工作流在哪一步停止。",
                "",
            ]
        )
        return "\n".join(lines)

    for index, shot in enumerate(shots, start=1):
        number = _shot_number(shot, index)
        scene = _text(shot.get("scene")) or "未命名场景"
        start = _number(shot.get("start_seconds"), 0.0)
        end = _number(shot.get("end_seconds"), 0.0)
        lines.extend(
            [
                f"## 镜头 {number} · {scene} · {start:g}–{end:g} 秒",
                "",
                "### 图片提示词",
                "",
                _text(shot.get("image_prompt")) or "（未生成）",
                "",
                "### 视频提示词",
                "",
                _text(shot.get("video_prompt")) or "（未生成）",
                "",
                "### 负向提示词",
                "",
                _text(shot.get("negative_prompt")) or "（无）",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_prompt_package(
    project_name: str,
    requirement: Mapping[str, Any] | None,
    storyboard: Mapping[str, Any] | None,
    target_model: str = "generic",
) -> str:
    """Return the best available prompt package for the project."""

    requirement = requirement or {}
    storyboard = storyboard or {}
    director = _director_dict(storyboard)
    if director:
        return _director_package(
            project_name,
            requirement,
            storyboard,
            target_model,
            director,
        )
    return _fallback_package(
        project_name,
        requirement,
        storyboard,
        target_model,
    )


def _media_package(
    project_name: str,
    requirement: Mapping[str, Any],
    storyboard: Mapping[str, Any],
    target_model: str,
    *,
    kind: str,
) -> str:
    """One copy-ready block for a single medium: still image or motion."""

    shots = storyboard.get("shots") or []
    director = _director_dict(storyboard) or {}
    director_shots = {
        _shot_number(item, index + 1): item
        for index, item in enumerate(director.get("shot_prompts") or [])
    }
    is_image = kind == "image"
    heading = "图片生成提示词包" if is_image else "视频生成提示词包"
    field = "image_prompt" if is_image else "video_prompt"
    explain = (
        "静止画面：每条提示词描述一个被冻结的瞬间，不含时间推进或镜头运动。"
        if is_image
        else "运动画面：每条提示词描述时长内的变化、摄影机运动与起止状态。"
    )

    lines: list[str] = [
        f"# {project_name or '未命名项目'} · {heading}",
        "",
        *_header_lines(project_name, requirement, storyboard, target_model),
        f"- {explain}",
        "",
    ]
    dialect_label = _text(director.get("dialect_label"))
    if dialect_label:
        lines.extend([f"- 体裁：{dialect_label}", ""])

    for index, shot in enumerate(shots, start=1):
        number = _shot_number(shot, index)
        scene = _text(shot.get("scene")) or "未命名场景"
        start = _number(shot.get("start_seconds"), 0.0)
        end = _number(shot.get("end_seconds"), 0.0)
        director_shot = director_shots.get(number) or {}
        prompt = _text(director_shot.get(field)) or _text(shot.get(field))
        negative = (
            _text(director_shot.get("negative_prompt"))
            or _text(shot.get("negative_prompt"))
            or _text(director.get("negative_prompt"))
        )
        lines.extend(
            [
                f"## 镜头 {number} · {scene} · {start:g}–{end:g} 秒",
                "",
                prompt or "（未生成）",
                "",
            ]
        )
        if negative:
            lines.extend([f"负向：{negative}", ""])

    return "\n".join(lines).rstrip() + "\n"


def build_image_prompt_package(
    project_name: str,
    requirement: Mapping[str, Any] | None,
    storyboard: Mapping[str, Any] | None,
    target_model: str = "generic",
) -> str:
    """Return the still-image prompts as one copy-ready block."""

    return _media_package(
        project_name,
        requirement or {},
        storyboard or {},
        target_model,
        kind="image",
    )


def build_video_prompt_package(
    project_name: str,
    requirement: Mapping[str, Any] | None,
    storyboard: Mapping[str, Any] | None,
    target_model: str = "generic",
) -> str:
    """Return the motion prompts as one copy-ready block."""

    return _media_package(
        project_name,
        requirement or {},
        storyboard or {},
        target_model,
        kind="video",
    )


def prompt_package_filename(project_name: str) -> str:
    """Return a safe, human-readable filename for the prompt package."""

    cleaned = "".join(
        character
        for character in (project_name or "aigc")
        if character not in '\\/:*?"<>|'
    ).strip()
    return f"{cleaned or 'aigc'}_提示词包.txt"


def media_package_filename(project_name: str, kind: str) -> str:
    label = "图片生成" if kind == "image" else "视频生成"
    cleaned = "".join(
        character
        for character in (project_name or "aigc")
        if character not in '\\/:*?"<>|'
    ).strip()
    return f"{cleaned or 'aigc'}_{label}提示词.txt"
