"""LLM-first decision layer for the guided studio.

Why this module exists
----------------------
Before this layer, *every* decision in the conversation was made by Python:
``ConversationEngine`` walked a fixed field order, pulled the options out of
module-level lists (``VEHICLE_OPTIONS``, ``SCENE_OPTIONS`` ...), and picked a
recommendation with a keyword rule. DeepSeek was only called at the very end to
turn an already-decided brief into JSON. That is a wizard, not an agent: the
model never chose what to do next.

``AgentDirector`` inverts that. On each turn the model receives the confirmed
brief, the question the user is currently looking at, and the last few
exchanges, and it decides:

* what the user actually meant (``understood``),
* whether to ask, propose, confirm, or revise (``action``),
* which single decision is worth asking about next and **why** (``reasoning``),
* which options to offer — generated for this specific request, not looked up
  in a table (``question.options``).

The engine still owns validation, persistence, and the option-id plumbing, so a
hallucinated field or a malformed option cannot corrupt the brief. When the
model is unavailable the deterministic engine takes over unchanged, and the
question is tagged ``policy_source="rules"`` so the UI never pretends a rule
turn was an agentic one.

Robustness notes
----------------
DeepSeek's JSON mode guarantees *valid JSON*, not *our schema*. In practice it
answers with ``question.text`` instead of ``prompt`` and invents field names
like ``tone``. So this module keeps the contract permissive on purpose:
aliases are accepted, unknown ``understood`` keys are mapped through a synonym
table and dropped otherwise, and a question whose field cannot be resolved is
rejected so the caller can fall back to the rule policy instead of guessing.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from schemas.conversation import (
    FIELD_KEYS,
    ClarifyingQuestion,
    ConversationStage,
    QuestionOption,
)
from services.clip_plan import VideoCapability, capability_for, duration_choices

# Field -> stage used when the model omits one, so the stage rail keeps working.
_FIELD_STAGE: dict[str, ConversationStage] = {
    "content_type": ConversationStage.CONCEPT,
    "subject": ConversationStage.SUBJECT,
    "vehicle_type": ConversationStage.SUBJECT,
    "vehicle_design": ConversationStage.ASSET,
    "vehicle_description": ConversationStage.ASSET,
    "vehicle_reference": ConversationStage.ASSET,
    "creative_direction": ConversationStage.CONCEPT,
    "scenes": ConversationStage.SCENES,
    "duration_seconds": ConversationStage.FORMAT,
    "aspect_ratio": ConversationStage.FORMAT,
    "visual_style": ConversationStage.CONCEPT,
    "camera_language": ConversationStage.CAMERA,
    "transition_requirements": ConversationStage.CAMERA,
    "sound_design": ConversationStage.CAMERA,
    "target_audience": ConversationStage.CONCEPT,
    "constraints": ConversationStage.PROPOSAL,
}

# The model sometimes names a decision in its own words. Map the common ones
# onto the brief's actual keys; anything else is discarded rather than invented.
_FIELD_ALIASES: dict[str, str] = {
    "product": "subject",
    "character": "subject",
    "main_subject": "subject",
    "car_type": "vehicle_type",
    "vehicle": "vehicle_type",
    "car": "vehicle_type",
    "design": "vehicle_design",
    "appearance": "vehicle_design",
    "look": "vehicle_design",
    "brand": "vehicle_reference",
    "brand_reference": "vehicle_reference",
    "direction": "creative_direction",
    "creative": "creative_direction",
    "concept": "creative_direction",
    "story": "creative_direction",
    "narrative": "creative_direction",
    "tone": "visual_style",
    "style": "visual_style",
    "mood": "visual_style",
    "image_language": "visual_style",
    "scene": "scenes",
    "locations": "scenes",
    "location": "scenes",
    "duration": "duration_seconds",
    "length": "duration_seconds",
    "seconds": "duration_seconds",
    "camera": "camera_language",
    "shots": "camera_language",
    "transition": "transition_requirements",
    "sound": "sound_design",
    "music": "sound_design",
    "audio": "sound_design",
    "audience": "target_audience",
    "aspect": "aspect_ratio",
    "ratio": "aspect_ratio",
    "constraints": "constraints",
    "requirement": "constraints",
}

# Last-resort field inference from a question's own wording. Only used when the
# model omitted ``question.field``; a miss returns ``None`` so the caller falls
# back to the rule policy.
_FIELD_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scenes", ("场景", "地点", "空间", "发生在哪", "在哪拍", "哪些地方")),
    ("duration_seconds", ("时长", "多长", "多少秒", "多短", "几秒")),
    (
        "camera_language",
        ("运镜", "镜头语言", "机位", "跟拍", "视角", "镜头怎么"),
    ),
    ("transition_requirements", ("转场", "衔接")),
    ("vehicle_design", ("外观方向", "造型方向", "概念车", "量产")),
    ("vehicle_type", ("车型", "跑车", "suv", "轿车", "越野")),
    (
        "visual_style",
        ("影调", "色调", "质感", "视觉风格", "影像语言", "画风"),
    ),
    ("sound_design", ("声音", "配乐", "音乐", "音效")),
    ("target_audience", ("受众", "面向", "给谁看")),
    ("aspect_ratio", ("画幅", "竖屏", "横屏", "画面比例")),
    ("subject", ("主角是谁", "创作主体")),
    ("creative_direction", ("创意结构", "创意方向", "叙事结构", "故事结构")),
)


class DirectorOption(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    label: str = Field(min_length=1, max_length=80)
    technique: str = Field(
        default="",
        max_length=400,
        validation_alias=AliasChoices("technique", "technical", "setup", "params"),
    )
    description: str = Field(
        default="",
        max_length=400,
        validation_alias=AliasChoices("description", "detail", "desc"),
    )
    best_for: str = Field(
        default="",
        max_length=200,
        validation_alias=AliasChoices("best_for", "good_for", "suitable_for"),
    )
    tradeoff: str = Field(
        default="",
        max_length=260,
        validation_alias=AliasChoices("tradeoff", "trade_off", "cost", "risk"),
    )
    reference: str = Field(
        default="",
        max_length=200,
        validation_alias=AliasChoices("reference", "reference_work", "ref"),
    )
    recommended: bool = False


class DirectorQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    field: str = ""
    prompt: str = Field(
        min_length=1,
        max_length=400,
        validation_alias=AliasChoices("prompt", "text", "question", "title"),
    )
    why_it_matters: str = Field(
        default="",
        max_length=600,
        validation_alias=AliasChoices("why_it_matters", "why", "rationale"),
    )
    options: list[DirectorOption] = Field(default_factory=list)
    recommendation_reason: str = Field(
        default="",
        max_length=800,
        validation_alias=AliasChoices(
            "recommendation_reason",
            "why_recommended",
            "recommend_reason",
        ),
    )
    allow_custom: bool = True
    multi_select: bool = False

    @field_validator("options")
    @classmethod
    def _distinct_options(cls, value: list[DirectorOption]) -> list[DirectorOption]:
        seen: set[str] = set()
        result: list[DirectorOption] = []
        for option in value:
            if option.label in seen:
                continue
            seen.add(option.label)
            result.append(option)
        return result

    def resolved_field(self) -> str | None:
        """Return a brief field for this question, or ``None`` if unsure."""

        candidate = (self.field or "").strip()
        if candidate in FIELD_KEYS:
            return candidate
        candidate = _FIELD_ALIASES.get(candidate.lower(), candidate)
        if candidate in FIELD_KEYS:
            return candidate

        haystack = " ".join(
            [self.prompt, self.why_it_matters]
            + [option.label for option in self.options]
            + [option.description for option in self.options]
        ).lower()
        # Score instead of first-match: a single incidental substring (for
        # example "落在哪" containing "在哪") must not win over a precise hit.
        scored = [
            (sum(1 for keyword in keywords if keyword in haystack), field)
            for field, keywords in _FIELD_HINTS
        ]
        best = max(scored, key=lambda item: item[0])
        return best[1] if best[0] > 0 else None


class DirectorDecision(BaseModel):
    """One reasoned turn of the creative director."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    reasoning: str = Field(min_length=1, max_length=1600)
    reply: str = Field(default="", max_length=800)
    understood: dict[str, Any] = Field(default_factory=dict)
    action: Literal["ask", "propose", "confirm", "revise"] = "ask"
    question: DirectorQuestion | None = None
    revision_summary: str = Field(default="", max_length=400)

    @field_validator("understood", mode="before")
    @classmethod
    def _normalise_keys(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key).strip()
            name = name if name in FIELD_KEYS else _FIELD_ALIASES.get(name.lower(), name)
            if name in FIELD_KEYS:
                result[name] = item
        return result

    @field_validator("action", mode="before")
    @classmethod
    def _normalise_action(cls, value: Any) -> str:
        text = str(value or "ask").strip().lower()
        mapping = {
            "question": "ask",
            "clarify": "ask",
            "answer": "ask",
            "plan": "propose",
            "proposal": "propose",
            "generate": "propose",
            "modify": "revise",
            "edit": "revise",
            "change": "revise",
            "start": "confirm",
            "go": "confirm",
        }
        text = mapping.get(text, text)
        return text if text in {"ask", "propose", "confirm", "revise"} else "ask"


