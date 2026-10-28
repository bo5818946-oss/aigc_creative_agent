from __future__ import annotations

from pathlib import Path

from database.repository import ProjectRepository
from services.project_service import CreativeProjectService
from tools.prompt_package import (
    build_image_prompt_package,
    build_prompt_package,
    build_video_prompt_package,
    media_package_filename,
    prompt_package_filename,
)


def test_prompt_package_contains_all_shot_prompts(
    tmp_path: Path,
    demo_requirement,
) -> None:
    repository = ProjectRepository(tmp_path / "prompt_package.sqlite3")
    result = CreativeProjectService(repository).run(demo_requirement)
    requirement = result["structured_requirement"]
    storyboard = result["storyboard"]

    package = build_prompt_package(
        requirement["project_name"],
        requirement,
        storyboard,
        "generic",
    )

    assert package.startswith("# 30秒汽车品牌广告 · AI 视频提示词包")
    assert package.count("### 图片提示词") == 5
    assert package.count("### 视频提示词") == 5
    assert package.count("### 负向提示词") == 5
    assert "## 镜头 1 · 森林" in package
    assert "## 镜头 5 · 城市" in package
    assert "（未生成）" not in package
    assert "通用视频模型" in package


def test_prompt_package_handles_empty_storyboard() -> None:
    package = build_prompt_package(
        "空项目",
        {"duration_seconds": 30, "aspect_ratio": "16:9"},
        {"shots": []},
        "generic",
    )

    assert "没有可用分镜" in package
    assert "没有提示词包" in package


def test_prompt_package_filename_is_safe() -> None:
    name = prompt_package_filename('项目：A/B*C?"D"')

    assert name.endswith("_提示词包.txt")
    assert "/" not in name
    assert "*" not in name
    assert "?" not in name
    assert '"' not in name


STORYBOARD = {
    "shots": [
        {
            "shot_number": 1,
            "scene": "森林",
            "start_seconds": 0,
            "end_seconds": 6,
            "image_prompt": "静态：正侧面特写，300mm，侧逆光",
            "video_prompt": "镜头从左侧跟拍推近，6 秒，车从静止加速",
            "negative_prompt": "无字幕",
        },
        {
            "shot_number": 2,
            "scene": "城市",
            "start_seconds": 6,
            "end_seconds": 12,
            "image_prompt": "静态：低机位全景，24mm，霓虹反射",
            "video_prompt": "镜头上升，12 秒内从街道升到楼顶",
            "negative_prompt": "无水印",
        },
    ]
}


def test_image_and_video_packages_are_separate() -> None:
    image_package = build_image_prompt_package(
        "测试项目", {"duration_seconds": 12}, STORYBOARD
    )
    video_package = build_video_prompt_package(
        "测试项目", {"duration_seconds": 12}, STORYBOARD
    )

    assert "图片生成提示词包" in image_package
    assert "视频生成提示词包" in video_package
    # Each package carries only its own medium.
    assert "静态：正侧面特写" in image_package
    assert "镜头从左侧跟拍推近" not in image_package
    assert "镜头从左侧跟拍推近" in video_package
    assert "静态：正侧面特写" not in video_package
    # Both keep the shot header so the blocks stay aligned.
    assert "## 镜头 1 · 森林" in image_package
    assert "## 镜头 2 · 城市" in video_package


def test_media_package_filenames_are_distinct() -> None:
    image_name = media_package_filename("项目", "image")
    video_name = media_package_filename("项目", "video")

    assert image_name.endswith("_图片生成提示词.txt")
    assert video_name.endswith("_视频生成提示词.txt")
    assert image_name != video_name
