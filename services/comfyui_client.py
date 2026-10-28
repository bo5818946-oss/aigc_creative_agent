"""Minimal ComfyUI HTTP client.

Only the endpoints the studio actually needs, and no knowledge of any specific
workflow: server stats for the status panel, ``/prompt`` to submit an
API-format graph, ``/history`` to wait for it, ``/view`` to collect the files.
Workflow editing happens in :mod:`services.workflow_registry`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any
from uuid import uuid4


class ComfyUIError(RuntimeError):
    """The server answered, but not with what the studio asked for."""


class ComfyUIUnavailable(ComfyUIError):
    """The server is not reachable at all."""


@dataclass(frozen=True)
class ComfyServer:
    url: str
    version: str = ""
    python: str = ""
    devices: tuple[str, ...] = ()
    vram_total_mb: float = 0.0

    def describe(self) -> str:
        parts = [f"ComfyUI {self.version or 'unknown'} @ {self.url}"]
        if self.devices:
            parts.append("设备：" + "、".join(self.devices))
        if self.vram_total_mb:
            parts.append(f"显存 {self.vram_total_mb / 1024:.1f} GB")
        return " · ".join(parts)


class ComfyUIClient:
    """Thin JSON client. Every failure is raised, never swallowed."""

    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client_id = uuid4().hex

    # ------------------------------------------------------------------
    # http
    # ------------------------------------------------------------------
    def _call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        raw: bool = False,
        timeout: float | None = None,
    ):
        url = f"{self.base_url}{path}"
        data = None
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(
                request, timeout=timeout or self.timeout
            ) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1200]
            raise ComfyUIError(f"ComfyUI HTTP {exc.code}：{detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ComfyUIUnavailable(
                f"连不上 ComfyUI（{self.base_url}）：{exc}"
            ) from exc
        if raw:
            return body
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ComfyUIError("ComfyUI 返回了非 JSON 响应。") from exc

    # ------------------------------------------------------------------
    # endpoints
    # ------------------------------------------------------------------
    def server(self) -> ComfyServer:
        stats = self._call("GET", "/system_stats")
        system = stats.get("system") or {}
        devices = tuple(
            str(item.get("name") or "unknown")
            for item in (stats.get("devices") or [])
        )
        vram_total = 0.0
        for item in stats.get("devices") or []:
            try:
                vram_total = max(vram_total, float(item.get("vram_total") or 0) / 1e6)
            except (TypeError, ValueError):
                continue
        return ComfyServer(
            url=self.base_url,
            version=str(system.get("comfyui_version") or ""),
            python=str(system.get("python_version") or ""),
            devices=devices,
            vram_total_mb=vram_total,
        )

    def object_info(self) -> dict[str, Any]:
        return self._call("GET", "/object_info")

    def submit(self, workflow: dict[str, Any]) -> str:
        response = self._call(
            "POST",
            "/prompt",
            {"prompt": workflow, "client_id": self.client_id},
        )
        prompt_id = response.get("prompt_id")
        if not prompt_id:
            # ``node_errors`` is where ComfyUI explains a rejected graph.
            raise ComfyUIError(
                "ComfyUI 拒绝了工作流："
                + json.dumps(response, ensure_ascii=False)[:1200]
            )
        return str(prompt_id)

    def history(self, prompt_id: str) -> dict[str, Any]:
        return self._call("GET", f"/history/{urllib.parse.quote(prompt_id)}")

    def wait(
        self,
        prompt_id: str,
        *,
        timeout: float = 1800.0,
        poll: float = 2.0,
        on_tick: Any = None,
    ) -> dict[str, Any]:
        """Block until the prompt finishes or ``timeout`` expires.

        ``on_tick(elapsed_seconds, queue_position)`` is called once per poll so
        a caller can draw a progress indicator while the GPU works. ComfyUI's
        HTTP API has no step counter; what it does expose is the queue, so the
        tick carries whether the job is still waiting or actually running.
        """

        started = time.monotonic()
        deadline = started + timeout
        while time.monotonic() < deadline:
            if on_tick is not None:
                elapsed = time.monotonic() - started
                try:
                    on_tick(elapsed, self._queue_position(prompt_id))
                except Exception:
                    # A rendering callback must never kill a running render.
                    pass
            entry = self.history(prompt_id).get(prompt_id)
            if entry:
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise ComfyUIError(_execution_error(entry))
                if status.get("completed") or entry.get("outputs"):
                    return entry
            time.sleep(poll)
        raise ComfyUIError(
            f"等待 ComfyUI 出片超时（{timeout:g} 秒），prompt_id={prompt_id}"
        )

    def _queue_position(self, prompt_id: str) -> str:
        """``running``, ``queued`` or ``unknown`` — for the progress caption."""

        try:
            queue = self._call("GET", "/queue")
        except ComfyUIError:
            return "unknown"
        for item in queue.get("queue_running") or []:
            if isinstance(item, list) and len(item) > 1 and item[1] == prompt_id:
                return "running"
        for item in queue.get("queue_pending") or []:
            if isinstance(item, list) and len(item) > 1 and item[1] == prompt_id:
                return "queued"
        return "running"

    def fetch(self, filename: str, subfolder: str = "", kind: str = "output") -> bytes:
        query = urllib.parse.urlencode(
            {"filename": filename, "subfolder": subfolder, "type": kind}
        )
        return self._call("GET", f"/view?{query}", raw=True, timeout=60)

    def interrupt(self) -> None:
        try:
            self._call("POST", "/interrupt", {})
        except ComfyUIError:
            # Interrupting a finished queue is a no-op, not a failure worth
            # surfacing to the user.
            pass


def _execution_error(entry: dict[str, Any]) -> str:
    status = entry.get("status") or {}
    for message in status.get("messages") or []:
        if (
            isinstance(message, (list, tuple))
            and len(message) == 2
            and message[0] == "execution_error"
        ):
            detail = message[1] or {}
            node = detail.get("node_type") or detail.get("node_id") or "?"
            text = detail.get("exception_message") or ""
            return f"ComfyUI 执行失败（节点 {node}）：{text}".strip()
    return "ComfyUI 执行失败，但没有返回具体节点信息。"


def output_files(entry: dict[str, Any]) -> list[dict[str, str]]:
    """Every file the finished prompt wrote, flattened."""

    files: list[dict[str, str]] = []
    for node_output in (entry.get("outputs") or {}).values():
        for key in ("images", "gifs", "videos", "audio"):
            for item in node_output.get(key) or []:
                if not isinstance(item, dict) or not item.get("filename"):
                    continue
                files.append(
                    {
                        "filename": str(item["filename"]),
                        "subfolder": str(item.get("subfolder") or ""),
                        "type": str(item.get("type") or "output"),
                    }
                )
    return files
