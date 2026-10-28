"""Read API-format ComfyUI workflows and fill in the studio's values.

The studio ships no workflow of its own: a graph is a property of the machine
it runs on (which checkpoint, which VAE, which sampler). So the user exports
their working graph once with *Workflow → Export (API)*, and this module binds
the prompt, the clip length, the frame size and the seed into it.

Two binding paths, in priority order:

1. **Explicit placeholders.** A string input containing ``{{prompt}}``,
   ``{{negative}}``, ``{{seconds}}``, ``{{width}}``, ``{{height}}``, ``{{seed}}``,
   ``{{project}}`` or ``{{shot}}`` is substituted. This is unambiguous and is
   what a hand-written template should use.
2. **Graph inspection.** No placeholder: follow the sampler's ``positive`` /
   ``negative`` links to the text encoder, and look for duration / size / seed
   inputs by name. Only names that genuinely exist are touched.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")

#: ``_meta.title`` marker for the one node that takes the clip length in
#: seconds. Everything model-specific (frame grids, fps) stays inside the graph.
DURATION_MARKER = "studio duration"

#: Input names that carry a duration in seconds.
_SECOND_KEYS = ("seconds", "duration", "length_seconds", "clip_seconds")
#: Input names that carry a duration in frames.
_FRAME_KEYS = ("length", "num_frames", "frame_count", "frames", "video_frames")
_SEED_KEYS = ("seed", "noise_seed", "rand_seed")

_VIDEO_HINTS = (
    "CreateVideo",
    "SaveVideo",
    "SaveAnimated",
    "VHS_VideoCombine",
    "VideoCombine",
)
_IMAGE_HINTS = ("SaveImage", "PreviewImage")


class WorkflowError(ValueError):
    """The file is not a usable API-format workflow."""


@dataclass(frozen=True)
class WorkflowTemplate:
    path: Path
    name: str
    kind: str  # "image" | "video"
    data: dict[str, Any]
    seconds: float | None = None
    frames: int | None = None
    fps: float | None = None
    positive_nodes: tuple[str, ...] = ()
    negative_nodes: tuple[str, ...] = ()
    #: Nodes whose input is literally called ``prompt`` (many video nodes take
    #: the text directly instead of through a CLIPTextEncode).
    inline_prompt_nodes: tuple[str, ...] = ()
    #: Node whose ``_meta.title`` is ``Studio Duration``. Workflows that compute
    #: frames from seconds (17k+5 grids, fps quirks) keep their own maths and
    #: expose just this one float for the studio to set.
    duration_node: str | None = None
    #: Boolean switch that enables a distilled turbo LoRA. Flipping it changes
    #: the cost per clip by an order of magnitude, so the studio exposes it.
    turbo_node: str | None = None
    #: Clip lengths this graph was trained/tested for, declared by the template
    #: (``_meta.studio_clips``). Empty means "the default value only".
    clip_choices: tuple[float, ...] = ()
    size_nodes: tuple[str, ...] = ()
    uses_placeholders: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def default_seconds(self) -> float | None:
        if self.seconds:
            return float(self.seconds)
        if self.frames and self.fps:
            return round(self.frames / self.fps, 3)
        return None


def _class(data: dict[str, Any], node_id: str) -> str:
    node = data.get(node_id) or {}
    return str(node.get("class_type") or "")


def _is_api_format(payload: Any) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    for value in payload.values():
        if not isinstance(value, dict):
            return False
        if "class_type" not in value:
            return False
    return True


def _linked_nodes(data: dict[str, Any], value: Any) -> list[str]:
    """Resolve a sampler's ``["6", 0]``-style link to node id(s)."""

    if isinstance(value, (list, tuple)) and len(value) == 2:
        node_id = str(value[0])
        if node_id in data:
            return [node_id]
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_linked_nodes(data, item))
        return result
    return []


def _text_of(data: dict[str, Any], node_id: str) -> str | None:
    inputs = (data.get(node_id) or {}).get("inputs") or {}
    for key in ("text", "text_g", "prompt", "positive"):
        value = inputs.get(key)
        if isinstance(value, str):
            return value
    return None


