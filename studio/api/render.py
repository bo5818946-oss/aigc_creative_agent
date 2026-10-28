"""Turn planned shots into real images through the local ComfyUI backend.

There is no placeholder output. A failed shot keeps ComfyUI's own error text
and the UI shows it. The service renders one job at a time because the local
8 GB card cannot usefully run several diffusion jobs at once.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import math
import os
import random
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageOps

from studio.api import config, store
from studio.api.comfy import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUIUnavailable,
    output_files,
)
from studio.api.models import ProjectResponse, RenderRecord, utc_now

log = logging.getLogger("lumen.render")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov"}


class RenderBusy(RuntimeError):
    """This project already has a render job running."""


class RenderInputError(RuntimeError):
    """The request does not match the project's plan."""


def size_for(aspect: str) -> tuple[int, int]:
    return config.ASPECT_SIZES.get(aspect) or config.ASPECT_SIZES["1:1"]


def load_workflow(reference: bool) -> dict[str, Any]:
    name = "zimage_turbo_ref.json" if reference else "zimage_turbo.json"
    path = config.WORKFLOW_DIR / name
    if not path.is_file():
        raise RenderInputError(f"缺少工作流文件：{path}")
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderInputError(f"工作流文件无法读取：{path}：{exc}") from exc
    if not isinstance(payload, dict) or not payload:
        raise RenderInputError(f"工作流文件不是有效的 API 格式图：{path}")
    return payload


