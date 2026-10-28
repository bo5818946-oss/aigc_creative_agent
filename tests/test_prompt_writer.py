from __future__ import annotations

import pytest

from services.llm_service import LLMService
from tests.fakes import FakeChatClient
from tools.prompt_builder import build_prompts_for_storyboard
from tools.prompt_package import build_prompt_package
from tools.prompt_writer import (
    PromptWriterError,
    write_director_package,
)
from tools.storyboard_tool import generate_deterministic_storyboard
from tools.validation_pipeline import run_validation


def _director_payload() -> dict:
    return {
        "title": "测试导演版",
        "global_prompt": (
            "生成一支 30 秒的电影级汽车广告。全片只出现同一辆银灰色"
            "流线型纯电轿车，车头始终朝右，车辆沿真实道路持续前进，"
            "轮胎接地，场景依次为森林、草原、沙漠、雪地和城市。"
            "每个场景都用近景参照物、道路标线、轮胎旋转和摄影机"
            "追赶证明真实高速运动；场景之间用动作匹配和前景遮挡"
            "完成连续转场，切点前后保持同一方向和车身比例。"
            "摄影机先落后再追赶，用近景、中景、远景的速度差建立"
            "运动视差；光线随环境变化，但汽车设计、颜色和材质不变。"
            "声音包含动力系统、风噪、轮胎接地和环境空间变化。"
            "结尾完成清晰的汽车英雄镜头，不出现字幕、水印或 Logo。"
        ),
        "negative_prompt": "禁止车头车尾颠倒、车身变形、悬浮、轮胎穿地。",
        "continuity_bible": [
            "全片同一辆银灰色流线型纯电轿车",
            "车头始终朝右",
            "轮胎持续接地",
        ],
        "shot_prompts": [
            {
                "shot_number": index,
                "scene": scene,
                "image_prompt": f"{scene}镜头图片提示词",
                "video_prompt": f"{scene}镜头视频提示词",
                "negative_prompt": "无字幕，无水印",
            }
            for index, scene in enumerate(
                ["森林", "草原", "沙漠", "雪地", "城市"],
                start=1,
            )
        ],
        "model_notes": "通用模型适配提示。",
    }


def _service(payload: dict | str) -> LLMService:
    return LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        max_retries=0,
        client=FakeChatClient([payload]),
        retry_backoff_seconds=0,
    )


def test_director_package_is_written_and_packaged(demo_requirement) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)
    storyboard = build_prompts_for_storyboard(
        storyboard,
        demo_requirement,
        "generic",
    )
    report = run_validation(storyboard.shots, demo_requirement, 0.5)

    package = write_director_package(
        _service(_director_payload()),
        demo_requirement,
        storyboard,
        report,
        "generic",
    )

    assert package.title == "测试导演版"
    assert len(package.global_prompt) > 200
    assert len(package.shot_prompts) == 5
    assert package.shot_prompts[0].video_prompt == "森林镜头视频提示词"

    updated = storyboard.model_copy(
        update={
            "director_package": package,
            "prompt_generation_method": "llm_director",
        }
    )
    output = build_prompt_package(
        demo_requirement.project_name,
        demo_requirement.model_dump(mode="json"),
        updated.model_dump(mode="json"),
        "generic",
    )

    assert output.startswith("# 测试导演版")
    assert "## 整片导演提示词" in output
    assert "测试导演版" in output
    assert "森林镜头视频提示词" in output
    assert "Python 规则拼装" not in output


def test_short_global_prompt_is_rejected(demo_requirement) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)
    storyboard = build_prompts_for_storyboard(
        storyboard,
        demo_requirement,
        "generic",
    )
    report = run_validation(storyboard.shots, demo_requirement, 0.5)

    with pytest.raises(PromptWriterError):
        write_director_package(
            _service(
                {
                    "title": "太短",
                    "global_prompt": "太短",
                    "shot_prompts": [],
                }
            ),
            demo_requirement,
            storyboard,
            report,
        )


def test_missing_shot_prompts_fall_back_to_storyboard(demo_requirement) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)
    storyboard = build_prompts_for_storyboard(
        storyboard,
        demo_requirement,
        "generic",
    )
    report = run_validation(storyboard.shots, demo_requirement, 0.5)

    package = write_director_package(
        _service(
            {
                "title": "只写整片",
                "global_prompt": "生成一支完整的 30 秒汽车广告。" * 20,
                "shot_prompts": [],
            }
        ),
        demo_requirement,
        storyboard,
        report,
    )

    assert len(package.shot_prompts) == 5
    assert package.shot_prompts[0].video_prompt == (
        storyboard.shots[0].video_prompt
    )
    assert package.continuity_bible