_SYSTEM_TEMPLATE = """你是 Alexis，一位资深广告片创意总监，同时是这个创作系统的决策者。
你不是问卷机器人：你要像真人导演一样听、判断、然后决定下一步。

每一轮你必须做完这几件事：
1. 从用户这句话里读出真正改变了的创作决策，放进 understood。只写你真的读到的，
   不要替用户编造。用户没说的字段不要出现。
2. 判断 action：
   - ask：还缺影响成片的关键信息，需要再问一个问题；
   - propose：信息足够出方案了，question 必须为 null；
   - revise：用户要改已经定下的东西，把改动写进 understood，question 可为 null；
   - confirm：用户明确要开始生成，question 必须为 null。
3. reasoning：2-4 句中文，说清你的判断依据——用户哪句话让你得出这个结论、
   为什么现在问这一项、为什么这样推荐。必须具体，禁止“为了更好地理解需求”
   这类空话。用户会直接看到这段文字。
4. 如果 action 是 ask，question 里给出 2-4 个**可执行的制作方案**，不是形容词。
   每个选项都必须能被现场执行，字段要求：
   - label：8-16 字，「技术 + 画面」，例如「单灯硬光·静止雕塑」。
     禁止只写情绪词（「高级感」「有质感」），也禁止只写技术（「微距」）。
   - technique：用「·」连接的可验证参数，**至少两项**，从这些维度里选：
       景别与焦段：100mm 微距 / 24mm 广角 / 85mm 长焦压缩 / 微距接圈
       光位与光质：单灯裸光 45° 侧逆 / 4×4 柔光顶光 / 实用光源+补光 / 硬光切轮廓
       摄影机运动：滑轨横移 / 电子炮推近 / 机械臂环绕 / 手持跟随 / 固定机位
       画质参数：120fps 升格 / f/2.8 浅景深 / f/8 全清晰 / 3200K 冷光 / 金色时刻
     示例：「100mm 微距 · 单灯裸光 45° 侧逆 · 黑绒背景 · 120fps 升格」
   - description：这套参数拍出来观众看到什么，2 句以内，用画面说话。
   - best_for：什么品类、什么传播目标下应该选它。
   - tradeoff：**必须写制作代价**（拍摄难度、置景、后期量、周期、预算），
     可以附带审美代价，但不能只有「情绪偏冷」这种话。
   - reference：一个可对照的坐标（一支广告 / 一部电影 / 一位摄影师 / 一个品牌）。
     没有合适参考就写「无」，不要编造不存在的片名。
   - 恰好一个 recommended=true。
   - question.prompt 用导演口吻问，但要让非专业用户答得上来：先说画面，再给术语。
   - why_it_matters 必须点出这一项影响哪些具体制作环节（光、镜头、剪辑、声音、预算）。

【不合格 vs 合格，对照这个标准】
不合格：「高级质感 / 用光影表现高级感 / 成本较高」——没有参数、没有取舍。
合格：
  label「单灯硬光·静止雕塑」
  technique「100mm 微距 · 单灯裸光 45° 侧逆 · 黑绒背景 · f/8 全清晰」
  description「瓶身只被一道硬光切出轮廓，其余全黑，8 秒不动机位。」
  tradeoff「要精确控光与除尘，指纹和浮尘会被放大，单镜头置景 4 小时以上」
  reference「Aesop 产品静物；Mert & Marcus 的硬光质感」
5. reply：一句给用户看的回应，语气像导演，不要复述 reasoning。

【按品类判断“这一问值不值得问”】
- 剧情、校园、人物、品牌故事这类叙事片：人物关系、空间、表演和镜头距离是核心决策。
- 美妆护肤 / 食品饮料 / 数码 / 时尚等产品向创意：**不要问“你想选哪些场景/地点”**。
  这类片子本来抽象，空间是光和材质，不是现实地点；场景由你在 understood 里直接定，
  然后把问题留给真正需要用户拍板的：呈现方式、质地、光位、使用仪式、成分或工艺。
- **只谈用户提到的东西。** 不要引入用户没提过的品类、道具或主角：
  用户说校园故事，就只谈校园里的人、空间和情绪，不要替故事新增别的品类，
  也不要把某个物件升格成主角。
- 无论什么品类，都不要给出与品类无关的地点。产品向创意里出现校园、教室、宿舍、天台，
  就是错的。
- 如果这一项对成片没有实质影响，就不要问，直接按专业判断补齐并进入 propose。

【输出 JSON 的键名必须完全照此书写，不要自创键名】
{
  "reasoning": "你的判断依据",
  "reply": "一句面向用户的回应",
  "understood": {"字段名": "从用户话里读到的值"},
  "action": "ask",
  "question": {
    "field": "本次提问对应的字段名",
    "prompt": "问句本身",
    "why_it_matters": "为什么这一项影响成片",
    "options": [
      {
        "label": "技术+画面，8-16 字",
        "technique": "焦段 · 光位 · 运动 · 画质参数，用「·」连接，至少两项",
        "description": "这套参数拍出来观众看到什么",
        "best_for": "适合什么品类与传播目标",
        "tradeoff": "制作代价：难度、置景、后期、周期",
        "reference": "可对照的广告/电影/摄影师/品牌，或「无」",
        "recommended": true
      }
    ],
    "recommendation_reason": "为什么推荐它",
    "allow_custom": true,
    "multi_select": false
  }
}

【字段名只能用下面这些，且只能用本项目适用的字段】
<<FIELDS>>

【字段取值约束】
- creative_direction 写创意结构本身（一句话讲清这支片怎么成立），不要写成方案正文。
<<VEHICLE_RULES>>

硬性规则：
- 一次只问一个决策，优先问最影响成片结果的那一项。
- 已经明确的字段不要重复问。
- duration_seconds 用数字（秒），且必须取自【生成能力约束】列出的可用成片时长；
  一次生成只产出一条片段，不要给出超过单条上限的时长。scenes 用字符串数组，不要写“15秒”这种字符串。
- scenes 必须返回**当前完整**的场景列表（包含之前已确认的场景），不要只写新增或改动的那个；
  写全量才不会被丢弃。
- 用户用了“你决定/随便/听你的”这类授权时，action 用 propose，并在 understood 里
  补齐你认为最专业的取值。
- 不要输出创作方案正文，只输出决策 JSON。
- 只输出一个 JSON 对象，不要 Markdown 代码块、不要解释、不要前后缀文字。
"""


