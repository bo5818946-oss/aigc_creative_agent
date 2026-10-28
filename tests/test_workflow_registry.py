"""Binding the studio's prompts into a user-exported ComfyUI API workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.workflow_registry import (
    WorkflowError,
    bind,
    load_templates,
    parse_template,
)


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _image_graph() -> dict:
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "z_image_turbo.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "placeholder positive", "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "placeholder negative", "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 1,
                "positive": ["2", 0],
                "negative": ["3", 0],
                "model": ["1", 0],
                "steps": 8,
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0]}},
    }


def _video_graph() -> dict:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "minimax_h3.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "old prompt", "clip": ["1", 1]},
        },
        "3": {
            "class_type": "MiniMaxH3ImageToVideo",
            "inputs": {
                "prompt": "old inner prompt",
                "width": 1344,
                "height": 768,
                "length": 73,
            },
        },
        "4": {"class_type": "CreateVideo", "inputs": {"images": ["3", 0], "fps": 24}},
        "5": {"class_type": "SaveVideo", "inputs": {"video": ["4", 0]}},
    }


def test_ui_format_is_rejected_with_the_export_hint(tmp_path: Path) -> None:
    path = _write(tmp_path, "ui.json", {"nodes": [{"id": 1}], "links": []})
    with pytest.raises(WorkflowError, match="Export \\(API\\)"):
        parse_template(path)


def test_image_workflow_binds_prompt_seed_and_size(tmp_path: Path) -> None:
    path = _write(tmp_path, "image.json", _image_graph())
    template = parse_template(path)
    assert template.kind == "image"
    assert template.positive_nodes == ("2",)
    assert template.negative_nodes == ("3",)

    bound = bind(
        template,
        prompt="a silver concept car on a wet runway",
        negative="text, watermark",
        width=1344,
        height=768,
        seed=42,
    )
    assert bound["2"]["inputs"]["text"].startswith("a silver concept car")
    assert bound["3"]["inputs"]["text"] == "text, watermark"
    assert bound["4"]["inputs"]["width"] == 1344
    assert bound["4"]["inputs"]["height"] == 768
    assert bound["5"]["inputs"]["seed"] == 42
    # The template itself must not be mutated: the next shot rebuilds from it.
    assert template.data["2"]["inputs"]["text"] == "placeholder positive"


def test_video_workflow_converts_seconds_to_frames(tmp_path: Path) -> None:
    path = _write(tmp_path, "video.json", _video_graph())
    template = parse_template(path)
    assert template.kind == "video"
    assert template.fps == 24.0
    assert template.default_seconds() == pytest.approx(73 / 24, rel=1e-3)

    bound = bind(template, prompt="a campus corridor at dawn", seconds=5)
    assert bound["3"]["inputs"]["length"] == 120
    assert bound["3"]["inputs"]["prompt"].startswith("a campus corridor")
    assert bound["3"]["inputs"]["width"] == 1344  # untouched when no size passed


def test_placeholders_win_over_graph_inspection(tmp_path: Path) -> None:
    graph = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt}}"}},
        "2": {
            "class_type": "SaveImage",
            "inputs": {"images": ["1", 0], "filename_prefix": "{{project}}_{{shot}}"},
        },
    }
    path = _write(tmp_path, "tpl.json", graph)
    template = parse_template(path)
    assert template.uses_placeholders is True
    bound = bind(template, prompt="hello", project="camp", shot=3)
    assert bound["1"]["inputs"]["text"] == "hello"
    assert bound["2"]["inputs"]["filename_prefix"] == "camp_3"


def test_unknown_placeholder_is_an_error(tmp_path: Path) -> None:
    graph = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{mystery}}"}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
    }
    path = _write(tmp_path, "tpl.json", graph)
    template = parse_template(path)
    with pytest.raises(WorkflowError, match="mystery"):
        bind(template, prompt="hello")


def test_load_templates_reports_broken_files(tmp_path: Path) -> None:
    _write(tmp_path, "good.json", _image_graph())
    _write(tmp_path, "bad.json", {"nodes": [], "links": []})
    templates, errors = load_templates(tmp_path)
    assert [item.name for item in templates] == ["good"]
    assert len(errors) == 1
    assert "bad.json" in errors[0]


# ----------------------------------------------------------------------
# the shipped MiniMax H3 graph
# ----------------------------------------------------------------------
H3_TEMPLATE = Path(__file__).resolve().parents[1] / "workflows" / "minimax_h3_t2v.json"


def test_h3_template_exposes_duration_and_turbo() -> None:
    template = parse_template(H3_TEMPLATE)
    assert template.kind == "video"
    assert template.duration_node == "10"
    assert template.turbo_node == "7"
    assert template.inline_prompt_nodes == ("5",)
    assert template.default_seconds() == 5.0


def test_h3_template_binds_an_initially_empty_prompt() -> None:
    """The template ships with ``"prompt": ""``; that must still be the slot."""

    template = parse_template(H3_TEMPLATE)
    assert template.data["5"]["inputs"]["prompt"] == ""

    bound = bind(
        template,
        prompt="夜晚教学楼天台，一个人背对镜头",
        seconds=5,
        width=768,
        height=432,
        seed=123,
        turbo=True,
    )
    assert bound["5"]["inputs"]["prompt"].startswith("夜晚教学楼天台")
    assert bound["10"]["inputs"]["value"] == 5
    assert bound["7"]["inputs"]["value"] is True
    assert bound["5"]["inputs"]["width"] == 768
    assert bound["16"]["inputs"]["noise_seed"] == 123
    # Frames stay computed by the graph's own 17k+5 expression, not by Python.
    assert bound["5"]["inputs"]["length"] == ["9", 1]


def test_turbo_switch_survives_a_second_bind() -> None:
    template = parse_template(H3_TEMPLATE)
    bind(template, prompt="a", seconds=5, turbo=True)
    again = bind(template, prompt="b", seconds=5, turbo=False)
    assert again["7"]["inputs"]["value"] is False