def _campus_requirement():
    from schemas.project import CreativeRequirement

    return CreativeRequirement(
        project_name="回声",
        content_type="校园剧情短片",
        subject="一个穿浅灰色连帽卫衣的学生",
        target_audience="校园与青春题材观众",
        duration_seconds=15,
        aspect_ratio="16:9",
        visual_style="自然纪实风格，低饱和色彩与胶片质感",
        scene_requirements=["校园", "教室", "校园走廊"],
        camera_language="手持跟拍，轻微呼吸感，缓慢推镜",
        consistency_constraints=[
            "全片只出现一个学生，浅灰色连帽卫衣和深色长裤保持一致。",
            "三个场景属于同一校园，窗框颜色和地面材质统一。",
        ],
        transition_requirements="硬切，不使用叠化或淡入淡出。",
    )


def test_non_vehicle_director_prompt_has_no_vehicle_sections() -> None:
    requirement = _campus_requirement()
    storyboard = generate_deterministic_storyboard(requirement)
    storyboard = build_prompts_for_storyboard(
        storyboard,
        requirement,
        "generic",
    )
    report = run_validation(storyboard.shots, requirement, 0.5)
    payload = {
        "title": "回声",
        "global_prompt": (
            "这是一支关于校园回声、专注与希望的导演阐述。"
            "全片围绕一个穿浅灰色连帽卫衣的学生展开，"
            "从校园室外到教室再到走廊，用环境声、钢琴声和光线变化推进情绪。"
            * 8
            + "\n1. 唯一主体资产锁定：同一个学生，浅灰色连帽卫衣和深色长裤。"
            "\n2. 车头/前进方向：本片无车辆，但主体运动方向必须遵循分镜。"
            "\n3. 轮胎接地：不适用。"
            "\n4. 道路连续性：不适用，但场景连续性必须保持：同一校园环境。"
            "\n5. 物理运动规则：动作符合自然重力与惯性，硬切转场。"
        ),
        "negative_prompt": "无字幕；无水印；禁止车头车尾颠倒。",
        "continuity_bible": [
            "全片同一个学生",
            "车头始终朝右",
            "轮胎持续接地",
        ],
        "shot_prompts": [
            {
                "shot_number": 1,
                "scene": "校园",
                "image_prompt": "学生在校园中行走，轮胎特写。",
                "video_prompt": "学生从画面左侧走入，镜头轻微手持跟拍。",
                "negative_prompt": "无字幕，无水印",
            }
        ],
        "model_notes": "通用视频模型；保持人物服装一致。",
    }
    client = FakeChatClient([payload])
    service = LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        max_retries=0,
        client=client,
        retry_backoff_seconds=0,
    )

    package = write_director_package(
        service,
        requirement,
        storyboard,
        report,
        "generic",
    )

    system_prompt = client.calls[0]["messages"][0]["content"]
    assert "车头" not in system_prompt
    assert "轮胎" not in system_prompt
    assert "道路连续性" not in system_prompt
    assert "车辆动作" not in system_prompt
    assert "结尾英雄镜头" not in system_prompt
    assert "不适用" not in package.global_prompt
    assert "车头" not in package.global_prompt
    assert "轮胎" not in package.global_prompt
    assert "道路连续性" not in package.global_prompt
    assert "场景连续性" in package.global_prompt
    assert all("轮胎" not in item for item in package.continuity_bible)
    assert "轮胎" not in package.shot_prompts[0].image_prompt


def test_vehicle_director_prompt_keeps_vehicle_sections(demo_requirement) -> None:
    storyboard = generate_deterministic_storyboard(demo_requirement)
    storyboard = build_prompts_for_storyboard(
        storyboard,
        demo_requirement,
        "generic",
    )
    report = run_validation(storyboard.shots, demo_requirement, 0.5)
    client = FakeChatClient([_director_payload()])
    service = LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        max_retries=0,
        client=client,
        retry_backoff_seconds=0,
    )

    write_director_package(
        service,
        demo_requirement,
        storyboard,
        report,
        "generic",
    )

    system_prompt = client.calls[0]["messages"][0]["content"]
    assert "车头/前进方向" in system_prompt
    assert "轮胎接地" in system_prompt
    assert "道路连续性" in system_prompt


def test_campus_content_type_wins_over_background_car_subject() -> None:
    from tools.prompt_writer import is_vehicle_project

    requirement = _campus_requirement()
    requirement.subject = "一个站在一辆汽车旁的学生"
    assert is_vehicle_project(requirement) is False
