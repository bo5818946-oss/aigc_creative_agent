"""Conversation and creative-decision contracts for the guided studio.

The conversation state is deliberately separate from ``CreativeRequirement``:
the requirement is what the execution graph consumes, while the conversation
state records how the user and the agent arrived at those decisions, including
which values were explicit, selected, inferred, or still unknown.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FieldSource(str, Enum):
    USER = "user"
    USER_SELECTED = "user_selected"
    AGENT_INFERRED = "agent_inferred"
    ASSET = "asset"
    SYSTEM_DEFAULT = "system_default"
    UNKNOWN = "unknown"


SOURCE_LABELS = {
    FieldSource.USER: "用户明确提供",
    FieldSource.USER_SELECTED: "用户选择确认",
    FieldSource.AGENT_INFERRED: "Agent 根据上下文推断",
    FieldSource.ASSET: "来自创作资产",
    FieldSource.SYSTEM_DEFAULT: "系统默认值",
    FieldSource.UNKNOWN: "尚未确定",
}


class ConversationStage(str, Enum):
    IDEA = "idea"
    SUBJECT = "subject"
    ASSET = "asset"
    CONCEPT = "concept"
    SCENES = "scenes"
    FORMAT = "format"
    CAMERA = "camera"
    PROPOSAL = "proposal"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"


class ConversationStatus(str, Enum):
    GUIDING = "guiding"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


FIELD_KEYS = (
    "content_type",
    "subject",
    "vehicle_type",
    "vehicle_design",
    "vehicle_description",
    "vehicle_reference",
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

FIELD_LABELS = {
    "content_type": "内容类型",
    "subject": "创作主体",
    "vehicle_type": "车型",
    "vehicle_design": "外观方向",
    "vehicle_description": "车辆外观",
    "vehicle_reference": "车型/品牌参考",
    "creative_direction": "广告创意",
    "scenes": "场景",
    "duration_seconds": "时长",
    "aspect_ratio": "画幅",
    "visual_style": "视觉风格",
    "camera_language": "镜头语言",
    "transition_requirements": "转场",
    "sound_design": "声音设计",
    "target_audience": "目标受众",
    "constraints": "创作约束",
}

#: Fields a project must settle before a proposal can be built. Automotive
#: projects additionally need ``vehicle_type``; see
#: ``services.agent_director.allowed_fields`` for which fields exist per genre.
REQUIRED_FIELD_KEYS = (
    "creative_direction",
    "scenes",
    "duration_seconds",
    "camera_language",
)


class BriefField(BaseModel):
    """One decision with provenance, not just a value."""

    model_config = ConfigDict(extra="forbid")

    value: Any = None
    source: FieldSource = FieldSource.UNKNOWN
    confirmed: bool = False
    note: str = ""

    def has_value(self) -> bool:
        if self.value is None:
            return False
        if isinstance(self.value, str):
            return bool(self.value.strip())
        if isinstance(self.value, (list, tuple, dict)):
            return len(self.value) > 0
        return True

    def display_value(self) -> str:
        if not self.has_value():
            return "待确定"
        if isinstance(self.value, list):
            return "、".join(str(item) for item in self.value)
        if isinstance(self.value, float):
            return f"{self.value:g}"
        return str(self.value)


class CreativeBrief(BaseModel):
    """The evolving creative brief shared by the guide and the workflow."""

    model_config = ConfigDict(extra="forbid")

    fields: dict[str, BriefField] = Field(default_factory=dict)
    autonomy_granted: bool = False

    @model_validator(mode="after")
    def ensure_fields(self) -> "CreativeBrief":
        for key in FIELD_KEYS:
            self.fields.setdefault(key, BriefField())
        return self

    def field(self, key: str) -> BriefField:
        self.fields.setdefault(key, BriefField())
        return self.fields[key]

    def set(
        self,
        key: str,
        value: Any,
        source: FieldSource,
        *,
        confirmed: bool | None = None,
        note: str = "",
    ) -> None:
        if confirmed is None:
            confirmed = source in {
                FieldSource.USER,
                FieldSource.USER_SELECTED,
                FieldSource.ASSET,
            }
        self.fields[key] = BriefField(
            value=value,
            source=source,
            confirmed=confirmed,
            note=note,
        )

    def get(self, key: str, default: Any = None) -> Any:
        item = self.field(key)
        return item.value if item.has_value() else default

    def has(self, key: str) -> bool:
        return self.field(key).has_value()

    def source(self, key: str) -> FieldSource:
        return self.field(key).source

    def missing(self, keys: tuple[str, ...]) -> list[str]:
        return [key for key in keys if not self.has(key)]

    def snapshot(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key in FIELD_KEYS:
            item = self.field(key)
            if (
                key == "duration_seconds"
                and isinstance(item.value, (int, float))
            ):
                display = f"{float(item.value):g} 秒"
            else:
                display = item.display_value()
            rows.append(
                {
                    "key": key,
                    "label": FIELD_LABELS.get(key, key),
                    "value": display,
                    "source": item.source.value,
                    "source_label": SOURCE_LABELS.get(item.source, item.source.value),
                    "confirmed": item.confirmed,
                    "note": item.note,
                }
            )
        return rows


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = ""
    best_for: str = ""
    visual_note: str = ""
    # Concrete production parameters behind the option (lens, light, movement,
    # frame rate). A director's options always come with these; without them the
    # card is just a mood word.
    technique: str = Field(default="", max_length=300)
    reference: str = Field(default="", max_length=160)
    challenge: str = ""
    recommended: bool = False


class ClarifyingQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    stage: ConversationStage
    prompt: str = Field(min_length=1)
    why_it_matters: str = ""
    options: list[QuestionOption] = Field(default_factory=list)
    recommended_option_id: str | None = None
    recommendation_reason: str = ""
    allow_custom: bool = True
    multi_select: bool = False
    min_selections: int = 1
    max_selections: int = 8
    helper: str = ""
    # Model-facing transparency. ``reasoning`` is the model's own justification
    # for choosing this question and these options, shown to the user instead of
    # a fabricated "thinking" animation. ``policy_source`` records what actually
    # decided the question so a rules-based turn is never passed off as an
    # agentic one.
    reasoning: str = ""
    policy_source: str = "rules"


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=lambda: uuid4().hex)
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=12000)
    kind: str = "text"
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class DecisionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    source: str


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    one_liner: str = ""
    concept_summary: str = ""
    vehicle_summary: str = ""
    creative_rationale: str = ""
    scene_order: list[str] = Field(default_factory=list)
    shot_strategy: list[str] = Field(default_factory=list)
    camera_plan: list[str] = Field(default_factory=list)
    transition_plan: list[str] = Field(default_factory=list)
    sound_plan: str = ""
    risks: list[str] = Field(default_factory=list)
    decisions: list[DecisionRow] = Field(default_factory=list)
    total_duration: float = 30
    #: Per-generation clip length and how many clips the film needs. A local
    #: model that returns 5 seconds per call needs six calls for a 30-second
    #: film; the proposal states that instead of implying one long generation.
    clip_seconds: float = 5
    clip_count: int = 6
    estimated_shots: int = 6
    output_summary: list[str] = Field(default_factory=list)
    ready_to_generate: bool = True


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: str | None = None
    original_idea: str = ""
    reference_files: list[str] = Field(default_factory=list)
    stage: ConversationStage = ConversationStage.IDEA
    status: ConversationStatus = ConversationStatus.GUIDING
    messages: list[ConversationMessage] = Field(default_factory=list)
    brief: CreativeBrief = Field(default_factory=CreativeBrief)
    pending_question: ClarifyingQuestion | None = None
    proposal: Proposal | None = None
    question_count: int = 0
    turn_count: int = 0
    last_change: str = ""
    generation_requested: bool = False
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)

    def add_message(
        self,
        role: Literal["user", "assistant", "system"],
        content: str,
        *,
        kind: str = "text",
        payload: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> ConversationMessage:
        message = ConversationMessage(
            role=role,
            content=content,
            kind=kind,
            payload=payload or {},
            created_at=created_at or utc_now(),
        )
        self.messages.append(message)
        # Keep the persisted transcript readable without letting one project
        # grow without bound. The full project result is stored separately.
        if len(self.messages) > 120:
            self.messages = self.messages[-120:]
        self.updated_at = message.created_at
        return message

    def touch(self) -> None:
        self.updated_at = utc_now()

    @property
    def last_assistant_message(self) -> ConversationMessage | None:
        for message in reversed(self.messages):
            if message.role == "assistant":
                return message
        return None


class VehicleAsset(BaseModel):
    """A reusable subject asset, currently focused on vehicles."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str = Field(min_length=1, max_length=100)
    kind: str = "vehicle"
    description: str = Field(default="", max_length=1000)
    attributes: dict[str, Any] = Field(default_factory=dict)
    rules: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
