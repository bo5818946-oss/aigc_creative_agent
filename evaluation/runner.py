"""Run the 20-case evaluation suite and build a report."""

from __future__ import annotations

import json
import platform
import re
import tempfile
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database.repository import ProjectRepository
from evaluation.cases import CASES
from evaluation.fakes import FakeChatClient
from evaluation.models import (
    CaseObservation,
    CaseResult,
    EvaluationCase,
)
from evaluation.report import write_report
from schemas.project import CreativeRequirement
from services.llm_service import LLMService
from services.project_service import (
    CreativeProjectService,
    build_raw_requirement,
)
from tools.export_tool import export_project

SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{8,}")

LIMITATIONS = [
    "脚本化 FakeLLM 验证的是工作流、校验和修正逻辑，不代表真实 DeepSeek 的创作质量。",
    "真实 API 只通过可选的 pytest 测试单独验证，不在本报告的默认运行范围内。",
    "20 条用例是课程项目的能力覆盖集，不是统计意义上的行业基准。",
    "工具级用例直接测试检查器，不等同于端到端视频生成质量评测。",
    "系统只生成结构化分镜和提示词，不生成图片或视频，因此没有视觉质量或审美评分。",
    "确定性一致性检查只能核对声明和明显矛盾，不能证明最终视频中的主体外观完全一致。",
    "英文偏好模型的提示词方言转换尚未实现，Runway 用例只验证“产生警告但不误判失败”。",
    "耗时数据来自当前机器，受磁盘、Python 和系统负载影响，不是性能基准。",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _make_llm_service(case: EvaluationCase) -> LLMService:
    return LLMService(
        api_key="evaluation-fake-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        max_retries=0,
        client=FakeChatClient(list(case.responses)),
        retry_backoff_seconds=0,
    )


def _workflow_observation(
    case: EvaluationCase,
    work_dir: Path,
) -> tuple[CaseObservation, dict[str, Any] | None]:
    repository = ProjectRepository(work_dir / f"{case.case_id}.sqlite3")
    llm_service = (
        _make_llm_service(case)
        if case.kind == "workflow_fake_llm"
        else None
    )
    service = CreativeProjectService(
        repository,
        llm_service=llm_service,
    )
    requirement = CreativeRequirement.model_validate(case.requirement or {})
    result = service.run(
        requirement,
        raw_requirement=build_raw_requirement(requirement),
        duration_tolerance_seconds=case.duration_tolerance_seconds,
        target_video_model=case.target_video_model,
        max_revisions=case.max_revisions,
    )
    project = repository.get_project(result["project_id"])
    report = result.get("validation_report") or {}
    check_results = {
        name: bool((report.get(name) or {}).get("passed"))
        for name in ("duration", "scene", "consistency", "prompt")
        if isinstance(report.get(name), dict)
    }
    usage = result.get("llm_usage") or {}
    revision_history = result.get("revision_history") or []
    structured = result.get("structured_requirement") or {}
    observation = CaseObservation(
        case_id=case.case_id,
        kind=case.kind,
        duration_ms=0.0,
        final_status=str(result.get("final_status") or "unknown"),
        revision_count=int(result.get("revision_count", 0)),
        validation_passed=(
            bool(report.get("passed")) if report else None
        ),
        check_results=check_results,
        llm_calls=int(usage.get("calls", 0)),
        llm_tokens=int(usage.get("total_tokens", 0)),
        errors=[str(item) for item in (result.get("errors") or [])],
        warnings=[
            str(item) for item in (report.get("warnings") or [])
        ],
        persisted_status=(
            str(project.get("status")) if project else None
        ),
        trace_nodes=[
            str(event.get("node_name", ""))
            for event in (result.get("trace_events") or [])
        ],
        revision_statuses=[
            str(record.get("status", ""))
            for record in revision_history
        ],
        revision_reasons=[
            str(record.get("reason", ""))
            for record in revision_history
        ],
        pending_confirmations=[
            str(item)
            for item in (structured.get("pending_confirmations") or [])
        ],
        warning_count=len(report.get("warnings") or []),
        project_id=str(result.get("project_id") or "") or None,
    )
    return observation, project


def _tool_observation(case: EvaluationCase) -> CaseObservation:
    if case.tool_runner is None:
        raise ValueError(f"{case.case_id} 没有 tool_runner")
    outcome = case.tool_runner()
    return CaseObservation(
        case_id=case.case_id,
        kind=case.kind,
        duration_ms=0.0,
        final_status="tool",
        tool_passed=outcome.passed,
        tool_errors=list(outcome.errors),
        tool_warnings=list(outcome.warnings),
        warning_count=len(outcome.warnings),
    )


def _compare(case: EvaluationCase, obs: CaseObservation) -> list[str]:
    expected = case.expected
    mismatches: list[str] = []

    if obs.exception:
        mismatches.append(f"执行异常：{obs.exception.splitlines()[-1]}")
        return mismatches

    if obs.final_status != expected.final_status:
        mismatches.append(
            f"最终状态：期望 {expected.final_status}，实际 {obs.final_status}"
        )

    if case.kind == "tool":
        if (
            expected.tool_passed is not None
            and obs.tool_passed != expected.tool_passed
        ):
            mismatches.append(
                f"工具检查结果：期望 {expected.tool_passed}，"
                f"实际 {obs.tool_passed}"
            )
        joined_tool_errors = " ".join(obs.tool_errors)
        for term in expected.tool_error_contains:
            if term not in joined_tool_errors:
                mismatches.append(f"工具错误缺少：{term}")
        joined_tool_warnings = " ".join(obs.tool_warnings)
        for term in expected.tool_warning_contains:
            if term not in joined_tool_warnings:
                mismatches.append(f"工具警告缺少：{term}")
        return mismatches

    if (
        expected.revision_count is not None
        and obs.revision_count != expected.revision_count
    ):
        mismatches.append(
            f"修正次数：期望 {expected.revision_count}，"
            f"实际 {obs.revision_count}"
        )

    if (
        expected.validation_passed is not None
        and obs.validation_passed != expected.validation_passed
    ):
        mismatches.append(
            f"综合校验：期望 {expected.validation_passed}，"
            f"实际 {obs.validation_passed}"
        )

    for name, value in expected.check_results.items():
        actual = obs.check_results.get(name)
        if actual is not value:
            mismatches.append(
                f"{name} 检查：期望 {value}，实际 {actual}"
            )

    if (
        expected.llm_calls is not None
        and obs.llm_calls != expected.llm_calls
    ):
        mismatches.append(
            f"模型调用次数：期望 {expected.llm_calls}，"
            f"实际 {obs.llm_calls}"
        )

    if (
        expected.warning_count_min is not None
        and obs.warning_count < expected.warning_count_min
    ):
        mismatches.append(
            f"警告数量：期望至少 {expected.warning_count_min}，"
            f"实际 {obs.warning_count}"
        )

    if (
        expected.pending_confirmation_min is not None
        and len(obs.pending_confirmations)
        < expected.pending_confirmation_min
    ):
        mismatches.append(
            f"待确认项：期望至少 {expected.pending_confirmation_min}，"
            f"实际 {len(obs.pending_confirmations)}"
        )

    joined_errors = " ".join(obs.errors)
    for term in expected.error_contains:
        if term not in joined_errors:
            mismatches.append(f"错误信息缺少：{term}")

    joined_reasons = " ".join(obs.revision_reasons)
    for term in expected.revision_reason_contains:
        if term not in joined_reasons:
            mismatches.append(f"修正原因缺少：{term}")

    if (
        expected.revision_statuses
        and tuple(obs.revision_statuses) != expected.revision_statuses
    ):
        mismatches.append(
            f"修正状态：期望 {expected.revision_statuses}，"
            f"实际 {tuple(obs.revision_statuses)}"
        )

    for node in expected.forbidden_trace_nodes:
        if node in obs.trace_nodes:
            mismatches.append(f"不应执行的节点出现了：{node}")

    if not obs.trace_nodes:
        mismatches.append("没有执行轨迹")
    if obs.persisted_status is None:
        mismatches.append("项目没有写入 SQLite")
    elif obs.persisted_status != obs.final_status:
        mismatches.append(
            f"SQLite 状态不一致：期望 {obs.final_status}，"
            f"实际 {obs.persisted_status}"
        )

    return mismatches


def run_case(case: EvaluationCase, work_dir: Path) -> CaseResult:
    started = time.perf_counter()
    project: dict[str, Any] | None = None
    try:
        if case.kind == "tool":
            observation = _tool_observation(case)
        else:
            observation, project = _workflow_observation(case, work_dir)
    except Exception:
        observation = CaseObservation(
            case_id=case.case_id,
            kind=case.kind,
            duration_ms=0.0,
            final_status="exception",
            exception=traceback.format_exc(),
        )
    observation.duration_ms = (time.perf_counter() - started) * 1000
    mismatches = _compare(case, observation)
    return CaseResult(
        case=case,
        observation=observation,
        mismatches=mismatches,
        project=project,
    )


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, int(round(0.95 * (len(ordered) - 1)))),
    )
    return ordered[index]


