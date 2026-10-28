from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schemas.project import CreativeRequirement  # noqa: E402


@pytest.fixture(autouse=True)
def _offline_guide(monkeypatch):
    """Never let the suite call a real model through the conversation layer.

    The repository ships a ``.env`` with a working key, so without this every
    Streamlit AppTest and conversation test would hit DeepSeek. Tests that want
    the model path inject a fake director explicitly.
    """

    monkeypatch.setenv("AIGC_GUIDE_MODE", "rules")


@pytest.fixture
def demo_requirement() -> CreativeRequirement:
    return CreativeRequirement(
        project_name="30秒汽车品牌广告",
        content_type="汽车商业广告",
        subject="一辆银灰色流线型纯电轿车",
        target_audience="关注科技感与驾驶质感的年轻消费者",
        duration_seconds=30,
        aspect_ratio="16:9",
        visual_style="电影感商业广告，冷暖对比光影，金属质感",
        scene_requirements=["森林", "草原", "沙漠", "雪地", "城市"],
        camera_language="航拍、低机位跟拍与车身细节特写结合",
        consistency_constraints=[
            "全片使用同一辆银灰色流线型纯电轿车",
            "明确车头与车尾方向，车辆前进方向始终一致",
            "避免镜头之间出现相互矛盾的车辆运动描述",
        ],
        transition_requirements="以车辆运动方向为依据的自然动势转场",
        output_formats=["markdown", "json"],
    )
