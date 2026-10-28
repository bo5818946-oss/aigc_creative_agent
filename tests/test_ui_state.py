from __future__ import annotations

from pathlib import Path

from database.repository import ProjectRepository
from ui.state import (
    RunSession,
    drain_session,
    execute_run,
    project_to_result,
    session_is_active,
)


def _project() -> dict:
    traces = [
        {
            "node_name": "analyze_requirements",
            "tool_arguments": {"usage": {"calls": 1, "total_tokens": 50}},
        },
        {
            "node_name": "generate_storyboard",
            "tool_arguments": {"usage": {"calls": 2, "total_tokens": 120}},
        },
        {
            "node_name": "finalize_result",
            "tool_arguments": None,
        },
    ]
    return {
        "project_id": "project-1",
        "status": "completed",
        "raw_requirement": "30秒汽车广告",
        "structured_requirement": {
            "project_name": "项目",
            "duration_seconds": 30,
        },
        "task_plan": [{"task_id": "finalize_result", "status": "completed"}],
        "storyboard": {"shots": [{"shot_number": 1, "scene": "森林"}]},
        "validation_reports": [
            {
                "report_type": "aggregate",
                "passed": 1,
                "report_json": {
                    "check_type": "aggregate",
                    "passed": True,
                    "errors": [],
                },
            }
        ],
        "revision_history": [
            {"revision_number": 1, "status": "completed"}
        ],
        "executions": [
            {
                "execution_id": "execution-1",
                "error": None,
                "traces": traces,
            }
        ],
        "created_at": "2026-10-19T10:00:00+00:00",
        "updated_at": "2026-10-19T10:01:00+00:00",
    }


def test_project_to_result_maps_history_data() -> None:
    result = project_to_result(_project())

    assert result["project_id"] == "project-1"
    assert result["execution_id"] == "execution-1"
    assert result["final_status"] == "completed"
    assert result["validation_report"]["passed"] is True
    assert result["revision_history"][0]["revision_number"] == 1
    assert result["llm_usage"] == {"calls": 2, "total_tokens": 120}
    assert len(result["trace_events"]) == 3
    assert result["errors"] == []


def test_project_to_result_handles_old_project() -> None:
    result = project_to_result(
        {
            "project_id": "old",
            "project_name": "旧项目",
            "status": "completed",
            "raw_requirement": "",
            "structured_requirement": {},
            "task_plan": [],
            "storyboard": {},
            "validation_reports": [],
            "revision_history": [],
            "executions": [],
        }
    )

    assert result["validation_report"] is None
    assert result["trace_events"] == []
    assert result["llm_usage"] == {}
    assert result["revision_history"] == []


def test_drain_session_reads_stream_events() -> None:
    session = RunSession()
    session.queue.put(
        {
            "state": {
                "trace_events": [{"node_name": "analyze_requirements"}],
                "task_plan": [{"task_id": "analyze_requirements"}],
            }
        }
    )
    session.queue.put(
        {
            "done": True,
            "result": {
                "final_status": "completed",
                "project_id": "p1",
                "errors": [],
            },
        }
    )
    session.queue.put({"worker_done": True})

    drain_session(session)

    assert session.thread_done is True
    assert session.status == "completed"
    assert session.result["project_id"] == "p1"
    assert session.latest_state["task_plan"][0]["task_id"] == (
        "analyze_requirements"
    )


def test_drain_session_records_failure() -> None:
    session = RunSession()
    session.queue.put({"worker_error": "LLM timeout"})
    session.queue.put({"worker_done": True})

    drain_session(session)

    assert session.status == "failed"
    assert session.error == "LLM timeout"
    assert session.result is None


def test_session_is_active_only_while_running() -> None:
    session = RunSession()
    assert session_is_active(session) is True

    session.thread_done = True
    assert session_is_active(session) is False

    session.finalized = True
    assert session_is_active(session) is False


def test_execute_run_completes_and_persists(
    tmp_path: Path,
    demo_requirement,
) -> None:
    db_path = tmp_path / "ui_run.sqlite3"
    session = RunSession()

    execute_run(
        session,
        demo_requirement,
        use_llm=False,
        target_video_model="generic",
        max_revisions=2,
        duration_tolerance_seconds=0.5,
        db_path=str(db_path),
    )
    drain_session(session)

    assert session.status == "completed"
    assert session.thread_done is True
    assert session.result is not None
    assert session.result["final_status"] == "completed"
    assert session.result["storyboard"]["prompt_generation_method"] == (
        "deterministic_builder"
    )
    project = ProjectRepository(db_path).get_project(
        session.result["project_id"]
    )
    assert project is not None
    assert project["status"] == "completed"
    assert project["validation_reports"][0]["report_type"] == "aggregate"
