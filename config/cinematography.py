"""Professional cinematography vocabulary and prompt-model reference data.

The terms are industry-standard film-production vocabulary. The model notes are
reference values compiled from public documentation and the open references
listed in ``docs/references.md``; vendor limits change, so the adapter that
actually calls a generation model must verify them again.

No external repository code or long text is copied into this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from schemas.cinematography import (
    CameraAngle,
    CameraMovement,
    ColorGrade,
    LightingStyle,
    ShotSize,
    TransitionType,
    VfxType,
)

SHOT_SIZE_LABELS: dict[ShotSize, str] = {
    ShotSize.EWS: "极广角 / 大远景",
    ShotSize.WS: "广角 / 远景",
    ShotSize.FULL: "全景 / 全身",
    ShotSize.MEDIUM_WIDE: "中远景 / 宽中景",
    ShotSize.COWBOY: "牛仔镜头",
    ShotSize.MS: "中景",
    ShotSize.MCU: "中近景 / 中特写",
    ShotSize.CU: "近景 / 特写",
    ShotSize.ECU: "大特写",
    ShotSize.INSERT: "插入镜头",
    ShotSize.TWO_SHOT: "双人镜头",
    ShotSize.OTS: "过肩镜头",
}

CAMERA_ANGLE_LABELS: dict[CameraAngle, str] = {
    CameraAngle.EYE_LEVEL: "平视",
    CameraAngle.LOW_ANGLE: "仰拍",
    CameraAngle.GROUND: "地面视角",
    CameraAngle.HIGH_ANGLE: "俯拍",
    CameraAngle.BIRD_EYE: "鸟瞰 / 顶拍",
    CameraAngle.DUTCH: "荷兰角 / 倾斜构图",
    CameraAngle.POV: "主观视角",
}

CAMERA_MOVEMENT_LABELS: dict[CameraMovement, str] = {
    CameraMovement.STATIC: "固定机位",
    CameraMovement.PUSH_IN: "推镜",
    CameraMovement.PULL_OUT: "拉镜",
    CameraMovement.PAN_LEFT: "左横摇",
    CameraMovement.PAN_RIGHT: "右横摇",
    CameraMovement.TILT_UP: "上纵摇",
    CameraMovement.TILT_DOWN: "下纵摇",
    CameraMovement.TRUCK_LEFT: "左横移",
    CameraMovement.TRUCK_RIGHT: "右横移",
    CameraMovement.CRANE_UP: "升镜",
    CameraMovement.CRANE_DOWN: "降镜",
    CameraMovement.TRACKING: "跟踪镜头",
    CameraMovement.ORBIT: "环绕",
    CameraMovement.CRANE_ORBIT: "升降环绕",
    CameraMovement.DOLLY_ZOOM: "希区柯克变焦",
    CameraMovement.PEDESTAL_UP: "升降台上升",
    CameraMovement.PEDESTAL_DOWN: "升降台下降",
    CameraMovement.WHIP_TILT: "甩摇",
    CameraMovement.HANDHELD: "手持",
    CameraMovement.GIMBAL: "稳定器",
    CameraMovement.STEADICAM: "斯坦尼康",
    CameraMovement.RACK_FOCUS: "焦点转换",
    CameraMovement.ZOOM_IN: "变焦推进",
    CameraMovement.ZOOM_OUT: "变焦拉远",
    CameraMovement.WHIP_PAN: "甩镜",
    CameraMovement.AERIAL: "航拍",
    CameraMovement.FPV: "FPV 穿越",
}

LIGHTING_LABELS: dict[LightingStyle, str] = {
    LightingStyle.GOLDEN_HOUR: "黄金时刻",
    LightingStyle.BLUE_HOUR: "蓝调时刻",
    LightingStyle.OVERCAST: "阴天漫射光",
    LightingStyle.HARD_KEY: "硬光",
    LightingStyle.SOFT_WINDOW: "柔和窗光",
    LightingStyle.NEON_SPILL: "霓虹溢光",
    LightingStyle.VOLUMETRIC: "体积光",
    LightingStyle.BACKLIGHT_RIM: "背光 / 轮廓光",
    LightingStyle.HIGH_KEY: "高调光",
    LightingStyle.LOW_KEY: "低调光",
    LightingStyle.PRACTICAL: "实景灯光",
    LightingStyle.STUDIO: "影棚灯光",
    LightingStyle.BUTTERFLY: "蝴蝶光",
    LightingStyle.TUNGSTEN: "钨丝灯暖光",
    LightingStyle.FLUORESCENT: "荧光冷白光",
}

COLOR_GRADE_LABELS: dict[ColorGrade, str] = {
    ColorGrade.NEUTRAL: "自然中性",
    ColorGrade.TEAL_ORANGE: "青橙调",
    ColorGrade.WARM: "暖调",
    ColorGrade.COOL: "冷调",
    ColorGrade.HIGH_SATURATION: "高饱和",
    ColorGrade.DESATURATED: "低饱和",
    ColorGrade.BLACK_AND_WHITE: "黑白",
}

TRANSITION_LABELS: dict[TransitionType, str] = {
    TransitionType.HARD_CUT: "硬切",
    TransitionType.MATCH_CUT: "匹配剪辑",
    TransitionType.CUT_ON_ACTION: "动作剪辑",
    TransitionType.WHIP_PAN: "甩镜转场",
    TransitionType.DISSOLVE: "叠化",
    TransitionType.FADE_TO_BLACK: "淡出到黑",
    TransitionType.MORPH: "形变转场",
    TransitionType.J_CUT: "J-cut 声音先入",
    TransitionType.L_CUT: "L-cut 声音延后",
    TransitionType.SPEED_RAMP: "速度渐变",
}

VFX_LABELS: dict[VfxType, str] = {
    VfxType.SLOW_MOTION: "慢动作",
    VfxType.SPEED_RAMP: "速度渐变",
    VfxType.BULLET_TIME: "子弹时间",
    VfxType.TIME_FREEZE: "时间冻结",
    VfxType.PARTICLE_SIMULATION: "粒子模拟",
    VfxType.VOLUMETRIC_LIGHT: "体积光",
    VfxType.SMOKE_FIRE_WATER: "烟火水等物理特效",
    VfxType.LENS_FLARE: "镜头光斑",
    VfxType.LIGHT_LEAK: "漏光",
    VfxType.GLITCH: "故障闪烁",
    VfxType.MORPH: "形变",
}


@dataclass(frozen=True)
class ModelProfile:
    """Generation and prompt-writing constraints for one video model.

    ``clip_seconds`` are the lengths one *generation call* can actually return:
    the values the vendor exposes as duration buttons. A finished film is cut
    together from whole clips, so every duration the studio plans has to be
    expressible as ``clip_count × clip_seconds``. Treating a 90-second film as a
    single call is the bug this field exists to prevent.

    ``negative_prompt_support`` is one of:

    - ``dedicated``: a separate negative-prompt field exists;
    - ``inline``: negatives are written inside the positive prompt;
    - ``partial``: support depends on the product surface or version;
    - ``none``: negatives are unsupported and can be harmful.
    """

    key: str
    display_name: str
    provider: str
    clip_seconds: tuple[float, ...]
    negative_prompt_support: Literal["dedicated", "inline", "partial", "none"]
    preferred_language: Literal["zh", "en", "either"]
    supports_multi_shot: bool
    notes: str

    @property
    def max_single_shot_seconds(self) -> float:
        """Longest clip a single generation call can return."""

        return max(self.clip_seconds)


MODEL_PROFILES: dict[str, ModelProfile] = {
    "generic": ModelProfile(
        key="generic",
        display_name="通用视频模型",
        provider="generic",
        clip_seconds=(5, 10),
        negative_prompt_support="partial",
        preferred_language="either",
        supports_multi_shot=True,
        notes="未指定目标模型时使用保守默认值；生成前需按实际模型能力复核。",
    ),
    "seedance": ModelProfile(
        key="seedance",
        display_name="Seedance 2.x",
        provider="ByteDance",
        clip_seconds=(5, 10, 15),
        negative_prompt_support="partial",
        preferred_language="either",
        supports_multi_shot=True,
        notes="8 要素公式；15 秒内 3-5 个镜头较稳；国内平台对 IP/品牌词过滤严格。",
    ),
    "veo": ModelProfile(
        key="veo",
        display_name="Veo 3.x",
        provider="Google DeepMind",
        clip_seconds=(4, 6, 8),
        negative_prompt_support="dedicated",
        preferred_language="en",
        supports_multi_shot=True,
        notes="单段常见 4/6/8 秒，可用 Extend 续接；负向字段建议写名词短语。",
    ),
    "kling": ModelProfile(
        key="kling",
        display_name="Kling 3.x",
        provider="Kuaishou",
        clip_seconds=(5, 10),
        negative_prompt_support="dedicated",
        preferred_language="either",
        supports_multi_shot=True,
        notes="有独立负向字段；违禁词过滤敏感，生成前清理 IP/品牌词。",
    ),
    "sora": ModelProfile(
        key="sora",
        display_name="Sora 2",
        provider="OpenAI",
        clip_seconds=(5, 10, 15, 20),
        negative_prompt_support="inline",
        preferred_language="en",
        supports_multi_shot=True,
        notes="无独立负向字段；IP 过滤严格；服务可用性需按官方最新状态确认。",
    ),
    "runway": ModelProfile(
        key="runway",
        display_name="Runway Gen-4.x",
        provider="Runway",
        clip_seconds=(5, 10),
        negative_prompt_support="none",
        preferred_language="en",
        supports_multi_shot=False,
        notes="不支持负向提示词；no/avoid 可能产生反效果，用正向描述替代。",
    ),
    "wan": ModelProfile(
        key="wan",
        display_name="Wan 2.x",
        provider="Alibaba",
        clip_seconds=(5, 10),
        negative_prompt_support="dedicated",
        preferred_language="zh",
        supports_multi_shot=True,
        notes="Entity + Scene + Motion + Sound；中文原生；适合音频与口型场景。",
    ),
    "hailuo": ModelProfile(
        key="hailuo",
        display_name="Hailuo 02",
        provider="MiniMax",
        clip_seconds=(5, 10),
        negative_prompt_support="partial",
        preferred_language="either",
        supports_multi_shot=False,
        notes="克制的导演式写法，强调物理细节；负向词不宜堆砌。",
    ),
    "pika": ModelProfile(
        key="pika",
        display_name="Pika 2.5",
        provider="Pika Labs",
        clip_seconds=(5, 10),
        negative_prompt_support="partial",
        preferred_language="en",
        supports_multi_shot=False,
        notes="Pikaframes 关键帧可到约 25 秒；普通文生视频仍以 5/10 秒为主。",
    ),
    "jimeng": ModelProfile(
        key="jimeng",
        display_name="即梦 3.0",
        provider="ByteDance",
        clip_seconds=(5, 10, 15),
        negative_prompt_support="partial",
        preferred_language="zh",
        supports_multi_shot=True,
        notes="中文友好；底层与 Seedance 相关；消费端时长受预设按钮限制。",
    ),
}


@dataclass(frozen=True)
class ConflictRule:
    """A pair of term groups that should not be requested together."""

    left_terms: tuple[str, ...]
    right_terms: tuple[str, ...]
    severity: Literal["error", "warning"]
    reason: str


CONFLICT_RULES: tuple[ConflictRule, ...] = (
    ConflictRule(
        left_terms=(
            "film grain",
            "8mm",
            "vhs",
            "retro grain",
            "胶片颗粒",
            "8毫米",
            "复古胶片",
        ),
        right_terms=(
            "4k",
            "8k",
            "ultra sharp",
            "hyper detailed",
            "超清",
            "极致清晰",
            "超锐利",
        ),
        severity="error",
        reason="胶片颗粒 / 复古质感与 4K 超清 / 超锐利互相抵消。",
    ),
    ConflictRule(
        left_terms=("slow motion", "slow-mo", "bullet time", "慢动作", "子弹时间"),
        right_terms=(
            "high-speed action",
            "fast action",
            "rapid action",
            "高速动作",
            "极速动作",
        ),
        severity="error",
        reason="慢动作与高速动作是速度矛盾。",
    ),
    ConflictRule(
        left_terms=("anime", "cel-shaded", "ghibli", "动漫", "二次元"),
        right_terms=(
            "photorealistic",
            "hyper-realistic",
            "live-action",
            "写实",
            "真人实拍",
        ),
        severity="error",
        reason="动漫 / 赛璐璐风格与写实 / 真人实拍风格冲突。",
    ),
    ConflictRule(
        left_terms=("static camera", "locked-off", "fixed camera", "固定机位", "固定镜头"),
        right_terms=(
            "handheld",
            "whip pan",
            "tracking shot",
            "手持",
            "甩镜",
            "跟踪镜头",
        ),
        severity="error",
        reason="固定机位与手持 / 甩镜 / 跟踪运动冲突。",
    ),
    ConflictRule(
        left_terms=("cinematic", "film look", "电影感"),
        right_terms=("documentary handheld", "raw handheld", "vérité", "纪实手持", "新闻手持"),
        severity="warning",
        reason="电影感与纪实手持可能互相拉扯，确认是否真的需要。",
    ),
)


CAMERA_MOVEMENT_KEYWORDS: dict[CameraMovement, tuple[str, ...]] = {
    CameraMovement.STATIC: (
        "固定机位",
        "固定镜头",
        "static camera",
        "locked-off",
        "fixed camera",
    ),
    CameraMovement.PUSH_IN: (
        "推镜",
        "缓慢推近",
        "向前推进",
        "push in",
        "dolly in",
        "slow push-in",
    ),
    CameraMovement.PULL_OUT: (
        "拉镜",
        "缓慢拉远",
        "向后拉远",
        "pull back",
        "dolly out",
        "pull out",
    ),
    CameraMovement.PAN_LEFT: ("左横摇", "向左摇", "pan left"),
    CameraMovement.PAN_RIGHT: ("右横摇", "向右摇", "pan right"),
    CameraMovement.TILT_UP: ("上纵摇", "向上摇", "tilt up"),
    CameraMovement.TILT_DOWN: ("下纵摇", "向下摇", "tilt down"),
    CameraMovement.TRUCK_LEFT: ("左横移", "向左移", "truck left"),
    CameraMovement.TRUCK_RIGHT: ("右横移", "向右移", "truck right"),
    CameraMovement.CRANE_UP: ("升镜", "升起", "crane up"),
    CameraMovement.CRANE_DOWN: ("降镜", "降下", "crane down"),
    CameraMovement.TRACKING: ("跟踪镜头", "跟拍", "跟踪拍摄", "tracking shot", "tracking"),
    CameraMovement.ORBIT: ("环绕", "orbit", "arc shot"),
    CameraMovement.HANDHELD: ("手持", "handheld"),
    CameraMovement.GIMBAL: ("稳定器", "gimbal"),
    CameraMovement.STEADICAM: ("斯坦尼康", "steadicam"),
    CameraMovement.RACK_FOCUS: ("焦点转换", "rack focus", "pull focus"),
    CameraMovement.ZOOM_IN: ("变焦推进", "zoom in"),
    CameraMovement.ZOOM_OUT: ("变焦拉远", "zoom out"),
    CameraMovement.WHIP_PAN: ("甩镜", "whip pan"),
    CameraMovement.AERIAL: ("航拍", "无人机", "aerial", "drone"),
    CameraMovement.FPV: ("fpv", "穿越机", "第一人称穿越"),
}


# Fields a generated professional shot must contain before prompt assembly.
# ``sound`` is intentionally optional because silent shots are valid.
PROFESSIONAL_SHOT_FIELDS: tuple[str, ...] = (
    "shot_id",
    "narrative_purpose",
    "cinematography",
    "action_start",
    "action_end",
    "image_prompt",
    "video_prompt",
    "negative_prompt",
    "continuity_locks",
)
