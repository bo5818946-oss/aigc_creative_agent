from __future__ import annotations

from pathlib import Path

from database.repository import ProjectRepository
from services.project_service import CreativeProjectService


def test_project_and_trace_survive_new_repository_instance(
    tmp_path: Path,
    demo_requirement,
) -> None:
    db_path = tmp_path / "persistence.sqlite3"
    first_repository = ProjectRepository(db_path)
    service = CreativeProjectService(first_repository)

    result = service.run(
        demo_requirement,
        raw_requirement="持久化测试：30 秒汽车广告，五个场景。",
    )
    project_id = result["project_id"]

    second_repository = ProjectRepository(db_path)
    project = second_repository.get_project(project_id)

    assert project is not None
    assert project["project_id"] == project_id
    assert project["project_name"] == "30秒汽车品牌广告"
    assert project["raw_requirement"].startswith("持久化测试")
    assert project["status"] == "completed"

    assert project["structured_requirement"]["duration_seconds"] == 30.0
    assert len(project["task_plan"]) == 8
    assert len(project["storyboard"]["shots"]) == 5
    assert project["storyboard"]["prompt_generation_method"] == (
        "deterministic_builder"
    )
    assert all(
        shot["image_prompt"] and shot["video_prompt"]
        for shot in project["storyboard"]["shots"]
    )

    assert len(project["validation_reports"]) == 1
    report = project["validation_reports"][0]
    assert report["report_type"] == "aggregate"
    assert report["passed"] == 1
    assert report["report_json"]["duration"]["timeline_end_seconds"] == 30.0
    assert report["report_json"]["scene"]["passed"] is True
    assert report["report_json"]["consistency"]["passed"] is True
    assert report["report_json"]["prompt"]["passed"] is True
    assert project["revision_history"] == []

    assert len(project["executions"]) == 1
    execution = project["executions"][0]
    assert execution["status"] == "completed"
    assert len(execution["traces"]) == 11

    duration_traces = [
        trace
        for trace in execution["traces"]
        if trace["tool_name"] == "tools.duration_checker.check_duration"
    ]
    assert len(duration_traces) == 1
    assert duration_traces[0]["tool_arguments"]["target_duration_seconds"] == 30.0
    assert "timeline_end=30" in duration_traces[0]["output_summary"]
