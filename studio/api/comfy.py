"""Small ComfyUI HTTP client used by Lunar Studio.

Only the endpoints the app needs: server stats, queue submission, history
polling, output download and reference-image upload. No workflow knowledge
lives here.
"""

from __future__ import annotations

from studio.api import config

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
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
            parts.append(" · ".join(self.devices))
        if self.vram_total_mb:
            parts.append(f"{self.vram_total_mb / 1024:.1f} GB VRAM")
        return " · ".join(parts)


class ComfyUIClient:
    def __init__(self, url: str, *, timeout: float = 15.0) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.client_id = config.COMFY_CLIENT_ID

    # -- HTTP ---------------------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        raw: bool = False,
        timeout: float | None = None,
    ) -> Any:
        body = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.url}{path}", data=body, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(
                request, timeout=timeout or self.timeout
            ) as response:
                data = response.read()
                if raw:
                    return data
                text = data.decode("utf-8", errors="replace")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1600]
            raise ComfyUIError(
                f"ComfyUI HTTP {exc.code}：{detail or exc.reason}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ComfyUIUnavailable(
                f"连不上 ComfyUI（{self.url}）：{reason}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ComfyUIError("ComfyUI 返回了无法解析的 JSON。") from exc

    # -- server -------------------------------------------------------

    def system_stats(self, *, timeout: float = 4.0) -> dict[str, Any]:
        return self._call("GET", "/system_stats", timeout=timeout)

    def server(self, *, timeout: float = 4.0) -> ComfyServer:
        payload = self.system_stats(timeout=timeout)
        system = payload.get("system") or {}
        devices: list[str] = []
        vram = 0.0
        for device in payload.get("devices") or []:
            if not isinstance(device, dict):
                continue
            name = str(device.get("name") or "").strip()
            if name:
                devices.append(name)
            try:
                vram = max(vram, float(device.get("vram_total") or 0))
            except (TypeError, ValueError):
                pass
        return ComfyServer(
            url=self.url,
            version=str(system.get("comfyui_version") or ""),
            python=str(system.get("python_version") or ""),
            devices=tuple(devices),
            vram_total_mb=round(vram / (1024 * 1024), 1),
        )

    # -- jobs ---------------------------------------------------------

    def queue_prompt(self, workflow: dict[str, Any]) -> str:
        response = self._call(
            "POST", "/prompt", {"prompt": workflow, "client_id": self.client_id}
        )
        prompt_id = response.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(
                "ComfyUI 拒绝了工作流："
                + json.dumps(response, ensure_ascii=False)[:1600]
            )
        return str(prompt_id)

    def history(self, prompt_id: str) -> dict[str, Any]:
        return self._call(
            "GET", f"/history/{urllib.parse.quote(prompt_id)}"
        )

    def wait(
        self,
        prompt_id: str,
        *,
        timeout: float = 1800.0,
        poll: float = 1.5,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        missing = 0
        while time.monotonic() < deadline:
            entry = self.history(prompt_id).get(prompt_id)
            if entry:
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise ComfyUIError(_execution_error(entry))
                if status.get("completed") or entry.get("outputs"):
                    return entry
                missing = 0
            else:
                # A prompt that is neither queued nor in history is gone: it was
                # cancelled, the backend restarted, or the job never landed.
                # Waiting the full 30 minutes would hold the single render
                # worker (and every later project) hostage.
                try:
                    queue = self._call("GET", "/queue")
                except ComfyUIError:
                    queue = None
                if queue is None:
                    missing = 0
                else:
                    running = [str(item[1]) for item in queue.get("queue_running", [])]
                    pending = [str(item[1]) for item in queue.get("queue_pending", [])]
                    if prompt_id in running or prompt_id in pending:
                        missing = 0
                    else:
                        missing += 1
                        if missing >= 3:
                            raise ComfyUIError(
                                "ComfyUI 里已经找不到这个任务（可能被中断或后端重启）。"
                                "重新点一次生成即可。"
                            )
            time.sleep(poll)
        raise ComfyUIError(
            f"等待 ComfyUI 出图超时（{timeout:g} 秒），prompt_id={prompt_id}"
        )

    def fetch(self, filename: str, subfolder: str = "", kind: str = "output") -> bytes:
        query = urllib.parse.urlencode(
            {"filename": filename, "subfolder": subfolder, "type": kind}
        )
        return self._call("GET", f"/view?{query}", raw=True, timeout=120)

    def upload_image(
        self,
        path: Path,
        *,
        filename: str | None = None,
        overwrite: bool = True,
    ) -> dict[str, str]:
        """POST a reference image to ComfyUI's input directory."""

        data = path.read_bytes()
        suffix = path.suffix or ".png"
        name = filename or f"{path.stem}{suffix}"
        boundary = f"----Lunar{uuid4().hex}"
        parts: list[bytes] = [
            f"--{boundary}\r\n".encode(),
            (
                'Content-Disposition: form-data; name="image"; '
                f'filename="{name}"\r\n'
            ).encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            data,
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="overwrite"\r\n\r\n',
            b"true" if overwrite else b"false",
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        body = b"".join(parts)
        request = urllib.request.Request(
            f"{self.url}/upload/image",
            data=body,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(
                    response.read().decode("utf-8", errors="replace") or "{}"
                )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1200]
            raise ComfyUIError(
                f"ComfyUI 上传参考图失败（HTTP {exc.code}）：{detail or exc.reason}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ComfyUIUnavailable(
                f"连不上 ComfyUI（{self.url}）：{reason}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ComfyUIError("ComfyUI 上传参考图后返回了无法解析的 JSON。") from exc
        returned = str(payload.get("name") or "").strip()
        if not returned:
            raise ComfyUIError(
                "ComfyUI 上传参考图后没有返回文件名："
                + json.dumps(payload, ensure_ascii=False)[:600]
            )
        subfolder = str(payload.get("subfolder") or "").strip()
        return {
            "name": f"{subfolder}/{returned}".lstrip("/") if subfolder else returned,
            "subfolder": subfolder,
            "type": str(payload.get("type") or "input"),
        }

    def interrupt(self) -> None:
        try:
            self._call("POST", "/interrupt", {})
        except ComfyUIError:
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
    """Every image file the finished prompt wrote, flattened."""

    files: list[dict[str, str]] = []
    for node_output in (entry.get("outputs") or {}).values():
        for item in node_output.get("images") or []:
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