def _format_brief(snapshot: list[dict[str, Any]]) -> str:
    known = [row for row in snapshot if row.get("value") != "待确定"]
    if not known:
        return "（还没有任何已确认的决策）"
    return "\n".join(
        f"- {row['label']}（{row['source_label']}）：{row['value']}"
        for row in known
    )


# ----------------------------------------------------------------------
# which fields exist for this project
# ----------------------------------------------------------------------
#: Fields every project can use.
_GENERAL_FIELD_KEYS: tuple[str, ...] = (
    "content_type",
    "subject",
    "creative_direction",
    "scenes",
    "duration_seconds",
    "aspect_ratio",
    "visual_style",
    "camera_language",
    "transition_requirements",
    "sound_design",
    "target_audience",
    "constraints",
)

#: Fields that only make sense when the subject is a vehicle.
_VEHICLE_FIELD_KEYS: tuple[str, ...] = (
    "vehicle_type",
    "vehicle_design",
    "vehicle_description",
    "vehicle_reference",
)

_GENERAL_FIELDS_TEXT = (
    "content_type 内容类型, subject 创作主体, creative_direction 广告创意,\n"
    "scenes 场景（数组）, duration_seconds 时长（数字，秒）, aspect_ratio 画幅,\n"
    "visual_style 视觉风格, camera_language 镜头语言, transition_requirements 转场,\n"
    "sound_design 声音设计, target_audience 目标受众, constraints 创作约束（数组）"
)

