"""End-to-end local generation against a real HTTP server.

The server here is a stand-in for ComfyUI, but everything between the studio
and it is the production code: ``urllib`` requests, the API-format workflow,
the binding, the polling, the file write, and the database record.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from database.repository import ProjectRepository
from services.comfyui_client import ComfyUIClient, ComfyUIUnavailable
from services.generation_service import LocalGenerationService
from services.workflow_registry import parse_template

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class _State:
    def __init__(self, *, with_outputs: bool = True):
        self.submitted: list[dict] = []
        self.with_outputs = with_outputs


def _make_handler(state: _State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # keep pytest output clean
            return

        def _json(self, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/system_stats"):
                self._json(
                    {
                        "system": {
                            "comfyui_version": "0.3.60",
                            "python_version": "3.13.0",
                        },
                        "devices": [
                            {"name": "NVIDIA GeForce RTX 4060", "vram_total": 8.5e9}
                        ],
                    }
                )
            elif self.path.startswith("/history/"):
                outputs = (
                    {
                        "7": {
                            "images": [
                                {
                                    "filename": "shot_01.png",
                                    "subfolder": "",
                                    "type": "output",
                                }
                            ]
                        }
                    }
                    if state.with_outputs
                    else {}
                )
                self._json(
                    {
                        "pid-1": {
                            "status": {"status_str": "success", "completed": True},
                            "outputs": outputs,
                        }
                    }
                )
            elif self.path.startswith("/view"):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(PNG)))
                self.end_headers()
                self.wfile.write(PNG)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            state.submitted.append(payload)
            self._json({"prompt_id": "pid-1"})

    return Handler


@pytest.fixture
def comfy(tmp_path: Path):
    state = _State()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield url, state
    finally:
        server.shutdown()
        server.server_close()


def _template(tmp_path: Path):
    payload = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "z.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "old", "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "old neg", "clip": ["1", 1]}},
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
            },
        },
        "7": {"class_type": "SaveImage", "inputs": {"images": ["5", 0]}},
    }
    path = tmp_path / "image.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return parse_template(path)


def test_probe_reports_a_live_server(comfy, tmp_path: Path) -> None:
    url, _ = comfy
    service = LocalGenerationService(
        ComfyUIClient(url, timeout=5),
        workflow_dir=tmp_path,
        media_dir=tmp_path / "media",
    )
    probe = service.probe()
    assert probe.reachable is True
    assert probe.server is not None
    assert probe.server.version == "0.3.60"
    assert "RTX 4060" in probe.server.describe()


def test_probe_reports_a_dead_server(tmp_path: Path) -> None:
    client = ComfyUIClient("http://127.0.0.1:9", timeout=1)
    service = LocalGenerationService(
        client,
        workflow_dir=tmp_path,
        media_dir=tmp_path / "media",
    )
    probe = service.probe()
    assert probe.reachable is False
    assert "连不上 ComfyUI" in probe.error
    with pytest.raises(ComfyUIUnavailable):
        client.server()


def test_render_writes_the_file_and_the_record(comfy, tmp_path: Path) -> None:
    url, state = comfy
    repository = ProjectRepository(tmp_path / "db.sqlite3")
    service = LocalGenerationService(
        ComfyUIClient(url, timeout=5),
        workflow_dir=tmp_path,
        media_dir=tmp_path / "media",
        repository=repository,
        poll=0.01,
        job_timeout=5,
    )
    events: list[str] = []
    jobs = service.render_shots(
        project_id="proj-1",
        shots=[(1, "a campus corridor at dawn", "text, watermark")],
        template=_template(tmp_path),
        seconds=5,
        size=(1344, 768),
        on_event=lambda job: events.append(job.status),
    )

    assert [job.status for job in jobs] == ["done"]
    assert jobs[0].files and jobs[0].files[0].path.exists()
    assert jobs[0].files[0].path.read_bytes() == PNG
    assert events == ["running", "done"]

    submitted = state.submitted[0]["prompt"]
    assert submitted["2"]["inputs"]["text"] == "a campus corridor at dawn"
    assert submitted["3"]["inputs"]["text"] == "text, watermark"
    assert submitted["4"]["inputs"]["width"] == 1344

    records = repository.list_media("proj-1")
    assert len(records) == 1
    assert records[0]["status"] == "done"
    assert Path(records[0]["file_path"]).exists()
    assert records[0]["duration_seconds"] == 5


def test_missing_output_fails_the_shot_instead_of_faking_a_file(
    tmp_path: Path,
) -> None:
    state = _State(with_outputs=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        repository = ProjectRepository(tmp_path / "db.sqlite3")
        service = LocalGenerationService(
            ComfyUIClient(f"http://127.0.0.1:{server.server_port}", timeout=5),
            workflow_dir=tmp_path,
            media_dir=tmp_path / "media",
            repository=repository,
            poll=0.01,
            job_timeout=5,
        )
        jobs = service.render_shots(
            project_id="proj-2",
            shots=[(1, "prompt", "")],
            template=_template(tmp_path),
            seconds=5,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert jobs[0].status == "failed"
    assert "没有文件" in jobs[0].error
    records = repository.list_media("proj-2")
    assert records[0]["status"] == "failed"
    assert records[0]["file_path"] == ""
    assert "没有文件" in records[0]["error"]
