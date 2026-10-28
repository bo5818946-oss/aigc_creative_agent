"""Phase 1 command-line entry point.

Examples:
    python main.py --demo
    python main.py --show-project <PROJECT_ID>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from pydantic import ValidationError

from config.settings import DB_PATH
from database.repository import ProjectRepository
from schemas.project import CreativeRequirement
from services.llm_service import LLMConfigurationError, LLMService
from services.project_service import CreativeProjectService


DEMO_REQUIREMENT: dict[str, Any] = {
    "project_name": "30秒汽车品牌广告",
    "content_type": "汽车商业广告",
    "subject": "一辆银灰色流线型纯电轿车",
    "target_audience": "关注科技感与驾驶质感的年轻消费者",
    "duration_seconds": 30,
    "aspect_ratio": "16:9",
    "visual_style": "电影感商业广告，冷暖对比光影，金属质感",
    "scene_requirements": ["森林", "草原", "沙漠", "雪地", "城市"],
    "camera_language": "航拍、低机位跟拍与车身细节特写结合",
    "consistency_constraints": [
        "全片使用同一辆银灰色流线型纯电轿车，车型与车身设计特征保持一致",
        "明确车头与车尾方向，车辆前进方向始终一致",
        "避免镜头之间出现相互矛盾的车辆运动描述",
    ],
    "transition_requirements": "以车辆运动方向为依据的自然动势转场",
    "output_formats": ["markdown", "json"],
    "notes": "第一阶段演示：验证真实工具调用、执行轨迹和 SQLite 持久化。",
}


def _prompt(label: str, default: str) -> str:
    raw = input(f"{label} [{default}]: ").strip()
    return raw or default


def _split_list(raw: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"[,，、;；]", raw)
        if item.strip()
    ]


def _build_requirement(args: argparse.Namespace) -> CreativeRequirement:
    if args.demo:
        return CreativeRequirement.model_validate(DEMO_REQUIREMENT)

    project_name = args.project_name or _prompt("项目名称", "30秒汽车品牌广告")
    content_type = args.content_type or _prompt("内容类型", "汽车商业广告")
    subject = args.subject or _prompt(
        "主体描述", "一辆银灰色流线型纯电轿车"
    )
    duration_raw = (
        str(args.duration)
        if args.duration is not None
        else _prompt("目标时长（秒）", "30")
    )
    scenes_raw = args.scenes or _prompt(
        "场景要求（逗号分隔）", "森林,草原,沙漠,雪地,城市"
    )
    style = args.style or _prompt(
        "视觉风格", "电影感商业广告，冷暖对比光影，金属质感"
    )
    constraints_raw = args.constraints or _prompt(
        "主体一致性约束（逗号分隔）", "保持同一辆车的外观与设计特征一致"
    )

    return CreativeRequirement.model_validate(
        {
            "project_name": project_name,
            "content_type": content_type,
            "subject": subject,
            "target_audience": "关注科技感与驾驶质感的年轻消费者",
            "duration_seconds": float(duration_raw),
            "aspect_ratio": "16:9",
            "visual_style": style,
            "scene_requirements": _split_list(scenes_raw),
            "camera_language": "航拍、低机位跟拍与车身细节特写结合",
            "consistency_constraints": _split_list(constraints_raw),
            "transition_requirements": "以车辆运动方向为依据的自然动势转场",
            "output_formats": ["markdown", "json"],
            "notes": "",
        }
    )


def _print_run_result(
    result: dict[str, Any],
    requirement: CreativeRequirement,
) -> None:
    print("=" * 72)
    print(f"项目名称：{requirement.project_name}")
    print(f"项目 ID：{result['project_id']}")
    print(f"执行 ID：{result['execution_id']}")
    print(f"最终状态：{result.get('final_status', 'unknown')}")
    print(f"数据库：{DB_PATH}")

    usage = result.get("llm_usage") or {}
    if usage:
        print("\n模型调用：")
        print(
            f"  调用 {usage.get('calls', 0)} 次 / "
            f"重试 {usage.get('retries', 0)} 次 / "
            f"错误 {usage.get('errors', 0)} 次"
        )
        print(
            f"  tokens: prompt {usage.get('prompt_tokens', 0)} + "
            f"completion {usage.get('completion_tokens', 0)} = "
            f"{usage.get('total_tokens', 0)}"
        )

    if requirement.pending_confirmations:
        print("\n待确认项：")
        for item in requirement.pending_confirmations:
            print(f"  - {item}")

    print("\n任务计划：")
    for task in result.get("task_plan", []):
        print(
            f"  {task.get('task_id')}: {task.get('name')} "
            f"[{task.get('status')}]"
        )

    storyboard = result.get("storyboard") or {}
    shots = storyboard.get("shots", [])
    print(
        f"\n分镜（{len(shots)} 个，生成方式："
        f"{storyboard.get('generation_method', 'unknown')}，"
        f"提示词方式：{storyboard.get('prompt_generation_method') or '未生成'}）："
    )
    for shot in shots:
        print(
            f"  镜头 {shot.get('shot_number')}: "
            f"{shot.get('start_seconds')}s - {shot.get('end_seconds')}s "
            f"| {shot.get('scene')}"
        )

    prompted = [
        shot
        for shot in shots
        if shot.get("image_prompt") and shot.get("video_prompt")
    ]
    print(f"\n提示词：{len(prompted)}/{len(shots)} 个镜头已生成图片和视频提示词。")
    if prompted:
        preview = prompted[0].get("video_prompt", "")
        print(
            "  镜头 1 视频提示词预览："
            f"{preview[:160]}{'...' if len(preview) > 160 else ''}"
        )

    report = result.get("validation_report")
    if report is not None:
        print("\n综合校验：")
        duration = report.get("duration") or {}
        scene = report.get("scene") or {}
        consistency = report.get("consistency") or {}
        prompt = report.get("prompt") or {}
        print(
            f"  时长：{'通过' if duration.get('passed') else '未通过'} "
            f"(目标 {duration.get('target_duration_seconds')} 秒 / "
            f"实际 {duration.get('timeline_end_seconds')} 秒)"
        )
        print(
            f"  场景覆盖：{'通过' if scene.get('passed') else '未通过'} "
            f"({scene.get('coverage_ratio', 0):.0%})，"
            f"缺失：{scene.get('missing_scenes') or '无'}"
        )
        print(
            f"  主体一致性："
            f"{'通过' if consistency.get('passed') else '未通过'}，"
            f"错误 {len(consistency.get('errors', []))} 项"
        )
        print(
            f"  提示词质量："
            f"{'通过' if prompt.get('passed') else '未通过'}，"
            f"错误 {len(prompt.get('errors', []))} 项"
        )
        print(f"  综合结果：{'通过' if report.get('passed') else '未通过'}")
        if report.get("errors"):
            print("  主要问题：")
            for error in report.get("errors", [])[:10]:
                print(f"  - {error}")

    revision_count = result.get("revision_count", 0)
    revision_history = result.get("revision_history") or []
    if revision_count or revision_history:
        print(f"\n自动修正：{revision_count} 次")
        for record in revision_history:
            print(
                f"  第 {record.get('revision_number')} 次 "
                f"[{record.get('status')}] {record.get('tool')}"
            )

    print("\n执行轨迹：")
    for event in result.get("trace_events", []):
        tool = event.get("tool_name") or "无工具"
        print(
            f"  {event.get('node_name')} [{event.get('status')}] "
            f"工具：{tool}"
        )
        if event.get("error"):
            print(f"    错误：{event.get('error')}")

    errors = result.get("errors") or []
    if errors:
        print("\n未解决的问题：")
        for error in errors:
            print(f"  - {error}")

    print("\n查看持久化记录：")
    print(f"  python main.py --show-project {result['project_id']}")


def _show_project(project_id: str) -> int:
    repository = ProjectRepository(DB_PATH)
    project = repository.get_project(project_id)
    if project is None:
        print(f"未找到项目：{project_id}")
        return 2
    print(json.dumps(project, ensure_ascii=False, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AIGC 智能创作工作流 Agent（第一阶段 MVP）"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="使用内置的 30 秒汽车广告需求运行演示",
    )
    parser.add_argument(
        "--show-project",
        metavar="PROJECT_ID",
        help="读取并打印已保存的创作项目",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="使用 DeepSeek 解析需求（需要在 .env 中配置密钥）",
    )
    parser.add_argument(
        "--requirement-text",
        help="自然语言创作需求；配合 --use-llm 使用，结构化字段作为兜底",
    )
    parser.add_argument("--project-name")
    parser.add_argument("--content-type")
    parser.add_argument("--subject")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--scenes", help="场景列表，逗号分隔")
    parser.add_argument("--style")
    parser.add_argument("--constraints", help="一致性约束，逗号分隔")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.show_project:
        return _show_project(args.show_project)

    try:
        requirement = _build_requirement(args)
    except (ValidationError, ValueError) as exc:
        print(f"需求数据无效：{exc}", file=sys.stderr)
        return 2

    llm_service: LLMService | None = None
    if args.use_llm:
        try:
            llm_service = LLMService.from_env()
        except LLMConfigurationError as exc:
            print(f"DeepSeek 配置失败：{exc}", file=sys.stderr)
            return 2

    mode = "DeepSeek 需求解析" if llm_service is not None else "第一阶段：无真实模型调用"
    print(f"正在运行 LangGraph 工作流（{mode}）...")
    repository = ProjectRepository(DB_PATH)
    service = CreativeProjectService(repository, llm_service=llm_service)
    try:
        result = service.run(
            requirement,
            raw_requirement=args.requirement_text,
        )
    except RuntimeError as exc:
        print(f"工作流执行失败：{exc}", file=sys.stderr)
        return 1

    _print_run_result(result, requirement)
    return 0 if result.get("final_status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
