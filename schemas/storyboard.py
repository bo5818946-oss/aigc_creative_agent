"""Storyboard data contracts.

Temporal correctness is deliberately checked by the deterministic duration
tool, not by Pydantic. This lets the checker report precise overlap, gap, and
negative-duration problems instead of failing during parsing.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.cinematography import CinematographySpec
from schemas.prompt import DirectorPromptPackage


class Shot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_number: int = Field(ge=1)
    shot_id: str = ""
    start_seconds: float
    end_seconds: float
    scene: str = Field(min_length=1)

    # Narrative and continuity fields.
    narrative_purpose: str = ""
    source_scene: str = ""
    subject_state: str = ""
    action: str = ""
    action_start: str = ""
    action_end: str = ""
    continuity_locks: list[str] = Field(default_factory=list)
    reference_roles: list[str] = Field(default_factory=list)

    # Free-text camera descriptions kept for compatibility with Phase 1 data.
    camera_position: str = ""
    camera_movement: str = ""
    framing: str = ""
    lighting_color: str = ""
    transition: str = ""

    # Controlled professional choices. Optional so placeholder storyboards and
    # existing database rows remain valid.
    cinematography: CinematographySpec | None = None

    # Prompt and generation fields.
    image_prompt: str = ""
    video_prompt: str = ""
    negative_prompt: str = ""
    sound: str = ""
    constraints: list[str] = Field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class Storyboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_method: str = "deterministic_placeholder"
    prompt_generation_method: str = ""
    director_package: DirectorPromptPackage | None = None
    shots: list[Shot] = Field(default_factory=list)


class ShotDraft(BaseModel):
    """Tolerant shape for one LLM-generated shot.

    Required temporal and scene fields stay optional here so conversion can
    report a precise error instead of failing during JSON parsing.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    shot_number: int | None = None
    shot_id: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    scene: str | None = None

    narrative_purpose: str | None = None
    source_scene: str | None = None
    subject_state: str | None = None
    action: str | None = None
    action_start: str | None = None
    action_end: str | None = None
    continuity_locks: list[str] = Field(default_factory=list)
    reference_roles: list[str] = Field(default_factory=list)

    camera_position: str | None = None
    camera_movement: str | None = None
    framing: str | None = None
    lighting_color: str | None = None
    transition: str | None = None
    cinematography: CinematographySpec | None = None

    image_prompt: str | None = None
    video_prompt: str | None = None
    negative_prompt: str | None = None
    sound: str | None = None
    constraints: list[str] = Field(default_factory=list)

    @field_validator("start_seconds", "end_seconds", mode="before")
    @classmethod
    def parse_time_value(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            match = re.search(r"-?\d+(?:\.\d+)?", value)
            if match:
                return float(match.group())
        return value

    @field_validator(
        "continuity_locks",
        "reference_roles",
        "constraints",
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


class StoryboardDraft(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    generation_method: str = "llm"
    shots: list[ShotDraft] = Field(default_factory=list)
