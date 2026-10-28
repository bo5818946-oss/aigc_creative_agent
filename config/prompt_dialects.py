"""Prompt dialects: one writing standard per genre of AI video work.

Why this is not another option table
------------------------------------
A hard-coded table decides *what the user may choose*. A dialect decides *how a
prompt must be written* — it encodes craft knowledge (what an e-commerce main
image must guarantee, how a sci-fi shot proves scale, why an anime prompt must
ban photoreal grain) and is fed to the model as a specification. The model still
writes every sentence; the dialect only says what a professional in that genre
would never omit and would never do.

Each dialect carries machine-checkable rules as well, so "quality" is not a
claim: ``audit_package`` can report which genre requirements a generated
package actually satisfies.

Adding a genre means adding one ``PromptDialect`` entry here. Nothing in the
pipeline switches on genre names anywhere else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class PromptDialect:
    key: str
    label: str
    #: Who the writer must be for this genre.
    role: str
    #: What the finished prompt has to achieve, in one or two sentences.
    intent: str
    #: Required sections of the whole-film prompt, in order.
    sections: tuple[str, ...]
    #: Production parameters every per-shot prompt must state.
    shot_rules: tuple[str, ...]
    #: Genre-specific additions for still-image prompts.
    image_emphasis: tuple[str, ...] = ()
    #: Genre-specific additions for motion/video prompts.
    video_emphasis: tuple[str, ...] = ()
    #: Hard requirements that must literally appear somewhere in the package.
    must_include: tuple[str, ...] = ()
    #: Moves that break this genre and must not appear.
    forbidden: tuple[str, ...] = ()
    #: Default negative constraints for the genre.
    negatives: tuple[str, ...] = ()
    #: (label, regex) pairs used by ``audit_package``.
    checks: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    #: Expected length of the package; an e-commerce brief must not become a
    #: 5000-character film treatment.
    length_hint: str = "整片 2500–5000 字，逐镜头每条 120–260 字"

    def system_block(self) -> str:
        lines = [
            f"【体裁】{self.label}",
            f"【你的身份】{self.role}",
            f"【这个体裁的提示词必须做到】{self.intent}",
            "",
            "【整片提示词必须按顺序写出的章节】",
        ]
        lines += [f"{index}. {item}" for index, item in enumerate(self.sections, 1)]
        lines += ["", "【图片提示词 image_prompt：冻结哪一帧】"]
        lines += [f"- {item}" for item in IMAGE_RULES]
        lines += [f"- {item}" for item in self.image_emphasis]
        lines += ["", "【视频提示词 video_prompt：画面怎么变】"]
        lines += [f"- {item}" for item in VIDEO_RULES]
        lines += [f"- {item}" for item in self.video_emphasis]
        if self.shot_rules:
            lines += ["", "【两种提示词都要写清的体裁参数】"]
            lines += [f"- {item}" for item in self.shot_rules]
        if self.must_include:
            lines += ["", "【全篇必须出现的信息】"]
            lines += [f"- {item}" for item in self.must_include]
        if self.forbidden:
            lines += ["", f"【{self.label}里禁止出现的写法】"]
            lines += [f"- {item}" for item in self.forbidden]
        if self.negatives:
            lines += ["", "【negative_prompt 默认要覆盖】"]
            lines += [f"- {item}" for item in self.negatives]
        return "\n".join(lines)


#: Format-level rules. An image prompt freezes a frame; a video prompt evolves
#: one. These are true for every genre; the genre adds emphasis on top.
IMAGE_RULES: tuple[str, ...] = (
    "冻结哪一帧：这是这一镜最有信息量的瞬间，不是过程",
    "景别、焦段与构图（主体在画面中的位置与占比）",
    "光位、光质、光比与色温",
    "材质、肌理与色彩（写具体，不写“高级感”）",
    "风格与渲染方式（写实 / 胶片 / 赛璐璐 / 渲染器）",
    "画幅与留白（哪里需要留白、给谁留）",
    "只用静帧能表达的方式暗示运动：姿态、方向、惯性",
    "禁止写时间推进、镜头运动过程、转场和音频",
)

VIDEO_RULES: tuple[str, ...] = (
    "时长与节拍：这条覆盖几秒、几个动作节拍",
    "起始状态 → 结束状态：画面里什么变了、什么必须不变",
    "摄影机运动：类型（推/拉/摇/移/跟/升降/环绕）、方向、速度",
    "主体运动：动作链的因果，以及连续性（服装、道具、方向）",
    "环境运动：风、水、粒子、光变化如何参与画面",
    "切点与转场：这一镜如何进入和离开",
    "如果目标模型支持音频：环境声、拟音、音乐方向",
    "禁止只写一帧的静态描述；这一条必须能看出变化",
)


ECOMMERCE = PromptDialect(
    key="ecommerce",
    label="电商视觉",
    role="电商视觉总监兼 AI 图像提示词工程师，做过主图、详情页和投放素材",
    intent=(
        "让商品在一秒内被看清、看得准，并产生点击欲望。"
        "信息优先级高于情绪：商品形态、材质、颜色必须还原，背景与光只服务商品。"
    ),
    sections=(
        "商品与核心卖点（一句话说清这张图/这条片卖什么）",
        "构图与商品占画面比例，以及文字安全区",
        "光线方案与材质还原（光位、光比、色温、反射控制）",
        "背景与环境处理（要什么、不要什么）",
        "是否需要模特或手部，以及出现方式",
        "平台规格：画幅、时长、首帧可读性",
        "色准要求：与真实商品颜色的偏差容忍度",
    ),
    shot_rules=(
        "商品占画面比例（例如 60% 主视觉、30% 场景图）",
        "背景处理方式与是否留文字位",
        "光位、光比、色温，以及高光是否溢出",
        "出现的手部/模特只做功能动作，不抢商品",
        "这一帧要传达的卖点关键词",
    ),
    must_include=("商品", "光", "背景", "画幅"),
    forbidden=(
        "遮挡商品主体或让商品小于画面 1/4",
        "戏剧化强光造成材质与颜色误读",
        "与卖点无关的叙事人物或剧情",
        "把商品放在画面边缘导致裁切风险",
    ),
    negatives=(
        "商品变形", "多余手指", "伪文字与乱码", "色差", "过曝高光",
        "塑料感", "水印", "logo 变形",
    ),
    length_hint="整片 800–1500 字，逐镜头每条 80–160 字",
    checks=(
        ("提到商品占画面比例", r"占画面|\d+\s*%|主体占比"),
        ("提到光线方案", r"光位|光比|色温|柔光|硬光|侧光|顶光"),
        ("提到画幅或平台规格", r"16:9|9:16|1:1|4:3|画幅|竖屏|横屏"),
    ),
)

BRAND_AD = PromptDialect(
    key="brand_ad",
    label="品牌广告 TVC",
    role="国际 4A 创意总监兼广告导演，擅长 15–60 秒品牌片",
    intent=(
        "全片只服务一个记忆点，产品是落点而不是全部。"
        "每个镜头都要有明确的叙事职责，不能靠堆漂亮画面撑时长。"
    ),
    sections=(
        "片名与规格（时长、画幅、类型、目标模型）",
        "核心创意与洞察：这支片想说的一句话",
        "叙事弧线：开场钩子、推进、转折、落点",
        "主体资产锁定与连续性规则",
        "按时间顺序的逐段分镜（每段写空间、主体动作、摄影机、光线）",
        "摄影与运动系统",
        "光线、色彩与材质",
        "声音与音乐方向",
        "转场逻辑",
        "结尾落点与品牌记忆",
        "全片负面约束",
    ),
    shot_rules=(
        "这个镜头的叙事职责（建立 / 推进 / 转折 / 收束）",
        "主体动作与走位，起止状态",
        "摄影机位置、运动与被摄体的相对关系",
        "光线来源与色温",
        "必须保持的连续性事实",
    ),
    must_include=("记忆点", "落点", "连续性"),
    forbidden=(
        "堆砌“电影感、高级感、震撼”等空词",
        "产品与人物抢焦点",
        "没有动机的运镜",
        "镜头之间主体外观漂移",
    ),
    negatives=("主体漂移", "多余肢体", "文字乱码", "logo 变形", "风格混用"),
    checks=(
        ("写了叙事弧线或结构", r"开场|推进|转折|落点|弧线"),
        ("写了摄影机运动", r"推近|拉远|跟拍|横移|环绕|固定机位|摇"),
        ("写了负面约束", r"负面|negative|避免"),
    ),
)

FILM_SCIFI = PromptDialect(
    key="film_scifi",
    label="科幻影视",
    role="科幻片导演兼概念设计师，重视世界观自洽与技术可信度",
    intent=(
        "让观众相信这个世界真的存在：技术设定有来源、空间尺度可读、"
        "光源有物理出处。奇观必须能被解释，不能靠魔法光。"
    ),
    sections=(
        "世界观与技术设定：这个世界的规则、年代、技术水平",
        "空间与尺度：场景有多大，人/物在其中的比例参照",
        "角色造型与服装的功能性",
        "镜头语言：大远景建尺度、微距建细节",
        "光源逻辑：每个光源的物理来源",
        "材质与介质：雾、尘、反射、湿气如何参与画面",
        "UI / 全息 / 屏幕信息的呈现方式",
        "声音设计：环境嗡鸣、机械、空间混响",
        "连续性：跨镜头的设定一致性",
    ),
    shot_rules=(
        "这一镜的空间尺度参照物（人、门、舷窗等）",
        "光源来自哪里，是实用光源还是环境光",
        "关键技术细节（材质、结构、界面信息）",
        "介质（雾/尘/水）如何影响光与能见度",
        "与前一镜的空间关系",
    ),
    must_include=("尺度", "光源"),
    forbidden=(
        "同一画面混用互斥的科技风格",
        "没有物理来源的发光体",
        "现代日常物品无解释地出现在未来场景",
        "镜头之间光照方向矛盾",
    ),
    negatives=(
        "塑料感", "卡通化", "光源矛盾", "时代错置道具",
        "过度镜头污渍", "UI 伪文字",
    ),
    checks=(
        ("给了尺度参照", r"尺度|参照|比例|巨大|渺小|远景"),
        ("交代了光源来源", r"光源|实用光|环境光|发光|照明"),
        ("交代了空间或介质", r"雾|尘|湿|反射|空间|舱|走廊"),
    ),
)

FILM_HUMAN = PromptDialect(
    key="film_human",
    label="人文剧情",
    role="作者电影导演兼摄影指导，重视表演、空间与克制",
    intent=(
        "让人物和空间自己说话。摄影克制、光源可用、情绪靠状态而不是台词，"
        "镜头之间的距离变化就是叙事。"
    ),
    sections=(
        "人物与关系：谁，和谁，什么张力",
        "时间与空间：发生在什么时候、什么质地的地方",
        "表演基调与走位",
        "镜头距离与景别策略",
        "可用光与实景光源",
        "声音与环境：现场声、留白、静默",
        "情绪曲线的克制处理",
    ),
    shot_rules=(
        "人物此刻的状态与视线方向",
        "机位高度、距离与景别（近景/中景/全景）",
        "走位起止点，以及与空间的关系",
        "光源：窗户、台灯、天光等实景来源",
        "这一镜的情绪落点",
    ),
    must_include=("视线", "景别", "光源"),
    forbidden=(
        "广告式大光比打光",
        "无动机的快速运镜",
        "用台词解释情绪",
        "过度调色掩盖表演",
    ),
    negatives=(
        "脸部变形", "多余手指", "过度锐化", "塑料皮肤",
        "滥用镜头光晕", "影棚感",
    ),
    checks=(
        ("写了景别或机位距离", r"近景|中景|全景|特写|机位|距离"),
        ("写了实景光源", r"窗|天光|台灯|实景|自然光|侧光"),
        ("写了视线或表演状态", r"视线|注视|停顿|呼吸|表情|沉默"),
    ),
)

FILM_ACTION = PromptDialect(
    key="film_action",
    label="动作 / 追逐",
    role="动作片导演兼特技指导，重视空间关系与动作因果",
    intent=(
        "让观众在任何一秒都清楚谁在哪、朝哪去、为什么快。"
        "速度必须被参照物证明，方向必须连续，动作必须有因果。"
    ),
    sections=(
        "追逐路线与空间地图：从哪到哪，经过什么",
        "动作因果：谁在追谁，为什么，代价是什么",
        "镜头与剪辑节奏：长镜头压迫 vs 碎切冲击",
        "速度的证明方式：参照物、视差、镜头追随",
        "运动方向与轴线规则",
        "安全边界与物理可信度",
        "声音：引擎、风、撞击、呼吸",
    ),
    shot_rules=(
        "运动方向（从画面哪一侧到哪一侧）",
        "近景参照物或速度参照物",
        "摄影机与被摄体的相对运动关系",
        "动作的因果（因为什么而发生）",
        "与前后镜头的轴线关系",
    ),
    must_include=("方向", "参照"),
    forbidden=(
        "无参照的高速模糊",
        "跳轴导致方向混乱",
        "动作因果断裂",
        "为了酷而牺牲物理可信度",
    ),
    negatives=(
        "方向混乱", "肢体扭曲", "穿模", "运动模糊过度",
        "车体变形", "多余人物",
    ),
    checks=(
        ("写了运动方向", r"从左|从右|向画面|方向|轴线"),
        ("写了速度参照", r"参照|掠过|视差|标线|近景"),
        ("写了动作因果", r"因为|为了|追|逃|撞击|闪避"),
    ),
)

ANIME = PromptDialect(
    key="anime",
    label="动画 / 动漫",
    role="动画监督兼 AI 作画提示词工程师，熟悉赛璐璐、厚涂与三维渲染的差别",
    intent=(
        "画风统一、作画重心明确。动画不是实拍：线条、上色和作画节奏就是摄影语言，"
        "任何实拍质感都会破坏风格。"
    ),
    sections=(
        "画风定义：流派、年代、参考作品",
        "线条与上色方式：赛璐璐 / 厚涂 / 渐变，线宽与描线习惯",
        "角色设定：发型、比例、服装、表情语言",
        "镜头与构图：动画特有的透视夸张与构图",
        "作画重心：这一卡要重点画什么（原画感 / 中割感）",
        "背景美术：手绘感、色块层次",
        "特效与光：光斑、速度线、色彩分层",
    ),
    shot_rules=(
        "画风参照与年代",
        "线条粗细与描线方式",
        "上色方式与色块层次",
        "这一卡的作画重心（动作、表情、机械细节）",
        "背景是手绘背景还是纯色/渐变",
    ),
    must_include=("画风", "线条"),
    forbidden=(
        "实拍质感：胶片颗粒、真实景深、镜头污渍",
        "三维渲染感混入二维作画",
        "同一镜头混用两种画风",
        "写实皮肤纹理",
    ),
    negatives=(
        "写实皮肤纹理", "实拍景深", "3D 渲染感", "线条抖动",
        "色块不匀", "画风混用",
    ),
    length_hint="整片 1500–3000 字，逐镜头每条 100–220 字",
    checks=(
        ("定义了画风", r"画风|赛璐璐|厚涂|动画|漫画|番剧|二维"),
        ("写了线条或上色", r"线条|描线|上色|色块|平涂"),
        ("写了作画重心", r"作画|原画|关键帧|中割|重心"),
    ),
)

EXPERIMENTAL = PromptDialect(
    key="experimental",
    label="创意实验",
    role="实验影像艺术家兼视觉设计师",
    intent=(
        "概念先行，形式即内容。允许反叙事，但必须有自洽的视觉规则，"
        "而且这条规则要能被重复使用。"
    ),
    sections=(
        "概念与视觉规则：这支片遵守什么法则",
        "视觉母题与它的变形方式",
        "材质、肌理与运动逻辑",
        "镜头与节奏：重复、循环、断裂",
        "色彩与光的形式化处理",
        "声音与静默的使用",
    ),
    shot_rules=(
        "这一镜遵守的视觉规则",
        "母题如何变形或重复",
        "材质与肌理的具体处理",
        "镜头运动是形式化的还是随机的",
    ),
    must_include=("规则", "母题"),
    forbidden=(
        "用叙事解释概念",
        "为了安全而妥协成常规广告",
        "无规则的随机噪点堆砌",
    ),
    negatives=("陈词滥调", "常规广告构图", "随机噪点", "无意义闪烁"),
    length_hint="整片 800–2000 字，逐镜头每条 80–180 字",
    checks=(
        ("写了视觉规则", r"规则|法则|逻辑|约束"),
        ("写了母题或材质", r"母题|材质|肌理|纹样"),
    ),
)

DOCUMENTARY = PromptDialect(
    key="documentary",
    label="纪实 / 纪录片",
    role="纪录片导演兼纪实摄影，习惯低干预拍摄",
    intent=(
        "让观众相信这是被观察到的，而不是被安排的。"
        "可用光、观察距离、环境声是真实感的三个支柱。"
    ),
    sections=(
        "人物与场景的真实性来源",
        "观察式机位与介入程度",
        "可用光与环境条件",
        "环境声与现场氛围",
        "时间连续性（不跳剪的段落）",
    ),
    shot_rules=(
        "机位距离与介入程度（是否被拍摄对象察觉）",
        "可用光源，不使用布光",
        "人物的自然行为，不设计动作",
        "现场环境声元素",
    ),
    must_include=("可用光", "环境声"),
    forbidden=(
        "摆拍痕迹",
        "影棚式布光",
        "用配乐强行煽情",
        "让被摄者念台词",
    ),
    negatives=("摆拍感", "影棚光", "过度调色", "配乐煽情", "塑料皮肤"),
    length_hint="整片 1200–2500 字，逐镜头每条 100–200 字",
    checks=(
        ("写了可用光", r"可用光|自然光|现场光|窗户|日光"),
        ("写了环境声", r"环境声|现场声|同期声|底噪"),
        ("写了观察距离", r"观察|跟拍|距离|不介入|手持"),
    ),
)


DIALECTS: dict[str, PromptDialect] = {
    dialect.key: dialect
    for dialect in (
        ECOMMERCE,
        BRAND_AD,
        FILM_SCIFI,
        FILM_HUMAN,
        FILM_ACTION,
        ANIME,
        EXPERIMENTAL,
        DOCUMENTARY,
    )
}

#: Genre-specific emphasis for the two prompt types. Kept separate from the
#: constructors above so the format-level rules stay in one place and the
#: genre only says what *its* still frame or motion beat must prove.
_EMPHASIS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "ecommerce": (
        (
            "商品在画面中的占比，以及文字安全区的位置",
            "是否需要手部或模特，以及他们只做功能动作",
        ),
        (
            "用展示动作与镜头位移证明尺寸、材质和使用方式",
            "镜头始终围着商品，不做叙事性移动",
        ),
    ),
    "brand_ad": (
        ("把记忆点压缩成一个可以截图的画面",),
        ("记忆点的揭示节奏：什么时候给、给几秒",),
    ),
    "film_scifi": (
        ("尺度参照物与光源的物理来源必须在静帧里看得见",),
        ("用摄影机运动揭示尺度，而不是靠剪辑解释",),
    ),
    "film_human": (
        ("视线方向、身体姿态与空间关系定格",),
        ("表演的微变化（呼吸、停顿、眼神）如何被镜头接住",),
    ),
    "film_action": (
        ("运动方向与参照物在同一帧内可读",),
        ("速度通过参照物掠过、摄影机追随与视差被证明",),
    ),
    "anime": (
        ("画风、线条与上色方式必须在静帧里成立", "这一卡的关键帧构图"),
        ("作画重心：哪一段是原画、哪里用中割衔接",),
    ),
    "experimental": (
        ("母题在这一帧的形态与它遵守的规则",),
        ("母题的变形过程与循环规则",),
    ),
    "documentary": (
        ("观察距离与可用光，画面里不出现布光痕迹",),
        ("人物的自然行为如何变化，不设计动作",),
    ),
}

DIALECTS = {
    key: replace(
        dialect,
        image_emphasis=_EMPHASIS[key][0],
        video_emphasis=_EMPHASIS[key][1],
    )
    for key, dialect in DIALECTS.items()
}

# Re-bind the named constants so direct imports see the same objects.
ECOMMERCE = DIALECTS["ecommerce"]
BRAND_AD = DIALECTS["brand_ad"]
FILM_SCIFI = DIALECTS["film_scifi"]
FILM_HUMAN = DIALECTS["film_human"]
FILM_ACTION = DIALECTS["film_action"]
ANIME = DIALECTS["anime"]
EXPERIMENTAL = DIALECTS["experimental"]
DOCUMENTARY = DIALECTS["documentary"]

DEFAULT_DIALECT_KEY = BRAND_AD.key

# Fallback classification only. The requirement parser is asked to choose the
# dialect itself; this map exists so a project created without a model still
# gets something better than the generic template.
_INFERENCE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("anime", ("动漫", "动画", "番剧", "二次元", "赛璐璐", "漫画感")),
    ("ecommerce", ("电商", "主图", "详情页", "带货", "商品图", "投放素材", "产品图")),
    ("film_scifi", ("科幻", "未来", "太空", "赛博", "机甲", "星际", "末日")),
    ("film_action", ("动作", "追逐", "追车", "打斗", "竞速", "跑酷")),
    ("film_human", ("人文", "剧情", "文艺", "家庭", "成长", "情感", "校园")),
    ("documentary", ("纪实", "纪录", "采访", "真实人物")),
    ("experimental", ("实验", "概念", "抽象", "先锋", "影像艺术")),
)


def infer_dialect_key(content_type: str, subject: str = "", notes: str = "") -> str:
    blob = f"{content_type} {subject} {notes}"
    for key, keywords in _INFERENCE:
        if any(keyword in blob for keyword in keywords):
            return key
    return DEFAULT_DIALECT_KEY


def resolve_dialect(
    prompt_dialect: str = "",
    *,
    content_type: str = "",
    subject: str = "",
    notes: str = "",
) -> PromptDialect:
    """Pick the dialect: model-provided value first, keyword inference second."""

    key = (prompt_dialect or "").strip().lower()
    if key in DIALECTS:
        return DIALECTS[key]
    return DIALECTS[infer_dialect_key(content_type, subject, notes)]


def dialect_choices() -> str:
    return " / ".join(f"{key}（{dialect.label}）" for key, dialect in DIALECTS.items())


def audit_text(text: str, dialect: PromptDialect) -> list[str]:
    """Return the genre requirements this text does not satisfy."""

    missing: list[str] = []
    for label, pattern in dialect.checks:
        if not re.search(pattern, text, re.IGNORECASE):
            missing.append(label)
    return missing


#: Format-level checks. They are deliberately positive-only: a still frame and a
#: moving shot fail in different ways, and that difference is checkable.
_IMAGE_AUDIT: tuple[tuple[str, str], ...] = (
    ("图片提示词没写景别或焦段", r"全景|中景|近景|特写|微距|广角|长焦|\d+\s*mm"),
    ("图片提示词没写光线", r"光位|光比|色温|柔光|硬光|侧光|顶光|逆光|自然光|光"),
    ("图片提示词没写材质或色彩", r"材质|肌理|釉面|金属|织物|皮肤|色彩|色调"),
    ("图片提示词没写画幅或构图", r"画幅|\d+:\d+|构图|留白|居中|偏左|偏右|三分"),
)

_VIDEO_AUDIT: tuple[tuple[str, str], ...] = (
    ("视频提示词没写时长或节拍", r"秒|时长|节拍"),
    (
        "视频提示词没写运动",
        r"推|拉|摇|移|跟|环绕|升降|手持|机位|镜头运动|运动",
    ),
    (
        "视频提示词没写起始到结束的变化",
        r"开始|结束|最后|逐渐|转为|变为|→|到",
    ),
)


def audit_image_prompts(prompts: list[str]) -> list[str]:
    """Which format-level requirements the still-image prompts miss."""

    combined = "\n".join(prompt for prompt in prompts if prompt)
    if not combined:
        return ["没有生成图片提示词"]
    return [
        label
        for label, pattern in _IMAGE_AUDIT
        if not re.search(pattern, combined, re.IGNORECASE)
    ]


def audit_video_prompts(prompts: list[str]) -> list[str]:
    """Which format-level requirements the motion prompts miss."""

    combined = "\n".join(prompt for prompt in prompts if prompt)
    if not combined:
        return ["没有生成视频提示词"]
    return [
        label
        for label, pattern in _VIDEO_AUDIT
        if not re.search(pattern, combined, re.IGNORECASE)
    ]


def audit_package(
    global_prompt: str,
    shot_prompts: list[str],
    dialect: PromptDialect,
) -> list[str]:
    """Audit the whole package: global prompt plus every shot prompt."""

    combined = "\n".join([global_prompt, *shot_prompts])
    return audit_text(combined, dialect)


__all__ = [
    "DIALECTS",
    "DEFAULT_DIALECT_KEY",
    "IMAGE_RULES",
    "VIDEO_RULES",
    "PromptDialect",
    "audit_image_prompts",
    "audit_package",
    "audit_text",
    "audit_video_prompts",
    "dialect_choices",
    "infer_dialect_key",
    "resolve_dialect",
]
