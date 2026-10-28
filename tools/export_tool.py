"""Export a saved project as Markdown and JSON without overwriting files."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_filename(value: str, *, max_length: int = 60) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z一-鿿_-]+", "_", value)
    cleaned = cleaned.strip("_")
    return (cleaned or "project")[:max_length]


def _unique_stem(directory: Path, base: str) -> str:
    stem = base
    counter = 1
    while any(
        (directory / f"{stem}{suffix}").exists()
        for suffix in (".json", ".md")
    ):
        stem = f"{base}_{counter}"
        counter += 1
    return stem


def _latest_report(project: dict[str, Any]) -> dict[str, Any] | None:
    reports = project.get("validation_reports") or []
    if not reports:
        return None
    report = reports[-1].get("report_json")
    return report if isinstance(report, dict) else None


def _latest_execution(project: dict[str, Any]) -> dict[str, Any] | None:
    executions = project.get("executions") or []
    return executions[-1] if executions else None


def _format_bool(value: Any) -> str:
    return "通过" if value is True else "未通过"


def _format_validation_report(report: dict[str, Any] | None) -> str:
    if not report:
        return "未执行。历史项目可能没有校验报告。\n"

    if report.get("check_type") != "aggregate":
        lines = [
            "### 时长检查（旧版报告）",
            "",
            f"- 目标时长：{report.get('target_duration_seconds', '未知')} 秒",
            f"- 实际终点：{report.get('timeline_end_seconds', '未知')} 秒",
            f"- 结果：{_format_bool(report.get('passed'))}",
        ]
        for error in report.get("errors", []):
            lines.append(f"- 错误：{error}")
        lines.extend(
            [
                "",
                "> 该报告来自旧版数据结构；场景、一致性和提示词检查未执行。",
            ]
        )
        return "\n".join(lines) + "\n"

    lines: list[str] = [
        f"- 综合结果：{_format_bool(report.get('passed'))}",
        "",
    ]
    duration = report.get("duration") or {}
    lines.extend(
        [
            "### 时长检查",
            "",
            f"- 结果：{_format_bool(duration.get('passed'))}",
            f"- 目标：{duration.get('target_duration_seconds', '未知')} 秒",
            f"- 实际终点：{duration.get('timeline_end_seconds', '未知')} 秒",
        ]
    )
    for error in duration.get("errors", []):
        lines.append(f"- 错误：{error}")

    scene = report.get("scene") or {}
    lines.extend(
        [
            "",
            "### 场景覆盖",
            "",
            f"- 结果：{_format_bool(scene.get('passed'))}",
            f"- 覆盖率：{scene.get('coverage_ratio', 0):.0%}",
            f"- 缺失场景：{'、'.join(scene.get('missing_scenes', [])) or '无'}",
        ]
    )
    for warning in scene.get("warnings", []):
        lines.append(f"- 警告：{warning}")

    consistency = report.get("consistency") or {}
    lines.extend(
        [
            "",
            "### 主体一致性",
            "",
            f"- 结果：{_format_bool(consistency.get('passed'))}",
        ]
    )
    for error in consistency.get("errors", []):
        lines.append(f"- 错误：{error}")
    for note in consistency.get("semantic_notes", []):
        lines.append(f"- 说明：{note}")

    prompt = report.get("prompt") or {}
    lines.extend(
        [
            "",
            "### 提示词质量",
            "",
            f"- 结果：{_format_bool(prompt.get('passed'))}",
        ]
    )
    for error in prompt.get("errors", []):
        lines.append(f"- 错误：{error}")
    for warning in prompt.get("warnings", []):
        lines.append(f"- 警告：{warning}")

    if report.get("errors"):
        lines.extend(["", "### 汇总错误", ""])
        for error in report.get("errors", []):
            lines.append(f"- {error}")

    return "\n".join(lines) + "\n"


def render_markdown(project: dict[str, Any]) -> str:
    requirement = project.get("structured_requirement") or {}
    storyboard = project.get("storyboard") or {}
    shots = storyboard.get("shots") or []
    task_plan = project.get("task_plan") or []
    execution = _latest_execution(project) or {}
    report = _latest_report(project)
    revisions = project.get("revision_history") or []

    lines: list[str] = [
        f"# {project.get('project_name') or '未命名项目'}",
        "",
        f"- 项目 ID：`{project.get('project_id', '')}`",
        f"- 状态：{project.get('status', '未知')}",
        f"- 创建时间：{project.get('created_at', '')}",
        f"- 更新时间：{project.get('updated_at', '')}",
        f"- 分镜生成方式：{storyboard.get('generation_method', '未知')}",
        f"- 提示词生成方式：{storyboard.get('prompt_generation_method', '未记录')}",
        "",
        "## 1. 原始需求",
        "",
        "```text",
        project.get("raw_requirement", ""),
        "```",
        "",
        "## 2. 结构化需求",
        "",
        f"- 内容类型：{requirement.get('content_type', '')}",
        f"- 主体：{requirement.get('subject', '')}",
        f"- 目标受众：{requirement.get('target_audience', '')}",
        f"- 目标时长：{requirement.get('duration_seconds', '')} 秒",
        f"- 画幅：{requirement.get('aspect_ratio', '')}",
        f"- 视觉风格：{requirement.get('visual_style', '')}",
        f"- 场景：{'、'.join(requirement.get('scene_requirements', []))}",
        f"- 镜头语言：{requirement.get('camera_language', '')}",
        f"- 转场：{requirement.get('transition_requirements', '')}",
        "",
        "### 一致性约束",
        "",
    ]
    for constraint in requirement.get("consistency_constraints", []):
        lines.append(f"- {constraint}")
    if requirement.get("pending_confirmations"):
        lines.extend(["", "### 待确认项", ""])
        for item in requirement["pending_confirmations"]:
            lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## 3. 任务计划",
            "",
            "| 任务 | 状态 | 开始 | 结束 | 错误 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for task in task_plan:
        lines.append(
            "| {name} | {status} | {started} | {finished} | {error} |".format(
                name=task.get("name", ""),
                status=task.get("status", ""),
                started=task.get("started_at", ""),
                finished=task.get("finished_at", ""),
                error=(task.get("error") or "")
                .replace("|", "\\|")
                .replace("\n", " "),
            )
        )

    lines.extend(["", "## 4. 分镜与提示词", ""])
    director = storyboard.get("director_package") or {}
    if isinstance(director, dict) and director.get("global_prompt"):
        lines.extend(
            [
                "### 整片导演提示词",
                "",
                "~~~text",
                director.get("global_prompt", ""),
                "~~~",
                "",
            ]
        )
        continuity = director.get("continuity_bible") or []
        if continuity:
            lines.extend(["### 连续性圣经", ""])
            for item in continuity:
                lines.append(f"- {item}")
            lines.append("")
        if director.get("negative_prompt"):
            lines.extend(
                [
                    "### 全片负向提示词",
                    "",
                    "~~~text",
                    director.get("negative_prompt", ""),
                    "~~~",
                    "",
                ]
            )

    director_shots = {
        int(item.get("shot_number")): item
        for item in (director.get("shot_prompts") or [])
        if isinstance(item, dict) and item.get("shot_number")
    }
    if not shots:
        lines.append("未生成分镜。")
    for shot in shots:
        shot_number = shot.get("shot_number")
        director_shot = director_shots.get(shot_number) or {}
        image_prompt = (
            director_shot.get("image_prompt")
            or shot.get("image_prompt", "")
        )
        video_prompt = (
            director_shot.get("video_prompt")
            or shot.get("video_prompt", "")
        )
        negative_prompt = (
            director_shot.get("negative_prompt")
            or shot.get("negative_prompt", "")
        )
        lines.extend(
            [
                f"### 镜头 {shot_number or ''} · {shot.get('scene', '')}",
                "",
                f"- 时间：{shot.get('start_seconds', '')}s - {shot.get('end_seconds', '')}s",
                f"- 叙事职责：{shot.get('narrative_purpose', '')}",
                f"- 起始状态：{shot.get('action_start', '')}",
                f"- 结束状态：{shot.get('action_end', '')}",
                f"- 主体状态：{shot.get('subject_state', '')}",
                "",
                "**图片提示词**",
                "",
                "~~~text",
                image_prompt,
                "~~~",
                "",
                "**视频提示词**",
                "",
                "~~~text",
                video_prompt,
                "~~~",
                "",
                "**负向提示词**",
                "",
                "~~~text",
                negative_prompt,
                "~~~",
                "",
            ]
        )

    lines.extend(
        [
            "## 5. 校验报告",
            "",
            _format_validation_report(report),
            "## 6. 修正记录",
            "",
        ]
    )
    if not revisions:
        lines.append("未触发自动修正。")
    else:
        for record in revisions:
            lines.extend(
                [
                    f"### 第 {record.get('revision_number', '')} 次修正",
                    "",
                    f"- 状态：{record.get('status', '')}",
                    f"- 原因：{record.get('reason', '')}",
                    f"- 工具：{record.get('tool', '')}",
                    f"- 时间：{record.get('created_at', '')}",
                    "",
                ]
            )

    lines.extend(
        [
            "## 7. 执行轨迹",
            "",
            "| 节点 | 工具 | 状态 | 摘要 | 错误 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for event in execution.get("traces") or []:
        lines.append(
            "| {node} | {tool} | {status} | {summary} | {error} |".format(
                node=event.get("node_name", ""),
                tool=event.get("tool_name") or "",
                status=event.get("status", ""),
                summary=(event.get("output_summary") or "")
                .replace("|", "\\|")
                .replace("\n", " "),
                error=(event.get("error") or "")
                .replace("|", "\\|")
                .replace("\n", " "),
            )
        )

    return "\n".join(lines).rstrip() + "\n"


def export_project(
    project: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    project_name = str(project.get("project_name") or "project")
    project_id = str(project.get("project_id") or "unknown")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = _safe_filename(
        f"{project_name}_{project_id[:8]}_{timestamp}"
    )
    stem = _unique_stem(directory, base)

    json_path = directory / f"{stem}.json"
    markdown_path = directory / f"{stem}.md"

    payload = dict(project)
    payload["exported_at"] = _now()
    payload["export_schema_version"] = 1
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(
        render_markdown(project),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": markdown_path}
