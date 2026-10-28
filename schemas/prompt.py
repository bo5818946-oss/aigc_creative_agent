"""Director-level prompt package contracts.

The storyboard remains the verifiable plan. This package is the creative,
model-facing deliverable: one cohesive director prompt plus per-shot prompts.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DirectorShotPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    shot_number: int = Field(ge=1)
    scene: str = ""
    image_prompt: str = ""
    video_prompt: str = ""
    negative_prompt: str = ""


class DirectorPromptPackage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    global_prompt: str = Field(min_length=200, max_length=30000)
    negative_prompt: str = Field(default="", max_length=6000)
    continuity_bible: list[str] = Field(default_factory=list)
    shot_prompts: list[DirectorShotPrompt] = Field(default_factory=list)
    model_notes: str = Field(default="", max_length=4000)
    #: Which genre standard this package was written to, and which of that
    #: standard's requirements the generated text does not visibly satisfy.
    dialect: str = Field(default="", max_length=40)
    dialect_label: str = Field(default="", max_length=60)
    dialect_audit: list[str] = Field(default_factory=list)
    #: Format-level audits: a still-image prompt and a motion prompt fail in
    #: different ways, so they are checked separately.
    image_audit: list[str] = Field(default_factory=list)
    video_audit: list[str] = Field(default_factory=list)


class DirectorShotPromptDraft(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    shot_number: int | None = None
    scene: str | None = None
    image_prompt: str | None = None
    video_prompt: str | None = None
    negative_prompt: str | None = None

    @field_validator("shot_number", mode="before")
    @classmethod
    def parse_shot_number(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            match = re.search(r"\d+", value)
            if match:
                return int(match.group())
        return value


class DirectorPromptDraft(BaseModel):
    """Tolerant shape for a model-written director package."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    title: str | None = None
    global_prompt: str | None = None
    negative_prompt: str | None = None
    continuity_bible: list[str] = Field(default_factory=list)
    shot_prompts: list[DirectorShotPromptDraft] = Field(default_factory=list)
    model_notes: str | None = None

    @field_validator("continuity_bible", mode="before")
    @classmethod
    def coerce_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [
                item.strip(" -•\t")
                for item in value.splitlines()
                if item.strip(" -•\t")
            ]
        return value
