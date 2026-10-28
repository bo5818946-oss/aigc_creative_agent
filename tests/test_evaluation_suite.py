from __future__ import annotations

import json
from pathlib import Path

from evaluation import run_evaluation
from evaluation.cases import CASES


def test_evaluation_has_20_unique_cases() -> None:
    assert len(CASES) == 20
    assert len({case.case_id for case in CASES}) == 20
    assert sum(case.kind == "tool" for case in CASES) == 3


def test_evaluation_suite_matches_all_expectations(
    tmp_path: Path,
) -> None:
    report = run_evaluation(output_dir=tmp_path)

    assert report["metrics"]["total_cases"] == 20
    assert report["metrics"]["suite_passed"] == 20
    assert report["metrics"]["suite_failed"] == 0
    assert report["metrics"]["intentional_failure_cases"] == 4
    assert report["metrics"]["persistence_ok_cases"] == 17
    assert report["export_verification"]["passed"] is True
    assert report["security_check"]["passed"] is True

    markdown_path = tmp_path / "evaluation_report.md"
    json_path = tmp_path / "evaluation_report.json"
    assert markdown_path.exists()
    assert json_path.exists()

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# AIGC 智能创作工作流 Agent 评测报告" in markdown
    assert "20 条用例的实际行为与预期一致" in markdown

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["metrics"]["suite_failed"] == 0
    assert len(payload["cases"]) == 20