def _compute_metrics(results: list[CaseResult]) -> dict[str, Any]:
    workflow = [
        item for item in results if item.case.kind != "tool"
    ]
    fake_llm = [
        item
        for item in results
        if item.case.kind == "workflow_fake_llm"
    ]
    tool = [item for item in results if item.case.kind == "tool"]
    total = len(results)
    suite_passed = sum(1 for item in results if item.passed)

    first_pass = sum(
        1
        for item in workflow
        if item.observation.final_status == "completed"
        and item.observation.revision_count == 0
    )
    recovered = sum(
        1
        for item in workflow
        if item.observation.final_status == "completed"
        and item.observation.revision_count > 0
    )
    revision_cases = sum(
        1 for item in workflow if item.observation.revision_count > 0
    )
    validation_failed = sum(
        1
        for item in workflow
        if item.observation.final_status == "validation_failed"
    )
    early_failed = sum(
        1
        for item in workflow
        if item.observation.final_status == "failed"
    )
    valid_revision_cases = recovered + validation_failed
    total_revisions = sum(
        item.observation.revision_count for item in workflow
    )
    durations = [item.observation.duration_ms for item in results]
    status_counts = Counter(
        item.observation.final_status for item in results
    )

    check_failures = {
        name: sum(
            1
            for item in workflow
            if item.observation.check_results.get(name) is False
        )
        for name in ("duration", "scene", "consistency", "prompt")
    }

    reason_keywords = {
        "时长": "总时长",
        "场景覆盖": "缺少必需场景",
        "一致性 / 方向": "相反",
        "提示词 / 动作": "动作描述",
        "修正执行异常": "自动修正失败",
    }
    revision_reason_categories = {
        label: sum(
            1
            for item in workflow
            if item.observation.revision_count > 0
            and keyword in " ".join(item.observation.revision_reasons)
        )
        for label, keyword in reason_keywords.items()
    }

    return {
        "total_cases": total,
        "suite_passed": suite_passed,
        "suite_failed": total - suite_passed,
        "suite_pass_rate": (
            suite_passed / total if total else 0.0
        ),
        "workflow_cases": len(workflow),
        "deterministic_cases": len(workflow) - len(fake_llm),
        "fake_llm_cases": len(fake_llm),
        "tool_cases": len(tool),
        "status_counts": dict(status_counts),
        "first_pass_cases": first_pass,
        "first_pass_rate": (
            first_pass / len(workflow) if workflow else 0.0
        ),
        "recovered_cases": recovered,
        "revision_cases": revision_cases,
        "recovery_rate": (
            recovered / revision_cases if revision_cases else 0.0
        ),
        "valid_revision_cases": valid_revision_cases,
        "content_recovery_rate": (
            recovered / valid_revision_cases
            if valid_revision_cases
            else 0.0
        ),
        "validation_failed_cases": validation_failed,
        "early_failed_cases": early_failed,
        "intentional_failure_cases": validation_failed + early_failed,
        "avg_revisions": (
            total_revisions / len(workflow) if workflow else 0.0
        ),
        "total_revisions": total_revisions,
        "llm_calls": sum(
            item.observation.llm_calls for item in fake_llm
        ),
        "llm_tokens": sum(
            item.observation.llm_tokens for item in fake_llm
        ),
        "check_failures": check_failures,
        "revision_reason_categories": revision_reason_categories,
        "persistence_ok_cases": sum(
            1
            for item in workflow
            if item.observation.persisted_status
            == item.observation.final_status
        ),
        "avg_duration_ms": (
            sum(durations) / len(durations) if durations else 0.0
        ),
        "p95_duration_ms": _p95(durations),
    }