def load_video_workflow() -> dict[str, Any]:
    """The H3 text-to-video graph. Missing file is an error, never a stub."""

    import json

    path = config.WORKFLOW_DIR / config.VIDEO_WORKFLOW
    if not path.is_file():
        raise RenderInputError(
            f"缺少视频工作流：{path}。请从 ComfyUI 导出 API 格式的 H3 图放到 studio/workflows/。"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderInputError(f"视频工作流无法读取：{path}：{exc}") from exc
    if not isinstance(payload, dict) or not payload:
        raise RenderInputError(f"视频工作流不是有效的 API 格式图：{path}")
    return payload


def video_size(aspect: str, seconds: float) -> tuple[int, int]:
    """10 s clips take the smaller step so an 8 GB card survives."""

    options = config.VIDEO_SIZES.get(aspect) or config.VIDEO_SIZES["16:9"]
    return options[1] if int(seconds) >= 10 else options[0]


def bind_video_workflow(
    template: dict[str, Any],
    *,
    prompt: str,
    width: int,
    height: int,
    seconds: float,
    seed: int,
    turbo: bool = True,
) -> dict[str, Any]:
    """Fill the H3 graph by role instead of hard-coded node ids."""

    graph = copy.deepcopy(template)
    prompt_nodes: list[str] = []
    duration_nodes: list[str] = []
    size_nodes: list[str] = []
    seed_nodes: list[str] = []
    turbo_nodes: list[str] = []

    for node_id, node in graph.items():
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        title = str((node.get("_meta") or {}).get("title") or "").lower()
        if isinstance(inputs.get("prompt"), str):
            prompt_nodes.append(node_id)
        if "studio duration" in title and isinstance(
            inputs.get("value"), (int, float)
        ) and not isinstance(inputs.get("value"), bool):
            duration_nodes.append(node_id)
        if isinstance(inputs.get("width"), int) and isinstance(
            inputs.get("height"), int
        ):
            size_nodes.append(node_id)
        if isinstance(inputs.get("noise_seed"), (int, float)):
            seed_nodes.append(node_id)
        if "turbo" in title and isinstance(inputs.get("value"), bool):
            turbo_nodes.append(node_id)

    if not prompt_nodes:
        raise RenderInputError("视频工作流里没有可写入 prompt 的节点。")
    if not duration_nodes:
        raise RenderInputError(
            "视频工作流里没有 Studio Duration 节点，无法按时长出片。"
        )

    for node_id in prompt_nodes:
        graph[node_id]["inputs"]["prompt"] = prompt
    for node_id in size_nodes:
        graph[node_id]["inputs"]["width"] = int(width)
        graph[node_id]["inputs"]["height"] = int(height)
    for node_id in duration_nodes:
        graph[node_id]["inputs"]["value"] = float(seconds)
    for node_id in seed_nodes:
        graph[node_id]["inputs"]["noise_seed"] = int(seed) % (2**31 - 1)
    for node_id in turbo_nodes:
        graph[node_id]["inputs"]["value"] = bool(turbo)
    return graph


def _fill(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _fill(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item, context) for item in value]
    if not isinstance(value, str):
        return value
    if value in context:
        return context[value]
    filled = value
    for key, replacement in context.items():
        if replacement is None:
            continue
        filled = filled.replace(key, str(replacement))
    return filled


def bind_workflow(
    template: dict[str, Any],
    *,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    project_id: str,
    shot_index: int,
    reference: str | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "{{prompt}}": prompt,
        "{{negative}}": negative,
        "{{width}}": int(width),
        "{{height}}": int(height),
        "{{seed}}": int(seed),
        "{{project}}": project_id,
        "{{shot}}": f"{shot_index:02d}",
        "{{reference}}": reference or "",
    }
    return _fill(copy.deepcopy(template), context)


def _safe_seed() -> int:
    return random.SystemRandom().randint(1, 2**31 - 1)


# Z-Image's reference latents are patchified at 2×2, so every spatial latent
# side must be even. The VAE downsamples by 8, which means the reference image
# itself must be a multiple of 16 on both sides. ComfyUI's auto_resize_images
# rounds to multiples of 8 only (1344×768 became 1352×776, latents 169×97),
# which crashes KSampler. Normalise here instead.
_REFERENCE_MAX_PIXELS = 1024 * 1024
_REFERENCE_MULTIPLE = 16


def reference_dimensions(
    width: int,
    height: int,
    *,
    max_pixels: int = _REFERENCE_MAX_PIXELS,
    multiple: int = _REFERENCE_MULTIPLE,
) -> tuple[int, int]:
    """Downscale a reference to about 1 MP with edges divisible by 16."""

    if width <= 0 or height <= 0:
        raise RenderInputError("参考图尺寸无效。")
    scale = min(1.0, math.sqrt(max_pixels / float(width * height)))

    def snap(value: float) -> int:
        return max(multiple, int(round(value / multiple)) * multiple)

    return snap(width * scale), snap(height * scale)


def prepare_reference(path: Path) -> Path:
    """Return a temporary RGB PNG that the Z-Image reference graph can encode."""

    target: Path | None = None
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            width, height = reference_dimensions(*image.size)
            if image.size != (width, height):
                image = image.resize((width, height), Image.Resampling.LANCZOS)
            descriptor, name = tempfile.mkstemp(
                prefix="lumen-ref-", suffix=".png"
            )
            os.close(descriptor)
            target = Path(name)
            image.save(target, format="PNG")
        return target
    except RenderInputError:
        if target is not None:
            target.unlink(missing_ok=True)
        raise
    except Exception as exc:
        if target is not None:
            target.unlink(missing_ok=True)
        raise RenderInputError(f"参考图无法读取或转换：{exc}") from exc


def _reference_name(project: ProjectResponse) -> str:
    digest = hashlib.sha256(
        f"{project.project_id}:{project.reference_id}".encode("utf-8")
    ).hexdigest()[:16]
    return f"lumen_ref_{digest}"


class RenderService:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="lumen-render"
        )
        self._active: set[str] = set()
        self._lock = threading.Lock()

    def is_active(self, project_id: str) -> bool:
        with self._lock:
            return project_id in self._active

    def submit(
        self, project_id: str, shot_indices: Iterable[int] | None = None
    ) -> list[int]:
        project = store.get_project(project_id)
        if project is None:
            raise RenderInputError("项目不存在。")
        available = {shot.index for shot in project.plan.shots}
        if shot_indices is None:
            selected = sorted(available)
        else:
            selected = sorted({int(index) for index in shot_indices})
            unknown = [index for index in selected if index not in available]
            if unknown:
                raise RenderInputError(
                    "这些镜头不在方案里：" + "、".join(str(index) for index in unknown)
                )
        if not selected:
            raise RenderInputError("这个项目还没有可生成的镜头。")
        with self._lock:
            if project_id in self._active:
                raise RenderBusy("这个项目已经在生成中。")
            self._active.add(project_id)
        # Create the rows now, not when the worker gets to them: a project that
        # is waiting behind another render must already read as „生成中” and
        # show its queued state in the UI.
        for index in selected:
            store.begin_render(project_id, index)
            store.set_shot_status(project_id, index, "queued")
        try:
            self._executor.submit(self._run, project_id, selected)
        except RuntimeError as exc:
            with self._lock:
                self._active.discard(project_id)
            self._fail_selected(project_id, selected, f"提交失败：{exc}")
            raise RenderInputError(f"提交失败：{exc}") from exc
        return selected

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- worker -------------------------------------------------------

    def _run(self, project_id: str, selected: list[int]) -> None:
        try:
            self._render(project_id, selected)
        except Exception:
            log.exception("render job crashed for project %s", project_id)
        finally:
            with self._lock:
                self._active.discard(project_id)

    def _render(self, project_id: str, selected: list[int]) -> None:
        project = store.get_project(project_id)
        if project is None:
            return
        client = ComfyUIClient(config.COMFYUI_URL, timeout=config.COMFYUI_HTTP_TIMEOUT)

        reference_path: Path | None = None
        if project.reference_id:
            reference_path = store.upload_path(project.reference_id)
            if reference_path is None:
                self._fail_selected(
                    project_id,
                    selected,
                    "参考图文件已丢失，无法生成。请重新上传参考图并重新规划。",
                )
                return

        is_video = project.plan.kind == "video"
        try:
            template = (
                load_video_workflow()
                if is_video
                else load_workflow(reference_path is not None)
            )
            client.server(timeout=5)
        except (RenderInputError, ComfyUIError) as exc:
            self._fail_selected(project_id, selected, str(exc))
            return

        reference_name: str | None = None
        prepared_reference: Path | None = None
        if reference_path is not None:
            try:
                prepared_reference = prepare_reference(reference_path)
                uploaded = client.upload_image(
                    prepared_reference,
                    filename=_reference_name(project) + ".png",
                )
                reference_name = uploaded["name"]
            except (ComfyUIError, OSError, RenderInputError) as exc:
                self._fail_selected(
                    project_id, selected, f"参考图上传到 ComfyUI 失败：{exc}"
                )
                return
            finally:
                if prepared_reference is not None:
                    try:
                        prepared_reference.unlink()
                    except OSError:
                        pass

        shots = {shot.index: shot for shot in project.plan.shots}
        for index in selected:
            shot = shots.get(index)
            if shot is None:
                continue
            render = store.begin_render(project_id, index)
            store.update_render(
                render.render_id, status="running", started_at=utc_now()
            )
            store.set_shot_status(project_id, index, "queued")
            seconds = float(shot.seconds or 0)
            if is_video:
                width, height = video_size(shot.aspect or project.plan.aspect, seconds)
            else:
                width, height = size_for(shot.aspect or project.plan.aspect)
            try:
                if is_video:
                    graph = bind_video_workflow(
                        template,
                        prompt=shot.prompt,
                        width=width,
                        height=height,
                        seconds=seconds,
                        seed=_safe_seed(),
                        turbo=config.VIDEO_TURBO,
                    )
                else:
                    graph = bind_workflow(
                        template,
                        prompt=shot.prompt,
                        negative=shot.negative,
                        width=width,
                        height=height,
                        seed=_safe_seed(),
                        project_id=project_id,
                        shot_index=index,
                        reference=reference_name,
                    )
                prompt_id = client.queue_prompt(graph)
                store.update_render(render.render_id, prompt_id=prompt_id)
                entry = client.wait(
                    prompt_id,
                    timeout=config.COMFYUI_JOB_TIMEOUT,
                    poll=1.5,
                )
                files = [item for item in output_files(entry) if item.get("type") != "temp"]
                if not files:
                    raise ComfyUIError(
                        ("ComfyUI 完成了任务，但没有返回任何视频文件。" if is_video else "ComfyUI 完成了任务，但没有返回任何图片文件。")
                    )
                first = files[0]
                data = client.fetch(
                    first["filename"],
                    first.get("subfolder", ""),
                    first.get("type", "output"),
                )
                if not data:
                    raise ComfyUIError(("ComfyUI 返回了空视频文件。" if is_video else "ComfyUI 返回了空图片文件。"))
                target = self._store_image(project_id, index, first["filename"], data)
                store.update_render(
                    render.render_id,
                    status="done",
                    file_url=f"/media/renders/{project_id}/{target.name}",
                    file_path=str(target),
                    width=width,
                    height=height,
                    error="",
                    finished_at=utc_now(),
                )
                store.set_shot_status(project_id, index, "done")
            except Exception as exc:
                message = str(exc).strip() or exc.__class__.__name__
                log.warning("shot %s of %s failed: %s", index, project_id, message)
                store.update_render(
                    render.render_id,
                    status="failed",
                    error=message[:4000],
                    finished_at=utc_now(),
                )
                store.set_shot_status(project_id, index, "failed")
            finally:
                store.touch_project(project_id)

    def _store_image(
        self, project_id: str, shot_index: int, filename: str, data: bytes
    ) -> Path:
        suffix = Path(filename).suffix.lower()
        if suffix in _VIDEO_SUFFIXES:
            pass
        elif suffix not in _IMAGE_SUFFIXES:
            suffix = ".mp4" if filename.lower().endswith(tuple(_VIDEO_SUFFIXES)) else ".png"
        folder = config.MEDIA_DIR / project_id
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"shot_{shot_index:02d}{suffix}"
        temporary = target.with_name(target.name + ".part")
        temporary.write_bytes(data)
        temporary.replace(target)
        for old in folder.glob(f"shot_{shot_index:02d}.*"):
            if old != target and old.name != temporary.name:
                try:
                    old.unlink()
                except OSError:
                    pass
        return target

    def _fail_selected(
        self, project_id: str, selected: Iterable[int], message: str
    ) -> None:
        for index in selected:
            render = store.begin_render(project_id, index)
            store.update_render(
                render.render_id,
                status="failed",
                error=message[:4000],
                finished_at=utc_now(),
            )
            store.set_shot_status(project_id, index, "failed")
        store.touch_project(project_id)


def render_file(project_id: str, render: RenderRecord) -> Path | None:
    if render.status != "done" or not render.file_url:
        return None
    name = Path(render.file_url).name
    target = (config.MEDIA_DIR / project_id / name).resolve()
    try:
        target.relative_to(config.MEDIA_DIR.resolve())
    except ValueError:
        return None
    return target if target.is_file() else None