_VEHICLE_FIELDS_TEXT = (
    "vehicle_type 车型, vehicle_design 外观方向,\n"
    "vehicle_description 车辆外观描述, vehicle_reference 车型/品牌参考"
)

_VEHICLE_RULES = (
    "- vehicle_design 只写外观路线，取值必须是“原创未来概念车 / 真实量产车型 /\n"
    "  高性能改装车 / 经典复古车型 / 极简豪华风”之一，不要往这里写颜色。\n"
    "- 颜色、车身线条、灯组等具体特征写进 vehicle_description，"
    "例如“一台银灰色纯电 SUV”。"
)

_NO_VEHICLE_RULES = (
    "- 这个项目不是汽车项目：不要使用任何车辆相关的字段，也不要就车辆提出问题。\n"
    "  主体长什么样、有什么特征，写进 subject。"
)

_AUTOMOTIVE_MARKERS = (
    "汽车",
    "轿车",
    "suv",
    "跑车",
    "超跑",
    "越野车",
    "车型",
    "摩托",
    "卡车",
    "皮卡",
    "新能源车",
    "车广告",
    "车辆",
)

#: Content types that are never about a vehicle as the subject. A campus film may
#: mention a car in passing; that must not turn the whole brief automotive.
_NON_AUTOMOTIVE_MARKERS = (
    "校园",
    "剧情",
    "短片",
    "微电影",
    "人物",
    "故事",
    "美妆",
    "护肤",
    "食品",
    "动画",
    "动漫",
    "纪实",
    "实验",
)


