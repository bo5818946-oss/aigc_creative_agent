"""The 20 reproducible evaluation cases.

Coverage:
- deterministic workflow runs across durations, scene counts, defaults, and
  target-model profiles;
- scripted-LLM workflow runs covering first-pass success, duration/scene/
  direction/prompt recovery, revision exhaustion, malformed model output, and
  revision failure;
- direct tool cases for gap/overlap, duplicate/missing scenes, and prompt
  conflicts that the deterministic storyboard path cannot naturally produce.

The suite never calls a real provider. All model calls go through
``evaluation.fakes.FakeChatClient``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from evaluation.models import EvaluationCase, ExpectedOutcome, ToolOutcome
from schemas.cinematography import (
    CameraAngle,
    CameraMovement,
    CinematographySpec,
    ColorGrade,
    LightingStyle,
    ScreenDirection,
    ShotSize,
    TransitionType,
)
from schemas.storyboard import Shot
from tools.duration_checker import check_duration
from tools.prompt_checker import check_prompt_quality
from tools.scene_checker import check_scene_coverage

VEHICLE_KEYWORDS = (
    "汽车",
    "轿车",
    "suv",
    "跑车",
    "卡车",
    "车辆",
    "车头",
    "车尾",
)


def _requirement(
    project_name: str,
    content_type: str,
    subject: str,
    duration_seconds: float,
    scenes: Sequence[str],
    *,
    constraints: Sequence[str] = (),
    target_audience: str = "关注科技感与品质感的年轻消费者",
    visual_style: str = "电影感商业广告，冷暖对比光影，细节质感",
    camera_language: str = "航拍、低机位跟拍与细节特写结合",
    transition: str = "自然动势转场",
) -> dict[str, Any]:
    return {
        "project_name": project_name,
        "content_type": content_type,
        "subject": subject,
        "target_audience": target_audience,
        "duration_seconds": float(duration_seconds),
        "aspect_ratio": "16:9",
        "visual_style": visual_style,
        "scene_requirements": list(scenes),
        "camera_language": camera_language,
        "consistency_constraints": list(constraints),
        "transition_requirements": transition,
        "output_formats": ["markdown", "json"],
        "notes": "20 条评测用例之一。",
    }


def _is_vehicle(requirement: Mapping[str, Any]) -> bool:
    text = " ".join(
        [
            str(requirement.get("content_type", "")),
            str(requirement.get("subject", "")),
            *[str(item) for item in requirement.get("consistency_constraints", [])],
        ]
    ).casefold()
    return any(keyword in text for keyword in VEHICLE_KEYWORDS)


def _action_text(
    subject: str,
    direction: str,
    *,
    start: bool,
) -> str:
    if direction == "right_to_left":
        return (
            f"{subject}从画面外进入，向左行驶"
            if start
            else f"{subject}继续向左行驶到画面中央"
        )
    if direction == "static":
        return (
            f"{subject}停在画面中央"
            if start
            else f"{subject}保持静止，细节清晰"
        )
    if direction == "toward_camera":
        return (
            f"{subject}从远处朝向镜头驶来"
            if start
            else f"{subject}在镜头前减速"
        )
    if direction == "away_from_camera":
        return (
            f"{subject}从镜头前向远处驶去"
            if start
            else f"{subject}逐渐远离镜头"
        )
    return (
        f"{subject}从画面外进入，向右行驶"
        if start
        else f"{subject}继续向右行驶到画面中央"
    )


def _storyboard_payload(
    requirement: Mapping[str, Any],
    *,
    scenes: Sequence[str] | None = None,
    total_seconds: float | None = None,
    direction: str = "left_to_right",
    direction_overrides: Mapping[int, str] | None = None,
    include_actions: bool = True,
) -> dict[str, Any]:
    """Build a scripted LLM storyboard with optional deliberate defects."""

    scene_list = list(
        scenes
        if scenes is not None
        else requirement.get("scene_requirements", [])
    )
    if not scene_list:
        scene_list = ["核心展示场景"]
    total = float(
        total_seconds
        if total_seconds is not None
        else requirement["duration_seconds"]
    )
    subject = str(requirement["subject"])
    vehicle = _is_vehicle(requirement)
    constraints = [
        str(item) for item in requirement.get("consistency_constraints", [])
    ]
    overrides = direction_overrides or {}
    step = total / len(scene_list)
    shots: list[dict[str, Any]] = []

    for index, scene in enumerate(scene_list):
        shot_direction = overrides.get(index, direction)
        start = round(index * step, 3)
        end = round(total if index == len(scene_list) - 1 else (index + 1) * step, 3)
        subject_state = f"{subject}，保持统一外观"
        if vehicle:
            if shot_direction == "right_to_left":
                subject_state += "，车头朝左"
            elif shot_direction in {"left_to_right", "toward_camera"}:
                subject_state += "，车头朝右"
        shots.append(
            {
                "shot_number": index + 1,
                "shot_id": f"SHOT-{index + 1:03d}",
                "start_seconds": start,
                "end_seconds": end,
                "scene": scene,
                "narrative_purpose": f"展示{scene}场景与主体",
                "action_start": (
                    _action_text(subject, shot_direction, start=True)
                    if include_actions
                    else ""
                ),
                "action_end": (
                    _action_text(subject, shot_direction, start=False)
                    if include_actions
                    else ""
                ),
                "subject_state": subject_state,
                "continuity_locks": constraints,
                "cinematography": {
                    "shot_size": (
                        "wide_shot" if index == 0 else "medium_shot"
                    ),
                    "camera_angle": "low_angle",
                    "camera_movement": (
                        "push_in" if index == 0 else "static"
                    ),
                    "lens": "35mm",
                    "composition": "rule_of_thirds",
                    "lighting_style": (
                        "golden_hour" if index % 2 == 0 else "soft_window"
                    ),
                    "color_grade": "teal_orange",
                    "transition": "hard_cut",
                    "vfx": [],
                    "screen_direction": shot_direction,
                },
                "sound": "环境声，无对白",
                "negative_prompt": "无字幕，无水印，无 Logo",
            }
        )
    return {"generation_method": "llm", "shots": shots}


def _requirement_response(
    requirement: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(requirement)
    payload["pending_confirmations"] = []
    return payload


def _workflow_case(
    case_id: str,
    name: str,
    category: str,
    kind: str,
    description: str,
    requirement: Mapping[str, Any],
    expected: ExpectedOutcome,
    *,
    responses: Sequence[Any] = (),
    max_revisions: int = 2,
    target_video_model: str = "generic",
    duration_tolerance_seconds: float = 0.5,
) -> EvaluationCase:
    return EvaluationCase(
        case_id=case_id,
        name=name,
        category=category,
        kind=kind,
        description=description,
        expected=expected,
        requirement=dict(requirement),
        responses=tuple(responses),
        max_revisions=max_revisions,
        target_video_model=target_video_model,
        duration_tolerance_seconds=duration_tolerance_seconds,
    )


# ---------------------------------------------------------------------------
# Deterministic workflow cases
# ---------------------------------------------------------------------------

_DEMO = _requirement(
    "30秒汽车品牌广告",
    "汽车商业广告",
    "一辆银灰色流线型纯电轿车",
    30,
    ["森林", "草原", "沙漠", "雪地", "城市"],
    constraints=[
        "全片使用同一辆银灰色流线型纯电轿车，车型与车身设计特征保持一致",
        "明确车头与车尾方向，车辆前进方向始终一致",
        "避免镜头之间出现相互矛盾的车辆运动描述",
    ],
    visual_style="电影感商业广告，冷暖对比光影，金属质感",
    camera_language="航拍、低机位跟拍与车身细节特写结合",
)

_COFFEE = _requirement(
    "15秒手冲咖啡短片",
    "咖啡品牌短视频",
    "一杯手冲咖啡",
    15,
    ["清晨厨房", "咖啡豆特写", "窗边品尝"],
    constraints=[
        "全片使用同一只白色陶瓷咖啡杯，杯型与杯沿设计保持一致",
        "咖啡液面与杯身外观保持稳定",
    ],
    visual_style="温暖自然光，浅景深，生活质感",
    camera_language="固定机位与缓慢推镜结合",
    transition="自然硬切",
)

_TRAVEL = _requirement(
    "60秒山野旅行纪录短片",
    "旅行纪录短片",
    "一位背着橙色登山包的年轻徒步者",
    60,
    ["山脚", "溪流", "松林", "山脊", "营地", "日出"],
    constraints=[
        "全片使用同一件橙色登山包与同一套深灰户外服装",
        "人物外观与装备特征保持一致",
    ],
    visual_style="自然纪录风格，清晨冷调与日出暖调过渡",
    camera_language="手持跟拍、航拍与远景结合",
    transition="动作衔接与自然叠化",
)

_SINGLE_SCENE = _requirement(
    "10秒香水瓶产品特写",
    "香水产品广告",
    "一瓶透明方形玻璃香水瓶，银色瓶盖",
    10,
    ["黑色镜面台面"],
    constraints=[
        "全片使用同一瓶透明方形玻璃香水瓶，瓶身与瓶盖设计一致",
        "避免瓶身颜色与折射质感变化",
    ],
    visual_style="极简产品摄影，黑色背景，冷静高光",
    camera_language="固定机位与微距细节特写",
    transition="硬切",
)

_DEFAULT_SCENES = _requirement(
    "无场景清单的测试项目",
    "产品广告",
    "一款白色无线耳机充电盒",
    12,
    [],
    constraints=[
        "全片使用同一款白色无线耳机充电盒，外观与开合结构一致"
    ],
    visual_style="干净的产品演示光线",
    camera_language="固定机位与缓慢环绕",
    transition="硬切",
)

_DEFAULT_CONSTRAINTS = _requirement(
    "无一致性约束的测试项目",
    "箱包产品广告",
    "一只棕色皮革手提包",
    18,
    ["工作室", "街角", "室内"],
    constraints=[],
    visual_style="温暖皮革质感，柔和侧光",
    camera_language="固定机位与细节特写",
    transition="自然硬切",
)

_NON_VEHICLE = _requirement(
    "20秒智能手表产品广告",
    "智能手表广告",
    "一块银色方形智能手表",
    20,
    ["城市天台", "手腕特写", "跑步场景", "夜景街道"],
    constraints=[
        "全片使用同一块银色方形智能手表，表盘与表带设计保持一致",
        "避免表盘颜色与表带材质变化",
    ],
    visual_style="科技感产品广告，冷调城市光线",
    camera_language="微距特写、环绕与运动跟拍结合",
    transition="动作匹配剪辑",
)

_DETERMINISTIC_CASES = [
    _workflow_case(
        "det-01",
        "30 秒汽车广告确定性基线",
        "happy_path",
        "workflow_deterministic",
        "五场景、30 秒，验证确定性分镜、提示词和四类校验一次通过。",
        _DEMO,
        ExpectedOutcome(
            final_status="completed",
            revision_count=0,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=0,
        ),
    ),
    _workflow_case(
        "det-02",
        "15 秒三场景非车辆主体",
        "happy_path",
        "workflow_deterministic",
        "短时长、非车辆主体，验证时长切分与主体一致性检查。",
        _COFFEE,
        ExpectedOutcome(
            final_status="completed",
            revision_count=0,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=0,
        ),
    ),
    _workflow_case(
        "det-03",
        "60 秒六场景旅行短片",
        "happy_path",
        "workflow_deterministic",
        "长时长与六场景，验证边界时长和场景覆盖。",
        _TRAVEL,
        ExpectedOutcome(
            final_status="completed",
            revision_count=0,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=0,
        ),
    ),
    _workflow_case(
        "det-04",
        "10 秒单场景产品特写",
        "happy_path",
        "workflow_deterministic",
        "单场景、短时长，验证最小场景集合。",
        _SINGLE_SCENE,
        ExpectedOutcome(
            final_status="completed",
            revision_count=0,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=0,
        ),
    ),
    _workflow_case(
        "det-05",
        "缺失场景清单时使用安全默认值",
        "input_default",
        "workflow_deterministic",
        "需求未提供场景，Pydantic 补占位场景并记录待确认项。",
        _DEFAULT_SCENES,
        ExpectedOutcome(
            final_status="completed",
            revision_count=0,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=0,
            pending_confirmation_min=1,
        ),
    ),
    _workflow_case(
        "det-06",
        "缺失一致性约束时使用安全默认值",
        "input_default",
        "workflow_deterministic",
        "需求未提供一致性约束，系统补通用约束并记录待确认项。",
        _DEFAULT_CONSTRAINTS,
        ExpectedOutcome(
            final_status="completed",
            revision_count=0,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=0,
            pending_confirmation_min=1,
        ),
    ),
    _workflow_case(
        "det-07",
        "非车辆主体的四场景产品广告",
        "happy_path",
        "workflow_deterministic",
        "智能手表主体，验证非车辆路径不误报方向问题。",
        _NON_VEHICLE,
        ExpectedOutcome(
            final_status="completed",
            revision_count=0,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=0,
        ),
    ),
    _workflow_case(
        "det-08",
        "Runway 目标模型仅产生警告",
        "model_profile",
        "workflow_deterministic",
        "英文偏好模型产生语言警告，但不应把警告伪装成错误或触发修正。",
        _DEMO,
        ExpectedOutcome(
            final_status="completed",
            revision_count=0,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=0,
            warning_count_min=5,
        ),
        target_video_model="runway",
    ),
]


# ---------------------------------------------------------------------------
# Scripted-LLM workflow cases
# ---------------------------------------------------------------------------

_LLM_BASE = _requirement(
    "LLM 汽车广告评测",
    "汽车商业广告",
    "一辆哑光黑色纯电 SUV",
    30,
    ["森林", "草原", "沙漠", "雪地", "城市"],
    constraints=[
        "全片使用同一辆哑光黑色纯电 SUV，车头始终朝右",
        "车辆前进方向始终一致",
    ],
    visual_style="电影感商业广告，冷暖对比光影",
    camera_language="航拍与低机位跟拍结合",
)

def _director_payload(
    requirement: Mapping[str, Any],
    *,
    scenes: Sequence[str] | None = None,
) -> dict[str, Any]:
    scene_list = list(scenes or requirement.get("scene_requirements", []))
    subject = str(requirement["subject"])
    shot_prompts = [
        {
            "shot_number": index,
            "scene": scene,
            "image_prompt": (
                f"镜头 {index}：{subject}位于{scene}，按分镜方向行驶，"
                "电影级汽车摄影，真实金属反射，35mm 镜头。"
            ),
            "video_prompt": (
                f"镜头 {index}：{subject}沿{scene}道路持续前进，"
                "轮胎接地，近景参照物快速后退，摄影机短暂落后再追赶。"
            ),
            "negative_prompt": "无字幕，无水印，无 Logo",
        }
        for index, scene in enumerate(scene_list, start=1)
    ]
    duration = float(requirement["duration_seconds"])
    return {
        "title": "评测导演版",
        "global_prompt": (
            f"生成一支 {duration:g} 秒、16:9 的电影级商业广告。"
            f"全片只出现同一主体：{subject}。车头始终指向实际前进方向，"
            "轮胎持续接地，车身比例、颜色和设计特征不随场景变化。"
            "按分镜顺序穿越所有场景，每个场景都通过近景参照物、"
            "道路标线、轮胎旋转和摄影机追赶证明真实速度。"
            "场景之间使用动作匹配、前景遮挡或甩镜完成转场，"
            "切点前后保持同一方向、同一车身比例和连续运动趋势。"
            "摄影机不要全程固定距离，要先落后再追赶，"
            "用近景、中景、远景的速度差建立运动视差。"
            "光线、色彩和环境反射随地貌连续变化，但主体设计不变。"
            "加入动力系统、风噪、轮胎接地和环境空间变化的声音层次。"
            "结尾完成清晰的英雄镜头，不出现品牌 Logo、字幕或水印。"
        ),
        "negative_prompt": (
            "禁止车头车尾颠倒、倒车式高速行驶、车身变形、悬浮、"
            "轮胎穿地、背景静止和用静态展示代替高速运动。"
        ),
        "continuity_bible": [
            f"全片同一主体：{subject}",
            "车头方向与前进方向一致",
            "轮胎持续滚动并接触路面",
        ],
        "shot_prompts": shot_prompts,
        "model_notes": "通用视频模型；逐镜头生成时保持同一主体与方向。",
    }


_LLM_REQ_RESPONSE = _requirement_response(_LLM_BASE)
_LLM_VALID = _storyboard_payload(_LLM_BASE)
_LLM_DIRECTOR = _director_payload(_LLM_BASE)
_LLM_SHORT = _storyboard_payload(_LLM_BASE, total_seconds=24)
_LLM_MISSING_SCENE = _storyboard_payload(
    _LLM_BASE,
    scenes=["森林", "草原", "沙漠", "城市"],
)
_LLM_DIRECTION_BAD = _storyboard_payload(
    _LLM_BASE,
    direction_overrides={2: "right_to_left"},
)
_LLM_NO_ACTIONS = _storyboard_payload(_LLM_BASE, include_actions=False)

_LLM_CASES = [
    _workflow_case(
        "llm-01",
        "LLM 分镜首次通过",
        "happy_path",
        "workflow_fake_llm",
        "脚本化模型返回合法需求与分镜，四类校验一次通过。",
        _LLM_BASE,
        ExpectedOutcome(
            final_status="completed",
            revision_count=0,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=3,
        ),
        responses=(_LLM_REQ_RESPONSE, _LLM_VALID, _LLM_DIRECTOR),
    ),
    _workflow_case(
        "llm-02",
        "LLM 时长不足后修正一次",
        "duration",
        "workflow_fake_llm",
        "初始分镜 24 秒，校验失败后模型修正到 30 秒。",
        _LLM_BASE,
        ExpectedOutcome(
            final_status="completed",
            revision_count=1,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=4,
            revision_statuses=("completed",),
            revision_reason_contains=("总时长",),
        ),
        responses=(
            _LLM_REQ_RESPONSE,
            _LLM_SHORT,
            _LLM_VALID,
            _LLM_DIRECTOR,
        ),
    ),
    _workflow_case(
        "llm-03",
        "LLM 缺失场景后修正一次",
        "scene_coverage",
        "workflow_fake_llm",
        "初始分镜缺少雪地，场景校验失败后补回全部五场景。",
        _LLM_BASE,
        ExpectedOutcome(
            final_status="completed",
            revision_count=1,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=4,
            revision_statuses=("completed",),
            revision_reason_contains=("缺少必需场景",),
        ),
        responses=(
            _LLM_REQ_RESPONSE,
            _LLM_MISSING_SCENE,
            _LLM_VALID,
            _LLM_DIRECTOR,
        ),
    ),
    _workflow_case(
        "llm-04",
        "LLM 方向矛盾后修正一次",
        "consistency",
        "workflow_fake_llm",
        "初始第三个镜头反向行驶，一致性校验失败后统一方向。",
        _LLM_BASE,
        ExpectedOutcome(
            final_status="completed",
            revision_count=1,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=4,
            revision_statuses=("completed",),
            revision_reason_contains=("相反",),
        ),
        responses=(
            _LLM_REQ_RESPONSE,
            _LLM_DIRECTION_BAD,
            _LLM_VALID,
            _LLM_DIRECTOR,
        ),
    ),
    _workflow_case(
        "llm-05",
        "LLM 缺失动作后修正一次",
        "prompt_quality",
        "workflow_fake_llm",
        "初始分镜没有动作描述，提示词校验失败后补齐动作链。",
        _LLM_BASE,
        ExpectedOutcome(
            final_status="completed",
            revision_count=1,
            validation_passed=True,
            check_results={
                "duration": True,
                "scene": True,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=4,
            revision_statuses=("completed",),
            revision_reason_contains=("动作描述",),
        ),
        responses=(
            _LLM_REQ_RESPONSE,
            _LLM_NO_ACTIONS,
            _LLM_VALID,
            _LLM_DIRECTOR,
        ),
    ),
    _workflow_case(
        "llm-06",
        "两次修正后仍缺场景，达到上限",
        "revision_limit",
        "workflow_fake_llm",
        "两次修正都没有补回雪地，系统在第二次后停止并明确失败。",
        _LLM_BASE,
        ExpectedOutcome(
            final_status="validation_failed",
            revision_count=2,
            validation_passed=False,
            check_results={
                "duration": True,
                "scene": False,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=4,
            revision_statuses=("completed", "completed"),
            revision_reason_contains=("缺少必需场景",),
            error_contains=("已达到自动修正上限 2 次",),
        ),
        responses=(
            _LLM_REQ_RESPONSE,
            _LLM_MISSING_SCENE,
            _LLM_MISSING_SCENE,
            _LLM_MISSING_SCENE,
        ),
    ),
    _workflow_case(
        "llm-07",
        "LLM 返回非法分镜 JSON",
        "llm_output_error",
        "workflow_fake_llm",
        "分镜响应不是 JSON：先带错误重试一次，仍非法则在分镜节点失败，不进入校验。",
        _LLM_BASE,
        ExpectedOutcome(
            final_status="failed",
            revision_count=0,
            validation_passed=None,
            llm_calls=3,
            error_contains=("分镜生成失败",),
            forbidden_trace_nodes=("validate_output",),
        ),
        responses=(_LLM_REQ_RESPONSE, "这不是 JSON", "这也不是 JSON"),
    ),
    _workflow_case(
        "llm-08",
        "LLM 需求解析返回非法 JSON",
        "llm_output_error",
        "workflow_fake_llm",
        "需求响应不是 JSON，系统在需求解析节点失败，不生成分镜。",
        _LLM_BASE,
        ExpectedOutcome(
            final_status="failed",
            revision_count=0,
            validation_passed=None,
            llm_calls=1,
            error_contains=("需求解析失败",),
            forbidden_trace_nodes=(
                "generate_storyboard",
                "validate_output",
            ),
        ),
        responses=("这不是 JSON",),
    ),
    _workflow_case(
        "llm-09",
        "LLM 修正响应非法",
        "llm_output_error",
        "workflow_fake_llm",
        "初始场景缺失，修正响应不是 JSON，修正失败并停止。",
        _LLM_BASE,
        ExpectedOutcome(
            final_status="failed",
            revision_count=1,
            validation_passed=False,
            check_results={
                "duration": True,
                "scene": False,
                "consistency": True,
                "prompt": True,
            },
            llm_calls=3,
            error_contains=("自动修正失败",),
            revision_statuses=("failed",),
            revision_reason_contains=("自动修正失败",),
        ),
        responses=(_LLM_REQ_RESPONSE, _LLM_MISSING_SCENE, "这不是 JSON"),
    ),
]


# ---------------------------------------------------------------------------
# Direct tool cases
# ---------------------------------------------------------------------------


def _run_duration_tool() -> ToolOutcome:
    shots = [
        Shot(
            shot_number=1,
            start_seconds=0,
            end_seconds=5,
            scene="森林",
        ),
        Shot(
            shot_number=2,
            start_seconds=7,
            end_seconds=10,
            scene="草原",
        ),
        Shot(
            shot_number=3,
            start_seconds=9,
            end_seconds=12,
            scene="城市",
        ),
    ]
    result = check_duration(
        shots,
        target_duration_seconds=12,
        tolerance_seconds=0.5,
    )
    return ToolOutcome(
        passed=result.passed,
        errors=tuple(result.errors),
        warnings=tuple(result.warnings),
    )


def _run_scene_tool() -> ToolOutcome:
    shots = [
        Shot(shot_number=1, start_seconds=0, end_seconds=4, scene="森林"),
        Shot(shot_number=2, start_seconds=4, end_seconds=8, scene="森林"),
        Shot(shot_number=3, start_seconds=8, end_seconds=12, scene="城市"),
    ]
    result = check_scene_coverage(
        shots,
        ["森林", "草原", "城市"],
    )
    return ToolOutcome(
        passed=result.passed,
        errors=tuple(result.errors),
        warnings=tuple(result.warnings),
    )


def _run_prompt_tool() -> ToolOutcome:
    requirement = _requirement(
        "提示词冲突工具测试",
        "汽车商业广告",
        "一辆银灰色纯电轿车",
        6,
        ["城市"],
        constraints=["全片使用同一辆银灰色纯电轿车"],
    )
    shot = Shot(
        shot_number=1,
        start_seconds=0,
        end_seconds=6,
        scene="城市",
        action="车辆向右行驶",
        subject_state="一辆银灰色纯电轿车",
        continuity_locks=["全片使用同一辆银灰色纯电轿车"],
        cinematography=CinematographySpec(
            shot_size=ShotSize.MS,
            camera_angle=CameraAngle.LOW_ANGLE,
            camera_movement=CameraMovement.STATIC,
            lighting_style=LightingStyle.GOLDEN_HOUR,
            color_grade=ColorGrade.TEAL_ORANGE,
            transition=TransitionType.HARD_CUT,
            screen_direction=ScreenDirection.LEFT_TO_RIGHT,
        ),
        image_prompt="城市街道，film grain，4K ultra sharp，车辆向右行驶",
        video_prompt=(
            "场景：城市。动作：车辆向右行驶。"
            "摄影：固定机位，手持跟拍。film grain，4K ultra sharp。"
            "光线：自然光。一致性要求：同一辆银灰色纯电轿车。"
        ),
        negative_prompt="无字幕，无水印",
    )
    from schemas.project import CreativeRequirement

    result = check_prompt_quality(
        [shot],
        CreativeRequirement.model_validate(requirement),
        "generic",
    )
    return ToolOutcome(
        passed=result.passed,
        errors=tuple(result.errors),
        warnings=tuple(result.warnings),
    )


_TOOL_CASES = [
    EvaluationCase(
        case_id="tool-01",
        name="时长工具检测空档与重叠",
        category="tool_precision",
        kind="tool",
        max_revisions=0,
        description="直接构造带 2 秒空档和 1 秒重叠的时间线。",
        expected=ExpectedOutcome(
            final_status="tool",
            tool_passed=False,
            tool_error_contains=("空档", "重叠"),
        ),
        tool_runner=_run_duration_tool,
    ),
    EvaluationCase(
        case_id="tool-02",
        name="场景工具检测缺失与重复",
        category="tool_precision",
        kind="tool",
        max_revisions=0,
        description="缺少草原且森林重复出现，检查错误与警告是否分开。",
        expected=ExpectedOutcome(
            final_status="tool",
            tool_passed=False,
            tool_error_contains=("缺少必需场景：草原",),
            tool_warning_contains=("出现 2 次",),
        ),
        tool_runner=_run_scene_tool,
    ),
    EvaluationCase(
        case_id="tool-03",
        name="提示词工具检测冲突约束与多运镜",
        category="tool_precision",
        kind="tool",
        max_revisions=0,
        description="同时包含胶片颗粒 + 4K 超清、固定机位 + 手持。",
        expected=ExpectedOutcome(
            final_status="tool",
            tool_passed=False,
            tool_error_contains=("胶片颗粒",),
            tool_warning_contains=("多种运镜",),
        ),
        tool_runner=_run_prompt_tool,
    ),
]


CASES: tuple[EvaluationCase, ...] = tuple(
    [*_DETERMINISTIC_CASES, *_LLM_CASES, *_TOOL_CASES]
)

CASE_BY_ID = {case.case_id: case for case in CASES}

if len(CASES) != 20:
    raise RuntimeError(f"Expected 20 evaluation cases, got {len(CASES)}")