def parse_template(path: Path) -> WorkflowTemplate:
    try:
        # utf-8-sig: Windows editors and PowerShell like to prepend a BOM.
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"{path.name} 读不出来：{exc}") from exc

    if isinstance(payload, dict) and "nodes" in payload and "links" in payload:
        raise WorkflowError(
            f"{path.name} 是 ComfyUI 的 UI 格式，不能直接提交。"
            "请在 ComfyUI 里用 Workflow → Export (API) 重新导出。"
        )
    if not _is_api_format(payload):
        raise WorkflowError(
            f"{path.name} 不是 API 格式工作流（需要 {{node_id: {{class_type, inputs}}}}）。"
        )

    data: dict[str, Any] = payload
    classes = {node_id: _class(data, node_id) for node_id in data}
    blob = " ".join(classes.values())
    if any(hint in blob for hint in _VIDEO_HINTS):
        kind = "video"
    elif any(hint in blob for hint in _IMAGE_HINTS):
        kind = "image"
    else:
        kind = "unknown"

    positive: list[str] = []
    negative: list[str] = []
    for node_id, node in data.items():
        inputs = node.get("inputs") or {}
        for key, bucket in (("positive", positive), ("negative", negative)):
            for target in _linked_nodes(data, inputs.get(key)):
                if target not in bucket and _text_of(data, target) is not None:
                    bucket.append(target)
    if not positive and not negative:
        encoders = [
            node_id
            for node_id in data
            if "CLIPTextEncode" in classes[node_id] and _text_of(data, node_id)
        ]
        encoders.sort(key=lambda item: int(item) if item.isdigit() else 0)
        if encoders:
            positive = [encoders[0]]
            negative = encoders[1:2]

    seconds = None
    frames = None
    fps = None
    size_nodes: list[str] = []
    inline_prompt: list[str] = []
    duration_node: str | None = None
    turbo_node: str | None = None
    clip_choices: tuple[float, ...] = ()
    for node_id, node in data.items():
        inputs = node.get("inputs") or {}
        meta = node.get("_meta") or {}
        title = str(meta.get("title") or "").lower()
        if DURATION_MARKER in title:
            value = inputs.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                duration_node = node_id
                seconds = float(value)
            declared = meta.get("studio_clips")
            if isinstance(declared, list):
                clip_choices = tuple(
                    sorted(
                        float(item)
                        for item in declared
                        if isinstance(item, (int, float)) and item > 0
                    )
                )
        if "turbo" in title and isinstance(inputs.get("value"), bool):
            turbo_node = node_id
        direct = inputs.get("prompt")
        # An empty string still marks the node as the prompt slot: a template
        # ships with ``"prompt": ""`` precisely so the studio can fill it.
        if isinstance(direct, str):
            inline_prompt.append(node_id)
        for key, value in inputs.items():
            if key in _SECOND_KEYS and isinstance(value, (int, float)):
                seconds = float(value)
            elif key in _FRAME_KEYS and isinstance(value, (int, float)):
                frames = int(value)
            elif key == "fps" and isinstance(value, (int, float)):
                fps = float(value)
        size_capable = (
            "batch_size" in inputs
            or "Latent" in classes[node_id]
            or "Video" in classes[node_id]
            or "Resolution" in classes[node_id]
        )
        if (
            isinstance(inputs.get("width"), int)
            and isinstance(inputs.get("height"), int)
            and size_capable
        ):
            size_nodes.append(node_id)

    uses_placeholders = any(
        isinstance(value, str) and PLACEHOLDER.search(value)
        for node in data.values()
        for value in (node.get("inputs") or {}).values()
    )

    notes: list[str] = []
    if kind == "video" and seconds is None and frames is None:
        notes.append("工作流里没找到时长输入（seconds/length），片段长度需要你手动指定。")
    if not positive:
        notes.append("没找到正向提示词节点，生成时不会替换提示词。")

    return WorkflowTemplate(
        path=path,
        name=path.stem,
        kind=kind,
        data=data,
        seconds=seconds,
        frames=frames,
        fps=fps,
        positive_nodes=tuple(positive),
        negative_nodes=tuple(negative),
        inline_prompt_nodes=tuple(inline_prompt),
        duration_node=duration_node,
        turbo_node=turbo_node,
        clip_choices=clip_choices,
        size_nodes=tuple(size_nodes),
        uses_placeholders=uses_placeholders,
        notes=tuple(notes),
    )