def is_automotive_brief(idea: str, content_type: str = "") -> bool:
    """Whether vehicle fields belong to this project at all."""

    kind = (content_type or "").casefold()
    if "汽车" in kind or "车辆" in kind:
        return True
    if any(marker in kind for marker in _NON_AUTOMOTIVE_MARKERS):
        return False
    blob = (idea or "").casefold()
    return any(marker in blob for marker in _AUTOMOTIVE_MARKERS)


def allowed_fields(automotive: bool) -> tuple[str, ...]:
    """The brief fields the model may write for this project."""

    if automotive:
        return _GENERAL_FIELD_KEYS + _VEHICLE_FIELD_KEYS
    return _GENERAL_FIELD_KEYS


def system_prompt(automotive: bool) -> str:
    """The director's brief, with only the fields this project actually has."""

    fields = _GENERAL_FIELDS_TEXT
    rules = _NO_VEHICLE_RULES
    if automotive:
        fields = f"{fields},\n{_VEHICLE_FIELDS_TEXT}"
        rules = _VEHICLE_RULES
    return (
        _SYSTEM_TEMPLATE.replace("<<FIELDS>>", fields)
        .replace("<<VEHICLE_RULES>>", rules)
    )


SYSTEM_PROMPT = system_prompt(automotive=False)


