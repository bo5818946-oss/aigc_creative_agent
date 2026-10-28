"""Storyboard generation tool.

The deterministic branch is used when no LLM is configured. The LLM branch
asks DeepSeek for structured shot fields only; prompts are assembled later by
``tools.prompt_builder`` so timing and continuity remain inspectable.
"""

from __future__ import annotations

import json

from config.cinematography import MODEL_PROFILES, ModelProfile
from schemas.cinematography import (
    CameraAngle,
    CameraMovement,
    CinematographySpec,
    ColorGrade,
    LightingStyle,
    ScreenDirection,
    ShotSize,
    TransitionType,
    VfxType,
)
from schemas.project import CreativeRequirement
from schemas.storyboard import Shot, Storyboard, StoryboardDraft
from services.llm_service import LLMResponseError, LLMService

DEFAULT_NEGATIVE_PROMPT = (
    "无字幕，无水印，无 Logo，主体不重复，不形变，无闪烁"
)

STORYBOARD_SYSTEM_PROMPT = """你是一名电影分镜师和 AI 视频导演。
你的任务是把创作需求转换成严格的结构化 JSON 分镜。

规则：
1. 只输出 JSON 对象，不要输出 Markdown 代码块、解释或前后缀文字。
2. 镜头数量控制在 4-10 个；用户要求的每个场景至少有一个镜头承载。
3. 时间线必须从 0 秒开始，总结束时间等于目标时长；镜头之间不能重叠，也不能有空档。
4. 每个镜头必须写清：start_seconds、end_seconds、scene、narrative_purpose、
   action_start、action_end、subject_state、continuity_locks、cinematography、sound。
5. cinematography 中的枚举字段必须使用下面给出的英文枚举值，不要写中文。
6. 全片保持主体一致，并按内容类型写清识别特征：人物写外观、服装、发型和随身物品；
   产品写材质、结构和颜色；汽车广告写车型/颜色/车身特征、车头方向、车辆前进方向和屏幕方向。
   如果约束要求某个运动方向一致，所有镜头的 screen_direction 必须使用同一个值，
   文本中的方向描述也必须一致；不要生成与分镜矛盾的反向运动。
7. 不要输出 image_prompt 或 video_prompt；后续会由 Python 根据结构化字段生成。
8. 不要输出 API 密钥、密码或其他敏感信息。
"""


def _enum_values(enum_cls) -> str:
    return ", ".join(item.value for item in enum_cls)


def allowed_enum_text() -> str:
    return (
        f"- shot_size: {_enum_values(ShotSize)}\n"
        f"- camera_angle: {_enum_values(CameraAngle)}\n"
        f"- camera_movement: {_enum_values(CameraMovement)}\n"
        f"- lighting_style: {_enum_values(LightingStyle)}\n"
        f"- color_grade: {_enum_values(ColorGrade)}\n"
        f"- transition: {_enum_values(TransitionType)}\n"
        f"- vfx: {_enum_values(VfxType)}\n"
        f"- screen_direction: {_enum_values(ScreenDirection)}"
    )


def _profile(model_profile_key: str) -> ModelProfile:
    return MODEL_PROFILES.get(
        model_profile_key,
        MODEL_PROFILES["generic"],
    )


def _clip_lock_text(requirement: CreativeRequirement) -> str:
    """The generation grid the storyboard has to fit.

    One shot is one generation call. When the backend only returns 5-second
    clips, a 30-second film is six shots of exactly 5 seconds — the model is
    told the grid instead of being left to invent shot lengths that no backend
    can produce.
    """

    clip = requirement.clip_seconds
    count = requirement.clip_count
    if not clip or not count:
        return "未指定片段长度（按目标模型单条上限自由切分）"
    last = count * clip
    return (
        f"共 {count} 条片段，每条 {clip:g} 秒，总时长 {last:g} 秒。\n"
        f"shots 必须正好 {count} 个；第 n 个镜头 start_seconds=(n-1)×{clip:g}，"
        f"end_seconds=n×{clip:g}，首尾相接不留空档。\n"
        "每条镜头就是一次生成调用：不要合并两条，也不要把一条拆成两个镜头。"
    )


