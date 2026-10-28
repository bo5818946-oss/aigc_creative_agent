"""Drive the local ComfyUI backend with the prompts the studio produced.

This is the "one click" step: every shot in the storyboard carries a prompt and
a clip length, and each one becomes exactly one submission to the local model.
Nothing here invents a prompt, a duration, or a file. If the backend is down or
the workflow rejects the graph, the shot is marked failed with the server's own
error text — no placeholder video, no fake success.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from config.settings import (
    COMFYUI_JOB_TIMEOUT_SECONDS,
    COMFYUI_POLL_SECONDS,
    MEDIA_DIR,
    WORKFLOW_DIR,
)
from schemas.conversation import utc_now
from services.clip_plan import VideoCapability, capability_for
from services.comfyui_client import (
    ComfyServer,
    ComfyUIClient,
    ComfyUIError,
    ComfyUIUnavailable,
    output_files,
)
from services.workflow_registry import (
    WorkflowError,
    WorkflowTemplate,
    bind,
    load_templates,
)

_SAFE = re.compile(r"[^0-9A-Za-z._-]+")


@dataclass(frozen=True)
class BackendProbe:
    reachable: bool
    url: str
    server: ComfyServer | None = None
    error: str = ""
    templates: tuple[WorkflowTemplate, ...] = ()
    template_errors: tuple[str, ...] = ()

    def of_kind(self, kind: str) -> list[WorkflowTemplate]:
        return [item for item in self.templates if item.kind == kind]


@dataclass
class MediaFile:
    filename: str
    path: Path
    kind: str


@dataclass
class ShotJob:
    shot_number: int
    prompt: str
    negative: str
    seconds: float
    status: str = "queued"  # queued | running | done | failed
    prompt_id: str = ""
    files: list[MediaFile] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "done" and bool(self.files)


def _safe_name(value: str) -> str:
    cleaned = _SAFE.sub("_", value).strip("_")
    return cleaned[:40] or "media"


class LocalGenerationService:
    """Submit one workflow per shot and collect the files the server wrote."""

    def __init__(
        self,
        client: ComfyUIClient,
        *,
        workflow_dir: Path = WORKFLOW_DIR,
        media_dir: Path = MEDIA_DIR,
        repository: Any | None = None,
        job_timeout: float = COMFYUI_JOB_TIMEOUT_SECONDS,
        poll: float = COMFYUI_POLL_SECONDS,
    ):
        self.client = client
        self.workflow_dir = workflow_dir
        self.media_dir = media_dir
        self.repository = repository
        self.job_timeout = job_timeout
        self.poll = poll

    # ------------------------------------------------------------------
    # discovery
    # ------------------------------------------------------------------
    def probe(self) -> BackendProbe:
        templates, errors = load_templates(self.workflow_dir)
        try:
            server = self.client.server()
        except (ComfyUIUnavailable, ComfyUIError) as exc:
            return BackendProbe(
                reachable=False,
                url=self.client.base_url,
                error=str(exc),
                templates=tuple(templates),
                template_errors=tuple(errors),
            )
        return BackendProbe(
            reachable=True,
            url=self.client.base_url,
            server=server,
            templates=tuple(templates),
            template_errors=tuple(errors),
        )

    def capability(
        self,
        *,
        template: WorkflowTemplate | None = None,
        clip_seconds: float | None = None,
        server: ComfyServer | None = None,
    ) -> VideoCapability:
        """Clip length the backend will actually return.

        The workflow's own duration input is the authority; a user override in
        the UI comes second; the reference table is only the last resort, and
        the returned capability says which one it used.
        """

        if clip_seconds:
            choices: tuple[float, ...] = (round(float(clip_seconds), 3),)
        elif template and template.clip_choices:
            choices = template.clip_choices
        elif template and template.default_seconds():
            choices = (round(float(template.default_seconds()), 3),)
        else:
            return capability_for()
        return capability_for(
            clip_seconds=choices,
            source="backend",
            display_name=(
                server.devices[0] if server and server.devices else "本地 ComfyUI"
            ),
            note=f"来自工作流 {template.name}" if template else "手动指定",
        )

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------
    def render_shots(
        self,
        *,
        project_id: str,
        shots: list[tuple[int, str, str]],
        template: WorkflowTemplate,
        seconds: float,
        size: tuple[int, int] | None = None,
        turbo: bool | None = None,
        on_event: Callable[[ShotJob], None] | None = None,
        on_tick: Callable[[int, float, str], None] | None = None,
    ) -> list[ShotJob]:
        """Render ``(shot_number, prompt, negative)`` triples in order.

        ``on_tick(shot_number, elapsed_seconds, state)`` fires every poll while
        a shot is running, so the page can show something moving instead of a
        frozen bar for four minutes.
        """

        notify = on_event or (lambda job: None)
        tick = on_tick or (lambda number, elapsed, state: None)
        width, height = size or (0, 0)
        jobs: list[ShotJob] = []
        for shot_number, prompt, negative in shots:
            job = ShotJob(
                shot_number=shot_number,
                prompt=prompt,
                negative=negative,
                seconds=seconds,
            )
            jobs.append(job)
            job.status = "running"
            notify(job)
            try:
                workflow = bind(
                    template,
                    prompt=prompt,
                    negative=negative,
                    seconds=seconds,
                    width=width or None,
                    height=height or None,
                    seed=random.randint(1, 2**31 - 1),
                    turbo=turbo,
                    project=project_id,
                    shot=shot_number,
                )
                job.prompt_id = self.client.submit(workflow)
                entry = self.client.wait(
                    job.prompt_id,
                    timeout=self.job_timeout,
                    poll=self.poll,
                    on_tick=lambda elapsed, state: tick(
                        shot_number, elapsed, state
                    ),
                )
                files = output_files(entry)
                if not files:
                    raise ComfyUIError(
                        "ComfyUI 跑完了，但输出里没有文件。"
                        "检查工作流是否接在 SaveVideo / SaveImage 上。"
                    )
                for item in files:
                    payload = self.client.fetch(
                        item["filename"],
                        item["subfolder"],
                        item["type"],
                    )
                    job.files.append(
                        self._write(project_id, shot_number, payload, item["filename"])
                    )
                job.status = "done"
            except (ComfyUIError, WorkflowError, OSError) as exc:
                job.status = "failed"
                job.error = str(exc)
            notify(job)
            self._persist(project_id, template, job)
        return jobs

    def _write(
        self,
        project_id: str,
        shot_number: int,
        payload: bytes,
        source_name: str,
    ) -> MediaFile:
        suffix = Path(source_name).suffix or ".bin"
        folder = self.media_dir / _safe_name(project_id)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"shot_{shot_number:02d}{suffix}"
        target.write_bytes(payload)
        kind = "video" if suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"} else "image"
        return MediaFile(filename=target.name, path=target, kind=kind)

    def _persist(
        self,
        project_id: str,
        template: WorkflowTemplate,
        job: ShotJob,
    ) -> None:
        if self.repository is None:
            return
        for item in job.files or [None]:
            self.repository.save_media(
                {
                    "media_id": uuid4().hex,
                    "project_id": project_id,
                    "shot_number": job.shot_number,
                    "kind": item.kind if item else template.kind,
                    "backend": self.client.base_url,
                    "workflow": template.name,
                    "prompt": job.prompt,
                    "file_path": str(item.path) if item else "",
                    "duration_seconds": job.seconds,
                    "status": job.status,
                    "error": job.error,
                    "created_at": utc_now(),
                }
            )
