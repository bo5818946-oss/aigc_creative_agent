"""Turn the vendored skills into strict, validated creative plans.

The skills are instructions for a model, not Python libraries. This module
loads their real SKILL.md text at runtime, adds only the references that the
request needs, and asks DeepSeek for the JSON contract the studio can render.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from studio.api import config
from studio.api.llm import LLMContractError
from studio.api.models import (
    ConceptRequest,
    CustomConceptRequest,
    Plan,
    PlanRequest,
    Shot,
    VideoConcept,
    utc_now,
)

DEFAULT_CINEMA_STYLE = (
    "standalone live-action film still, practical location, natural skin texture, "
    "soft highlight roll-off, restrained production design, subtle uneven grain"
)

DEFAULT_ECOM_STYLE = (
    "Campaign Style Lock: consistent premium ecommerce visual system across the entire "
    "image set; fixed palette of clean off-white background #F7F6F1, deep charcoal text "
    "#2D2D2D, one product-matched accent color and one soft secondary accent; neutral-cool "
    "studio lighting at 5500K; modern geometric sans-serif headline placeholders only; "
    "consistent rounded rectangular info labels; consistent thin-line icon style; clean "
    "high-end product photography mixed with minimal infographic elements; stable product "
    "scale and placement; generous whitespace; no color palette changes, no mixed fonts, "
    "no random backgrounds, no inconsistent lighting, no mismatched icon styles."
)

DEFAULT_CINEMA_NEGATIVE = (
    "text, watermark, logo, extra limbs, plastic skin, HDR halos"
)

DEFAULT_ECOM_NEGATIVE = (
    "text, letters, words, typography, numbers, hex codes, color swatches, "
    "labels, icons, placeholder boxes, UI panels, infographic chips, "
    "fake specs, watermark, fake logo, distorted product, duplicated product, "
    "clutter, extra props, inconsistent lighting, color shift, plastic texture"
)

_CJK = re.compile(r"[\u4e00-\u9fff]")

#: Hex colours and the style-lock label are instructions for the writer, not
#: content for the renderer. Z-Image paints them as visible text.
_HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
_STYLE_LABEL = re.compile(r"campaign\s+style\s+lock\s*:?", re.IGNORECASE)


def render_prompt(text: str) -> str:
    """Strip planning-contract text so the image model only sees the picture."""

    cleaned = _HEX_COLOR.sub("", text or "")
    cleaned = _STYLE_LABEL.sub("", cleaned)
    lines = [line.strip(" ,;:") for line in cleaned.splitlines()]
    kept = [line for line in lines if line.strip()]
    return "\n\n".join(kept).strip()


@lru_cache(maxsize=32)
def read_skill_file(skill: str, relative: str) -> str:
    root = Path(config.SKILLS[skill]["path"])
    path = (root / relative).resolve()
    if not str(path).startswith(str(root.resolve())):
        raise ValueError("非法的技能文件路径")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=8)
def skill_text(skill: str) -> str:
    return read_skill_file(skill, "SKILL.md")


@lru_cache(maxsize=1)
def ecom_templates() -> tuple[dict[str, Any], ...]:
    root = Path(config.SKILLS["ecommerce"]["path"]) / "references" / "templates"
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payload["_file"] = path.name
            items.append(payload)
    return tuple(items)


def ecom_template_index() -> str:
    lines = [
        "可用模板（只把真正匹配的模板全文附在下面；这里是索引）：",
        "id | 名称 | 触发词",
    ]
    for item in ecom_templates():
        keywords = " / ".join(str(word) for word in (item.get("keywords") or [])[:8])
        lines.append(f"- {item.get('id')} | {item.get('name')} | {keywords}")
    return "\n".join(lines)


def select_ecom_templates(brief: str, product_name: str = "", limit: int = 4) -> list[dict[str, Any]]:
    text = f"{brief} {product_name}".lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in ecom_templates():
        words = [
            str(word).lower()
            for word in (item.get("keywords") or []) + (item.get("trigger_phrases") or [])
        ]
        score = sum(1 for word in words if word and word in text)
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("id", "")))
    chosen = [item for _, item in scored[:limit]]
    if not chosen:
        fallback = next(
            (item for item in ecom_templates() if item.get("id") == "hero-image"),
            ecom_templates()[0] if ecom_templates() else None,
        )
        return [fallback] if fallback else []
    return chosen


def _template_block(items: list[dict[str, Any]]) -> str:
    if not items:
        return "（没有匹配到模板，按 SKILL.md 的通用图片 Prompt 结构执行。）"
    blocks = []
    for item in items:
        blocks.append(
            f"### 模板 {item.get('id')} · {item.get('name')}\n"
            + json.dumps(item, ensure_ascii=False, indent=2)
        )
    return "\n\n".join(blocks)


def cinema_references(*, brief: str, shot_count: int, has_reference: bool) -> list[str]:
    names = ["references/story-state-continuity.md"]
    if shot_count == 9:
        names.append("references/nine-shot-story-protocol-v3.md")
    if has_reference:
        names.extend(
            [
                "references/style-reference-fidelity.md",
                "references/asset-space-protocol.md",
            ]
        )
    low = brief.lower()
    if any(word in low for word in ("空间", "机位", "轴线", "room", "space", "blocking")):
        if "references/asset-space-protocol.md" not in names:
            names.append("references/asset-space-protocol.md")
    return names


def _reference_note(req: PlanRequest) -> str:
    if not req.reference_id:
        return "没有参考图。不要声称已看到或已识别任何画面。"
    labels = {
        "auto": "由你根据需求判断用途，但不要描述图里的具体内容",
        "product": "商品参考：保持商品外形、结构、颜色、标签和材质，不重新设计商品",
        "style": "画风参考：保留媒介、线条、色块和纹理，不把画风默认改成真人实拍",
        "character": "人物参考：保持身份与少量稳定外貌锚点",
        "scene": "场景参考：保持空间结构、材质与光源逻辑",
        "mood": "氛围参考：只参考光线、色彩和质感，不复制具体物体",
    }
    return (
        f"用户提供了一张参考图，用途：{labels.get(req.reference_role, labels['auto'])}。"
        "当前规划层没有视觉识别能力，禁止编造图中的人物、商品、品牌或文字细节；"
        "参考图会在本地 ComfyUI 生图时真正作为条件输入。"
    )


def _json_contract_cinema() -> str:
    return """