def _format_tail(tail: list[tuple[str, str]]) -> str:
    if not tail:
        return "（这是第一句）"
    speaker = {"user": "用户", "assistant": "你", "system": "系统"}
    return "\n".join(
        f"{speaker.get(role, role)}：{content[:300]}" for role, content in tail
    )


def _capability_block(capability: VideoCapability | None) -> str:
    """Tell the model what the generator can actually return.

    Without this the director happily offers "90 秒" for a backend that returns
    five seconds per call, and the user only finds out after a failed render.
    """

    if capability is None:
        return ""
    clips = " / ".join(f"{value:g}" for value in capability.clip_seconds)
    rows = "、".join(
        f"{plan.total_seconds:g} 秒（{plan.clip_count} 条 × {plan.clip_seconds:g} 秒）"
        for plan in duration_choices(capability, limit=10)
    )
    return f"""
【生成能力约束｜时长只能在这些值里选】
- 生成后端：{capability.display_name}；一次调用只产出一条片段，长度只能是 {clips} 秒。
- 单条视频不可能超过 {capability.max_clip_seconds:g} 秒；成片由若干整条片段拼接。
- 可选成片时长：{rows}。
- duration_seconds 只能取上面列出的数字。用户要更长的片子时，直说需要多少条、
  超出上限多少，给出拆分建议，不要顺着答应一个做不到的时长。
"""


def build_user_prompt(
    *,
    idea: str,
    brief_snapshot: list[dict[str, Any]],
    pending_field: str,
    pending_prompt: str,
    user_text: str,
    tail: list[tuple[str, str]],
    rejected_fields: list[str],
    force_action: str | None = None,
    fields: tuple[str, ...] | None = None,
    capability: VideoCapability | None = None,
) -> str:
    allowed = set(fields) if fields is not None else None
    rows = [
        row
        for row in brief_snapshot
        if allowed is None or row.get("key") in allowed
    ]
    missing = [row["label"] for row in rows if row.get("value") == "待确定"]
    rejected = "、".join(rejected_fields) if rejected_fields else "（无）"
    forced = (
        "\n【本轮强制】action 必须是 ask，并且必须给出一个 question 和 2-4 个选项，"
        "不要再给方案，也不要重复已经确认的字段。\n"
        if force_action == "ask"
        else ""
    )
    return f"""【用户的原始创意】
{idea}

【已确认的决策】
{_format_brief(rows)}

【当前还缺的字段】
{"、".join(missing) or "（关键字段已齐）"}
{_capability_block(capability)}

【用户此刻正在看的问题】
{pending_prompt or "（当前没有待答问题）"}（字段：{pending_field or "无"}）

【最近对话】
{_format_tail(tail)}

【用户这句话】
{user_text}
{forced}
【本轮请避开】
这些字段用户刚刚明确表示不想回答，不要再问它们：{rejected}

请按系统提示的要求，输出这一个 JSON 对象。"""


