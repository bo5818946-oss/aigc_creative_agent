"""Progress tracking: ComfyUI websocket events -> honest percentages."""

from __future__ import annotations

from studio.api import progress
from studio.api.main import _elapsed_seconds


def test_progress_records_steps_and_eta_inputs() -> None:
    tracker = progress.ComfyProgress()
    tracker._handle({"type": "execution_start", "data": {"prompt_id": "p1"}})
    tracker._handle(
        {"type": "progress", "data": {"prompt_id": "p1", "value": 3, "max": 8}}
    )
    snapshot = tracker.snapshot("p1")
    assert snapshot is not None
    assert snapshot["value"] == 3
    assert snapshot["max"] == 8
    assert snapshot["phase"] == "running"


def test_progress_finishing_then_cleared() -> None:
    tracker = progress.ComfyProgress()
    tracker._handle({"type": "execution_start", "data": {"prompt_id": "p2"}})
    tracker._handle({"type": "executing", "data": {"prompt_id": "p2", "node": None}})
    assert tracker.snapshot("p2")["phase"] == "finishing"
    tracker._handle({"type": "execution_success", "data": {"prompt_id": "p2"}})
    assert tracker.snapshot("p2") is None


def test_progress_ignores_messages_without_prompt_id() -> None:
    tracker = progress.ComfyProgress()
    tracker._handle({"type": "progress", "data": {"value": 1, "max": 8}})
    assert tracker.snapshot("") is None


def test_elapsed_seconds_tolerates_missing_timestamps() -> None:
    assert _elapsed_seconds(None) == 0.0
    assert _elapsed_seconds("") == 0.0
    assert _elapsed_seconds("not-a-date") == 0.0
    assert _elapsed_seconds("2020-01-01T00:00:00+00:00") > 0
