from __future__ import annotations

from pathlib import Path

from database.repository import ProjectRepository
from services.llm_service import LLMService
from services.project_service import CreativeProjectService
from tests.fakes import FakeChatClient


def _seed_history(
    tmp_path: Path,
    demo_requirement,
) -> ProjectRepository:
    repository = ProjectRepository(tmp_path / "history.sqlite3")
    completed = CreativeProjectService(repository)
    completed.run(demo_requirement)

    failed_requirement = demo_requirement.model_copy(
        update={"project_name": "失败项目"}
    )
    llm_service = LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        client=FakeChatClient(["这不是 JSON"]),
        retry_backoff_seconds=0,
    )
    failed = CreativeProjectService(
        repository,
        llm_service=llm_service,
    )
    result = failed.run(
        failed_requirement,
        raw_requirement="失败项目测试",
    )
    assert result["final_status"] == "failed"
    return repository


def test_list_projects_supports_search_status_and_pagination(
    tmp_path: Path,
    demo_requirement,
) -> None:
    repository = _seed_history(tmp_path, demo_requirement)

    all_projects = repository.list_projects(order_by="name_asc")
    assert len(all_projects) == 2
    assert [item["project_name"] for item in all_projects] == [
        "30秒汽车品牌广告",
        "失败项目",
    ]
    completed = all_projects[0]
    assert completed["status"] == "completed"
    assert completed["duration_seconds"] == 30.0
    assert completed["scene_count"] == 5
    assert completed["shot_count"] == 5
    assert completed["generation_method"] == "deterministic_placeholder"

    failed = repository.list_projects(status="failed")
    assert len(failed) == 1
    assert failed[0]["project_name"] == "失败项目"

    searched = repository.list_projects(search="失败")
    assert len(searched) == 1
    assert searched[0]["status"] == "failed"

    first_page = repository.list_projects(
        order_by="name_asc",
        limit=1,
        offset=0,
    )
    second_page = repository.list_projects(
        order_by="name_asc",
        limit=1,
        offset=1,
    )
    assert len(first_page) == 1
    assert len(second_page) == 1
    assert first_page[0]["project_id"] != second_page[0]["project_id"]

    assert repository.count_projects() == 2
    assert repository.count_projects(status="completed") == 1
    assert repository.count_projects(search="失败") == 1


def test_empty_database_returns_empty_list(tmp_path: Path) -> None:
    repository = ProjectRepository(tmp_path / "empty.sqlite3")

    assert repository.list_projects() == []
    assert repository.list_projects(search="anything") == []
    assert repository.count_projects() == 0