只输出一个 JSON 对象，不要 Markdown、不要解释、不要代码围栏。结构：
{
  "title": "项目标题，中文，最多 24 字",
  "summary": "一句话说明这组画面在讲什么",
  "reasoning": "你为什么这样排镜：事件、观看位置、连续性各一句；不要写空泛的审美词",
  "aspect": "2.39:1",
  "style_lock": "这组画面的视觉合同：媒介、画幅、色板、光线、材质、禁止项",
  "continuity": "连续性圣经：世界、身份、关键道具、每镜状态（简洁中文）",
  "shots": [
    {
      "index": 1,
      "title": "镜头标题，中文，最多 12 字",
      "purpose": "这一镜让观众多知道了什么",
      "prompt": "可直接提交给本地图像模型的英文提示词",
      "negative": "英文负面约束，简短",
      "camera": "机位、景别、拍向、光学意图（中文）",
      "notes": "连续性依赖、动作阶段、参考图用途（中文）"
    }
  ],
  "warnings": ["需要用户确认的假设或未验证项"]
}
""".strip()


def _json_contract_ecom() -> str:
    return """
只输出一个 JSON 对象，不要 Markdown、不要解释、不要代码围栏。结构：
{
  "title": "项目标题，中文，最多 24 字",
  "summary": "一句话说明这套图要促成什么转化",
  "reasoning": "先判断转化驱动力（视觉/痛点/情感），再说明为什么这样排图；不要编造销量、评分、认证",
  "platform": "平台或使用场景",
  "style_lock": "Campaign Style Lock，英文，整套图逐字复用",
  "shots": [
    {
      "index": 1,
      "title": "图片标题，中文，最多 12 字",
      "purpose": "这张图在货架或详情页里承担什么任务",
      "prompt": "可直接提交给本地图像模型的英文提示词；第一段必须是逐字相同的 Campaign Style Lock",
      "negative": "英文负面约束，必须具体",
      "copy": "图片内文案建议；没有就写空字符串。不要编造证明",
      "aspect": "必须与本次图片包的画幅要求一致；12 张时按 1:1 / 2:3 结构填写",
      "notes": "产品占比、留白、平台安全区、参考图用途（中文）"
    }
  ],
  "warnings": ["需要用户确认的假设；没有真实证据的证明点"]
}
""".strip()


def build_cinema_messages(req: PlanRequest) -> tuple[str, str]:
    count = req.shot_count or 3
    aspect = req.aspect or config.DEFAULT_ASPECT["cinema"]
    refs = cinema_references(
        brief=req.brief, shot_count=count, has_reference=bool(req.reference_id)
    )
    reference_text = "\n\n".join(
        f"## {name}\n{read_skill_file('cinema', name)}" for name in refs
    )
    reference_rule = (
        "7. 本次没有参考图：任何 prompt 都不得出现“参考图”“attached reference”"
        "“use the reference”等字样；画面信息只来自用户文字，缺少的关键事实写进 warnings。"
        if not req.reference_id
        else "7. 参考图没有经过视觉识别，禁止描述图中具体内容；每镜 prompt 必须包含"
        "“使用所附参考图作为……参考”的明确可执行约束，因为本地生成会把它作为真正的条件输入。"
    )
    system = f"""你是 Lunar Studio 的影视图规划层，正在执行 Cinema DNA 3.1.1 技能。

