"""Live sampler progress from ComfyUI's websocket.

ComfyUI broadcasts ``progress`` events with ``value``/``max`` while a sampler
runs. The render worker only polls HTTP, so this module keeps one lightweight
websocket open and stores the latest numbers per ``prompt_id``; the API then
exposes them to the browser instead of inventing a fake percentage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any

import websockets

from studio.api import config

log = logging.getLogger("lumen.progress")

_RECONNECT_SECONDS = 3.0
_IDLE_FORGET_SECONDS = 900.0


class ComfyProgress:
    """One websocket to ComfyUI, a thread-safe map of prompt_id -> step data."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._connected = False

    # -- lifecycle ----------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="comfy-progress", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    # -- worker -------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                asyncio.run(self._listen())
            except Exception as exc:  # noqa: BLE001 - the socket must never kill the app
                log.debug("progress socket closed: %s", exc)
            finally:
                with self._lock:
                    self._connected = False
            self._stop.wait(_RECONNECT_SECONDS)

    async def _listen(self) -> None:
        base = config.COMFYUI_URL.replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        url = f"{base}/ws?clientId={config.COMFY_CLIENT_ID}"
        async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
            with self._lock:
                self._connected = True
            self._prune()
            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):
                    continue
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                self._handle(message)

    def _prune(self) -> None:
        cutoff = time.time() - _IDLE_FORGET_SECONDS
        with self._lock:
            stale = [
                prompt_id
                for prompt_id, job in self._jobs.items()
                if job.get("updated", 0) < cutoff
            ]
            for prompt_id in stale:
                self._jobs.pop(prompt_id, None)

    def _handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        data = message.get("data") or {}
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            return
        now = time.time()
        with self._lock:
            job = self._jobs.get(prompt_id)
            if job is None:
                job = {
                    "value": 0,
                    "max": 0,
                    "phase": "queued",
                    "node": "",
                    "started": now,
                    "updated": now,
                }
                self._jobs[prompt_id] = job
            job["updated"] = now
            if kind == "execution_start":
                job["phase"] = "running"
                job["started"] = job.get("started") or now
            elif kind == "progress":
                try:
                    job["value"] = int(data.get("value") or 0)
                    job["max"] = int(data.get("max") or 0)
                except (TypeError, ValueError):
                    pass
                job["phase"] = "running"
                job["node"] = str(data.get("node") or "")
            elif kind == "executing":
                if data.get("node") is None:
                    job["phase"] = "finishing"
            elif kind in {"execution_success", "execution_error", "execution_interrupted"}:
                self._jobs.pop(prompt_id, None)

    # -- readers ------------------------------------------------------

    def snapshot(self, prompt_id: str) -> dict[str, Any] | None:
        if not prompt_id:
            return None
        with self._lock:
            job = self._jobs.get(prompt_id)
            return dict(job) if job else None


progress = ComfyProgress()
