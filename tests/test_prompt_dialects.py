"""Genre standards for prompt writing.

The genre must be a real constraint on the writer, not a label: two genres have
to produce different writing standards, and the audit must be able to say that a
package does not satisfy its own genre.
"""

from __future__ import annotations

from config.prompt_dialects import (
    ANIME,
    BRAND_AD,
    DIALECTS,
    ECOMMERCE,
    FILM_ACTION,
    FILM_HUMAN,
    FILM_SCIFI,
    audit_image_prompts,
    audit_package,
    audit_text,
    audit_video_prompts,
    infer_dialect_key,
    resolve_dialect,
)
from schemas.project import CreativeRequirement
from services.llm_service import LLMService
from tests.fakes import FakeChatClient
from tools.prompt_builder import build_prompts_for_storyboard
from tools.prompt_writer import write_director_package
from tools.storyboard_tool import generate_deterministic_storyboard
from tools.validation_pipeline import run_validation


def _requirement(**overrides) -> CreativeRequirement:
    base = {
        "project_name": "测试项目",
        "content_type": "商业广告",
        "subject": "一款白色陶瓷罐装面霜",
        "duration_seconds": 10,
        "aspect_ratio": "1:1",
        "scene_requirements": ["纯色背景商品台"],
    }
    base.update(overrides)
    return CreativeRequirement(**base)


def _service(payload: dict) -> LLMService:
    return LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        max_retries=0,
        client=FakeChatClient([payload]),
        retry_backoff_seconds=0,
    )


# ----------------------------------------------------------------------
# selection
# ----------------------------------------------------------------------
def test_explicit_dialect_wins_over_inference() -> None:
    dialect = resolve_dialect(
        "anime",
        content_type="电商视觉",
        subject="面霜",
    )

    assert dialect.key == "anime"


def test_dialect_is_inferred_when_not_provided() -> None:
    assert resolve_dialect("", content_type="电商主图").key == "ecommerce"
    assert resolve_dialect("", content_type="科幻短片").key == "film_scifi"
    assert resolve_dialect("", content_type="动画番剧").key == "anime"
    assert resolve_dialect("", content_type="追车动作片").key == "film_action"
    assert resolve_dialect("", content_type="纪实访谈").key == "documentary"
    # Unknown content falls back to the brand-commercial standard.
    assert resolve_dialect("", content_type="随便什么").key == BRAND_AD.key


def test_unknown_dialect_string_is_ignored() -> None:
    assert resolve_dialect("not-a-genre", content_type="动画").key == "anime"


def test_inference_returns_keys_that_exist() -> None:
    for content in ("电商", "科幻", "动画", "动作", "纪实", "实验", "剧情", ""):
        assert infer_dialect_key(content) in DIALECTS


# ----------------------------------------------------------------------
# the standards are genuinely different
# ----------------------------------------------------------------------
def test_each_genre_states_its_own_craft_standard() -> None:
    assert "电商视觉" in ECOMMERCE.system_block()
    assert "文字安全区" in ECOMMERCE.system_block()
    assert "尺度" in FILM_SCIFI.system_block()
    assert "轴线" in FILM_ACTION.system_block()
    assert "实拍质感" in ANIME.system_block()
    assert "可用光" in FILM_HUMAN.system_block()


def test_two_genres_do_not_share_the_same_standard() -> None:
    ecommerce = ECOMMERCE.system_block()
    anime = ANIME.system_block()

    assert ecommerce != anime
    assert "画幅" in ecommerce and "线条" not in ecommerce
    assert "线条" in anime and "文字安全区" not in anime


def test_genre_negatives_are_genre_specific() -> None:
    assert any("线稿" in item or "线条" in item for item in ANIME.negatives)
    assert any("色差" in item for item in ECOMMERCE.negatives)
    assert any("光源" in item for item in FILM_SCIFI.negatives)


def test_image_and_video_rules_are_different_tasks() -> None:
    block = ECOMMERCE.system_block()

    assert "图片提示词 image_prompt：冻结哪一帧" in block
    assert "视频提示词 video_prompt：画面怎么变" in block
    # A still frame must not be written as motion, and vice versa.
    assert "禁止写时间推进、镜头运动过程、转场和音频" in block
    assert "禁止只写一帧的静态描述" in block
    # Genre emphasis lands on the right medium.
    assert "文字安全区的位置" in block.split("视频提示词")[0]