下面是技能的完整执行规则。必须遵守；技能要求的“先事实、再连续性、再镜头、最后审美”顺序不能倒。
{skill_text('cinema')}

下面是本次请求需要加载的技能参考资料：
{reference_text}

额外工程约束：
1. 这是“图片”领域，不是视频。只规划静态画面，不写运镜视频提示词；每镜是独立静帧。
2. 不要要求图像模型直接画三联、九宫格或分镜表。每镜必须能独立生成、独立替换。
3. 默认画幅 {aspect}；用户指定时以用户为准。不要拉伸。
4. 目标后端是本机 Z-Image Turbo（8 GB 显存）。提示词写清楚画面，不要写 API 参数、模型名或“8K”之类空话。
5. 每镜 prompt 用英文写，且必须是可执行的最终提示词；purpose、camera、notes 用中文。
6. 不要编造用户没有提供的角色、品牌、商品或剧情事实。缺失的关键事实写进 warnings。
{reference_rule}

{_json_contract_cinema()}
"""
    user = f"""创作需求：
{req.brief}

模式：影视图
镜头数量：{count}
画幅：{aspect}
{_reference_note(req)}
语言：中文导演说明 + 英文图像提示词。
"""
    return system, user


def build_ecom_messages(req: PlanRequest) -> tuple[str, str]:
    pack = req.pack_size or 5
    base_aspect = req.aspect or config.DEFAULT_ASPECT["ecommerce"]
    if pack == 12:
        aspect_rule = (
            "12 张时前 5 张主图固定 1:1，后 7 张详情页固定 2:3；"
            "每张 shots[i].aspect 必须按所在位置填写。"
        )
    else:
        aspect_rule = f"{pack} 张统一使用 {base_aspect}；每张 shots[i].aspect 填 {base_aspect}。"
    platform = (req.platform or "通用电商平台").strip()
    product = (req.product_name or "").strip() or "（用户未单独填写商品名，从需求中提取）"
    templates = select_ecom_templates(req.brief, product, limit=4)
    template_names = ", ".join(str(item.get("id")) for item in templates)
    reference_rule = (
        "7. 本次没有参考图：任何 prompt 都不得出现“参考图”“attached reference image”"
        "“use the reference”等字样；商品外观按文字描述生成，并把外观一致性风险写进 warnings。"
        if not req.reference_id
        else "7. 参考图没有经过视觉识别。不要描述图里商品的具体外观；每张 prompt 必须包含"
        "“使用所附商品参考图，保持商品外形、结构、颜色、标签和材质不变”的明确指令，"
        "因为本地生成会把它作为真正的条件输入。"
    )
    system = f"""你是 Lunar Studio 的电商视觉规划层，正在执行 ecom-details-image 技能。

下面是技能的完整执行规则。必须遵守它的 Campaign Style Lock、GPT-Image-2 Prompt 铁律、
转化驱动力诊断和证据边界。
{skill_text('ecommerce')}

{ecom_template_index()}

下面是本次请求匹配到的模板全文。只使用与当前商品和任务相符的部分，不要机械套模板：
{_template_block(templates)}

额外工程约束：
1. 这是“图片”领域。只规划静态图，不写视频脚本。
2. 目标后端是本机 Z-Image Turbo（8 GB 显存）。prompt 用英文写，具体、可执行；不要写 API 参数。
3. 用户没有给真实证明时，禁止编造认证、实验数据、评分、销量、真实评价或品牌授权。需要证明的位置写 proof placeholder，并放进 warnings。
4. prompt 只写画面：主体、环境、光线、材质、构图、镜头。禁止写标题、文字、占位文案、信息条、图标、色卡、UI 或“left panel / right column”这类版式位置——本机模型会把它们直接画进图里，而且拼不对；文字与版式由后期叠加。
5. 一组图用同一段视觉风格描述开头（用文字写颜色和光线，例如 off-white background、deep charcoal、midnight navy、sand），确保整组一致；禁止 hex 色值、百分比、色温数字，禁止出现“Campaign Style Lock”字样。
6. 图片内文案只写“建议”，不要声称模型一定能准确渲染中文；复杂笔画换简单同义字。
{reference_rule}
8. 本次图片包数量：{pack} 张。{aspect_rule}
9. 平台：{platform}。

{_json_contract_ecom()}
"""
    user = f"""商品/需求：
{req.brief}

