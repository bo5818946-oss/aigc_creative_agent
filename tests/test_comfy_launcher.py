"""Starting ComfyUI from the studio, without guessing machine paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from services import comfy_launcher


def test_config_only_lists_folders_that_exist(tmp_path: Path) -> None:
    for name in ("diffusion_models", "vae", "not_a_comfy_folder"):
        (tmp_path / name).mkdir()

    body = comfy_launcher.build_model_config(tmp_path)

    assert "diffusion_models: diffusion_models" in body
    assert "vae: vae" in body
    assert "checkpoints" not in body
    assert "not_a_comfy_folder" not in body
    assert tmp_path.as_posix() in body


def test_empty_model_dir_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(comfy_launcher.LaunchError, match="模型目录"):
        comfy_launcher.build_model_config(tmp_path / "missing")

    (tmp_path / "empty").mkdir()
    with pytest.raises(comfy_launcher.LaunchError, match="没有 ComfyUI 认识"):
        comfy_launcher.build_model_config(tmp_path / "empty")


def test_unconfigured_launch_says_what_to_set(monkeypatch) -> None:
    monkeypatch.setattr(comfy_launcher, "COMFYUI_PYTHON", "")
    monkeypatch.setattr(comfy_launcher, "COMFYUI_HOME", "")

    result = comfy_launcher.launch()

    assert result.ok is False
    assert "AIGC_COMFYUI_PYTHON" in result.message
    assert comfy_launcher.is_configured() is False


def test_launch_refuses_a_home_without_main(tmp_path: Path, monkeypatch) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    monkeypatch.setattr(comfy_launcher, "COMFYUI_PYTHON", str(python))
    monkeypatch.setattr(comfy_launcher, "COMFYUI_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        comfy_launcher,
        "COMFYUI_URL",
        "http://127.0.0.1:9",
    )
    (tmp_path / "home").mkdir()

    with pytest.raises(comfy_launcher.LaunchError, match="main.py"):
        comfy_launcher.launch(timeout=1)
