"""Shared state passed through the LangGraph workflow."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    project_id: str
    execution_id: str
    raw_requirement: str
    requirement_input: dict[str, Any]
    structured_requirement: dict[str, Any]
    task_plan: list[dict[str, Any]]
    storyboard: dict[str, Any]
    validation_report: dict[str, Any] | None
    duration_tolerance_seconds: float
    use_llm: bool
    target_video_model: str
    llm_usage: dict[str, Any]
    errors: list[str]
    revision_count: int
    max_revisions: int
    revision_failed: bool
    director_prompt_failed: bool
    revision_history: Annotated[list[dict[str, Any]], operator.add]
    final_status: str
    trace_events: Annotated[list[dict[str, Any]], operator.add]