商品名：{product}
平台/用途：{platform}
图片包数量：{pack}
统一画幅：{base_aspect if pack != 12 else '5×1:1 + 7×2:3'}
{_reference_note(req)}
语言：中文说明 + 英文图像提示词。匹配模板：{template_names or '无'}
"""
    return system, user


def build_auto_messages(req: PlanRequest) -> tuple[str, str]:
    system = """你是 Lunar Studio 的自主创作决策层。用户不选影视图或电商图，由你判断该走哪条路线，并决定全部创作参数。

判断标准：
- 目标是卖一个具体商品、做货架主图/详情页/广告图/转化素材 → ecommerce。
- 目标是讲故事、人物、情绪、世界、电影静帧、概念视觉 → cinema。
- 两者都像时：有明确商品和平台优先 ecommerce；只有氛围、角色、叙事优先 cinema。
- 不要因为“看起来高级”就选电影；也不要因为“有产品”就把品牌故事硬做成货架图。

参数合同（必须成套，不能混用两条路线）：
- route = "cinema"：params.shot_count 必须是 1、3 或 9 之一；params.pack_size 必须是 null。aspect 用影视图画幅。
- route = "ecommerce"：params.pack_size 必须是 1、5 或 12 之一；params.shot_count 必须是 null。aspect 用电商画幅。
- 12 张电商图片包固定为 5 张 1:1 主图 + 7 张 2:3 详情，reasoning 必须写清这个结构。
- 用户已经明确指定的数量、画幅、平台必须保留，不要擅自改。
- reasoning 最多三句话。第三句必须写出最终数量与画幅，数字和结构必须与 params 完全一致；选择 ecommerce 时不要提“9 镜”，选择 cinema 时不要提“图片包”。

只输出 JSON：
{
  "route": "cinema" 或 "ecommerce",
  "reasoning": "三句话内：任务判断、路线理由、最终数量与画幅",
  "title_hint": "项目标题，中文，最多 24 字",
  "params": {
    "shot_count": 1|3|9|null,
    "aspect": "影视图：2.39:1|21:9|16:9|4:3|1:1；电商图：1:1|4:5|3:4|2:3|16:9",
    "pack_size": 1|5|12|null,
    "product_name": "商品名或空字符串",
    "platform": "平台或空字符串"
  },
  "warnings": ["需要用户知道的假设"]
}

正确示例（只能二选一，不是让两条都输出）：
{"route":"cinema","reasoning":"这是一个带有明确人物和场景的叙事静帧需求。我选影视图，因为它要靠事件与连续性打动人。最终为 3 镜，画幅 2.39:1。","title_hint":"夜班后的早餐铺","params":{"shot_count":3,"aspect":"2.39:1","pack_size":null,"product_name":"","platform":""},"warnings":[]}
{"route":"ecommerce","reasoning":"这是一个有明确商品和独立站转化目标的视觉需求。我选电商图，因为需要货架主图与详情页信息。最终为 5 张，统一 4:5 画幅。","title_hint":"通勤邮差包电商图","params":{"shot_count":null,"aspect":"4:5","pack_size":5,"product_name":"通勤邮差包","platform":"独立站"},"warnings":[]}

不要输出 Markdown 或代码围栏。"""
    user = f"""用户需求：
{req.brief}