def _verify_export(
    results: list[CaseResult],
    work_dir: Path,
) -> dict[str, Any]:
    completed = next(
        (
            item
            for item in results
            if item.project is not None
            and item.observation.final_status == "completed"
        ),
        None,
    )
    if completed is None or completed.project is None:
        return {
            "passed": False,
            "reason": "没有可导出的 completed 项目",
        }

    export_dir = work_dir / "export"
    first = export_project(completed.project, export_dir)
    second = export_project(completed.project, export_dir)
    files = sorted(export_dir.iterdir())
    json_path = first["json"]
    markdown_path = first["markdown"]
    json_valid = False
    markdown_sections_present = False
    try:
        payload = json.loads(
            json_path.read_text(encoding="utf-8")
        )
        json_valid = (
            payload.get("export_schema_version") == 1
            and bool(payload.get("project_id"))
            and isinstance(payload.get("storyboard"), dict)
        )
    except (OSError, json.JSONDecodeError):
        json_valid = False
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
        markdown_sections_present = all(
            section in markdown
            for section in (
                "## 1. 原始需求",
                "## 4. 分镜与提示词",
                "## 5. 校验报告",
            )
        )
    except OSError:
        markdown_sections_present = False

    suffixes = Counter(file.suffix for file in files)
    unique_files = (
        len(files) == 4
        and len({file.stem for file in files}) == 2
        and suffixes.get(".json") == 2
        and suffixes.get(".md") == 2
        and first["json"] != second["json"]
        and first["markdown"] != second["markdown"]
    )
    passed = bool(
        json_valid
        and markdown_sections_present
        and unique_files
        and len(first) == 2
        and len(second) == 2
    )
    return {
        "passed": passed,
        "file_count": len(files),
        "json_valid": json_valid,
        "markdown_sections_present": markdown_sections_present,
        "unique_files": unique_files,
        "project_id": completed.project.get("project_id"),
        "json_file": json_path.name,
        "markdown_file": markdown_path.name,
    }


