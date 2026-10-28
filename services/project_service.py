"""Application service that runs one creative workflow and persists it."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent.graph import build_workflow
from config.settings import (
    DURATION_TOLERANCE_SECONDS,
    MAX_REVISIONS,
    TARGET_VIDEO_MODEL,
)
from database.repository import ProjectRepository
from schemas.project import CreativeRequirement
from services.llm_service import LLMService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_raw_requirement(requirement: CreativeRequirement) -> str:
    scenes = "、".join(requirement.scene_requirements)
    constraints = "；".join(requirement.consistency_constraints)
    return (
        f"项目：{requirement.project_name}\n"
        f"内容类型：{requirement.content_type}\n"
        f"主体：{requirement.subject}\n"
        f"目标受众：{requirement.target_audience}\n"
        f"时长：{requirement.duration_seconds:g} 秒\n"
        f"画幅：{requirement.aspect_ratio}\n"
        f"视觉风格：{requirement.visual_style}\n"
        f"场景：{scenes}\n"
        f"镜头语言：{requirement.camera_language}\n"
        f"转场：{requirement.transition_requirements}\n"
        f"一致性约束：{constraints}\n"
        f"备注：{requirement.notes}"
    )


class CreativeProjectService:
    def __init__(
        self,
        repository: ProjectRepository,
        graph: Any | None = None,
        llm_service: LLMService | None = None,
    ):
        self.repository = repository
        self.llm_service = llm_service
        self.graph = graph or build_workflow(llm_service)

    def _prepare_run(
        self,
        requirement: CreativeRequirement,
        *,
        raw_requirement: str | None,
        duration_tolerance_seconds: float,
        target_video_model: str | None,
        max_revisions: int | None,
        project_id: str | None = None,
    ) -> tuple[str, str, dict[str, Any]]:
        effective_max_revisions = (
            MAX_REVISIONS if max_revisions is None else max_revisions
        )
        if not 0 <= effective_max_revisions <= 2:
            raise ValueError("max_revisions must be between 0 and 2")

        execution_id = uuid4().hex
        started_at = _now()
        raw_text = raw_requirement or build_raw_requirement(requirement)

        if project_id:
            existing = self.repository.get_project(project_id)
            if existing is None:
                raise ValueError(f"Project not found: {project_id}")
        else:
            project_id = uuid4().hex
            self.repository.create_project(
                project_id=project_id,
                requirement=requirement,
                raw_requirement=raw_text,
                created_at=started_at,
            )
        self.repository.start_execution(
            execution_id=execution_id,
            project_id=project_id,
            started_at=started_at,
        )

        initial_state: dict[str, Any] = {
            "project_id": project_id,
            "execution_id": execution_id,
            "raw_requirement": raw_text,
            "requirement_input": requirement.model_dump(mode="json"),
            "structured_requirement": {},
            "task_plan": [],
            "storyboard": {},
            "validation_report": None,
            "duration_tolerance_seconds": duration_tolerance_seconds,
            "use_llm": self.llm_service is not None,
            "target_video_model": target_video_model or TARGET_VIDEO_MODEL,
            "llm_usage": {},
            "errors": [],
            "revision_count": 0,
            "max_revisions": effective_max_revisions,
            "revision_failed": False,
            "director_prompt_failed": False,
            "revision_history": [],
            "final_status": "running",
            "trace_events": [],
        }

        if self.llm_service is not None:
            self.llm_service.reset_usage()

        return project_id, execution_id, initial_state

    def _persist_result(
        self,
        project_id: str,
        execution_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        final_status = result.get("final_status") or "failed"
        finished_at = _now()
        structured_requirement = result.get("structured_requirement") or None
        project_name = (
            structured_requirement.get("project_name")
            if structured_requirement
            else None
        )
        self.repository.finish_run(
            project_id=project_id,
            execution_id=execution_id,
            status=final_status,
            task_plan=result.get("task_plan", []),
            storyboard=result.get("storyboard", {}),
            validation_report=result.get("validation_report"),
            trace_events=result.get("trace_events", []),
            error=(
                None
                if final_status == "completed"
                else "; ".join(result.get("errors", [])) or None
            ),
            finished_at=finished_at,
            structured_requirement=structured_requirement,
            project_name=project_name or None,
            revision_history=result.get("revision_history", []),
            raw_requirement=result.get("raw_requirement"),
        )

        persisted = dict(result)
        persisted["project_id"] = project_id
        persisted["execution_id"] = execution_id
        persisted["llm_usage"] = result.get("llm_usage") or {}
        persisted["revision_history"] = (
            result.get("revision_history") or []
        )
        persisted["created_at"] = result.get("created_at") or finished_at
        persisted["updated_at"] = finished_at
        return persisted

    def _persist_failure(
        self,
        project_id: str,
        execution_id: str,
        error: str,
        state: dict[str, Any],
    ) -> None:
        finished_at = _now()
        error_event = {
            "node_name": "workflow",
            "tool_name": None,
            "tool_arguments": None,
            "input_summary": f"project_id={project_id}",
            "output_summary": "工作流未完成",
            "status": "error",
            "error": error,
            "created_at": finished_at,
        }
        trace_events = list(state.get("trace_events") or [])
        trace_events.append(error_event)
        structured_requirement = (
            state.get("structured_requirement") or None
        )
        project_name = (
            structured_requirement.get("project_name")
            if structured_requirement
            else None
        )
        self.repository.finish_run(
            project_id=project_id,
            execution_id=execution_id,
            status="failed",
            task_plan=state.get("task_plan", []),
            storyboard=state.get("storyboard", {}),
            validation_report=None,
            trace_events=trace_events,
            error=error,
            finished_at=finished_at,
            structured_requirement=structured_requirement,
            project_name=project_name or None,
            revision_history=state.get("revision_history", []),
            raw_requirement=state.get("raw_requirement"),
        )

    def stream_run(
        self,
        requirement: CreativeRequirement,
        *,
        raw_requirement: str | None = None,
        duration_tolerance_seconds: float = DURATION_TOLERANCE_SECONDS,
        target_video_model: str | None = None,
        max_revisions: int | None = None,
        project_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        project_id, execution_id, initial_state = self._prepare_run(
            requirement,
            raw_requirement=raw_requirement,
            duration_tolerance_seconds=duration_tolerance_seconds,
            target_video_model=target_video_model,
            max_revisions=max_revisions,
            project_id=project_id,
        )
        last_state: dict[str, Any] = initial_state

        try:
            yield {
                "project_id": project_id,
                "execution_id": execution_id,
                "state": last_state,
                "done": False,
            }
            for state in self.graph.stream(
                initial_state,
                stream_mode="values",
            ):
                last_state = {**initial_state, **state}
                yield {
                    "project_id": project_id,
                    "execution_id": execution_id,
                    "state": last_state,
                    "done": False,
                }
        except Exception as exc:
            error = (
                f"工作流执行异常：{type(exc).__name__}: {exc}"
            )
            self._persist_failure(
                project_id,
                execution_id,
                error,
                last_state,
            )
            raise RuntimeError(error) from exc

        result = self._persist_result(
            project_id,
            execution_id,
            last_state,
        )
        yield {
            "project_id": project_id,
            "execution_id": execution_id,
            "state": last_state,
            "result": result,
            "done": True,
        }

    def run(
        self,
        requirement: CreativeRequirement,
        *,
        raw_requirement: str | None = None,
        duration_tolerance_seconds: float = DURATION_TOLERANCE_SECONDS,
        target_video_model: str | None = None,
        max_revisions: int | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        last_event: dict[str, Any] | None = None
        for event in self.stream_run(
            requirement,
            raw_requirement=raw_requirement,
            duration_tolerance_seconds=duration_tolerance_seconds,
            target_video_model=target_video_model,
            max_revisions=max_revisions,
            project_id=project_id,
        ):
            last_event = event

        if last_event is None or "result" not in last_event:
            raise RuntimeError("工作流未返回最终结果。")
        return last_event["result"]