用户已指定的限制：
- 镜头数量：{req.shot_count if req.shot_count is not None else '未指定'}
- 画幅：{req.aspect or '未指定'}
- 图片包数量：{req.pack_size if req.pack_size is not None else '未指定'}
- 商品名：{req.product_name or '未指定'}
- 平台：{req.platform or '未指定'}
- 参考图：{'有，用途 ' + req.reference_role if req.reference_id else '无'}
"""
    return system, user


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _first(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _as_text(payload.get(key))
        if value:
            return value
    return ""


def _normalise_shots(payload: dict[str, Any], *, expected: int, aspect: str) -> list[Shot]:
    raw = payload.get("shots") or payload.get("images") or []
    if not isinstance(raw, list):
        raise LLMContractError("模型返回的 shots 不是数组。")
    shots: list[Shot] = []
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        prompt = _first(item, "prompt", "image_prompt", "final_prompt")
        if len(prompt) < 12:
            continue
        try:
            index = int(item.get("index") or position)
        except (TypeError, ValueError):
            index = position
        shots.append(
            Shot(
                index=index,
                title=_first(item, "title", "name") or f"镜头 {position}",
                purpose=_first(item, "purpose", "role", "function"),
                prompt=prompt,
                negative=_first(item, "negative", "negative_prompt"),
                camera=_first(item, "camera", "shot", "framing"),
                caption=_first(item, "copy", "text", "headline"),
                notes=_first(item, "notes", "continuity", "reference_note"),
                aspect=_first(item, "aspect", "ratio") or aspect,
            )
        )
    if not shots:
        raise LLMContractError("模型没有返回任何可用的镜头提示词。")
    if expected and len(shots) != expected:
        raise LLMContractError(
            f"模型返回了 {len(shots)} 个镜头，契约要求 {expected} 个。"
            "请重试；系统不会把多出的镜头悄悄截掉，也不会用占位镜头补齐。"
        )
    if len(shots) > max(9, expected):
        raise LLMContractError(
            f"模型返回了 {len(shots)} 张图，超过当前契约允许的数量。"
        )
    shots.sort(key=lambda shot: shot.index)
    for position, shot in enumerate(shots, start=1):
        shot.index = position
    return shots


def _base_plan(
    payload: dict[str, Any],
    req: PlanRequest,
    *,
    route: str,
    skill: str,
    skill_version: str,
    expected: int,
    aspect: str,
    template: str = "",
) -> Plan:
    warnings = payload.get("warnings")
    if isinstance(warnings, str):
        warnings = [warnings]
    if not isinstance(warnings, list):
        warnings = []
    warnings = [str(item).strip() for item in warnings if str(item).strip()]
    if req.reference_id:
        warnings.append("参考图已用于本地生成条件，但规划层没有做视觉识别。")
    if route == "ecommerce" and not req.reference_id:
        warnings.append("未提供商品参考图，商品外观一致性无法保证。")
    title = _first(payload, "title") or req.brief[:24]
    return Plan(
        mode=req.mode,
        route=route,  # type: ignore[arg-type]
        title=title[:120],
        summary=_first(payload, "summary"),
        reasoning=_first(payload, "reasoning", "thought", "analysis"),
        style_lock=_first(payload, "style_lock", "campaign_style_lock"),
        continuity=_first(payload, "continuity", "continuity_bible"),
        aspect=aspect,
        shots=_normalise_shots(payload, expected=expected, aspect=aspect),
        warnings=warnings,
        skill=skill,
        skill_version=skill_version,
        template=template,
        created_at=utc_now(),
    )


def parse_cinema_plan(payload: dict[str, Any], req: PlanRequest) -> Plan:
    expected = req.shot_count or 3
    aspect = req.aspect or config.DEFAULT_ASPECT["cinema"]
    plan = _base_plan(
        payload,
        req,
        route="cinema",
        skill="cinema-dna",
        skill_version=str(config.SKILLS["cinema"]["version"]),
        expected=expected,
        aspect=aspect,
    )
    if not plan.style_lock:
        plan.style_lock = DEFAULT_CINEMA_STYLE
    if not plan.continuity:
        plan.continuity = "未单独列出连续性圣经；以每镜 notes 为准。"
    for shot in plan.shots:
        shot.aspect = aspect
        if not shot.negative:
            shot.negative = DEFAULT_CINEMA_NEGATIVE
    return plan


def parse_ecom_plan(payload: dict[str, Any], req: PlanRequest) -> Plan:
    expected = req.pack_size or 5
    base_aspect = req.aspect or config.DEFAULT_ASPECT["ecommerce"]
    style_lock = _first(payload, "style_lock", "campaign_style_lock") or DEFAULT_ECOM_STYLE
    plan = _base_plan(
        payload,
        req,
        route="ecommerce",
        skill="ecom-details-image",
        skill_version=str(config.SKILLS["ecommerce"]["version"]),
        expected=expected,
        aspect=base_aspect,
        template=", ".join(
            str(item.get("id"))
            for item in select_ecom_templates(req.brief, req.product_name or "", limit=4)
        ),
    )
    plan.style_lock = style_lock
    for shot in plan.shots:
        if expected == 12:
            shot.aspect = "1:1" if shot.index <= 5 else "2:3"
        else:
            shot.aspect = base_aspect
        prompt = render_prompt(shot.prompt)
        if not prompt:
            raise LLMContractError(
                f"第 {shot.index} 张的 prompt 只有风格锁、没有画面内容，无法生成。"
            )
        shot.prompt = prompt
        if not shot.negative:
            shot.negative = DEFAULT_ECOM_NEGATIVE
    if expected == 12:
        plan.aspect = "5×1:1 + 7×2:3"
    return plan


def build_reprompt_messages(plan: Plan) -> tuple[str, str]:
    """Rewrite stored prompts under the current renderer rules.

    The plan itself (shot count, aspects, titles) must not change: this only
    replaces the text that reaches the image model, dropping planning-contract
    language that the renderer would paint as visible text.
    """

    if plan.route == "ecommerce":
        picture_rule = (
            "这是电商图：prompt 只描述商品、环境、光线、材质和构图。"
            "不要写标题、文案、信息条、图标、色卡、UI 或版式位置；"
            "不要使用 hex 色值、百分比或色温数字——本地图像模型会把它们直接画进画面。"
            "颜色用文字描述（off-white、deep charcoal、midnight navy、sand）。"
        )
    else:
        picture_rule = (
            "这是影视静帧：prompt 只描述人物、场景、光线、材质和镜头。"
            "画面里不要出现任何文字、字幕、标题或水印。"
        )

    shots = [
        {
            "index": shot.index,
            "title": shot.title,
            "purpose": shot.purpose,
            "camera": shot.camera,
            "notes": shot.notes,
            "aspect": shot.aspect,
            "caption": shot.caption,
            "current_prompt": shot.prompt,
        }
        for shot in plan.shots
    ]
    system = f"""你是 Lunar Studio 的提示词重写层，负责把已有分镜的提示词改写成可直接送进本机图像模型的英文 prompt。