class AgentDirector:
    """Wraps an ``LLMService`` into a reasoned next-action decision."""

    def __init__(
        self,
        llm_service: Any,
        capability: VideoCapability | None = None,
    ):
        self.llm_service = llm_service
        self._capability = capability

    @property
    def capability(self) -> VideoCapability:
        if self._capability is None:
            self._capability = capability_for()
        return self._capability

    @property
    def model(self) -> str:
        return str(getattr(self.llm_service, "model", "unknown"))

    def decide(
        self,
        *,
        idea: str,
        brief_snapshot: list[dict[str, Any]],
        pending_field: str,
        pending_prompt: str,
        user_text: str,
        tail: list[tuple[str, str]],
        rejected_fields: list[str] | None = None,
        force_action: str | None = None,
    ) -> DirectorDecision:
        content_type = next(
            (
                str(row.get("value"))
                for row in brief_snapshot
                if row.get("key") == "content_type"
                and row.get("value") not in (None, "", "待确定")
            ),
            "",
        )
        automotive = is_automotive_brief(idea, content_type)
        fields = allowed_fields(automotive)
        prompt = build_user_prompt(
            idea=idea,
            brief_snapshot=brief_snapshot,
            pending_field=pending_field,
            pending_prompt=pending_prompt,
            user_text=user_text,
            tail=tail,
            rejected_fields=rejected_fields or [],
            force_action=force_action,
            fields=fields,
            capability=self.capability,
        )
        return self.llm_service.chat_json(
            system_prompt=system_prompt(automotive),
            user_prompt=prompt,
            response_model=DirectorDecision,
            temperature=0.4,
            max_tokens=1600,
        )

    # ------------------------------------------------------------------
    # contract conversion
    # ------------------------------------------------------------------
    @staticmethod
    def to_question(decision: DirectorDecision) -> ClarifyingQuestion | None:
        payload = decision.question
        if payload is None:
            return None
        field = payload.resolved_field()
        if field is None or not payload.options:
            # Unresolvable field: the caller falls back to the rule policy
            # rather than writing a value into a guessed field.
            return None

        options = [
            QuestionOption(
                option_id=f"{field}_{index + 1}",
                label=option.label,
                description=option.description,
                best_for=option.best_for,
                technique=option.technique,
                reference=option.reference,
                challenge=option.tradeoff,
                recommended=option.recommended,
            )
            for index, option in enumerate(payload.options)
        ]
        recommended = next(
            (option.option_id for option in options if option.recommended),
            None,
        )
        if recommended is None:
            recommended = options[0].option_id
            options[0] = options[0].model_copy(update={"recommended": True})

        return ClarifyingQuestion(
            question_id=f"llm_{field}",
            field=field,
            stage=_FIELD_STAGE.get(field, ConversationStage.CONCEPT),
            prompt=payload.prompt,
            why_it_matters=payload.why_it_matters,
            options=options,
            recommended_option_id=recommended,
            recommendation_reason=payload.recommendation_reason,
            allow_custom=payload.allow_custom,
            multi_select=payload.multi_select or field == "scenes",
            max_selections=max(2, min(6, len(options) or 3)),
            helper="可以直接选，也可以用自己的话说；选中后我只会更新这一项。",
            reasoning=decision.reasoning,
            policy_source="llm",
        )


def coerce_field_value(field: str, value: Any) -> Any:
    """Normalise a model-provided value into the shape the brief expects."""

    if value is None:
        return None
    if field == "duration_seconds":
        if isinstance(value, (int, float)):
            return float(value)
        import re

        match = re.search(r"\d+(?:\.\d+)?", str(value))
        return float(match.group()) if match else None
    if field in {"scenes", "constraints"}:
        if isinstance(value, str):
            import re

            parts = [
                item.strip()
                for item in re.split(r"[,，、;；\n]", value)
                if item.strip()
            ]
            return parts or None
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return None
    if isinstance(value, (list, tuple)):
        return "、".join(str(item) for item in value)
    text = str(value).strip()
    return text or None


def decision_confidence(decision: DirectorDecision) -> str:
    labels = {
        "ask": "继续追问",
        "propose": "给出方案",
        "revise": "调整方案",
        "confirm": "开始生成",
    }
    return labels.get(decision.action, decision.action)


def dump_decision(decision: DirectorDecision) -> str:
    return json.dumps(decision.model_dump(mode="json"), ensure_ascii=False)


__all__ = [
    "AgentDirector",
    "DirectorDecision",
    "DirectorOption",
    "DirectorQuestion",
    "coerce_field_value",
    "decision_confidence",
    "dump_decision",
]
