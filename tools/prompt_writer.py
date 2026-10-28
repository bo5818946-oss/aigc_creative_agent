"""Director-level prompt writing.

The storyboard is the verifiable plan. This module asks a strong model to turn
that plan into the artifact a creator actually pastes into a video model: one
cohesive director prompt plus per-shot prompts and a continuity bible.

Automotive and non-automotive projects need different director prompts. A
campus film must not inherit "front direction", "tyre contact", or "road
continuity" sections merely because the same writer serves car commercials.
"""

from __future__ import annotations

import json
import re

from config.cinematography import MODEL_PROFILES
from config.prompt_dialects import (
    BRAND_AD,
    PromptDialect,
    audit_image_prompts,
    audit_package,
    audit_video_prompts,
    resolve_dialect,
)
from schemas.project import CreativeRequirement
from schemas.prompt import (
    DirectorPromptDraft,
    DirectorPromptPackage,
    DirectorShotPrompt,
)
from schemas.storyboard import Storyboard
from schemas.validation import AggregateValidationReport
from services.llm_service import LLMService


class PromptWriterError(RuntimeError):
    """Raised when the director prompt cannot be produced safely."""


_VEHICLE_SUBJECT_TERMS = (
    "汽车",
    "轿车",
    "SUV",
    "suv",
    "跑车",
    "超跑",
    "越野车",
    "卡车",
    "摩托",
    "车型",
    "载具",
)

_VEHICLE_ONLY_MARKERS = (
    "车头",
    "车尾",
    "轮胎",
    "道路连续性",
    "车辆动作",
    "车辆前进方向",
    "车辆行驶方向",
)

_DIRECTOR_JSON_SCHEMA = """{
  "title": "片名",
  "global_prompt": "完整整片导演提示词，长文，包含上述全部要素",
  "negative_prompt": "全片统一负面约束",
  "continuity_bible": ["必须保持的事实1", "事实2"],
  "shot_prompts": [
    {
      "shot_number": 1,
      "scene": "场景名",
      "image_prompt": "该镜头图片提示词",
      "video_prompt": "该镜头视频提示词",
      "negative_prompt": "该镜头负面约束"
    }
  ],
  "model_notes": "目标模型的适配提醒"
}
"""


def is_vehicle_project(requirement: CreativeRequirement) -> bool:
    """Whether the project is actually about a vehicle.

    Content type and subject are authoritative. Notes and negative constraints
    are deliberately excluded: a campus film saying "无真实车型" in its
    negative prompt must not be treated as a car commercial.
    """

    content_type = (requirement.content_type or "").casefold()
    subject = (requirement.subject or "").casefold()
    if "汽车" in content_type or "车辆" in content_type:
        return True
    # A campus film may mention a car in the background; its content type
    # should win over a subject keyword.
    if any(
        marker in content_type
        for marker in ("校园", "剧情", "短片", "微电影", "人物", "故事", "美妆", "食品")
    ):
        return False
    return any(term.casefold() in subject for term in _VEHICLE_SUBJECT_TERMS)


def _has_vehicle_only_marker(text: str) -> bool:
    return any(marker in text for marker in _VEHICLE_ONLY_MARKERS)