规则：
1. 镜头数量、index、用途、机位、画幅都不能改；只重写 prompt 与 negative。
2. {picture_rule}
3. 每张 prompt 用英文写，具体可执行；同一组图共用同一段视觉风格开头，保证观感一致。
4. 保留原 prompt 里真实的画面内容与细节，删掉属于规划阶段的说明（风格锁原文、版式说明、占比数字、hex）。
5. negative 用英文逗号分隔的禁止项，针对这一类画面的典型失败模式。
6. 只输出 JSON，不要解释：
{{"shots": [{{"index": 1, "prompt": "...", "negative": "..."}}]}}
"""
    user = json.dumps(
        {
            "route": plan.route,
            "aspect": plan.aspect,
            "style_lock": plan.style_lock,
            "shots": shots,
        },
        ensure_ascii=False,
        indent=2,
    )
    return system, user


def parse_reprompt(payload: Any, plan: Plan) -> list[Shot]:
    """Validate a rewrite against the plan it belongs to."""

    if not isinstance(payload, dict):
        raise LLMContractError("重写提示词没有返回 JSON 对象。")
    raw = payload.get("shots")
    if not isinstance(raw, list) or not raw:
        raise LLMContractError("重写提示词没有返回 shots。")
    if len(raw) != len(plan.shots):
        raise LLMContractError(
            f"重写后应该还是 {len(plan.shots)} 张，但模型返回了 {len(raw)} 张。"
        )
    by_index: dict[int, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        index = _safe_int(item.get("index"))
        if index is not None:
            by_index[index] = item
    updated: list[Shot] = []
    for shot in plan.shots:
        item = by_index.get(shot.index)
        if item is None:
            raise LLMContractError(f"重写结果缺少第 {shot.index} 张。")
        prompt = render_prompt(str(item.get("prompt") or ""))
        if len(prompt) < 12:
            raise LLMContractError(f"第 {shot.index} 张重写后的 prompt 不完整。")
        negative = str(item.get("negative") or "").strip()
        if not negative:
            negative = (
                DEFAULT_ECOM_NEGATIVE
                if plan.route == "ecommerce"
                else DEFAULT_CINEMA_NEGATIVE
            )
        updated.append(
            shot.model_copy(
                update={"prompt": prompt, "negative": negative, "status": "planned"}
            )
        )
    return updated


def final_auto_decision_params(plan: Plan, req: PlanRequest) -> dict[str, Any]:
    """Describe the plan that was actually saved, not the model's raw draft."""

    if plan.route == "cinema":
        return {
            "shot_count": len(plan.shots),
            "aspect": plan.aspect,
        }
    params: dict[str, Any] = {
        "pack_size": len(plan.shots),
        "aspect": plan.aspect,
    }
    product = (req.product_name or "").strip()
    platform = (req.platform or "").strip()
    if product:
        params["product_name"] = product
    if platform:
        params["platform"] = platform
    return params


def parse_auto_decision(payload: dict[str, Any]) -> dict[str, Any]:
    route = str(payload.get("route") or "").strip().lower()
    if route not in {"cinema", "ecommerce"}:
        raise LLMContractError("自主决策层没有返回合法的 route。")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    return {
        "route": route,
        "reasoning": _first(payload, "reasoning", "analysis"),
        "title_hint": _first(payload, "title_hint", "title"),
        "params": params,
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
    }


