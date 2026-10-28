"""Controlled cinematography vocabulary and per-shot camera specification.

The values are standard film-production terms rather than model-specific
prompt strings. Chinese labels and model capability notes live in
``config.cinematography`` so schemas stay free of presentation data.

Models drift: they return ``full_shot``, ``medium wide shot``, ``MS``, ``特写``
or ``close-up`` for values this enum spells ``medium_wide_shot`` /
``medium_close_up``. Rejecting those cost an entire storyboard generation, so
every enum accepts the common spellings, abbreviations and Chinese terms via
``_missing_``. A value that matches nothing still fails: this normalises
vocabulary, it does not invent creative choices.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _normalise_key(value: Any) -> str:
    text = str(value).strip().casefold()
    for character in (" ", "-", "/", ".", "(", ")", "'", '"'):
        text = text.replace(character, "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _resolve(enum_cls: type[Enum], value: Any, aliases: dict[str, str]) -> Any:
    """Map a model-provided spelling onto a member, or return ``None``."""

    if value is None:
        return None
    if isinstance(value, enum_cls):
        return value
    key = _normalise_key(value)
    members = enum_cls._value2member_map_  # type: ignore[attr-defined]
    if key in members:
        return members[key]
    canonical = aliases.get(key)
    if canonical is not None:
        _record(enum_cls.__name__, value, canonical)
        return members.get(canonical)
    # "close_ups" -> "close_up"; only strip a plural s.
    if key.endswith("s") and not key.endswith("ss"):
        singular = key[:-1]
        if singular in members:
            return members[singular]
        canonical = aliases.get(singular)
        if canonical is not None:
            _record(enum_cls.__name__, value, canonical)
            return members.get(canonical)
    _record_unknown(enum_cls.__name__, value)
    return None


#: What the model actually wrote, and what it was normalised into. Drained by
#: the storyboard node so the execution trace can show it: that is the evidence
#: needed to grow the vocabulary from real usage instead of guesswork.
_NORMALISATIONS: list[dict[str, str]] = []
_UNKNOWN_VALUES: list[dict[str, str]] = []


def _record(enum_name: str, raw: Any, canonical: str) -> None:
    _NORMALISATIONS.append(
        {"field": enum_name, "raw": str(raw), "canonical": canonical}
    )


def _record_unknown(enum_name: str, raw: Any) -> None:
    _UNKNOWN_VALUES.append({"field": enum_name, "raw": str(raw)})


def take_normalisations() -> dict[str, list[dict[str, str]]]:
    """Drain the normalisation log (called once per generation)."""

    normalised = list(_NORMALISATIONS)
    unknown = list(_UNKNOWN_VALUES)
    _NORMALISATIONS.clear()
    _UNKNOWN_VALUES.clear()
    return {"normalised": normalised, "unknown": unknown}


class ShotSize(str, Enum):
    EWS = "extreme_wide_shot"
    WS = "wide_shot"
    FULL = "full_shot"
    MEDIUM_WIDE = "medium_wide_shot"
    COWBOY = "cowboy_shot"
    MS = "medium_shot"
    MCU = "medium_close_up"
    CU = "close_up"
    ECU = "extreme_close_up"
    INSERT = "insert_shot"
    TWO_SHOT = "two_shot"
    OTS = "over_the_shoulder"

    @classmethod
    def _missing_(cls, value: Any) -> "ShotSize | None":
        return _resolve(cls, value, _SHOT_SIZE_ALIASES)


class CameraAngle(str, Enum):
    EYE_LEVEL = "eye_level"
    LOW_ANGLE = "low_angle"
    GROUND = "ground_level"
    HIGH_ANGLE = "high_angle"
    BIRD_EYE = "bird_eye"
    DUTCH = "dutch_angle"
    POV = "pov"

    @classmethod
    def _missing_(cls, value: Any) -> "CameraAngle | None":
        return _resolve(cls, value, _CAMERA_ANGLE_ALIASES)


class CameraMovement(str, Enum):
    STATIC = "static"
    PUSH_IN = "push_in"
    PULL_OUT = "pull_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    TILT_UP = "tilt_up"
    TILT_DOWN = "tilt_down"
    TRUCK_LEFT = "truck_left"
    TRUCK_RIGHT = "truck_right"
    CRANE_UP = "crane_up"
    CRANE_DOWN = "crane_down"
    TRACKING = "tracking"
    ORBIT = "orbit"
    CRANE_ORBIT = "crane_orbit"
    DOLLY_ZOOM = "dolly_zoom"
    PEDESTAL_UP = "pedestal_up"
    PEDESTAL_DOWN = "pedestal_down"
    WHIP_TILT = "whip_tilt"
    HANDHELD = "handheld"
    GIMBAL = "gimbal"
    STEADICAM = "steadicam"
    RACK_FOCUS = "rack_focus"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    WHIP_PAN = "whip_pan"
    AERIAL = "aerial"
    FPV = "fpv"

    @classmethod
    def _missing_(cls, value: Any) -> "CameraMovement | None":
        return _resolve(cls, value, _CAMERA_MOVEMENT_ALIASES)


class LightingStyle(str, Enum):
    GOLDEN_HOUR = "golden_hour"
    BLUE_HOUR = "blue_hour"
    OVERCAST = "overcast"
    HARD_KEY = "hard_key"
    SOFT_WINDOW = "soft_window"
    NEON_SPILL = "neon_spill"
    VOLUMETRIC = "volumetric"
    BACKLIGHT_RIM = "backlight_rim"
    HIGH_KEY = "high_key"
    LOW_KEY = "low_key"
    PRACTICAL = "practical"
    STUDIO = "studio"
    BUTTERFLY = "butterfly"
    TUNGSTEN = "tungsten"
    FLUORESCENT = "fluorescent"

    @classmethod
    def _missing_(cls, value: Any) -> "LightingStyle | None":
        return _resolve(cls, value, _LIGHTING_ALIASES)


class ColorGrade(str, Enum):
    NEUTRAL = "neutral"
    TEAL_ORANGE = "teal_orange"
    WARM = "warm"
    COOL = "cool"
    HIGH_SATURATION = "high_saturation"
    DESATURATED = "desaturated"
    BLACK_AND_WHITE = "black_and_white"

    @classmethod
    def _missing_(cls, value: Any) -> "ColorGrade | None":
        return _resolve(cls, value, _COLOR_GRADE_ALIASES)


class TransitionType(str, Enum):
    HARD_CUT = "hard_cut"
    MATCH_CUT = "match_cut"
    CUT_ON_ACTION = "cut_on_action"
    WHIP_PAN = "whip_pan"
    DISSOLVE = "dissolve"
    FADE_TO_BLACK = "fade_to_black"
    MORPH = "morph"
    J_CUT = "j_cut"
    L_CUT = "l_cut"
    SPEED_RAMP = "speed_ramp"

    @classmethod
    def _missing_(cls, value: Any) -> "TransitionType | None":
        return _resolve(cls, value, _TRANSITION_ALIASES)


class VfxType(str, Enum):
    SLOW_MOTION = "slow_motion"
    SPEED_RAMP = "speed_ramp"
    BULLET_TIME = "bullet_time"
    TIME_FREEZE = "time_freeze"
    PARTICLE_SIMULATION = "particle_simulation"
    VOLUMETRIC_LIGHT = "volumetric_light"
    SMOKE_FIRE_WATER = "smoke_fire_water"
    LENS_FLARE = "lens_flare"
    LIGHT_LEAK = "light_leak"
    GLITCH = "glitch"
    MORPH = "morph"

    @classmethod
    def _missing_(cls, value: Any) -> "VfxType | None":
        return _resolve(cls, value, _VFX_ALIASES)


class ScreenDirection(str, Enum):
    LEFT_TO_RIGHT = "left_to_right"
    RIGHT_TO_LEFT = "right_to_left"
    TOWARD_CAMERA = "toward_camera"
    AWAY_FROM_CAMERA = "away_from_camera"
    STATIC = "static"

    @classmethod
    def _missing_(cls, value: Any) -> "ScreenDirection | None":
        return _resolve(cls, value, _SCREEN_DIRECTION_ALIASES)


_SHOT_SIZE_ALIASES = {
    # English spellings and abbreviations
    "ews": "extreme_wide_shot",
    "extreme_wide": "extreme_wide_shot",
    "very_wide_shot": "extreme_wide_shot",
    "ultra_wide_shot": "extreme_wide_shot",
    "ws": "wide_shot",
    "wide": "wide_shot",
    "long_shot": "wide_shot",
    "ls": "wide_shot",
    "full": "full_shot",
    "fs": "full_shot",
    "full_body": "full_shot",
    "medium_wide": "medium_wide_shot",
    "medium_wide_shot": "medium_wide_shot",
    "mws": "medium_wide_shot",
    "wide_medium_shot": "medium_wide_shot",
    "cowboy": "cowboy_shot",
    "cowboy_shot_size": "cowboy_shot",
    "american_shot": "cowboy_shot",
    "牛仔镜头": "cowboy_shot",
    "ms": "medium_shot",
    "medium": "medium_shot",
    "mid_shot": "medium_shot",
    "mcu": "medium_close_up",
    "medium_closeup": "medium_close_up",
    "cu": "close_up",
    "close": "close_up",
    "closeup": "close_up",
    "close_shot": "close_up",
    "ecu": "extreme_close_up",
    "extreme_closeup": "extreme_close_up",
    "big_close_up": "extreme_close_up",
    "detail_shot": "extreme_close_up",
    "insert": "insert_shot",
    "cutaway": "insert_shot",
    "2_shot": "two_shot",
    "2s": "two_shot",
    "two": "two_shot",
    "ots": "over_the_shoulder",
    "over_shoulder": "over_the_shoulder",
    "over_the_shoulders": "over_the_shoulder",
    # Chinese terms
    "大远景": "extreme_wide_shot",
    "远景": "wide_shot",
    "全景": "full_shot",
    "中远景": "medium_wide_shot",
    "中景": "medium_shot",
    "中近景": "medium_close_up",
    "近景": "close_up",
    "特写": "close_up",
    "大特写": "extreme_close_up",
    "微距": "extreme_close_up",
    "插入": "insert_shot",
    "插入镜头": "insert_shot",
    "双人": "two_shot",
    "双人镜头": "two_shot",
    "过肩": "over_the_shoulder",
    "过肩镜头": "over_the_shoulder",
}

_CAMERA_ANGLE_ALIASES = {
    "eye": "eye_level",
    "front": "eye_level",
    "straight_on": "eye_level",
    "flat": "eye_level",
    "low": "low_angle",
    "from_below": "low_angle",
    "worm_eye": "low_angle",
    "ground": "ground_level",
    "ground_level": "ground_level",
    "floor_level": "ground_level",
    "地面视角": "ground_level",
    "high": "high_angle",
    "from_above": "high_angle",
    "top": "bird_eye",
    "overhead": "bird_eye",
    "top_down": "bird_eye",
    "aerial_view": "bird_eye",
    "dutch": "dutch_angle",
    "canted": "dutch_angle",
    "tilted": "dutch_angle",
    "first_person": "pov",
    "subjective": "pov",
    "平视": "eye_level",
    "正面": "eye_level",
    "仰拍": "low_angle",
    "低角度": "low_angle",
    "俯拍": "high_angle",
    "顶拍": "bird_eye",
    "鸟瞰": "bird_eye",
    "斜角": "dutch_angle",
    "主观": "pov",
}

_CAMERA_MOVEMENT_ALIASES = {
    "fixed": "static",
    "locked_off": "static",
    "locked": "static",
    "still": "static",
    "dolly_in": "push_in",
    "dolly_out": "pull_out",
    "push": "push_in",
    "pull": "pull_out",
    "pan": "pan_right",
    "tilt": "tilt_up",
    "crane": "crane_up",
    "jib_up": "crane_up",
    "jib_down": "crane_down",
    "tracking_shot": "tracking",
    "follow": "tracking",
    "following": "tracking",
    "arc": "orbit",
    "crane_orbit": "crane_orbit",
    "orbit_crane": "crane_orbit",
    "dolly_zoom": "dolly_zoom",
    "vertigo": "dolly_zoom",
    "vertigo_effect": "dolly_zoom",
    "zolly": "dolly_zoom",
    "pedestal": "pedestal_up",
    "ped_up": "pedestal_up",
    "ped_down": "pedestal_down",
    "whip_tilt": "whip_tilt",
    "升降环绕": "crane_orbit",
    "希区柯克变焦": "dolly_zoom",
    "滑动变焦": "dolly_zoom",
    "升降": "pedestal_up",
    "hand_held": "handheld",
    "steadicam_shot": "steadicam",
    "focus_pull": "rack_focus",
    "zoom": "zoom_in",
    "drone": "aerial",
    "aerial_shot": "aerial",
    "fps": "fpv",
    "固定": "static",
    "固定机位": "static",
    "推": "push_in",
    "推镜": "push_in",
    "拉": "pull_out",
    "拉镜": "pull_out",
    "摇": "pan_right",
    "横摇": "pan_right",
    "移": "truck_right",
    "横移": "truck_right",
    "升": "crane_up",
    "降": "crane_down",
    "跟": "tracking",
    "跟拍": "tracking",
    "跟踪": "tracking",
    "环绕": "orbit",
    "手持": "handheld",
    "稳定器": "gimbal",
    "变焦": "zoom_in",
    "甩": "whip_pan",
    "航拍": "aerial",
    "焦点转换": "rack_focus",
}

_LIGHTING_ALIASES = {
    "golden": "golden_hour",
    "blue": "blue_hour",
    "cloudy": "overcast",
    "soft": "soft_window",
    "window": "soft_window",
    "natural": "soft_window",
    "hard": "hard_key",
    "neon": "neon_spill",
    "rim": "backlight_rim",
    "backlight": "backlight_rim",
    "high_key_light": "high_key",
    "low_key_light": "low_key",
    "bright": "high_key",
    "dark": "low_key",
    "高调": "high_key",
    "亮调": "high_key",
    "低调": "low_key",
    "暗调": "low_key",
    "practical_light": "practical",
    "studio_light": "studio",
    "golden_hour_light": "golden_hour",
    "黄金时刻": "golden_hour",
    "蓝调": "blue_hour",
    "阴天": "overcast",
    "硬光": "hard_key",
    "窗光": "soft_window",
    "柔光": "soft_window",
    "霓虹": "neon_spill",
    "体积光": "volumetric",
    "轮廓光": "backlight_rim",
    "背光": "backlight_rim",
    "实景光": "practical",
    "影棚": "studio",
    "蝴蝶光": "butterfly",
    "钨丝灯": "tungsten",
    "荧光灯": "fluorescent",
}

_COLOR_GRADE_ALIASES = {
    "teal_and_orange": "teal_orange",
    "orange_teal": "teal_orange",
    "warm_tone": "warm",
    "cool_tone": "cool",
    "saturated": "high_saturation",
    "low_saturation": "desaturated",
    "desat": "desaturated",
    "bw": "black_and_white",
    "b_w": "black_and_white",
    "monochrome": "black_and_white",
    "black_white": "black_and_white",
    "青橙": "teal_orange",
    "青橙调": "teal_orange",
    "暖": "warm",
    "暖调": "warm",
    "冷": "cool",
    "冷调": "cool",
    "高饱和": "high_saturation",
    "低饱和": "desaturated",
    "黑白": "black_and_white",
    "中性": "neutral",
}

_TRANSITION_ALIASES = {
    "cut": "hard_cut",
    "straight_cut": "hard_cut",
    "match": "match_cut",
    "action_cut": "cut_on_action",
    "whip": "whip_pan",
    "fade": "dissolve",
    "fade_out": "dissolve",
    "fade_to_black": "fade_to_black",
    "fade_out_to_black": "fade_to_black",
    "黑场": "fade_to_black",
    "淡出到黑": "fade_to_black",
    "cross_dissolve": "dissolve",
    "morph_cut": "morph",
    "speedramp": "speed_ramp",
    "硬切": "hard_cut",
    "切": "hard_cut",
    "匹配剪辑": "match_cut",
    "动作剪辑": "cut_on_action",
    "甩镜": "whip_pan",
    "叠化": "dissolve",
    "淡入淡出": "dissolve",
    "变形": "morph",
}

_VFX_ALIASES = {
    "slowmo": "slow_motion",
    "slow_mo": "slow_motion",
    "slow": "slow_motion",
    "speedramp": "speed_ramp",
    "bullet_time_effect": "bullet_time",
    "matrix": "bullet_time",
    "freeze": "time_freeze",
    "freeze_frame": "time_freeze",
    "particles": "particle_simulation",
    "particle": "particle_simulation",
    "volumetric": "volumetric_light",
    "god_rays": "volumetric_light",
    "smoke": "smoke_fire_water",
    "fire": "smoke_fire_water",
    "water": "smoke_fire_water",
    "rain": "smoke_fire_water",
    "flare": "lens_flare",
    "anamorphic_flare": "lens_flare",
    "leak": "light_leak",
    "glitch_effect": "glitch",
    "morphing": "morph",
    "慢动作": "slow_motion",
    "升格": "slow_motion",
    "子弹时间": "bullet_time",
    "时间冻结": "time_freeze",
    "粒子": "particle_simulation",
    "体积光": "volumetric_light",
    "烟雾": "smoke_fire_water",
    "火焰": "smoke_fire_water",
    "水": "smoke_fire_water",
    "雨": "smoke_fire_water",
    "镜头光晕": "lens_flare",
    "光晕": "lens_flare",
    "漏光": "light_leak",
    "故障": "glitch",
    "变形": "morph",
}

_SCREEN_DIRECTION_ALIASES = {
    "ltr": "left_to_right",
    "left_right": "left_to_right",
    "rtl": "right_to_left",
    "right_left": "right_to_left",
    "toward": "toward_camera",
    "towards_camera": "toward_camera",
    "inward": "toward_camera",
    "away": "away_from_camera",
    "outward": "away_from_camera",
    "still": "static",
    "从左到右": "left_to_right",
    "从右到左": "right_to_left",
    "朝向镜头": "toward_camera",
    "背离镜头": "away_from_camera",
    "静止": "static",
}


class CinematographySpec(BaseModel):
    """Structured camera, lighting, and editorial choices for one shot."""

    model_config = ConfigDict(extra="forbid")

    shot_size: ShotSize = ShotSize.MS
    camera_angle: CameraAngle = CameraAngle.EYE_LEVEL
    camera_movement: CameraMovement = CameraMovement.STATIC
    lens: str = Field(default="35mm", max_length=50)
    composition: str = Field(default="rule_of_thirds", max_length=100)
    lighting_style: LightingStyle = LightingStyle.SOFT_WINDOW
    color_grade: ColorGrade = ColorGrade.NEUTRAL
    transition: TransitionType = TransitionType.HARD_CUT
    vfx: list[VfxType] = Field(default_factory=list)
    screen_direction: ScreenDirection | None = None
