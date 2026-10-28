from __future__ import annotations

import json
from pathlib import Path

from database.repository import ProjectRepository
from services.project_service import CreativeProjectService
from tools.export_tool import export_project, render_markdown


def _completed_project(tmp_path: Path, demo_requirement) -> dict:
    repository = ProjectRepository(tmp_path / "export.sqlite3")
    service = CreativeProjectService(repository)
    result = service.run(demo_requirement)
    project = repository.get_project(result["project_id"])
    assert project is not None
    return project


def test_export_writes_valid_json_and_complete_markdown(
    tmp_path: Path,
    demo_requirement,
) -> None:
    project = _completed_project(tmp_path, demo_requirement)
    output = tmp_path / "output"

    paths = export_project(project, output)

    assert paths["json"].exists()
    assert paths["markdown"].exists()
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["project_id"] == project["project_id"]
    assert payload["export_schema_version"] == 1
    assert len(payload["storyboard"]["shots"]) == 5
    assert payload["revision_history"] == []

    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "# 30秒汽车品牌广告" in markdown
    assert "## 1. 原始需求" in markdown
    assert "## 4. 分镜与提示词" in markdown
    assert "**图片提示词**" in markdown
    assert "**视频提示词**" in markdown
    assert "## 5. 校验报告" in markdown
    assert "综合结果：通过" in markdown
    assert "## 6. 修正记录" in markdown
    assert "## 7. 执行轨迹" in markdown
    assert "场景：森林" in markdown


def test_export_never_overwrites_existing_files(
    tmp_path: Path,
    demo_requirement,
) -> None:
    project = _completed_project(tmp_path, demo_requirement)
    output = tmp_path / "output"

    first = export_project(project, output)
    second = export_project(project, output)

    assert first["json"] != second["json"]
    assert first["markdown"] != second["markdown"]
    assert first["json"].exists() and second["json"].exists()
    assert first["markdown"].exists() and second["markdown"].exists()


def test_old_duration_report_is_labeled_not_executed() -> None:
    project = {
        "project_id": "old-project",
        "project_name": "旧项目",
        "status": "completed",
        "raw_requirement": "旧需求",
        "structured_requirement": {
            "content_type": "商业广告",
            "subject": "主体",
            "duration_seconds": 15,
            "scene_requirements": ["城市"],
            "consistency_constraints": [],
        },
        "task_plan": [],
        "storyboard": {"shots": []},
        "validation_reports": [
            {
                "report_type": "duration",
                "passed": 1,
                "report_json": {
                    "check_type": "duration",
                    "passed": True,
                    "target_duration_seconds": 15,
                    "timeline_end_seconds": 15,
                    "errors": [],
                },
            }
        ],
        "revision_history": [],
        "executions": [],
        "created_at": "",
        "updated_at": "",
    }

    markdown = render_markdown(project)

    assert "旧版报告" in markdown
    assert "场景、一致性和提示词检查未执行" in markdown
    assert "## 5. 校验报告" in markdown


def test_empty_storyboard_and_missing_report_are_explicit(
    tmp_path: Path,
) -> None:
    project = {
        "project_id": "empty-project",
        "project_name": "空项目",
        "status": "failed",
        "raw_requirement": "",
        "structured_requirement": {},
        "task_plan": [],
        "storyboard": {"shots": []},
        "validation_reports": [],
        "revision_history": [],
        "executions": [],
        "created_at": "",
        "updated_at": "",
    }

    paths = export_project(project, tmp_path / "out")
    markdown = paths["markdown"].read_text(encoding="utf-8")
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))

    assert "未生成分镜" in markdown
    assert "未执行" in markdown
    assert payload["project_id"] == "empty-project"
