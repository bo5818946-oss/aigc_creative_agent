"""Contracts shared by the Lunar API, the planner, and the browser."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Mode = Literal["cinema", "ecommerce", "auto", "video"]
Route = Literal["cinema", "ecommerce", "video"]
PlanKind = Literal["image", "video"]
VideoSeconds = Literal[5, 10]
ShotStatus = Literal["planned", "queued", "running", "done", "failed"]
ProjectStatus = Literal["planned", "rendering", "done", "partial", "failed"]

VIDEO_ASPECTS = ("16:9", "2.39:1", "9:16", "1:1", "4:3")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PlanRequest(BaseModel):
    mode: Mode = "cinema"
    brief: str = Field(min_length=2, max_length=6000)
    reference_id: str | None = None
    reference_role: str = "auto"
    aspect: str | None = None
    shot_count: int | None = None
    pack_size: int | None = None
    product_name: str | None = None
    platform: str | None = None
    language: Literal["zh", "en"] = "zh"

    @field_validator("brief")
    @classmethod
    def _brief(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("需求不能为空")
        return value

    @field_validator("reference_role")
    @classmethod
    def _reference_role(cls, value: str) -> str:
        allowed = {"auto", "product", "style", "character", "scene", "mood"}
        return value if value in allowed else "auto"

    @model_validator(mode="after")
    def _limits(self) -> "PlanRequest":
        if self.mode == "cinema":
            if self.shot_count is not None and self.shot_count not in {1, 3, 9}:
                raise ValueError("影视图只能生成 1、3 或 9 个镜头")
            if self.aspect and self.aspect not in {
                "2.39:1",
                "21:9",
                "16:9",
                "4:3",
                "1:1",
            }:
                raise ValueError("不支持的影视图画幅")
        if self.mode == "ecommerce":
            if self.pack_size is not None and self.pack_size not in {1, 5, 12}:
                raise ValueError("电商图包只能是 1、5 或 12 张")
            if self.aspect and self.aspect not in {
                "1:1",
                "4:5",
                "3:4",
                "2:3",
                "16:9",
            }:
                raise ValueError("不支持的电商图画幅")
        return self


class Shot(BaseModel):
    index: int = Field(ge=1)
    title: str = ""
    purpose: str = ""
    prompt: str = Field(min_length=12)
    negative: str = ""
    camera: str = ""
    caption: str = ""
    notes: str = ""
    aspect: str = ""
    #: Video clips carry their length; image shots leave it at zero.
    seconds: float = 0.0
    status: ShotStatus = "planned"

    @field_validator("index")
    @classmethod
    def _index(cls, value: int) -> int:
        if value < 1:
            raise ValueError("镜头编号从 1 开始")
        return value


class Plan(BaseModel):
    kind: PlanKind = "image"
    mode: Mode
    route: Route
    title: str = Field(min_length=1, max_length=120)
    summary: str = ""
    reasoning: str = ""
    style_lock: str = ""
    continuity: str = ""
    aspect: str
    shots: list[Shot] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
    skill: str
    skill_version: str = ""
    template: str = ""
    agent_decision: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _ordered(self) -> "Plan":
        self.shots.sort(key=lambda shot: shot.index)
        for position, shot in enumerate(self.shots, start=1):
            shot.index = position
            if not shot.aspect:
                shot.aspect = self.aspect
        if self.kind == "video":
            if len(self.shots) != 1:
                raise ValueError("一个视频项目只对应一条片子")
            seconds = self.shots[0].seconds
            if int(seconds) not in (5, 10) or float(seconds) != int(seconds):
                raise ValueError("视频长度只能是 5 秒或 10 秒")
            if self.aspect not in VIDEO_ASPECTS:
                raise ValueError(f"视频不支持的画幅：{self.aspect}")
        return self


class ProjectRecord(BaseModel):
    project_id: str
    title: str
    mode: Mode
    route: Route
    brief: str
    plan: Plan
    reference_id: str | None = None
    status: ProjectStatus = "planned"
    created_at: str
    updated_at: str
    render_count: int = 0
    done_count: int = 0
    failed_count: int = 0
    cover_urls: list[str] = Field(default_factory=list)


class RenderRecord(BaseModel):
    render_id: str
    project_id: str
    shot_index: int
    status: Literal["queued", "running", "done", "failed"]
    file_url: str = ""
    error: str = ""
    prompt_id: str = ""
    width: int = 0
    height: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str
    updated_at: str


class ProjectResponse(ProjectRecord):
    renders: list[RenderRecord] = Field(default_factory=list)


class ProjectList(BaseModel):
    items: list[ProjectRecord]
    total: int


class UploadRecord(BaseModel):
    upload_id: str
    filename: str
    mime: str
    url: str
    created_at: str


class HealthResponse(BaseModel):
    deepseek_configured: bool
    deepseek_model: str
    comfyui_configured: bool
    comfyui_url: str
    comfyui_reachable: bool
    comfyui_version: str = ""
    comfyui_devices: list[str] = Field(default_factory=list)
    comfyui_vram_gb: float = 0.0
    comfyui_error: str = ""
    skills: list[dict[str, str]] = Field(default_factory=list)
    project_count: int = 0
    launch_configured: bool = False


class RenderRequest(BaseModel):
    shot_indices: list[int] | None = None

    @field_validator("shot_indices")
    @classmethod
    def _positive(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        cleaned = sorted({int(item) for item in value if int(item) > 0})
        if not cleaned:
            raise ValueError("至少要选一个镜头")
        return cleaned


class ShotPatch(BaseModel):
    title: str | None = None
    purpose: str | None = None
    prompt: str | None = Field(default=None, min_length=12)
    negative: str | None = None
    camera: str | None = None
    caption: str | None = None
    notes: str | None = None

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


# ---------------------------------------------------------------------------
# Video: four directions, one clip
# ---------------------------------------------------------------------------


class VideoConcept(BaseModel):
    concept_id: str = ""
    title: str = Field(min_length=2, max_length=80)
    logline: str = Field(min_length=4, max_length=240)
    treatment: str = Field(min_length=10, max_length=800)
    prompt: str = Field(min_length=40, max_length=2400)
    negative: str = ""
    sound: str = ""
    risk: str = ""


class ConceptRequest(BaseModel):
    brief: str = Field(min_length=2, max_length=6000)
    duration: VideoSeconds = 5
    aspect: str = "16:9"
    language: Literal["zh", "en"] = "zh"

    @field_validator("brief")
    @classmethod
    def _brief(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("需求不能为空")
        return cleaned

    @field_validator("aspect")
    @classmethod
    def _aspect(cls, value: str) -> str:
        if value not in VIDEO_ASPECTS:
            raise ValueError(f"视频不支持的画幅：{value}")
        return value


class ConceptList(BaseModel):
    concepts: list[VideoConcept] = Field(min_length=4, max_length=4)
    duration: VideoSeconds = 5
    aspect: str = "16:9"
    skill: str = "video"
    skill_version: str = ""


class VideoProjectRequest(BaseModel):
    brief: str = Field(min_length=2, max_length=6000)
    duration: VideoSeconds = 5
    aspect: str = "16:9"
    concept: VideoConcept

    @field_validator("aspect")
    @classmethod
    def _aspect(cls, value: str) -> str:
        if value not in VIDEO_ASPECTS:
            raise ValueError(f"视频不支持的画幅：{value}")
        return value


class CustomConceptRequest(ConceptRequest):
    """The user wrote their own direction; the agent turns it into a prompt."""

    direction: str = Field(min_length=2, max_length=1200)


class VideoReviseRequest(BaseModel):
    feedback: str = Field(min_length=2, max_length=800)

    @field_validator("feedback")
    @classmethod
    def _feedback(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("追加要求不能为空")
        return cleaned