def test_image_and_video_audits_are_separate() -> None:
    static_only = ["产品特写，占画面 60%，柔光箱 45 度，5600K，陶瓷釉面，1:1 画幅"]
    motion_only = ["镜头推近 6 秒，从全景推到特写"]

    assert audit_image_prompts(static_only) == []
    assert audit_video_prompts(static_only)  # no time, no movement
    assert audit_video_prompts(motion_only) == []
    assert audit_image_prompts(motion_only)  # no light or material


def test_empty_media_prompts_are_reported() -> None:
    assert audit_image_prompts([]) == ["没有生成图片提示词"]
    assert audit_video_prompts([]) == ["没有生成视频提示词"]


# ----------------------------------------------------------------------
# audit
# ----------------------------------------------------------------------
def test_audit_passes_a_compliant_text() -> None:
    text = (
        "商品占画面 60%，右侧留文字安全区。光位为柔光箱 45 度，"
        "光比 1:2，色温 5600K。画幅 1:1，背景纯色无缝。"
    )

    assert audit_text(text, ECOMMERCE) == []


def test_audit_reports_what_is_missing() -> None:
    missing = audit_text("一个很高级的广告片。", ECOMMERCE)

    assert missing
    assert any("光" in item for item in missing)
    assert any("画幅" in item for item in missing)


def test_audit_covers_shot_prompts_too() -> None:
    global_prompt = "商品占画面 60%，光位柔和，画幅 1:1。"
    missing = audit_package(
        global_prompt,
        ["纯色背景，无文字位信息"],
        ECOMMERCE,
    )

    # The global prompt satisfies the checks, so the package passes even though
    # a single shot does not repeat everything.
    assert missing == []


# ----------------------------------------------------------------------
# the writer honours the genre
# ----------------------------------------------------------------------
def _payload(global_prompt: str, *, shots: int = 1) -> dict:
    return {
        "title": "测试",
        "global_prompt": global_prompt,
        "negative_prompt": "商品变形，色差",
        "continuity_bible": ["同一罐面霜"],
        "shot_prompts": [
            {
                "shot_number": index,
                "scene": "商品台",
                "image_prompt": f"第 {index} 张图片提示词",
                "video_prompt": f"第 {index} 条视频提示词",
                "negative_prompt": "色差",
            }
            for index in range(1, shots + 1)
        ],
        "model_notes": "",
    }


def test_writer_attaches_the_genre_and_audits_the_package() -> None:
    requirement = _requirement(prompt_dialect="ecommerce")
    storyboard = build_prompts_for_storyboard(
        generate_deterministic_storyboard(requirement),
        requirement,
        "generic",
    )
    report = run_validation(storyboard.shots, requirement, 0.5)
    compliant = (
        "本片为电商主图视频，时长 6 秒，画幅 1:1。"
        "唯一商品主体为一款白色陶瓷罐装面霜，全片素材一致。"
        "商品占画面 60%，机位平视，推镜幅度克制，商品水平位置不变。"
        "光位为柔光箱 45 度，右侧反光板补光，光比 1:2，色温 5600K，"
        "高光柔和不过曝，釉面呈现细腻漫反射。"
        "背景为纯色无缝商品台，暖白或浅米灰，右侧留 30% 文字安全区，"
        "安全区内无物体与阴影。"
        "全片不使用模特与手部，不做戏剧化强光，标签文字保持水平且不变形，"
        "首帧在手机端一米外可读。"
    )

    package = write_director_package(
        _service(_payload(compliant)),
        requirement,
        storyboard,
        report,
        "generic",
    )

    assert package.dialect == "ecommerce"
    assert package.dialect_label == "电商视觉"
    assert package.dialect_audit == []


def test_writer_flags_a_package_that_ignores_its_genre() -> None:
    requirement = _requirement(prompt_dialect="ecommerce")
    storyboard = build_prompts_for_storyboard(
        generate_deterministic_storyboard(requirement),
        requirement,
        "generic",
    )
    report = run_validation(storyboard.shots, requirement, 0.5)
    vague = (
        "这是一支很有质感的片子，画面高级，节奏舒服，观众看完会记住这个品牌的气质和它的温度。"
    ) * 6

    package = write_director_package(
        _service(_payload(vague)),
        requirement,
        storyboard,
        report,
        "generic",
    )

    assert package.dialect == "ecommerce"
    assert package.dialect_audit, "a genre-blind prompt must be flagged"
    assert any("光" in item for item in package.dialect_audit)
