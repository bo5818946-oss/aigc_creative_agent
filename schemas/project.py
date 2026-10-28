"""Project, requirement, and task-plan data contracts."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_IMPLEMENTED = "not_implemented"


class CreativeRequirement(BaseModel):
    """Structured version of the user's creative brief.

    Optional fields receive safe defaults. Any default that could materially
    change the creative result is recorded in ``pending_confirmations`` rather
    than silently treated as confirmed.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    project_name: str = Field(min_length=1, max_length=100)
    content_type: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=300)
    #: Which prompt dialect the writer must use (see config/prompt_dialects.py).
    #: Chosen by the requirement parser; empty means "infer from the content".
    prompt_dialect: str = Field(default="", max_length=40)
    target_audience: str = Field(default="大众消费者", max_length=200)
    duration_seconds: float = Field(gt=0, le=600)
    #: Length of one generation call and how many calls the film needs. Both are
    #: derived from the target backend; a film is cut from whole clips, so this
    #: is the number the local generator is actually asked for.
    clip_seconds: float | None = Field(default=None, gt=0, le=120)
    clip_count: int | None = Field(default=None, ge=1, le=60)
    aspect_ratio: str = Field(default="16:9", max_length=30)
    visual_style: str = Field(default="电影感商业广告", max_length=300)
    scene_requirements: list[str] = Field(default_factory=list)
    camera_language: str = Field(default="稳定运镜，主体清晰", max_length=300)
    consistency_constraints: list[str] = Field(default_factory=list)
    transition_requirements: str = Field(default="自然连贯", max_length=300)
    output_formats: list[str] = Field(default_factory=lambda: ["markdown", "json"])
    notes: str = Field(default="", max_length=1000)
    pending_confirmations: list[str] = Field(default_factory=list)

    @field_validator("scene_requirements", "consistency_constraints", mode="after")
    @classmethod
    def strip_and_drop_empty_items(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]

    @model_validator(mode="after")
    def add_safe_defaults(self) -> "CreativeRequirement":
        if not self.scene_requirements:
            self.scene_requirements = ["核心展示场景"]
            self.pending_confirmations.append(
                "未提供场景清单，已使用占位场景，需用户确认。"
            )
        if not self.consistency_constraints:
            self.consistency_constraints.append(
                f"保持{self.subject}的外观与设计特征一致。"
            )
            self.pending_confirmations.append(
                "未提供主体一致性约束，已使用通用约束，需用户确认。"
            )
        return self


class RequirementDraft(BaseModel):
    """Tolerant shape for LLM-extracted requirement fields.

    Every field is optional so the model can omit information it cannot infer
    instead of inventing it. ``merge_requirement_draft`` applies safe defaults
    and records unresolved items in ``pending_confirmations``.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    project_name: str | None = None
    content_type: str | None = None
    subject: str | None = None
    prompt_dialect: str | None = None
    target_audience: str | None = None
    duration_seconds: float | None = Field(default=None, gt=0, le=600)
    aspect_ratio: str | None = None
    visual_style: str | None = None
    scene_requirements: list[str] = Field(default_factory=list)
    camera_language: str | None = None
    consistency_constraints: list[str] = Field(default_factory=list)
    transition_requirements: str | None = None
    output_formats: list[str] = Field(
        default_factory=lambda: ["markdown", "json"]
    )
    notes: str | None = None
    pending_confirmations: list[str] = Field(default_factory=list)

    @field_validator("duration_seconds", mode="before")
    @classmethod
    def parse_duration_text(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            match = re.search(r"\d+(?:\.\d+)?", value)
            if match:
                return float(match.group())
        return value

    @field_validator(
        "scene_requirements",
        "consistency_constraints",
        "output_formats",
        "pending_confirmations",
        mode="before",
    )
    @classmethod
    def coerce_string_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [
                item.strip()
                for item in re.split(r"[,，、;；\n]", value)
                if item.strip()
            ]
        return value


class TaskItem(BaseModel):
    """A single item in the structured execution plan."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: TaskStatus
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
