"""LangGraph node implementations.

Phase 1 uses a deterministic storyboard placeholder so the real workflow and
the real duration tool can be exercised without a model or API key. The
placeholder is explicitly labelled in the storyboard and in the trace.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from agent.state import AgentState
from config.settings import DURATION_TOLERANCE_SECONDS
from schemas.project import CreativeRequirement, TaskItem, TaskStatus
from schemas.storyboard import Storyboard
from schemas.validation import AggregateValidationReport
from schemas.cinematography import take_normalisations
from services.llm_service import (
    LLMCallError,
    LLMConfigurationError,
    LLMResponseError,
    LLMService,
)
from tools.prompt_builder import build_prompts_for_storyboard
from tools.prompt_writer import (
    PromptWriterError,
    write_director_package,
)
from tools.revision_tool import (
    RevisionError,
    revise_storyboard_deterministically,
    revise_storyboard_with_llm,
    summarize_storyboard,
)
from tools.storyboard_tool import (
    generate_deterministic_storyboard,
    generate_storyboard_with_llm,
)
from tools.validation_pipeline import run_validation


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _errors(state: AgentState) -> list[str]:
    return list(state.get("errors") or [])


def _event(
    node_name: str,
    *,
    status: str,
    input_summary: str = "",
    output_summary: str = "",
    error: str | None = None,
    tool_name: str | None = None,
    tool_arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "node_name": node_name,
        "tool_name": tool_name,
        "tool_arguments": tool_arguments,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "status": status,
        "error": error,
        "created_at": _now(),
    }


def _set_task(
    task_plan: list[dict[str, Any]],
    task_id: str,
    status: TaskStatus,
    *,
    started_at: str | None = None,
    finished_at: str | None = None,
    output_data: dict[str, Any] | None = None,
    error: str | None = None,
) -> list[dict[str, Any]]:
    updated = [dict(task) for task in task_plan]
    for task in updated:
        if task.get("task_id") != task_id:
            continue
        task["status"] = status.value
        if started_at is not None:
            task["started_at"] = started_at
        if finished_at is not None:
            task["finished_at"] = finished_at
        if output_data is not None:
            task["output_data"] = output_data
        if error is not None:
            task["error"] = error
    return updated


def _task(
    task_id: str,
    name: str,
    status: TaskStatus,
    *,
    input_data: dict[str, Any] | None = None,
    output_data: dict[str, Any] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    return TaskItem(
        task_id=task_id,
        name=name,
        status=status,
        input_data=input_data or {},
        output_data=output_data or {},
        started_at=started_at,
        finished_at=finished_at,
    ).model_dump(mode="json")


def _format_validation_error(exc: ValidationError) -> str:
    messages: list[str] = []
    for item in exc.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item.get("loc", ()))
        prefix = f"{location}: " if location else ""
        messages.append(f"{prefix}{item.get('msg', '字段校验失败')}")
    return "; ".join(messages)


def _analyze_requirements_deterministic(
    state: AgentState,
) -> dict[str, Any]:
    raw_requirement = state.get("raw_requirement", "")
    try:
        requirement = CreativeRequirement.model_validate(
            state.get("requirement_input") or {}
        )
    except ValidationError as exc:
        message = f"需求数据校验失败：{_format_validation_error(exc)}"
        event = _event(
            "analyze_requirements",
            status="error",
            input_summary=raw_requirement[:200],
            error=message,
        )
        return {
            "errors": _errors(state) + [message],
            "final_status": "failed",
            "trace_events": [event],
        }

    requirement_json = requirement.model_dump(mode="json")
    event = _event(
        "analyze_requirements",
        status="success",
        input_summary=raw_requirement[:200],
        output_summary=(
            f"已生成结构化需求：{requirement.content_type}，"
            f"目标 {requirement.duration_seconds:g} 秒，"
            f"{len(requirement.scene_requirements)} 个场景，"
            f"{len(requirement.pending_confirmations)} 项待确认。"
        ),
    )
    return {
        "structured_requirement": requirement_json,
        "errors": _errors(state),
        "revision_count": 0,
        "trace_events": [event],
    }


def _llm_tool_arguments(
    llm_service: LLMService,
    raw_requirement: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    return {
        "model": llm_service.model,
        "raw_requirement_length": len(raw_requirement),
        "fallback_fields": sorted(fallback.keys()),
        "usage": llm_service.usage.as_dict(),
    }


def _llm_error_result(
    state: AgentState,
    llm_service: LLMService,
    raw_requirement: str,
    fallback: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    event = _event(
        "analyze_requirements",
        status="error",
        input_summary=raw_requirement[:200],
        error=message,
        tool_name="services.llm_service.LLMService.parse_requirement",
        tool_arguments=_llm_tool_arguments(
            llm_service,
            raw_requirement,
            fallback,
        ),
    )
    return {
        "errors": _errors(state) + [message],
        "final_status": "failed",
        "llm_usage": llm_service.usage.as_dict(),
        "trace_events": [event],
    }


def _analyze_requirements_with_llm(
    state: AgentState,
    llm_service: LLMService,
) -> dict[str, Any]:
    raw_requirement = state.get("raw_requirement", "")
    fallback = state.get("requirement_input") or {}

    try:
        requirement = llm_service.parse_requirement(
            raw_requirement,
            fallback=fallback,
        )
    except ValidationError as exc:
        return _llm_error_result(
            state,
            llm_service,
            raw_requirement,
            fallback,
            "需求解析失败：模型返回的数据未通过最终校验："
            + _format_validation_error(exc),
        )
    except (
        LLMConfigurationError,
        LLMCallError,
        LLMResponseError,
        ValueError,
    ) as exc:
        return _llm_error_result(
            state,
            llm_service,
            raw_requirement,
            fallback,
            f"需求解析失败：{exc}",
        )

    requirement_json = requirement.model_dump(mode="json")
    event = _event(
        "analyze_requirements",
        status="success",
        input_summary=raw_requirement[:200],
        output_summary=(
            f"模型已解析需求：{requirement.content_type}，"
            f"目标 {requirement.duration_seconds:g} 秒，"
            f"{len(requirement.scene_requirements)} 个场景，"
            f"{len(requirement.pending_confirmations)} 项待确认。"
        ),
        tool_name="services.llm_service.LLMService.parse_requirement",
        tool_arguments=_llm_tool_arguments(
            llm_service,
            raw_requirement,
            fallback,
        ),
    )
    return {
        "structured_requirement": requirement_json,
        "errors": _errors(state),
        "revision_count": 0,
        "llm_usage": llm_service.usage.as_dict(),
        "trace_events": [event],
    }


def make_analyze_requirements_node(
    llm_service: LLMService | None,
) -> Callable[[AgentState], dict[str, Any]]:
    """Bind the analysis node to an optional LLM service."""

    def node(state: AgentState) -> dict[str, Any]:
        if llm_service is None:
            return _analyze_requirements_deterministic(state)
        return _analyze_requirements_with_llm(state, llm_service)

    return node


def analyze_requirements(state: AgentState) -> dict[str, Any]:
    """Deterministic entry point kept for direct callers."""

    return _analyze_requirements_deterministic(state)


def plan_workflow(state: AgentState) -> dict[str, Any]:
    started_at = _now()
    try:
        requirement = CreativeRequirement.model_validate(
            state.get("structured_requirement") or {}
        )
    except ValidationError as exc:
        message = f"任务规划失败：{_format_validation_error(exc)}"
        event = _event("plan_workflow", status="error", error=message)
        return {
            "errors": _errors(state) + [message],
            "trace_events": [event],
        }

    analysis_event = next(
        (
            event
            for event in state.get("trace_events", [])
            if event.get("node_name") == "analyze_requirements"
        ),
        None,
    )
    analysis_at = (
        analysis_event.get("created_at") if analysis_event is not None else started_at
    )
    finished_at = _now()
    tolerance = float(
        state.get("duration_tolerance_seconds", DURATION_TOLERANCE_SECONDS)
    )

    task_plan = [
        _task(
            "analyze_requirements",
            "需求解析与校验",
            TaskStatus.COMPLETED,
            input_data={"raw_requirement": state.get("raw_requirement", "")[:200]},
            output_data={
                "summary": (
                    f"目标 {requirement.duration_seconds:g} 秒，"
                    f"场景：{'、'.join(requirement.scene_requirements)}"
                )
            },
            started_at=analysis_at,
            finished_at=analysis_at,
        ),
        _task(
            "plan_workflow",
            "任务规划",
            TaskStatus.COMPLETED,
            input_data={
                "duration_seconds": requirement.duration_seconds,
                "scene_count": len(requirement.scene_requirements),
            },
            output_data={"summary": "生成 7 个阶段任务"},
            started_at=started_at,
            finished_at=finished_at,
        ),
        _task(
            "generate_storyboard",
            "分镜生成",
            TaskStatus.PENDING,
            input_data={
                "scenes": requirement.scene_requirements,
                "duration_seconds": requirement.duration_seconds,
                "target_video_model": state.get(
                    "target_video_model",
                    "generic",
                ),
            },
        ),
        _task(
            "generate_prompts",
            "图片与视频提示词生成",
            TaskStatus.PENDING,
            input_data={
                "target_video_model": state.get(
                    "target_video_model",
                    "generic",
                ),
            },
        ),
        _task(
            "validate_output",
            "综合校验（时长/场景/一致性/提示词）",
            TaskStatus.PENDING,
            input_data={
                "target_duration_seconds": requirement.duration_seconds,
                "tolerance_seconds": tolerance,
                "scene_requirements": requirement.scene_requirements,
                "target_video_model": state.get(
                    "target_video_model",
                    "generic",
                ),
            },
        ),
        _task(
            "write_director_prompt",
            "导演提示词生成",
            TaskStatus.PENDING,
            input_data={
                "target_video_model": state.get(
                    "target_video_model",
                    "generic",
                ),
            },
        ),
        _task(
            "revise_output",
            "自动修正（最多 2 次）",
            TaskStatus.PENDING,
            input_data={
                "max_revisions": int(state.get("max_revisions", 2)),
            },
        ),
        _task(
            "finalize_result",
            "结果归档",
            TaskStatus.PENDING,
        ),
    ]

    event = _event(
        "plan_workflow",
        status="success",
        input_summary=(
            f"{requirement.content_type} / {requirement.duration_seconds:g} 秒 / "
            f"{len(requirement.scene_requirements)} 个场景"
        ),
        output_summary=f"已生成 {len(task_plan)} 个结构化任务。",
    )
    return {"task_plan": task_plan, "trace_events": [event]}


def _generate_storyboard(
    state: AgentState,
    llm_service: LLMService | None,
) -> dict[str, Any]:
    started_at = _now()
    task_plan = state.get("task_plan", [])
    target_model = state.get("target_video_model", "generic")
    try:
        requirement = CreativeRequirement.model_validate(
            state.get("structured_requirement") or {}
        )
        if llm_service is None:
            storyboard = generate_deterministic_storyboard(requirement)
            tool_name = (
                "tools.storyboard_tool.generate_deterministic_storyboard"
            )
            tool_arguments = {
                "scene_count": len(requirement.scene_requirements),
                "duration_seconds": requirement.duration_seconds,
                "target_video_model": target_model,
            }
            output_summary = (
                f"已生成 {len(storyboard.shots)} 个确定性占位镜头；"
                "未调用模型。"
            )
            usage = None
            model_generated = False
        else:
            storyboard = generate_storyboard_with_llm(
                llm_service,
                requirement,
                target_model,
            )
            usage = llm_service.usage.as_dict()
            tool_name = "tools.storyboard_tool.generate_storyboard_with_llm"
            # What the model actually wrote versus what the vocabulary accepted.
            # Recording it is how the enum grows from real usage instead of
            # guesswork.
            vocabulary = take_normalisations()
            tool_arguments = {
                "model": llm_service.model,
                "target_video_model": target_model,
                "shot_count": len(storyboard.shots),
                "usage": usage,
                "vocabulary_normalised": vocabulary["normalised"],
                "vocabulary_unknown": vocabulary["unknown"],
            }
            normalised = vocabulary["normalised"]
            output_summary = (
                f"模型已生成 {len(storyboard.shots)} 个结构化镜头。"
            )
            if normalised:
                pairs = "、".join(
                    f"{item['raw']}→{item['canonical']}" for item in normalised[:5]
                )
                output_summary += (
                    f"其中 {len(normalised)} 个取值按同义词归一化：{pairs}"
                    + ("…" if len(normalised) > 5 else "")
                )
            model_generated = True

        finished_at = _now()
        task_plan = _set_task(
            task_plan,
            "generate_storyboard",
            TaskStatus.COMPLETED,
            started_at=started_at,
            finished_at=finished_at,
            output_data={
                "shot_count": len(storyboard.shots),
                "generation_method": storyboard.generation_method,
                "model_generated": model_generated,
                "target_video_model": target_model,
            },
        )
        event = _event(
            "generate_storyboard",
            status="success",
            input_summary=(
                f"{len(requirement.scene_requirements)} 个场景，"
                f"目标 {requirement.duration_seconds:g} 秒，"
                f"目标模型 {target_model}"
            ),
            output_summary=output_summary,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )
        result = {
            "storyboard": storyboard.model_dump(mode="json"),
            "task_plan": task_plan,
            "trace_events": [event],
        }
        if usage is not None:
            result["llm_usage"] = usage
        return result
    except (
        LLMConfigurationError,
        LLMCallError,
        LLMResponseError,
        ValidationError,
        ValueError,
    ) as exc:
        message = f"分镜生成失败：{exc}"
        finished_at = _now()
        task_plan = _set_task(
            task_plan,
            "generate_storyboard",
            TaskStatus.FAILED,
            started_at=started_at,
            finished_at=finished_at,
            error=message,
        )
        if llm_service is not None:
            tool_name = "tools.storyboard_tool.generate_storyboard_with_llm"
            tool_arguments = {
                "model": llm_service.model,
                "target_video_model": target_model,
                "usage": llm_service.usage.as_dict(),
            }
        else:
            tool_name = (
                "tools.storyboard_tool.generate_deterministic_storyboard"
            )
            tool_arguments = {"target_video_model": target_model}
        event = _event(
            "generate_storyboard",
            status="error",
            input_summary=f"目标模型 {target_model}",
            error=message,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )
        result = {
            "errors": _errors(state) + [message],
            "task_plan": task_plan,
            "trace_events": [event],
        }
        if llm_service is not None:
            result["llm_usage"] = llm_service.usage.as_dict()
        return result


def make_generate_storyboard_node(
    llm_service: LLMService | None,
) -> Callable[[AgentState], dict[str, Any]]:
    def node(state: AgentState) -> dict[str, Any]:
        return _generate_storyboard(state, llm_service)

    return node


def generate_storyboard(state: AgentState) -> dict[str, Any]:
    """Deterministic entry point kept for direct callers."""

    return _generate_storyboard(state, None)


def generate_prompts(state: AgentState) -> dict[str, Any]:
    started_at = _now()
    task_plan = state.get("task_plan", [])
    target_model = state.get("target_video_model", "generic")
    try:
        requirement = CreativeRequirement.model_validate(
            state.get("structured_requirement") or {}
        )
        storyboard = Storyboard.model_validate(
            state.get("storyboard") or {}
        )
        updated = build_prompts_for_storyboard(
            storyboard,
            requirement,
            target_model,
        )
        finished_at = _now()
        task_plan = _set_task(
            task_plan,
            "generate_prompts",
            TaskStatus.COMPLETED,
            started_at=started_at,
            finished_at=finished_at,
            output_data={
                "shot_count": len(updated.shots),
                "prompt_generation_method": (
                    updated.prompt_generation_method
                ),
                "target_video_model": target_model,
            },
        )
        event = _event(
            "generate_prompts",
            status="success",
            input_summary=(
                f"{len(storyboard.shots)} 个镜头，目标模型 {target_model}"
            ),
            output_summary=(
                f"已为 {len(updated.shots)} 个镜头生成图片和视频提示词。"
            ),
            tool_name="tools.prompt_builder.build_prompts_for_storyboard",
            tool_arguments={
                "shot_count": len(updated.shots),
                "target_video_model": target_model,
            },
        )
        return {
            "storyboard": updated.model_dump(mode="json"),
            "task_plan": task_plan,
            "trace_events": [event],
        }
    except (ValidationError, ValueError) as exc:
        message = f"提示词生成失败：{exc}"
        finished_at = _now()
        task_plan = _set_task(
            task_plan,
            "generate_prompts",
            TaskStatus.FAILED,
            started_at=started_at,
            finished_at=finished_at,
            error=message,
        )
        event = _event(
            "generate_prompts",
            status="error",
            input_summary=f"目标模型 {target_model}",
            error=message,
            tool_name="tools.prompt_builder.build_prompts_for_storyboard",
            tool_arguments={"target_video_model": target_model},
        )
        return {
            "errors": _errors(state) + [message],
            "task_plan": task_plan,
            "trace_events": [event],
        }


def _revision_record(
    revision_number: int,
    status: str,
    reason: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    tool: str,
    created_at: str,
    llm_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "revision_number": revision_number,
        "status": status,
        "reason": reason[:1000],
        "before": before,
        "after": after,
        "tool": tool,
        "llm_usage": llm_usage or {},
        "created_at": created_at,
    }


def _blocked_revision(
    state: AgentState,
    task_plan: list[dict[str, Any]],
    started_at: str,
    message: str,
) -> dict[str, Any]:
    finished_at = _now()
    task_plan = _set_task(
        task_plan,
        "revise_output",
        TaskStatus.FAILED,
        started_at=started_at,
        finished_at=finished_at,
        error=message,
    )
    event = _event(
        "revise_output",
        status="error",
        error=message,
        tool_name="tools.revision_tool.revision",
    )
    return {
        "errors": _errors(state) + [message],
        "task_plan": task_plan,
        "revision_failed": True,
        "trace_events": [event],
    }


def validate_output(state: AgentState) -> dict[str, Any]:
    started_at = _now()
    task_plan = state.get("task_plan", [])
    target_model = state.get("target_video_model", "generic")
    try:
        requirement = CreativeRequirement.model_validate(
            state.get("structured_requirement") or {}
        )
        storyboard = Storyboard.model_validate(
            state.get("storyboard") or {}
        )
        tolerance = float(
            state.get(
                "duration_tolerance_seconds",
                DURATION_TOLERANCE_SECONDS,
            )
        )
        report = run_validation(
            storyboard.shots,
            requirement,
            tolerance,
            target_model,
        )
        report_data = report.model_dump(mode="json")
        finished_at = _now()
        task_plan = _set_task(
            task_plan,
            "validate_output",
            (
                TaskStatus.COMPLETED
                if report.passed
                else TaskStatus.FAILED
            ),
            started_at=started_at,
            finished_at=finished_at,
            output_data={
                "passed": report.passed,
                "duration_passed": report.duration.passed,
                "scene_passed": report.scene.passed,
                "consistency_passed": report.consistency.passed,
                "prompt_passed": report.prompt.passed,
                "error_count": len(report.errors),
                "warning_count": len(report.warnings),
                "revision_count": int(
                    state.get("revision_count", 0)
                ),
            },
            error=(
                None
                if report.passed
                else (
                    report.errors[0]
                    if report.errors
                    else "综合校验未通过。"
                )
            ),
        )

        events = [
            _event(
                "validate_output",
                status="success",
                input_summary=(
                    f"目标 {requirement.duration_seconds:g} 秒，"
                    f"{len(storyboard.shots)} 个镜头，"
                    f"{len(requirement.scene_requirements)} 个场景"
                ),
                output_summary=(
                    f"时长：{'通过' if report.duration.passed else '未通过'}；"
                    f"场景：{'通过' if report.scene.passed else '未通过'}；"
                    f"一致性："
                    f"{'通过' if report.consistency.passed else '未通过'}；"
                    f"提示词："
                    f"{'通过' if report.prompt.passed else '未通过'}。"
                ),
                tool_name="tools.validation_pipeline.run_validation",
                tool_arguments={
                    "target_duration_seconds": (
                        requirement.duration_seconds
                    ),
                    "tolerance_seconds": tolerance,
                    "shot_count": len(storyboard.shots),
                    "scene_requirements": (
                        requirement.scene_requirements
                    ),
                    "target_video_model": target_model,
                },
            ),
            _event(
                "validate_output",
                status="success",
                output_summary=(
                    f"timeline_end="
                    f"{report.duration.timeline_end_seconds:g} 秒，"
                    f"errors={len(report.duration.errors)}。"
                ),
                tool_name="tools.duration_checker.check_duration",
                tool_arguments={
                    "target_duration_seconds": (
                        requirement.duration_seconds
                    ),
                    "tolerance_seconds": tolerance,
                    "shot_count": len(storyboard.shots),
                },
            ),
            _event(
                "validate_output",
                status="success",
                output_summary=(
                    f"coverage={report.scene.coverage_ratio:.2f}，"
                    f"missing={report.scene.missing_scenes}，"
                    f"duplicates={report.scene.duplicate_scenes}。"
                ),
                tool_name="tools.scene_checker.check_scene_coverage",
                tool_arguments={
                    "required_scenes": (
                        requirement.scene_requirements
                    ),
                    "shot_count": len(storyboard.shots),
                },
            ),
            _event(
                "validate_output",
                status="success",
                output_summary=(
                    f"checks={len(report.consistency.checks)}，"
                    f"errors={len(report.consistency.errors)}，"
                    f"warnings={len(report.consistency.warnings)}。"
                ),
                tool_name="tools.consistency_checker.check_consistency",
                tool_arguments={
                    "shot_count": len(storyboard.shots),
                    "constraint_count": len(
                        requirement.consistency_constraints
                    ),
                },
            ),
            _event(
                "validate_output",
                status="success",
                output_summary=(
                    f"prompt_errors={len(report.prompt.errors)}，"
                    f"prompt_warnings={len(report.prompt.warnings)}。"
                ),
                tool_name="tools.prompt_checker.check_prompt_quality",
                tool_arguments={
                    "shot_count": len(storyboard.shots),
                    "target_video_model": target_model,
                },
            ),
        ]
        return {
            "validation_report": report_data,
            "task_plan": task_plan,
            "trace_events": events,
        }
    except (ValidationError, ValueError, TypeError) as exc:
        message = f"综合校验失败：{type(exc).__name__}: {exc}"
        finished_at = _now()
        task_plan = _set_task(
            task_plan,
            "validate_output",
            TaskStatus.FAILED,
            started_at=started_at,
            finished_at=finished_at,
            error=message,
        )
        event = _event(
            "validate_output",
            status="error",
            error=message,
            tool_name="tools.validation_pipeline.run_validation",
        )
        return {
            "errors": _errors(state) + [message],
            "task_plan": task_plan,
            "validation_report": None,
            "trace_events": [event],
        }


def _write_director_prompt(
    state: AgentState,
    llm_service: LLMService | None,
) -> dict[str, Any]:
    started_at = _now()
    task_plan = state.get("task_plan", [])
    target_model = state.get("target_video_model", "generic")

    if llm_service is None:
        finished_at = _now()
        task_plan = _set_task(
            task_plan,
            "write_director_prompt",
            TaskStatus.SKIPPED,
            started_at=started_at,
            finished_at=finished_at,
            output_data={
                "reason": "演示模式未调用模型，使用规则拼装提示词。"
            },
        )
        event = _event(
            "write_director_prompt",
            status="skipped",
            output_summary=(
                "未配置模型，跳过导演提示词生成；"
                "保留规则拼装提示词。"
            ),
        )
        return {
            "task_plan": task_plan,
            "trace_events": [event],
            "director_prompt_failed": False,
        }

    try:
        requirement = CreativeRequirement.model_validate(
            state.get("structured_requirement") or {}
        )
        storyboard = Storyboard.model_validate(
            state.get("storyboard") or {}
        )
        report = AggregateValidationReport.model_validate(
            state.get("validation_report") or {}
        )
        package = write_director_package(
            llm_service,
            requirement,
            storyboard,
            report,
            target_model,
        )
        updated = storyboard.model_copy(
            update={
                "director_package": package,
                "prompt_generation_method": "llm_director",
            }
        )
        usage = llm_service.usage.as_dict()
        finished_at = _now()
        task_plan = _set_task(
            task_plan,
            "write_director_prompt",
            TaskStatus.COMPLETED,
            started_at=started_at,
            finished_at=finished_at,
            output_data={
                "title": package.title,
                "global_prompt_chars": len(package.global_prompt),
                "shot_prompt_count": len(package.shot_prompts),
                "target_video_model": target_model,
                "usage": usage,
            },
        )
        event = _event(
            "write_director_prompt",
            status="success",
            input_summary=(
                f"{len(storyboard.shots)} 个镜头，"
                f"目标模型 {target_model}"
            ),
            output_summary=(
                f"已生成导演提示词 {len(package.global_prompt)} 字符，"
                f"{len(package.shot_prompts)} 个镜头提示词。"
            ),
            tool_name="tools.prompt_writer.write_director_package",
            tool_arguments={
                "model": llm_service.model,
                "target_video_model": target_model,
                "usage": usage,
            },
        )
        return {
            "storyboard": updated.model_dump(mode="json"),
            "task_plan": task_plan,
            "trace_events": [event],
            "llm_usage": usage,
        }
    except (
        PromptWriterError,
        LLMConfigurationError,
        LLMCallError,
        LLMResponseError,
        ValidationError,
        ValueError,
    ) as exc:
        message = f"导演提示词生成失败：{exc}"
        usage = llm_service.usage.as_dict()
        finished_at = _now()
        task_plan = _set_task(
            task_plan,
            "write_director_prompt",
            TaskStatus.FAILED,
            started_at=started_at,
            finished_at=finished_at,
            error=message,
        )
        event = _event(
            "write_director_prompt",
            status="error",
            input_summary=f"目标模型 {target_model}",
            error=message,
            tool_name="tools.prompt_writer.write_director_package",
            tool_arguments={
                "model": llm_service.model,
                "target_video_model": target_model,
                "usage": usage,
            },
        )
        return {
            "errors": _errors(state) + [message],
            "task_plan": task_plan,
            "trace_events": [event],
            "director_prompt_failed": True,
            "llm_usage": usage,
        }


def make_write_director_prompt_node(
    llm_service: LLMService | None,
) -> Callable[[AgentState], dict[str, Any]]:
    def node(state: AgentState) -> dict[str, Any]:
        return _write_director_prompt(state, llm_service)

    return node


def _revise_output(
    state: AgentState,
    llm_service: LLMService | None,
) -> dict[str, Any]:
    started_at = _now()
    task_plan = state.get("task_plan", [])
    target_model = state.get("target_video_model", "generic")
    revision_count = int(state.get("revision_count", 0))
    max_revisions = int(state.get("max_revisions", 2))
    report_data = state.get("validation_report")

    if report_data is None:
        return _blocked_revision(
            state,
            task_plan,
            started_at,
            "自动修正失败：没有可用的校验报告。",
        )

    try:
        report = AggregateValidationReport.model_validate(report_data)
        requirement = CreativeRequirement.model_validate(
            state.get("structured_requirement") or {}
        )
        storyboard = Storyboard.model_validate(
            state.get("storyboard") or {}
        )
    except ValidationError as exc:
        return _blocked_revision(
            state,
            task_plan,
            started_at,
            "自动修正失败：修正输入数据无效："
            + _format_validation_error(exc),
        )

    if report.passed:
        return _blocked_revision(
            state,
            task_plan,
            started_at,
            "自动修正失败：当前校验已通过，不需要修正。",
        )
    if revision_count >= max_revisions:
        return _blocked_revision(
            state,
            task_plan,
            started_at,
            f"自动修正失败：已达到上限 {max_revisions} 次。",
        )

    next_revision = revision_count + 1
    before_summary = summarize_storyboard(storyboard)
    tool_name = (
        "tools.revision_tool.revise_storyboard_with_llm"
        if llm_service is not None
        else "tools.revision_tool.revise_storyboard_deterministically"
    )

    try:
        if llm_service is not None:
            revised = revise_storyboard_with_llm(
                llm_service,
                requirement,
                storyboard,
                report,
                target_model,
            )
            usage = llm_service.usage.as_dict()
        else:
            revised = revise_storyboard_deterministically(
                requirement,
                storyboard,
                report,
            )
            usage = {}

        after_summary = summarize_storyboard(revised)
        record = _revision_record(
            next_revision,
            "completed",
            "; ".join(report.errors[:5]),
            before_summary,
            after_summary,
            tool_name,
            _now(),
            usage,
        )
        finished_at = _now()
        task_plan = _set_task(
            task_plan,
            "revise_output",
            TaskStatus.COMPLETED,
            started_at=started_at,
            finished_at=finished_at,
            output_data={
                "revision_number": next_revision,
                "errors_before": len(report.errors),
                "before": before_summary,
                "after": after_summary,
                "tool": tool_name,
            },
        )
        event = _event(
            "revise_output",
            status="success",
            input_summary=(
                f"第 {next_revision} 次修正，"
                f"{len(report.errors)} 项错误"
            ),
            output_summary=(
                f"镜头 {before_summary['shot_count']} → "
                f"{after_summary['shot_count']}，"
                f"终点 {before_summary['timeline_end_seconds']:g} → "
                f"{after_summary['timeline_end_seconds']:g} 秒。"
            ),
            tool_name=tool_name,
            tool_arguments={
                "revision_number": next_revision,
                "max_revisions": max_revisions,
                "error_count": len(report.errors),
                "target_video_model": target_model,
                "usage": usage,
            },
        )
        result = {
            "storyboard": revised.model_dump(mode="json"),
            "task_plan": task_plan,
            "revision_count": next_revision,
            "revision_failed": False,
            "revision_history": [record],
            "trace_events": [event],
        }
        if usage:
            result["llm_usage"] = usage
        return result
    except (
        RevisionError,
        LLMConfigurationError,
        LLMCallError,
        LLMResponseError,
        ValidationError,
        ValueError,
    ) as exc:
        message = f"自动修正失败：{exc}"
        usage = (
            llm_service.usage.as_dict()
            if llm_service is not None
            else {}
        )
        record = _revision_record(
            next_revision,
            "failed",
            message,
            before_summary,
            None,
            tool_name,
            _now(),
            usage,
        )
        finished_at = _now()
        task_plan = _set_task(
            task_plan,
            "revise_output",
            TaskStatus.FAILED,
            started_at=started_at,
            finished_at=finished_at,
            output_data={
                "revision_number": next_revision,
                "before": before_summary,
            },
            error=message,
        )
        event = _event(
            "revise_output",
            status="error",
            input_summary=f"第 {next_revision} 次修正",
            error=message,
            tool_name=tool_name,
            tool_arguments={
                "revision_number": next_revision,
                "max_revisions": max_revisions,
                "usage": usage,
            },
        )
        result = {
            "errors": _errors(state) + [message],
            "task_plan": task_plan,
            "revision_count": next_revision,
            "revision_failed": True,
            "revision_history": [record],
            "trace_events": [event],
        }
        if usage:
            result["llm_usage"] = usage
        return result


def make_revise_output_node(
    llm_service: LLMService | None,
) -> Callable[[AgentState], dict[str, Any]]:
    def node(state: AgentState) -> dict[str, Any]:
        return _revise_output(state, llm_service)

    return node


def finalize_result(state: AgentState) -> dict[str, Any]:
    report = state.get("validation_report")
    revision_count = int(state.get("revision_count", 0))
    max_revisions = int(state.get("max_revisions", 2))
    revision_failed = bool(state.get("revision_failed", False))
    director_prompt_failed = bool(
        state.get("director_prompt_failed", False)
    )

    if report is not None and report.get("passed"):
        final_status = "failed" if director_prompt_failed else "completed"
    elif revision_failed:
        final_status = "failed"
    elif report is not None:
        final_status = "validation_failed"
    else:
        final_status = "failed"

    remaining_errors = list(state.get("errors") or [])
    if report is not None and report.get("passed") and director_prompt_failed:
        remaining_errors.append(
            "导演提示词生成失败，未输出可用的整片提示词。"
        )
    if report is not None and not report.get("passed"):
        remaining_errors.extend(
            f"校验未通过：{error}"
            for error in report.get("errors", [])
        )
        if revision_failed:
            remaining_errors.append("自动修正执行失败，已停止。")
        elif revision_count >= max_revisions:
            remaining_errors.append(
                f"已达到自动修正上限 {max_revisions} 次，"
                "仍有未解决问题。"
            )

    seen: set[str] = set()
    unique_errors: list[str] = []
    for error in remaining_errors:
        if error not in seen:
            seen.add(error)
            unique_errors.append(error)
    remaining_errors = unique_errors[:30]

    now = _now()
    task_plan = _set_task(
        state.get("task_plan", []),
        "finalize_result",
        TaskStatus.COMPLETED,
        started_at=now,
        finished_at=now,
        output_data={
            "final_status": final_status,
            "remaining_errors": len(remaining_errors),
            "revision_count": revision_count,
            "max_revisions": max_revisions,
            "director_prompt_failed": director_prompt_failed,
        },
    )
    if revision_count == 0:
        task_plan = _set_task(
            task_plan,
            "revise_output",
            TaskStatus.SKIPPED,
            started_at=now,
            finished_at=now,
            output_data={"reason": "综合校验一次通过，无需修正。"},
        )
    event = _event(
        "finalize_result",
        status="success",
        input_summary=(
            f"校验报告存在：{report is not None}；"
            f"修正次数：{revision_count}/{max_revisions}"
        ),
        output_summary=f"工作流最终状态：{final_status}",
    )
    return {
        "final_status": final_status,
        "task_plan": task_plan,
        "errors": remaining_errors,
        "trace_events": [event],
    }
