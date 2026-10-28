from __future__ import annotations

from pathlib import Path

import pytest

from database.repository import ProjectRepository
from schemas.storyboard import Storyboard
from services.llm_service import LLMService
from services.project_service import CreativeProjectService
from tests.fakes import FakeChatClient
from tests.test_llm_workflow import (
    _director_payload,
    _llm_payload,
    _storyboard_payload,
)
from tools.prompt_builder import build_prompts_for_storyboard
from tools.revision_tool import (
    RevisionError,
    revise_storyboard_deterministically,
)
from tools.storyboard_tool import generate_deterministic_storyboard
from tools.validation_pipeline import run_validation


def _storyboard_with_timeline(total: float) -> dict:
    payload = _storyboard_payload()
    payload["shots"][-1]["end_seconds"] = total
    return payload


def _service(
    tmp_path: Path,
    name: str,
    responses: list,
) -> tuple[CreativeProjectService, ProjectRepository]:
    repository = ProjectRepository(tmp_path / name)
    llm_service = LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        client=FakeChatClient(responses),
        retry_backoff_seconds=0,
    )
    return (
        CreativeProjectService(repository, llm_service=llm_service),
        repository,
    )


def test_llm_revision_repairs_duration_and_completes(
    tmp_path: Path,
    demo_requirement,
) -> None:
    service, repository = _service(
        tmp_path,
        "revision_success.sqlite3",
        [
            _llm_payload(),
            _storyboard_with_timeline(27),
            _storyboard_payload(),
            _director_payload(),
        ],
    )

    result = service.run(
        demo_requirement,
        raw_requirement="30 秒汽车广告，时长需要精确。",
    )

    assert result["final_status"] == "completed"
    assert result["revision_count"] == 1
    assert result["llm_usage"]["calls"] == 4
    assert result["validation_report"]["passed"] is True
    assert result["storyboard"]["director_package"] is not None

    history = result["revision_history"]
    assert len(history) == 1
    assert history[0]["status"] == "completed"
    assert history[0]["before"]["timeline_end_seconds"] == 27.0
    assert history[0]["after"]["timeline_end_seconds"] == 30.0
    assert any(
        event.get("tool_name")
        == "tools.revision_tool.revise_storyboard_with_llm"
        for event in result["trace_events"]
    )

    task_statuses = {
        task["task_id"]: task["status"] for task in result["task_plan"]
    }
    assert task_statuses["revise_output"] == "completed"

    project = repository.get_project(result["project_id"])
    assert project is not None
    assert project["status"] == "completed"
    assert len(project["revision_history"]) == 1
    stored = project["revision_history"][0]
    assert stored["status"] == "completed"
    assert stored["details_json"]["after"]["timeline_end_seconds"] == 30.0


def test_revision_loop_stops_after_two_attempts(
    tmp_path: Path,
    demo_requirement,
) -> None:
    bad = _storyboard_with_timeline(27)
    service, repository = _service(
        tmp_path,
        "revision_exhausted.sqlite3",
        [_llm_payload(), bad, bad, bad],
    )

    result = service.run(
        demo_requirement,
        raw_requirement="连续修正仍然失败的需求。",
        max_revisions=2,
    )

    assert result["final_status"] == "validation_failed"
    assert result["revision_count"] == 2
    assert result["llm_usage"]["calls"] == 4
    assert len(result["revision_history"]) == 2
    assert any(
        "已达到自动修正上限 2 次" in error
        for error in result["errors"]
    )
    assert result["validation_report"]["duration"]["passed"] is False

    project = repository.get_project(result["project_id"])
    assert project is not None
    assert project["status"] == "validation_failed"
    assert len(project["revision_history"]) == 2


def test_revision_call_failure_is_reported(
    tmp_path: Path,
    demo_requirement,
) -> None:
    service, repository = _service(
        tmp_path,
        "revision_failed.sqlite3",
        [
            _llm_payload(),
            _storyboard_with_timeline(27),
            "这不是 JSON",
        ],
    )

    result = service.run(
        demo_requirement,
        raw_requirement="修正调用失败测试。",
    )

    assert result["final_status"] == "failed"
    assert result["revision_count"] == 1
    assert result["revision_history"][0]["status"] == "failed"
    assert any(
        "自动修正失败" in error for error in result["errors"]
    )

    project = repository.get_project(result["project_id"])
    assert project is not None
    assert project["status"] == "failed"


def test_zero_revisions_goes_straight_to_failure(
    tmp_path: Path,
    demo_requirement,
) -> None:
    service, repository = _service(
        tmp_path,
        "revision_disabled.sqlite3",
        [_llm_payload(), _storyboard_with_timeline(27)],
    )

    result = service.run(
        demo_requirement,
        raw_requirement="关闭自动修正。",
        max_revisions=0,
    )

    assert result["final_status"] == "validation_failed"
    assert result["revision_count"] == 0
    assert result["revision_history"] == []
    assert result["llm_usage"]["calls"] == 2


def test_deterministic_revision_repairs_duration(
    demo_requirement,
) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)
    shots = list(storyboard.shots)
    shots[-1] = shots[-1].model_copy(update={"end_seconds": 27.0})
    bad = Storyboard(
        generation_method=storyboard.generation_method,
        shots=shots,
    )
    bad = build_prompts_for_storyboard(bad, demo_requirement)
    report = run_validation(bad.shots, demo_requirement, 0.5)

    assert report.duration.passed is False
    assert report.scene.passed is True
    assert report.consistency.passed is True
    assert report.prompt.passed is True

    revised = revise_storyboard_deterministically(
        demo_requirement,
        bad,
        report,
    )
    revised = build_prompts_for_storyboard(revised, demo_requirement)
    new_report = run_validation(revised.shots, demo_requirement, 0.5)

    assert revised.shots[-1].end_seconds == 30.0
    assert new_report.passed is True


def test_deterministic_revision_rejects_scene_errors(
    demo_requirement,
) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)
    shots = list(storyboard.shots)
    shots[3] = shots[3].model_copy(update={"scene": "城市"})
    bad = Storyboard(
        generation_method=storyboard.generation_method,
        shots=shots,
    )
    bad = build_prompts_for_storyboard(bad, demo_requirement)
    report = run_validation(bad.shots, demo_requirement, 0.5)

    assert report.scene.passed is False
    with pytest.raises(RevisionError):
        revise_storyboard_deterministically(
            demo_requirement,
            bad,
            report,
        )
