from __future__ import annotations

from pathlib import Path
from typing import Any

import tools.validation_pipeline as validation_pipeline
from agent.graph import build_workflow
from database.repository import ProjectRepository
from services.project_service import CreativeProjectService


def test_workflow_completes_and_calls_real_duration_tool(
    tmp_path: Path,
    demo_requirement,
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []
    original = validation_pipeline.check_duration

    def spy(*args, **kwargs):
        calls.append({"args": args, "kwargs": dict(kwargs)})
        return original(*args, **kwargs)

    monkeypatch.setattr(validation_pipeline, "check_duration", spy)

    repository = ProjectRepository(tmp_path / "workflow.sqlite3")
    service = CreativeProjectService(repository)
    result = service.run(
        demo_requirement,
        raw_requirement="汽车广告：森林、草原、沙漠、雪地、城市，30 秒。",
    )

    assert len(calls) == 1
    assert calls[0]["kwargs"]["target_duration_seconds"] == 30.0

    assert result["final_status"] == "completed"
    assert result["validation_report"]["passed"] is True
    assert result["storyboard"]["generation_method"] == "deterministic_placeholder"
    assert result["storyboard"]["prompt_generation_method"] == (
        "deterministic_builder"
    )
    assert len(result["storyboard"]["shots"]) == 5
    assert all(
        shot["image_prompt"] and shot["video_prompt"]
        for shot in result["storyboard"]["shots"]
    )

    task_statuses = {
        task["task_id"]: task["status"] for task in result["task_plan"]
    }
    assert task_statuses == {
        "analyze_requirements": "completed",
        "plan_workflow": "completed",
        "generate_storyboard": "completed",
        "generate_prompts": "completed",
        "validate_output": "completed",
        "write_director_prompt": "skipped",
        "revise_output": "skipped",
        "finalize_result": "completed",
    }
    assert result["storyboard"]["director_package"] is None

    tool_events = [
        event
        for event in result["trace_events"]
        if event.get("tool_name") == "tools.duration_checker.check_duration"
    ]
    assert len(tool_events) == 1
    assert "timeline_end=30" in tool_events[0]["output_summary"]
    assert tool_events[0]["tool_arguments"]["target_duration_seconds"] == 30.0

    project = repository.get_project(result["project_id"])
    assert project is not None
    assert project["status"] == "completed"
    assert project["validation_reports"][0]["passed"] == 1
    assert project["validation_reports"][0]["report_type"] == "aggregate"
    duration_traces = [
        trace
        for trace in project["executions"][0]["traces"]
        if trace["tool_name"]
        == "tools.duration_checker.check_duration"
    ]
    assert len(duration_traces) == 1
    assert project["revision_history"] == []


def test_invalid_requirement_fails_cleanly_without_running_tools(
    tmp_path: Path,
) -> None:
    repository = ProjectRepository(tmp_path / "invalid.sqlite3")
    service = CreativeProjectService(repository)
    graph = service.graph

    result = graph.invoke(
        {
            "project_id": "test-project",
            "execution_id": "test-execution",
            "raw_requirement": "缺少必要字段",
            "requirement_input": {
                "project_name": "",
                "content_type": "",
                "subject": "",
                "duration_seconds": 0,
            },
            "structured_requirement": {},
            "task_plan": [],
            "storyboard": {},
            "validation_report": None,
            "duration_tolerance_seconds": 0.5,
            "errors": [],
            "revision_count": 0,
            "final_status": "running",
            "trace_events": [],
        }
    )

    assert result["final_status"] == "failed"
    assert result["validation_report"] is None
    assert any("需求数据校验失败" in error for error in result["errors"])
    assert all(
        event.get("tool_name") != "tools.duration_checker.check_duration"
        for event in result["trace_events"]
    )
    assert [event["node_name"] for event in result["trace_events"]] == [
        "analyze_requirements",
        "finalize_result",
    ]