def _build_storyboard_user_prompt(
    requirement: CreativeRequirement,
    profile: ModelProfile,
) -> str:
    requirement_json = json.dumps(
        requirement.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
    return (
        "请为下面的创作需求生成分镜。\n\n"
        f"创作需求：\n{requirement_json}\n\n"
        f"目标视频模型：{profile.display_name}\n"
        f"模型提示：{profile.notes}\n"
        f"单镜头建议上限：{profile.max_single_shot_seconds:g} 秒\n"
        f"生成单元约束：\n{_clip_lock_text(requirement)}\n\n"
        "可用枚举值：\n"
        f"{allowed_enum_text()}\n\n"
        "vfx 只能从上面的枚举值中选择；没有特效时输出空数组 []。"
        "不要自创特效名称，也不要把中文特效词写进 vfx。\n\n"
        "输出 JSON 结构示例（只输出这个结构，不要输出其他文字）：\n"
        "{\n"
        '  "generation_method": "llm",\n'
        '  "shots": [\n'
        "    {\n"
        '      "shot_number": 1,\n'
        '      "shot_id": "SHOT-001",\n'
        '      "start_seconds": 0.0,\n'
        '      "end_seconds": 6.0,\n'
        '      "scene": "森林",\n'
        '      "narrative_purpose": "建立环境与主体",\n'
        '      "action_start": "主体从画面左侧进入",\n'
        '      "action_end": "主体到达画面中央",\n'
        '      "subject_state": "同一主体，关键识别特征保持一致",\n'
        '      "continuity_locks": ["主体的外观、服装或产品结构保持一致"],\n'
        '      "cinematography": {\n'
        '        "shot_size": "wide_shot",\n'
        '        "camera_angle": "low_angle",\n'
        '        "camera_movement": "push_in",\n'
        '        "lens": "35mm",\n'
        '        "composition": "rule_of_thirds",\n'
        '        "lighting_style": "golden_hour",\n'
        '        "color_grade": "teal_orange",\n'
        '        "transition": "hard_cut",\n'
        '        "vfx": [],\n'
        '        "screen_direction": "left_to_right"\n'
        "      },\n"
        '      "sound": "环境声，无对白",\n'
        '      "negative_prompt": "无字幕，无水印，无 Logo"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "请确保 shots 覆盖所有 scenes，时间线连续且总时长准确。\n"
        "每个镜头的时长必须等于生成单元的片段长度，镜头数必须等于片段数。"
        "只输出 JSON。"
    )


def generate_storyboard_with_llm(
    llm_service: LLMService,
    requirement: CreativeRequirement,
    model_profile_key: str = "generic",
) -> Storyboard:
    profile = _profile(model_profile_key)
    user_prompt = _build_storyboard_user_prompt(requirement, profile)
    request = dict(
        system_prompt=STORYBOARD_SYSTEM_PROMPT,
        response_model=StoryboardDraft,
        temperature=0.4,
    )
    try:
        draft = llm_service.chat_json(user_prompt=user_prompt, **request)
    except LLMResponseError as exc:
        # One corrective retry, only for a structurally invalid answer. The
        # model already had the enum list; giving it the complaint once is
        # cheaper than making the user restart the whole project. A second
        # failure surfaces unchanged: nothing is repaired by guessing.
        corrected = (
            user_prompt
            + "\n\n【上一次输出被校验拒绝】\n"
            + str(exc)[:800]
            + "\n请严格使用上面列出的枚举值，重新输出完整 JSON，不要解释。"
        )
        draft = llm_service.chat_json(user_prompt=corrected, **request)
    return draft_to_storyboard(
        draft,
        requirement,
        generation_method="llm",
    )


def draft_to_storyboard(
    draft: StoryboardDraft,
    requirement: CreativeRequirement,
    generation_method: str,
) -> Storyboard:
    if not draft.shots:
        raise ValueError("模型没有返回任何镜头。")

    shots: list[Shot] = []
    for index, shot_draft in enumerate(draft.shots, start=1):
        if shot_draft.start_seconds is None or shot_draft.end_seconds is None:
            raise ValueError(
                f"镜头 {index} 缺少 start_seconds 或 end_seconds。"
            )
        if not shot_draft.scene or not shot_draft.scene.strip():
            raise ValueError(f"镜头 {index} 缺少 scene。")

        cinematography = shot_draft.cinematography or CinematographySpec()
        action = shot_draft.action or " → ".join(
            part
            for part in (shot_draft.action_start, shot_draft.action_end)
            if part
        )
        continuity_locks = shot_draft.continuity_locks or list(
            requirement.consistency_constraints
        )
        constraints = shot_draft.constraints or list(
            requirement.consistency_constraints
        )

        shots.append(
            Shot(
                shot_number=shot_draft.shot_number or index,
                shot_id=shot_draft.shot_id or f"SHOT-{index:03d}",
                start_seconds=shot_draft.start_seconds,
                end_seconds=shot_draft.end_seconds,
                scene=shot_draft.scene,
                narrative_purpose=(
                    shot_draft.narrative_purpose
                    or f"展示{shot_draft.scene}场景"
                ),
                source_scene=shot_draft.source_scene or "",
                subject_state=(
                    shot_draft.subject_state
                    or f"{requirement.subject}保持统一外观"
                ),
                action=action,
                action_start=shot_draft.action_start or "",
                action_end=shot_draft.action_end or "",
                continuity_locks=continuity_locks,
                reference_roles=shot_draft.reference_roles,
                camera_position=shot_draft.camera_position or "",
                camera_movement=shot_draft.camera_movement or "",
                framing=shot_draft.framing or "",
                lighting_color=shot_draft.lighting_color or "",
                transition=shot_draft.transition or "",
                cinematography=cinematography,
                image_prompt=shot_draft.image_prompt or "",
                video_prompt=shot_draft.video_prompt or "",
                negative_prompt=(
                    shot_draft.negative_prompt or DEFAULT_NEGATIVE_PROMPT
                ),
                sound=shot_draft.sound or "",
                constraints=constraints,
            )
        )

    return Storyboard(
        generation_method=generation_method,
        prompt_generation_method="",
        shots=shots,
    )


def generate_deterministic_storyboard(
    requirement: CreativeRequirement,
) -> Storyboard:
    """Generate a clearly labelled, deterministic storyboard placeholder.

    It is intentionally simple. Its purpose is to keep the workflow, tool
    calls, persistence, and prompt assembly testable without a model.
    """

    scenes = requirement.scene_requirements
    if not scenes:
        raise ValueError("场景清单为空，无法准备分镜。")

    count = len(scenes)
    boundaries = [0.0]
    for index in range(1, count):
        boundaries.append(
            round(requirement.duration_seconds * index / count, 3)
        )
    boundaries.append(requirement.duration_seconds)

    shots: list[Shot] = []
    for index, scene in enumerate(scenes):
        shot_size = ShotSize.WS if index == 0 else ShotSize.MS
        camera_movement = (
            CameraMovement.PUSH_IN if index == 0 else CameraMovement.STATIC
        )
        cinematography = CinematographySpec(
            shot_size=shot_size,
            camera_angle=CameraAngle.EYE_LEVEL,
            camera_movement=camera_movement,
            lens="35mm",
            composition="rule_of_thirds",
            lighting_style=(
                LightingStyle.GOLDEN_HOUR
                if index % 2 == 0
                else LightingStyle.SOFT_WINDOW
            ),
            color_grade=ColorGrade.TEAL_ORANGE,
            transition=TransitionType.HARD_CUT,
            vfx=[],
            screen_direction=ScreenDirection.LEFT_TO_RIGHT,
        )
        shots.append(
            Shot(
                shot_number=index + 1,
                shot_id=f"SHOT-{index + 1:03d}",
                start_seconds=boundaries[index],
                end_seconds=boundaries[index + 1],
                scene=scene,
                narrative_purpose=f"展示{scene}场景与主体",
                subject_state=f"{requirement.subject}保持统一外观",
                action=f"{requirement.subject}在{scene}中平稳行进",
                action_start=f"{requirement.subject}进入{scene}画面",
                action_end=f"{requirement.subject}驶出{scene}画面",
                continuity_locks=list(
                    requirement.consistency_constraints
                ),
                camera_position="平视机位",
                camera_movement="缓慢推镜" if index == 0 else "固定机位",
                framing=(
                    "广角 / 全景" if index == 0 else "中景"
                ),
                lighting_color=requirement.visual_style,
                transition="硬切" if index < count - 1 else "结束",
                cinematography=cinematography,
                negative_prompt=DEFAULT_NEGATIVE_PROMPT,
                sound="环境声，无对白",
                constraints=list(requirement.consistency_constraints),
            )
        )

    return Storyboard(
        generation_method="deterministic_placeholder",
        prompt_generation_method="",
        shots=shots,
    )