def _security_check(report_text: str, report_json: str) -> dict[str, Any]:
    combined = report_text + "\n" + report_json
    matches = SECRET_PATTERN.findall(combined)
    return {
        "passed": not matches,
        "secret_like_match_count": len(matches),
        "llm_mode": "scripted_fake_llm",
        "real_api_calls": 0,
    }


def run_evaluation(
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="aigc_eval_") as temp:
        work_dir = Path(temp)
        results = [run_case(case, work_dir) for case in CASES]
        export_verification = _verify_export(results, work_dir)
        metrics = _compute_metrics(results)
        metrics["total_duration_ms"] = round(
            (time.perf_counter() - started) * 1000, 2
        )

        report: dict[str, Any] = {
            "schema_version": 1,
            "generated_at": _now(),
            "python_version": platform.python_version(),
            "mode": (
                "确定性工具 + 脚本化 FakeLLM；"
                "不调用真实 DeepSeek API"
            ),
            "metrics": metrics,
            "export_verification": export_verification,
            "security_check": {
                "passed": True,
                "secret_like_match_count": 0,
                "llm_mode": "scripted_fake_llm",
                "real_api_calls": 0,
            },
            "cases": [
                item.to_dict()
                for item in results
            ],
            "limitations": list(LIMITATIONS),
        }
        report_json = json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        from evaluation.report import render_markdown

        report_text = render_markdown(report)
        report["security_check"] = _security_check(
            report_text,
            report_json,
        )

        if output_dir is not None:
            paths = write_report(report, output_dir)
            report["report_paths"] = {
                "json": str(paths["json"]),
                "markdown": str(paths["markdown"]),
            }
        return report