def apply_auto_decision(req: PlanRequest, decision: dict[str, Any]) -> PlanRequest:
    params = decision.get("params") or {}
    route = decision["route"]
    data = req.model_dump()
    data["mode"] = "auto"
    if route == "cinema":
        count = req.shot_count or _safe_int(params.get("shot_count"))
        if count is None:
            raise LLMContractError(
                "自主决策选择了影视图，却没有给出镜头数量（params.shot_count）。"
            )
        data["shot_count"] = count
        data["aspect"] = req.aspect or _safe_aspect(params.get("aspect"), "cinema") or "2.39:1"
        data["pack_size"] = None
    else:
        pack = req.pack_size or _safe_int(params.get("pack_size"))
        if pack is None:
            raise LLMContractError(
                "自主决策选择了电商图，却没有给出图片数量（params.pack_size）。"
            )
        data["pack_size"] = pack
        data["aspect"] = req.aspect or _safe_aspect(params.get("aspect"), "ecommerce") or "1:1"
        data["shot_count"] = None
        if not data.get("product_name"):
            data["product_name"] = str(params.get("product_name") or "").strip()
        if not data.get("platform"):
            data["platform"] = str(params.get("platform") or "").strip()
    return PlanRequest(**data)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_aspect(value: Any, route: str) -> str | None:
    candidate = str(value or "").strip()
    allowed = (
        {"2.39:1", "21:9", "16:9", "4:3", "1:1"}
        if route == "cinema"
        else {"1:1", "4:5", "3:4", "2:3", "16:9"}
    )
    return candidate if candidate in allowed else None


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text))

# ---------------------------------------------------------------------------
# Video: four directions, one H3 clip
# ---------------------------------------------------------------------------

DEFAULT_VIDEO_NEGATIVE = (
    "text, captions, subtitles, watermark, logo, extra limbs, warped hands, "
    "flickering, strobing, jump cut, morphing, duplicate subject, cartoon, "
    "plastic skin"
)

_VIDEO_CONCEPT_CONTRACT = """{
  "concepts": [
    {
      "title": "中文标题，12 字以内",
      "logline": "一句话说清这条片子拍什么、情绪是什么",
      "treatment": "两三句中文：机位怎么走、主体做什么、光怎么打",
      "prompt": "ENGLISH prompt, 60-120 words, exactly what the video model receives",
      "negative": "short English negative list",
      "sound": "一句中文：环境声/动作声/有没有音乐",
      "risk": "一句中文：这条在本地 8GB 上最可能翻车的地方"
    }
  ]
}"""


def _video_skill_text() -> str:
    try:
        return skill_text("video")
    except (KeyError, OSError, ValueError):
        return ""


def build_concept_messages(req: ConceptRequest) -> tuple[str, str]:
    """Ask for four genuinely different directions for one generated clip."""

    skill = _video_skill_text()
    system = (
        "你是本地视频工作室的策划层，只服务一个 MiniMax H3 文本转视频模型。\n"
        f"用户要一条 {req.duration} 秒、{req.aspect} 画幅的单一镜头。\n"
        "你必须给出 4 个彼此真正不同的方向：机位策略、主体动作、光的逻辑至少有一项不同，"
        "不能只是换形容词。\n"
        "prompt 字段是要直接送进模型的英文文本，必须严格遵循下面的技能规范：\n\n"
        f"{skill}\n\n"
        "只返回 JSON，结构如下，concepts 必须正好 4 条：\n"
        f"{_VIDEO_CONCEPT_CONTRACT}\n"
        "不要编造用户没给的事实（人物身份、地点、品牌、数据）。缺失的信息写进 risk。"
    )
    user = (
        f"需求：{req.brief}\n\n"
        f"时长：{req.duration} 秒（模型只支持 5 或 10 秒，不要提别的时长）\n"
        f"画幅：{req.aspect}\n"
        "每条 prompt 都必须是一镜到底，不能出现多个镜头或转场。"
    )
    return system, user


def _concept_from_payload(item: Any, index: int) -> VideoConcept:
    if not isinstance(item, dict):
        raise LLMContractError(f"第 {index + 1} 个方向不是对象。")

    def field(name: str, *, minimum: int = 1) -> str:
        value = item.get(name)
        text = str(value).strip() if value is not None else ""
        if len(text) < minimum:
            raise LLMContractError(
                f"第 {index + 1} 个方向缺少 {name}（至少 {minimum} 个字符）。"
            )
        return text

    prompt = field("prompt", minimum=40)
    if has_cjk(prompt):
        raise LLMContractError(
            f"第 {index + 1} 个方向的 prompt 必须是英文，"
            "视频模型只按英文描述出片。"
        )
    return VideoConcept(
        concept_id="abcd"[index],
        title=field("title", minimum=2)[:80],
        logline=field("logline", minimum=4)[:240],
        treatment=field("treatment", minimum=10)[:800],
        prompt=prompt[:2400],
        negative=str(item.get("negative") or "").strip()[:400],
        sound=str(item.get("sound") or "").strip()[:240],
        risk=str(item.get("risk") or "").strip()[:240],
    )


