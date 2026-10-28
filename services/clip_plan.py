"""Plan a film as whole generation clips.

A video model returns **one clip per call**. Nothing in this project may plan a
duration the model cannot actually return: a 90-second film is nine 10-second
calls (or eighteen 5-second calls), and on a local setup with a 5-second
workflow it simply is not one video.

This module is the single place where that arithmetic lives. Everything else —
the director's question options, the storyboard length, the proposal copy, the
UI badges — reads a :class:`ClipPlan` instead of guessing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from config.cinematography import MODEL_PROFILES
from config.settings import MAX_CLIPS_PER_PROJECT, TARGET_VIDEO_MODEL


class DurationNotPlannable(ValueError):
    """Raised when a requested duration cannot be split into whole clips."""


@dataclass(frozen=True)
class VideoCapability:
    """What one generation backend can actually return per call."""

    key: str
    display_name: str
    clip_seconds: tuple[float, ...]
    #: ``model_profile`` for the static reference table, ``backend`` when the
    #: numbers were read from a live workflow / server.
    source: str = "model_profile"
    note: str = ""
    max_clips: int = MAX_CLIPS_PER_PROJECT

    @property
    def max_clip_seconds(self) -> float:
        return max(self.clip_seconds)

    @property
    def min_clip_seconds(self) -> float:
        return min(self.clip_seconds)

    @property
    def max_total_seconds(self) -> float:
        """Longest single film this backend can produce within the clip budget."""

        return self.min_clip_seconds * self.max_clips

    def quote(self) -> str:
        clips = "/".join(f"{value:g}" for value in self.clip_seconds)
        source = "本地后端" if self.source == "backend" else "参考能力表"
        return (
            f"{self.display_name}：单次生成 {clips} 秒，"
            f"单支片最多 {self.max_clips} 条（上限 {self.max_total_seconds:g} 秒，"
            f"来源：{source}）"
        )


@dataclass(frozen=True)
class ClipPlan:
    """A duration expressed as whole generation clips."""

    total_seconds: float
    clip_seconds: float
    clip_count: int

    @property
    def generated_seconds(self) -> float:
        return self.clip_seconds * self.clip_count

    @property
    def overrun_seconds(self) -> float:
        return self.generated_seconds - self.total_seconds

    @property
    def exact(self) -> bool:
        return abs(self.overrun_seconds) < 1e-6

    @property
    def single_generation(self) -> bool:
        return self.clip_count == 1

    def describe(self) -> str:
        if self.single_generation:
            return f"{self.total_seconds:g} 秒 · 1 条（单次生成）"
        text = (
            f"{self.total_seconds:g} 秒 · {self.clip_count} 条 × "
            f"{self.clip_seconds:g} 秒"
        )
        if not self.exact:
            text += f"（素材 {self.generated_seconds:g} 秒，多出 {self.overrun_seconds:g} 秒）"
        return text

    def brief_line(self) -> str:
        """One line for the requirement / prompt headers."""

        if self.single_generation:
            return f"成片 {self.total_seconds:g} 秒，一条生成，单条 {self.clip_seconds:g} 秒"
        return (
            f"成片 {self.total_seconds:g} 秒，共 {self.clip_count} 条，"
            f"每条 {self.clip_seconds:g} 秒（素材合计 {self.generated_seconds:g} 秒）"
        )

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "total_seconds": self.total_seconds,
            "clip_seconds": self.clip_seconds,
            "clip_count": self.clip_count,
            "generated_seconds": self.generated_seconds,
            "overrun_seconds": self.overrun_seconds,
            "description": self.describe(),
        }


def capability_for(
    model_key: str | None = None,
    *,
    clip_seconds: tuple[float, ...] | None = None,
    source: str = "model_profile",
    note: str = "",
    display_name: str | None = None,
) -> VideoCapability:
    """Resolve a capability from the model table, optionally overridden by a
    live backend probe.

    ``clip_seconds`` is the numbers the backend actually accepts. When it is
    given it wins, because a real workflow outranks a reference table.
    """

    key = (model_key or TARGET_VIDEO_MODEL or "generic").strip().lower()
    profile = MODEL_PROFILES.get(key)
    if profile is None:
        known = "、".join(sorted(MODEL_PROFILES))
        raise ValueError(f"未知的目标视频模型 {key!r}；可选：{known}")
    values = tuple(sorted({float(v) for v in (clip_seconds or profile.clip_seconds)}))
    if not values or any(value <= 0 for value in values):
        raise ValueError("clip_seconds 必须是正数集合")
    return VideoCapability(
        key=key,
        display_name=display_name or profile.display_name,
        clip_seconds=values,
        source=source,
        note=note or profile.notes,
    )


def _best_plan(
    total: float,
    capability: VideoCapability,
    min_clips: int = 1,
) -> ClipPlan | None:
    best: ClipPlan | None = None
    for clip in capability.clip_seconds:
        count = math.ceil(total / clip - 1e-9)
        if count < max(1, min_clips):
            continue
        candidate = ClipPlan(total_seconds=total, clip_seconds=clip, clip_count=count)
        if best is None:
            best = candidate
            continue
        # Least overrun first, then *more* clips: on measured local hardware a
        # long clip costs superlinearly (5 s = 235 s, 10 s = 582 s), and more
        # short shots also give the editor finer control.
        key = (round(candidate.overrun_seconds, 6), -candidate.clip_count, clip)
        best_key = (round(best.overrun_seconds, 6), -best.clip_count, best.clip_seconds)
        if key < best_key:
            best = candidate
    return best


def plan_for(
    total_seconds: float,
    capability: VideoCapability,
    *,
    min_clips: int = 1,
) -> ClipPlan:
    """Split ``total_seconds`` into whole clips.

    ``min_clips`` is the number of separate places the film has to visit (one
    per scene). A six-scene film cannot be cut from three 10-second clips, so
    the planner drops to shorter clips instead of silently merging scenes.

    A duration above ``capability.max_total_seconds`` raises instead of being
    silently accepted — that is the 90-second bug.
    """

    total = float(total_seconds)
    if total <= 0:
        raise DurationNotPlannable("成片时长必须大于 0 秒。")
    if total > capability.max_total_seconds + 1e-6:
        raise DurationNotPlannable(too_long_message(total, capability))
    plan = _best_plan(total, capability, min_clips=min_clips)
    if plan is None:
        raise DurationNotPlannable(
            f"{total:g} 秒装不下 {min_clips} 个场景："
            f"{capability.display_name} 每条最长 {capability.max_clip_seconds:g} 秒，"
            f"{total:g} 秒最多 {min_clips - 1} 条。请减少场景或延长时长。"
        )
    if plan.clip_count > capability.max_clips:
        raise DurationNotPlannable(too_long_message(total, capability))
    return plan


def too_long_message(total: float, capability: VideoCapability) -> str:
    shortest = capability.min_clip_seconds
    needed = math.ceil(total / shortest)
    return (
        f"{total:g} 秒做不到：{capability.display_name} 每次最多生成 "
        f"{capability.max_clip_seconds:g} 秒，"
        f"{total:g} 秒需要 {needed} 条（每条 {shortest:g} 秒），"
        f"超过单支片 {capability.max_clips} 条 / "
        f"{capability.max_total_seconds:g} 秒的上限。"
        f"建议拆成 {math.ceil(total / capability.max_total_seconds)} 支 "
        f"≤ {capability.max_total_seconds:g} 秒的片子。"
    )


def shortest_message(total: float, capability: VideoCapability) -> str:
    clips = "/".join(f"{value:g}" for value in capability.clip_seconds)
    return (
        f"{total:g} 秒不能用 {clips} 秒的片段拼出来；"
        f"最近的可选值是 "
        f"{', '.join(f'{plan.total_seconds:g}' for plan in nearest_plans(total, capability))} 秒。"
    )


def nearest_plans(total: float, capability: VideoCapability, count: int = 3) -> list[ClipPlan]:
    """The closest representable durations around ``total``."""

    candidates: list[ClipPlan] = []
    for clip in capability.clip_seconds:
        for step in range(1, capability.max_clips + 1):
            value = clip * step
            if value > capability.max_total_seconds + 1e-6:
                continue
            candidates.append(
                ClipPlan(total_seconds=value, clip_seconds=clip, clip_count=step)
            )
    if not candidates:
        return []
    candidates.sort(key=lambda plan: (abs(plan.total_seconds - total), plan.clip_count))
    picked: list[ClipPlan] = []
    seen: set[float] = set()
    for plan in candidates:
        if plan.total_seconds in seen:
            continue
        seen.add(plan.total_seconds)
        picked.append(plan)
        if len(picked) >= count:
            break
    return picked


def duration_choices(
    capability: VideoCapability,
    *,
    limit: int | None = None,
) -> list[ClipPlan]:
    """Representable film durations, shortest first, one per distinct total.

    The list is what the director may offer and what the UI may show: every
    value is a whole number of clips on the current backend.
    """

    seen: dict[float, ClipPlan] = {}
    for clip in capability.clip_seconds:
        for step in range(1, capability.max_clips + 1):
            total = clip * step
            if total > capability.max_total_seconds + 1e-6:
                continue
            plan = ClipPlan(total_seconds=total, clip_seconds=clip, clip_count=step)
            current = seen.get(total)
            if current is None or plan.clip_count < current.clip_count:
                seen[total] = plan
    ordered = sorted(seen.values(), key=lambda plan: plan.total_seconds)
    if limit is None or len(ordered) <= limit:
        return ordered
    # Keep both ends of the range plus evenly spaced values in between.
    step = (len(ordered) - 1) / (limit - 1)
    indexes = sorted({round(index * step) for index in range(limit)})
    return [ordered[index] for index in indexes]


@dataclass(frozen=True)
class DurationCheck:
    ok: bool
    plan: ClipPlan | None
    message: str


def check_duration(
    total_seconds: float,
    capability: VideoCapability,
    *,
    min_clips: int = 1,
) -> DurationCheck:
    """Validate a proposed film duration against the backend capability."""

    total = float(total_seconds)
    if total <= 0:
        return DurationCheck(False, None, "成片时长必须大于 0 秒。")
    if total > capability.max_total_seconds + 1e-6:
        return DurationCheck(False, None, too_long_message(total, capability))
    try:
        plan = plan_for(total, capability, min_clips=min_clips)
    except DurationNotPlannable as exc:
        return DurationCheck(False, None, str(exc))
    if not plan.exact:
        return DurationCheck(False, plan, shortest_message(total, capability))
    return DurationCheck(True, plan, plan.describe())