def _sanitize_non_vehicle_text(text: str) -> str:
    """Remove vehicle-only sections while retaining useful generic clauses.

    Models sometimes ignore the instruction and emit sections such as
    "2. 车头/前进方向：本片无车辆，但主体方向……"。We drop the vehicle-only
    part but keep the useful clause after "但", and never keep a bare
    "不适用" placeholder. This is a safety net, not the primary prompt design.
    """

    if not text:
        return ""
    parts = re.split(r"(?<=[。！？；\n])", text)
    kept: list[str] = []
    for part in parts:
        stripped = re.sub(r"^\s*\d+\.\s*", "", part).strip()
        if not stripped:
            continue
        has_na = bool(
            re.search(r"不适用|无车辆|没有车辆|N/?A", stripped, re.IGNORECASE)
        )
        if has_na:
            # "道路连续性：不适用，但场景连续性必须保持……" keeps the
            # second half. A bare "轮胎接地：不适用。" is dropped entirely.
            if "但" in stripped:
                tail = stripped.split("但", 1)[1].strip()
                if tail and not _has_vehicle_only_marker(tail):
                    kept.append(tail)
            continue
        if _has_vehicle_only_marker(stripped):
            continue
        kept.append(part)
    result = "".join(kept)
    result = re.sub(r"\n[ \t]+", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _renumber_numbered_lines(text: str) -> str:
    number = 0
    lines: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^(\s*)\d+\.\s*(.*)$", line)
        if match and match.group(2).strip():
            number += 1
            lines.append(f"{match.group(1)}{number}. {match.group(2)}")
        else:
            lines.append(line)
    return "\n".join(lines)


def _director_system_prompt(
    dialect: PromptDialect,
    *,
    is_vehicle: bool,
) -> str:
    """Compose the writer's brief from the genre's own craft standard.

    The genre is not a label on top of a generic template: it decides the role,
    the required sections, what every shot prompt must state, what is forbidden
    and what the negative prompt has to cover.
    """

    if is_vehicle:
        asset_rule = (
            "唯一车辆资产锁定（车型、颜色、材质、结构、灯组、轮毂等）；"
            "车头/前进方向；轮胎接地；道路连续性；车辆物理运动规则"
        )
    else:
        asset_rule = (
            "唯一主体资产锁定（人物/产品/道具的外观、服装、材质、结构、"
            "关键识别特征）；主体运动方向、视线方向、屏幕方向；"
            "空间连续性；物理运动规则"
        )

    sections = [
        dialect.system_block(),
        "",
        "【通用硬约束，任何体裁都适用】",
        "1. 以给定分镜为硬约束：不得增加、删除、重排镜头，不得改变场景、时间线、主体和已确定的摄影参数。",
        "2. 整片提示词必须先写死资产与物理规则："
        f"{asset_rule}。",
        f"3. 篇幅按体裁来：{dialect.length_hint}。不要用几句话概括整片，也不要为了凑字数复述。",
        "4. 文字要具体、可执行、有导演判断，落到可见细节；禁止堆砌“电影感、高级感、震撼”等空词。",
        "5. 分镜中的 image_prompt/video_prompt 只是结构化参考，不要照抄，要重写成这套体裁的导演语言。",
        "6. 逐镜头提示词必须覆盖每一个镜头，按分镜时间顺序，一镜一条，不得合并。",
        "7. 不得虚构品牌 Logo、真实品牌或未经用户提供的外部 IP；片名可以创作，但画面文字只能用用户项目名或中性文字。",
        "8. negative_prompt 要覆盖这个体裁最典型的失败模式，不要只写“低质量”。",
        "9. 图片提示词和视频提示词是两种不同的写作任务，不要互相复述："
        "image_prompt 写的是被冻结的那一帧（构图、光、材质、画幅），"
        "禁止写时间推进、摄影机运动过程和转场；"
        "video_prompt 写的是画面如何变化（时长、起止状态、摄影机运动、主体运动），"
        "禁止只写一帧的静态描述。同一个镜头两者不能是同一段话。",
        "10. 只输出 JSON 对象，不要输出 Markdown 代码块、解释或前后缀文字。",
        "",
        "JSON 结构：",
        _DIRECTOR_JSON_SCHEMA,
    ]
    return "\n".join(sections)


# Kept for callers that want the brand-commercial default.
PROMPT_WRITER_SYSTEM_PROMPT = _director_system_prompt(
    BRAND_AD,
    is_vehicle=True,
)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _fallback_negative(storyboard: Storyboard) -> str:
    values = [
        shot.negative_prompt
        for shot in storyboard.shots
        if shot.negative_prompt.strip()
    ]
    return "；".join(_unique(values))


def _build_user_prompt(
    requirement: CreativeRequirement,
    storyboard: Storyboard,
    validation_report: AggregateValidationReport,
    target_model: str,
    *,
    is_vehicle: bool,
    dialect: PromptDialect | None = None,
) -> str:
    profile = MODEL_PROFILES.get(
        target_model,
        MODEL_PROFILES["generic"],
    )
    requirement_json = json.dumps(
        requirement.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
    storyboard_json = json.dumps(
        storyboard.model_dump(mode="json", exclude={"director_package"}),
        ensure_ascii=False,
        indent=2,
    )
    validation_summary = json.dumps(
        {
            "passed": validation_report.passed,
            "errors": validation_report.errors[:10],
            "warnings": validation_report.warnings[:10],
        },
        ensure_ascii=False,
        indent=2,
    )
    project_type = "汽车广告" if is_vehicle else "非汽车项目（人物/产品/场景/剧情等）"
    if is_vehicle:
        rhythm_requirement = (
            "- 摄影与速度系统必须写清速度如何通过道路标线、近景参照物、"
            "轮胎旋转、摄影机落后/追赶和视差被画面证明；\n"
        )
    else:
        rhythm_requirement = (
            "- 摄影与节奏系统必须写清运动/时间如何通过主体走位、背景视差、"
            "手势或呼吸、光线变化被画面证明；不要使用速度或载具专属表述；\n"
        )
    return (
        "请为下面的项目写导演级提示词。\n\n"
        f"项目类型：{project_type}\n"
        + (
            f"体裁：{dialect.label}（{dialect.key}）\n"
            f"这个体裁全篇必须出现：{'、'.join(dialect.must_include)}\n"
            f"negative_prompt 默认覆盖：{'、'.join(dialect.negatives)}\n"
            if dialect is not None
            else ""
        )
        + f"创作需求：\n{requirement_json}\n\n"
        f"已通过校验的分镜：\n{storyboard_json}\n\n"
        f"校验摘要：\n{validation_summary}\n\n"
        f"目标视频模型：{profile.display_name}\n"
        f"模型能力提示：{profile.notes}\n"
        f"单镜头建议上限：{profile.max_single_shot_seconds:g} 秒\n\n"
        "写作要求：\n"
        "- global_prompt 必须是完整的整片导演阐述，不少于 2500 个中文字符，"
        "建议 3000-5000 字；每个场景至少 3-5 句，不要写成摘要；\n"
        "- 必须包含逐段分镜、转场、摄影机、光线、声音、负面约束和结尾；\n"
        f"{rhythm_requirement}"
        "- 每个镜头的 shot_prompts 必须齐全，按分镜时间顺序；\n"
        "- 不能改变分镜的场景顺序、镜头数量、时间范围和主体；\n"
        "- 不要照抄分镜里的结构化提示词，要重新组织为导演语言；\n"
        + (
            "- 本项目不是载具/汽车广告：只写主体、空间、道具、走位、视线和"
            "节奏；不适用项直接省略，禁止输出“不适用”占位；\n"
            if not is_vehicle
            else "- 汽车项目必须写清主体资产、运动方向、接地、道路连续性和物理运动规则；\n"
        )
        + "- 只输出 JSON。"
    )


def normalize_director_package(
    draft: DirectorPromptDraft,
    requirement: CreativeRequirement,
    storyboard: Storyboard,
    target_model: str,
    *,
    is_vehicle: bool | None = None,
    dialect: PromptDialect | None = None,
) -> DirectorPromptPackage:
    """Merge the model draft with the validated storyboard.

    The global prompt is the primary deliverable and is required. Per-shot
    prompts fall back to the validated storyboard prompts only when the model
    omitted a shot, so the package never silently loses a shot.

    For non-vehicle projects, vehicle-only sections are removed as a safety
    net. The instruction layer already tells the model not to write them.
    """

    if is_vehicle is None:
        is_vehicle = is_vehicle_project(requirement)

    global_prompt = (draft.global_prompt or "").strip()
    if not is_vehicle:
        global_prompt = _renumber_numbered_lines(
            _sanitize_non_vehicle_text(global_prompt)
        )
    if len(global_prompt) < 200:
        raise PromptWriterError(
            "导演提示词过短或缺失，无法作为整片提示词使用。"
        )

    draft_shots = {
        shot.shot_number: shot
        for shot in draft.shot_prompts
        if shot.shot_number is not None
    }
    shot_prompts: list[DirectorShotPrompt] = []
    for shot in storyboard.shots:
        draft_shot = draft_shots.get(shot.shot_number)
        image_prompt = (
            (draft_shot.image_prompt if draft_shot else "")
            or shot.image_prompt
        )
        video_prompt = (
            (draft_shot.video_prompt if draft_shot else "")
            or shot.video_prompt
        )
        negative_prompt = (
            (draft_shot.negative_prompt if draft_shot else "")
            or shot.negative_prompt
        )
        if not is_vehicle:
            image_prompt = (
                _sanitize_non_vehicle_text(image_prompt)
                or shot.image_prompt
            )
            video_prompt = (
                _sanitize_non_vehicle_text(video_prompt)
                or shot.video_prompt
            )
            negative_prompt = (
                _sanitize_non_vehicle_text(negative_prompt)
                or shot.negative_prompt
            )
        shot_prompts.append(
            DirectorShotPrompt(
                shot_number=shot.shot_number,
                scene=shot.scene,
                image_prompt=image_prompt,
                video_prompt=video_prompt,
                negative_prompt=negative_prompt,
            )
        )

    if not any(item.video_prompt for item in shot_prompts):
        raise PromptWriterError(
            "导演提示词没有为任何镜头提供视频提示词。"
        )

    profile = MODEL_PROFILES.get(
        target_model,
        MODEL_PROFILES["generic"],
    )
    negative_prompt = (
        (draft.negative_prompt or "").strip()
        or _fallback_negative(storyboard)
    )
    if not is_vehicle:
        negative_prompt = (
            _sanitize_non_vehicle_text(negative_prompt)
            or _fallback_negative(storyboard)
        )
    continuity = _unique(
        draft.continuity_bible
        or list(requirement.consistency_constraints)
    )
    if not is_vehicle:
        continuity = [
            item
            for item in continuity
            if not _has_vehicle_only_marker(item)
            and not re.search(
                r"不适用|无车辆|没有车辆|N/?A",
                item,
                re.IGNORECASE,
            )
        ]
        if not continuity:
            continuity = [
                item
                for item in requirement.consistency_constraints
                if not _has_vehicle_only_marker(item)
            ]
    title = (draft.title or requirement.project_name).strip()
    model_notes = (draft.model_notes or profile.notes).strip()
    if not is_vehicle:
        model_notes = _sanitize_non_vehicle_text(model_notes) or profile.notes

    resolved = dialect or resolve_dialect(
        requirement.prompt_dialect,
        content_type=requirement.content_type,
        subject=requirement.subject,
        notes=f"{requirement.visual_style} {requirement.notes}",
    )
    audit = audit_package(
        global_prompt,
        [item.video_prompt for item in shot_prompts],
        resolved,
    )
    image_audit = audit_image_prompts([item.image_prompt for item in shot_prompts])
    video_audit = audit_video_prompts([item.video_prompt for item in shot_prompts])

    return DirectorPromptPackage(
        title=title or requirement.project_name,
        global_prompt=global_prompt,
        negative_prompt=negative_prompt,
        continuity_bible=continuity,
        shot_prompts=shot_prompts,
        model_notes=model_notes,
        dialect=resolved.key,
        dialect_label=resolved.label,
        dialect_audit=audit,
        image_audit=image_audit,
        video_audit=video_audit,
    )


def write_director_package(
    llm_service: LLMService,
    requirement: CreativeRequirement,
    storyboard: Storyboard,
    validation_report: AggregateValidationReport,
    target_model: str = "generic",
    *,
    dialect: PromptDialect | None = None,
) -> DirectorPromptPackage:
    if dialect is None:
        dialect = resolve_dialect(
            requirement.prompt_dialect,
            content_type=requirement.content_type,
            subject=requirement.subject,
            notes=f"{requirement.visual_style} {requirement.notes}",
        )
    is_vehicle = is_vehicle_project(requirement)
    draft = llm_service.chat_json(
        system_prompt=_director_system_prompt(dialect, is_vehicle=is_vehicle),
        user_prompt=_build_user_prompt(
            requirement,
            storyboard,
            validation_report,
            target_model,
            is_vehicle=is_vehicle,
            dialect=dialect,
        ),
        response_model=DirectorPromptDraft,
        temperature=0.55,
        max_tokens=8000,
    )
    return normalize_director_package(
        draft,
        requirement,
        storyboard,
        target_model,
        is_vehicle=is_vehicle,
        dialect=dialect,
    )
