"""Render the evaluation report as Markdown and JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _kind_label(kind: str) -> str:
    return {
        "workflow_deterministic": "确定性工作流",
        "workflow_fake_llm": "脚本化 LLM 工作流",
        "tool": "工具级",
    }.get(kind, kind)


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines: list[str] = [
        "# AIGC 智能创作工作流 Agent 评测报告",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- Python：{report['python_version']}",
        f"- 运行模式：{report['mode']}",
        f"- 用例总数：{metrics['total_cases']}",
        f"- 期望匹配：{metrics['suite_passed']} / {metrics['total_cases']}",
        "",
        "> 本报告由 `evaluation` 包自动生成。默认使用确定性工具和",
        "> 脚本化 FakeLLM，不调用真实 DeepSeek API，不消耗模型额度。",
        "> 脚本化模型只验证工作流、校验和修正逻辑，不代表真实模型",
        "> 的创作质量。",
        "",
        "## 1. 评测方法",
        "",
        "每条用例在独立的临时 SQLite 数据库中运行，记录最终状态、",
        "任务轨迹、四类校验结果、修正记录、模型调用次数和持久化状态。",
        "工作流用例检查：",
        "",
        "- 是否按预期完成、失败或在修正上限处停止；",
        "- 是否只执行必要的节点，不在早期失败后继续调用下游工具；",
        "- 四类校验结果是否符合预期；",
        "- 修正次数、修正原因和修正状态是否符合预期；",
        "- 项目是否以相同状态写入 SQLite；",
        "- 脚本化模型调用次数是否与预期一致。",
        "",
        "工具级用例直接调用时长、场景和提示词检查器，用于覆盖确定性",
        "占位分镜无法自然产生的空档、重叠、重复场景和提示词冲突。",
        "",
        "## 2. 总体指标",
        "",
        "| 指标 | 值 |",
        "| --- | --- |",
        f"| 用例总数 | {metrics['total_cases']} |",
        f"| 期望匹配 | {metrics['suite_passed']} |",
        f"| 期望不匹配 | {metrics['suite_failed']} |",
        f"| 工作流用例 | {metrics['workflow_cases']} |",
        f"| 确定性工作流 | {metrics['deterministic_cases']} |",
        f"| 脚本化 LLM 工作流 | {metrics['fake_llm_cases']} |",
        f"| 工具级用例 | {metrics['tool_cases']} |",
        f"| 首次通过 | {metrics['first_pass_cases']} / {metrics['workflow_cases']} ({_pct(metrics['first_pass_rate'])}) |",
        f"| 修正后通过 | {metrics['recovered_cases']} |",
        f"| 达到修正上限 | {metrics['validation_failed_cases']} |",
        f"| 早期失败 | {metrics['early_failed_cases']} |",
        f"| 预期内最终失败 | {metrics['intentional_failure_cases']} |",
        f"| 平均修正次数 | {metrics['avg_revisions']:.2f} |",
        f"| 修正恢复率（全部修正用例） | {metrics['recovered_cases']} / {metrics['revision_cases']} ({_pct(metrics['recovery_rate'])}) |",
        f"| 修正恢复率（修正响应有效） | {metrics['recovered_cases']} / {metrics['valid_revision_cases']} ({_pct(metrics['content_recovery_rate'])}) |",
        f"| SQLite 状态一致 | {metrics['persistence_ok_cases']} / {metrics['workflow_cases']} |",
        f"| 脚本化模型调用 | {metrics['llm_calls']} |",
        f"| 脚本化合成 tokens | {metrics['llm_tokens']} |",
        f"| 平均用例耗时 | {metrics['avg_duration_ms']:.1f} ms |",
        f"| P95 用例耗时 | {metrics['p95_duration_ms']:.1f} ms |",
        "",
        "最终状态分布：",
        "",
        "| 状态 | 数量 |",
        "| --- | --- |",
    ]
    for status, count in sorted(metrics["status_counts"].items()):
        lines.append(f"| {_md(status)} | {count} |")

    lines.extend(
        [
            "",
            "## 3. 逐用例结果",
            "",
            "| ID | 用例 | 类型 | 期望状态 | 实际状态 | 修正 | 结果 | 耗时(ms) |",
            "| --- | --- | --- | --- | --- | ---: | --- | ---: |",
        ]
    )
    for item in report["cases"]:
        case = item["case"]
        obs = item["observation"]
        result = "PASS" if item["passed"] else "FAIL"
        lines.append(
            "| {id} | {name} | {kind} | {expected} | {actual} | {revisions} | {result} | {duration} |".format(
                id=_md(case["case_id"]),
                name=_md(case["name"]),
                kind=_md(_kind_label(case["kind"])),
                expected=_md(case["expected"]["final_status"]),
                actual=_md(obs["final_status"]),
                revisions=obs["revision_count"],
                result=result,
                duration=f"{obs['duration_ms']:.1f}",
            )
        )

    lines.extend(
        [
            "",
            "### 3.1 四类校验的最终结果",
            "",
            "| ID | 时长 | 场景覆盖 | 主体一致性 | 提示词质量 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in report["cases"]:
        if item["case"]["kind"] == "tool":
            continue
        checks = item["observation"]["check_results"]
        cells = []
        for name in ("duration", "scene", "consistency", "prompt"):
            value = checks.get(name)
            cells.append("通过" if value is True else "未通过" if value is False else "未执行")
        lines.append(
            f"| {_md(item['case']['case_id'])} | "
            + " | ".join(cells)
            + " |"
        )

    lines.extend(
        [
            "",
            "### 3.2 触发修正的问题类别",
            "",
            "按修正记录中的关键词统计，一条用例可能归入多个类别。",
            "",
            "| 类别 | 用例数 |",
            "| --- | ---: |",
        ]
    )
    for category, count in metrics["revision_reason_categories"].items():
        lines.append(f"| {_md(category)} | {count} |")

    lines.extend(
        [
            "",
            "### 3.3 最终报告中的校验失败",
            "",
            "| 检查 | 未通过用例数 |",
            "| --- | ---: |",
            f"| 时长 | {metrics['check_failures']['duration']} |",
            f"| 场景覆盖 | {metrics['check_failures']['scene']} |",
            f"| 主体一致性 | {metrics['check_failures']['consistency']} |",
            f"| 提示词质量 | {metrics['check_failures']['prompt']} |",
            "",
            "这里只统计最终报告；初始失败后修正通过的用例见 3.2。",
            "",
            "## 4. 用例目录",
            "",
        ]
    )
    for item in report["cases"]:
        case = item["case"]
        lines.extend(
            [
                f"### {case['case_id']} · {case['name']}",
                "",
                f"- 类型：{_kind_label(case['kind'])}",
                f"- 类别：{case['category']}",
                f"- 说明：{case['description']}",
                f"- 目标模型：{case['target_video_model']}",
                f"- 最大修正次数：{case['max_revisions']}",
                "",
            ]
        )

    lines.extend(
        [
            "## 5. 失败分析",
            "",
            "本节区分两类失败：",
            "",
            "1. **预期内的任务失败**：系统按设计停止，并在报告中保留真实错误；",
            "2. **评测期望不匹配**：系统行为与用例预期不一致，属于需要修复的问题。",
            "",
            "### 5.1 预期内的任务失败",
            "",
        ]
    )
    intentional = [
        item
        for item in report["cases"]
        if item["case"]["expected"]["final_status"] in {"failed", "validation_failed"}
    ]
    if not intentional:
        lines.append("无。")
    else:
        lines.extend(
            [
                "| ID | 最终状态 | 实际错误摘要 | 判定 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in intentional:
            errors = item["observation"]["errors"]
            summary = errors[0] if errors else "无错误文本"
            lines.append(
                f"| {_md(item['case']['case_id'])} | "
                f"{_md(item['observation']['final_status'])} | "
                f"{_md(summary)} | 预期内，系统未伪造成功 |"
            )
        lines.extend(
            [
                "",
                "这些用例的失败是评测设计的一部分：系统应在模型输出非法、",
                "连续修正仍无法满足约束或修正工具失败时明确停止，而不是",
                "把未通过的结果标记为完成。",
                "",
            ]
        )

    tool_items = [
        item for item in report["cases"] if item["case"]["kind"] == "tool"
    ]
    lines.extend(
        [
            "### 5.2 工具级预期失败",
            "",
            "| ID | 检查器错误 | 检查器警告 |",
            "| --- | --- | --- |",
        ]
    )
    for item in tool_items:
        obs = item["observation"]
        lines.append(
            f"| {_md(item['case']['case_id'])} | "
            f"{_md('；'.join(obs['tool_errors']) or '无')} | "
            f"{_md('；'.join(obs['tool_warnings']) or '无')} |"
        )
    lines.extend(
        [
            "",
            "工具级用例验证的是检查器能否准确报错，不代表工作流失败。",
            "",
            "### 5.3 评测期望不匹配",
            "",
        ]
    )
    mismatched = [item for item in report["cases"] if item["mismatches"]]
    if not mismatched:
        lines.append("无。20 条用例的实际行为与预期一致。")
    else:
        for item in mismatched:
            lines.extend(
                [
                    f"#### {item['case']['case_id']} · {item['case']['name']}",
                    "",
                ]
            )
            for mismatch in item["mismatches"]:
                lines.append(f"- {mismatch}")
            lines.append("")

    lines.extend(
        [
            "",
            "## 6. 导出、持久化与安全",
            "",
            "### 6.1 导出验证",
            "",
            f"- 结果：{'通过' if report['export_verification']['passed'] else '失败'}",
            f"- 导出文件数：{report['export_verification'].get('file_count', 0)}",
            f"- JSON 可解析：{report['export_verification'].get('json_valid')}",
            f"- Markdown 关键章节存在：{report['export_verification'].get('markdown_sections_present')}",
            f"- 重复导出文件名唯一：{report['export_verification'].get('unique_files')}",
            f"- 项目：{report['export_verification'].get('project_id') or '无'}",
            "",
            "### 6.2 持久化",
            "",
            f"- 工作流用例状态一致：{metrics['persistence_ok_cases']} / {metrics['workflow_cases']}",
            "",
            "### 6.3 安全",
            "",
            f"- 密钥样式字符串扫描：{'通过' if report['security_check']['passed'] else '失败'}",
            f"- 命中数量：{report['security_check']['secret_like_match_count']}",
            f"- 运行方式：{report['security_check']['llm_mode']}",
            f"- 真实 API 调用：{report['security_check']['real_api_calls']}",
            "",
            "评测报告不读取 `.env`，不创建真实 OpenAI 客户端；",
            "模型调用全部由注入的 FakeChatClient 处理。",
            "",
            "## 7. 局限性",
            "",
        ]
    )
    for limitation in report["limitations"]:
        lines.append(f"- {limitation}")

    lines.extend(
        [
            "",
            "## 8. 复现",
            "",
            "```powershell",
            "cd D:\\Projects\\aigc_creative_agent",
            ".\\\\.venv\\\\Scripts\\\\python.exe -m evaluation --output-dir output/evaluation",
            "```",
            "",
            "测试套件中的 `tests/test_evaluation_suite.py` 也会运行同一套用例，",
            "并断言 20 条用例全部符合预期。",
            "",
            "## 9. 结论",
            "",
            (
                "本套评测验证了确定性工作流、脚本化 LLM 工作流、四类校验、"
                "最多两次修正、早期失败、修正上限、SQLite 持久化、导出和"
                "安全边界。测试默认不调用真实模型；真实模型质量仍需单独的"
                "人工评审和真实 API 回归。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_report(
    report: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "evaluation_report.json"
    markdown_path = directory / "evaluation_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(
        render_markdown(report),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": markdown_path}