def parse_concepts(payload: dict[str, Any], req: ConceptRequest) -> list[VideoConcept]:
    """Exactly four concepts, each with an English single-take prompt."""

    items = payload.get("concepts")
    if not isinstance(items, list) or len(items) != 4:
        raise LLMContractError(
            "模型没有返回 4 个方向（concepts 必须是长度 4 的数组）。"
        )
    concepts = [_concept_from_payload(item, index) for index, item in enumerate(items)]
    titles = {concept.title for concept in concepts}
    if len(titles) < 4:
        raise LLMContractError("4 个方向的标题重复了，说明并不是真的不同方向。")
    return concepts


def build_video_plan(
    *,
    brief: str,
    concept: VideoConcept,
    duration: int,
    aspect: str,
) -> Plan:
    """Turn the picked direction into the stored, renderable plan."""

    shot = Shot(
        index=1,
        title=concept.title,
        purpose=concept.logline,
        prompt=concept.prompt.strip(),
        negative=(concept.negative or DEFAULT_VIDEO_NEGATIVE).strip(),
        caption=concept.logline,
        notes=concept.sound,
        aspect=aspect,
        seconds=float(duration),
    )
    return Plan(
        kind="video",
        mode="video",
        route="video",
        title=concept.title,
        summary=concept.logline,
        reasoning=concept.treatment,
        continuity=concept.sound,
        aspect=aspect,
        shots=[shot],
        warnings=[concept.risk] if concept.risk else [],
        skill=str(config.SKILLS["video"]["label"]),
        skill_version=str(config.SKILLS["video"]["version"]),
        agent_decision={"brief": brief, "concept": concept.model_dump()},
    )


def build_video_revise_messages(plan: Plan, feedback: str) -> tuple[str, str]:
    """Apply a follow-up note to the clip prompt without changing its length."""

    shot = plan.shots[0]
    system = (
        "你在改一条已经规划好的本地视频提示词。只按用户追加的要求修改，"
        "保持一镜到底、保持原来的秒数，不要引入新的角色或地点，除非用户明确要求。\n"
        "prompt 必须仍是英文，仍然遵循下面的技能规范：\n\n"
        f"{_video_skill_text()}\n\n"
        '只返回 JSON：{"title": "...", "prompt": "...", "negative": "...", "notes": "一句中文说明改了什么"}'
    )
    user = (
        f"原始需求：{plan.agent_decision.get('brief', '')}\n"
        f"当前标题：{shot.title}\n"
        f"当前时长：{shot.seconds:g} 秒\n"
        f"当前 prompt：{shot.prompt}\n"
        f"当前负向词：{shot.negative}\n\n"
        f"用户追加的要求：{feedback}"
    )
    return system, user


def parse_video_revision(payload: dict[str, Any], plan: Plan) -> Plan:
    prompt = str(payload.get("prompt") or "").strip()
    if len(prompt) < 40:
        raise LLMContractError("改写的 prompt 太短了（少于 40 个字符）。")
    if has_cjk(prompt):
        raise LLMContractError("改写的 prompt 必须保持英文。")
    title = str(payload.get("title") or plan.title).strip()[:80] or plan.title
    negative = str(payload.get("negative") or plan.shots[0].negative).strip()[:400]
    note = str(payload.get("notes") or "").strip()[:240]

    shot = plan.shots[0].model_copy(
        update={"title": title, "prompt": prompt[:2400], "negative": negative}
    )
    warnings = [item for item in plan.warnings if item]
    if note:
        warnings.append(note)
    return plan.model_copy(update={"title": title, "shots": [shot], "warnings": warnings})

def build_custom_concept_messages(req: CustomConceptRequest) -> tuple[str, str]:
    """One direction the user wrote themselves, written to the skill rules."""

    system = (
        "用户已经自己想好了要拍什么，你要做的是把它写成一条可直接交给 "
        "MiniMax H3 的提示词，而不是改成一个新点子。\n"
        "保持用户的人物、地点、动作和情绪；补足机位、光、声音和运动描述即可。\n"
        "prompt 必须是英文的一镜到底描述，严格遵循下面的技能规范：\n\n"
        f"{_video_skill_text()}\n\n"
        "只返回 JSON：\n"
        '{"title": "中文标题（12 字内）", "logline": "一句话", '
        '"treatment": "两三句中文，说明机位与运动", "prompt": "ENGLISH 60-120 words", '
        '"negative": "short English list", "sound": "一句中文", '
        '"risk": "一句中文：本地最可能翻车的地方"}'
    )
    user = (
        f"原始需求：{req.brief}\n"
        f"用户自己的想法：{req.direction}\n"
        f"时长：{req.duration} 秒，画幅：{req.aspect}（只写一镜到底，不要多镜头）"
    )
    return system, user


def parse_custom_concept(
    payload: dict[str, Any], req: CustomConceptRequest
) -> VideoConcept:
    concept = _concept_from_payload(payload, 0)
    return concept.model_copy(update={"concept_id": "custom"})