def load_templates(directory: Path) -> list[WorkflowTemplate]:
    """Every valid template in ``directory``, plus the ones that failed.

    Returns ``(templates, errors)`` so the UI can show a broken file instead of
    quietly offering fewer workflows than exist on disk.
    """

    templates: list[WorkflowTemplate] = []
    errors: list[str] = []
    if not directory.exists():
        return templates, errors
    for path in sorted(directory.glob("*.json")):
        try:
            templates.append(parse_template(path))
        except WorkflowError as exc:
            errors.append(str(exc))
    return templates, errors


def _substitute(value: Any, context: dict[str, Any], used: set[str]) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in context:
                raise WorkflowError(f"工作流用了未知占位符 {{{{{key}}}}}。")
            used.add(key)
            return str(context[key])

        return PLACEHOLDER.sub(replace, value)
    if isinstance(value, list):
        return [_substitute(item, context, used) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, context, used) for key, item in value.items()}
    return value


def bind(
    template: WorkflowTemplate,
    *,
    prompt: str,
    negative: str = "",
    seconds: float | None = None,
    width: int | None = None,
    height: int | None = None,
    seed: int | None = None,
    turbo: bool | None = None,
    project: str = "",
    shot: int = 0,
) -> dict[str, Any]:
    """Return a submittable copy of the template with this shot filled in."""

    data = copy.deepcopy(template.data)
    context = {
        "prompt": prompt,
        "negative": negative,
        "seconds": seconds if seconds is not None else (template.default_seconds() or 0),
        "width": width or 0,
        "height": height or 0,
        "seed": seed if seed is not None else 0,
        "project": project,
        "shot": shot,
    }

    if template.uses_placeholders:
        used: set[str] = set()
        data = _substitute(data, context, used)
        if "prompt" not in used:
            raise WorkflowError("工作流有占位符但没有用 {{prompt}}。")

    for node_id in template.positive_nodes:
        inputs = data[node_id].setdefault("inputs", {})
        if not any(isinstance(v, str) and PLACEHOLDER.search(v) for v in inputs.values()):
            inputs["text"] = prompt
    for node_id in template.inline_prompt_nodes:
        inputs = data[node_id].setdefault("inputs", {})
        if "prompt" in inputs and not any(
            isinstance(v, str) and PLACEHOLDER.search(v) for v in inputs.values()
        ):
            inputs["prompt"] = prompt
    if negative:
        for node_id in template.negative_nodes:
            inputs = data[node_id].setdefault("inputs", {})
            if not any(
                isinstance(v, str) and PLACEHOLDER.search(v) for v in inputs.values()
            ):
                inputs["text"] = negative

    fps = template.fps or 24.0
    if template.duration_node and seconds is not None:
        data[template.duration_node].setdefault("inputs", {})["value"] = round(
            float(seconds), 3
        )
    if template.turbo_node and turbo is not None:
        data[template.turbo_node].setdefault("inputs", {})["value"] = bool(turbo)
    for node in data.values():
        inputs = node.setdefault("inputs", {})
        for key, value in list(inputs.items()):
            if key in _SECOND_KEYS and seconds is not None and isinstance(
                value, (int, float)
            ):
                inputs[key] = round(float(seconds), 3)
            elif key in _FRAME_KEYS and seconds is not None and isinstance(value, int):
                inputs[key] = max(1, int(round(float(seconds) * fps)))
            elif key in _SEED_KEYS and seed is not None and isinstance(value, int):
                inputs[key] = int(seed)

    for node_id in template.size_nodes:
        inputs = data[node_id]["inputs"]
        if width:
            inputs["width"] = int(width)
        if height:
            inputs["height"] = int(height)

    return data
