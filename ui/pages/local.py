"""Local generation: hand the finished prompts to a model on this machine.

The studio's job ends with prompts. This page is the step after: it binds each
shot's prompt into a ComfyUI API workflow, submits it, and puts the returned
files next to the project. Image prompts go to the image graph, video prompts
to the video graph — the kind is chosen on entry, not guessed.

Nothing is simulated — if the backend is down the page says so, and if a shot
fails the server's error is shown verbatim.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import streamlit as st

from config.settings import COMFYUI_HTTP_TIMEOUT_SECONDS, COMFYUI_URL
from services import comfy_launcher
from services.comfyui_client import ComfyUIClient
from services.generation_service import (
    BackendProbe,
    LocalGenerationService,
    ShotJob,
)
from services.workflow_registry import WorkflowTemplate
from ui.state import get_repository
from ui.theme import (
    badge,
    empty_state,
    escape,
    page_header,
    section_header,
)

_KINDS = {
    "video": ("视频", "video_prompt", "视频工作流"),
    "image": ("图片", "image_prompt", "图片工作流"),
}

_PHASE_LABELS = {"running": "生成中", "queued": "排队中", "unknown": "生成中"}


def _clock(seconds: float) -> str:
    total = int(max(0.0, seconds))
    return f"{total // 60}:{total % 60:02d}"


def _service() -> LocalGenerationService:
    client = ComfyUIClient(COMFYUI_URL, timeout=COMFYUI_HTTP_TIMEOUT_SECONDS)
    return LocalGenerationService(client, repository=get_repository())


def _probe(refresh: bool = False) -> BackendProbe:
    cached = st.session_state.get("local_probe")
    if cached is not None and not refresh:
        return cached
    probe = _service().probe()
    st.session_state["local_probe"] = probe
    return probe


def _director_map(director: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(director.get("shot_prompts") or []):
        try:
            number = int(item.get("shot_number") or index + 1)
        except (TypeError, ValueError):
            number = index + 1
        result[number] = item
    return result


def _shot_rows(
    result: dict[str, Any],
    kind: str = "video",
) -> list[tuple[int, str, str]]:
    """``(shot_number, prompt, negative)`` for one prompt type."""

    key = _KINDS.get(kind, _KINDS["video"])[1]
    storyboard = result.get("storyboard") or {}
    director = storyboard.get("director_package") or {}
    mapping = _director_map(director)
    fallback_negative = str(director.get("negative_prompt") or "").strip()
    rows: list[tuple[int, str, str]] = []
    for index, shot in enumerate(storyboard.get("shots") or [], start=1):
        try:
            number = int(shot.get("shot_number") or index)
        except (TypeError, ValueError):
            number = index
        item = mapping.get(number, {})
        prompt = str(item.get(key) or "").strip()
        if not prompt:
            continue
        negative = str(item.get("negative_prompt") or fallback_negative).strip()
        rows.append((number, prompt, negative))
    return rows


def _render_backend(probe: BackendProbe) -> None:
    section_header("生成后端", "ComfyUI 跑在本机，工作室只负责把提示词送进去")
    st.caption(f"地址：{probe.url}")
    if probe.reachable and probe.server is not None:
        server = probe.server
        st.markdown(
            badge(f"已连接 · ComfyUI {server.version or 'unknown'}", "success"),
            unsafe_allow_html=True,
        )
        st.caption(server.describe())
    else:
        st.markdown(badge("未连接", "error"), unsafe_allow_html=True)
        st.error(probe.error or "连不上 ComfyUI。")
        if comfy_launcher.is_configured():
            if st.button(
                "启动 ComfyUI",
                type="primary",
                key="local_launch",
                help="用 .env 里配置的 Python 和安装目录把服务拉起来，再自动重连。",
            ):
                with st.spinner("正在启动 ComfyUI，第一次加载模型会慢一点…"):
                    try:
                        outcome = comfy_launcher.launch()
                        st.success(outcome.message)
                    except comfy_launcher.LaunchError as exc:
                        st.error(str(exc))
                _probe(refresh=True)
                st.rerun()
        else:
            st.caption(comfy_launcher.describe_configuration())
        st.caption(
            "也可以手动启动 ComfyUI Desktop，或在安装目录运行 "
            "`python main.py --listen 127.0.0.1 --port 8188`；"
            "换端口就设置环境变量 AIGC_COMFYUI_URL。"
        )
    for error in probe.template_errors:
        st.warning(error)
    if st.button("重新探测", key="local_reprobe"):
        _probe(refresh=True)
        st.rerun()


def _render_plan(
    result: dict[str, Any],
    shot_count: int,
    fallback_clip: float | None = None,
) -> None:
    requirement = result.get("structured_requirement") or {}
    duration = requirement.get("duration_seconds")
    clip = requirement.get("clip_seconds") or fallback_clip
    count = requirement.get("clip_count")
    columns = st.columns(3)
    with columns[0]:
        st.metric("成片时长", f"{float(duration):g} 秒" if duration else "—")
    with columns[1]:
        st.metric("每条片段", f"{float(clip):g} 秒" if clip else "—")
    with columns[2]:
        st.metric("需要生成", f"{count or shot_count} 条")


_SIZE_PRESETS: dict[str, tuple[tuple[int, int], ...]] = {
    "16:9": ((768, 432), (1024, 576), (1344, 768)),
    "9:16": ((432, 768), (576, 1024), (768, 1344)),
    "1:1": ((768, 768), (1024, 1024)),
}

_ASPECT = re.compile(r"([\d.]+)\s*[:：x×]\s*([\d.]+)")


def _aspect_ratio(aspect: str) -> float:
    match = _ASPECT.search(aspect or "")
    if match:
        try:
            left, right = float(match.group(1)), float(match.group(2))
        except ValueError:
            return 16 / 9
        if left > 0 and right > 0:
            return left / right
    return 16 / 9


def _size_options(aspect: str) -> list[tuple[int, int]]:
    """Three resolutions that match the project's real aspect ratio.

    A 2.39:1 film must not come out 16:9. Unknown ratios are derived from the
    numbers and snapped down to a multiple of 32, which is what the latents
    expect.
    """

    text = (aspect or "").strip()
    if text in _SIZE_PRESETS:
        return list(_SIZE_PRESETS[text])
    ratio = _aspect_ratio(text)
    sizes: list[tuple[int, int]] = []
    for base in (432, 576, 768):
        if ratio >= 1:
            height = base
            width = max(64, int(ratio * height) // 32 * 32)
        else:
            width = base
            height = max(64, int(width / ratio) // 32 * 32)
        sizes.append((width, height))
    return sizes


def _default_size_index(
    options: list[tuple[int, int]],
    vram_mb: float,
    kind: str = "video",
) -> int:
    """Pick a size that fits the card instead of a pretty number that OOMs.

    Measured on this 8 GB card: the image graph finishes 1344×768, the H3 video
    graph dies there with "would exceed allowed memory" and finishes at 768×432.
    So the video default is VRAM-aware while images may use the native size.
    """

    if kind == "image":
        return len(options) - 1 if vram_mb >= 8000 else 0
    if vram_mb >= 16384:
        return len(options) - 1
    if vram_mb >= 12288:
        return min(1, len(options) - 1)
    return 0


def _size_picker(probe: BackendProbe, aspect: str, kind: str) -> tuple[int, int]:
    options = _size_options(aspect)
    vram = probe.server.vram_total_mb if probe.server else 0.0
    labels = [f"{width}×{height}" for width, height in options]
    index = st.selectbox(
        "分辨率",
        range(len(options)),
        index=_default_size_index(options, vram, kind),
        format_func=lambda item: labels[item],
        key=f"local_size_{kind}",
    )
    if vram:
        st.caption(
            f"显存 {vram / 1024:.1f} GB · 画幅 {aspect} · "
            "更大的档位更清晰，但可能 OOM"
        )
    return options[index]


def _template_picker(
    label: str,
    templates: list[WorkflowTemplate],
    key: str,
) -> WorkflowTemplate | None:
    if not templates:
        st.info(
            f"没有可用的{label}。在 ComfyUI 里打开你的图，"
            "用 Workflow → Export (API) 导出，放到 "
            "`workflows/` 目录（可用 AIGC_WORKFLOW_DIR 改路径）。"
        )
        return None
    names = [f"{item.name}（{item.kind}）" for item in templates]
    index = st.selectbox(label, range(len(names)), format_func=lambda i: names[i], key=key)
    template = templates[index]
    default = template.default_seconds()
    if default:
        st.caption(f"工作流里的时长输入：{default:g} 秒")
    for note in template.notes:
        st.caption(f"注意：{note}")
    return template


def _render_media(path: Path, kind: str) -> None:
    if not path or not str(path).strip():
        return
    if not path.exists():
        st.warning(f"文件不见了：{path}")
        return
    if kind == "video":
        st.video(str(path))
    else:
        st.image(str(path))
    st.caption(f"`{path}`")


def _render_jobs(jobs: list[ShotJob]) -> None:
    done = [job for job in jobs if job.ok]
    failed = [job for job in jobs if job.status == "failed"]
    st.caption(f"完成 {len(done)} 条，失败 {len(failed)} 条。")
    for job in jobs:
        suffix = f" · {job.seconds:g} 秒" if job.seconds else ""
        with st.expander(
            f"镜头 {job.shot_number} · {job.status}{suffix}",
            expanded=bool(job.files),
        ):
            st.caption(job.prompt[:400])
            if job.error:
                st.error(job.error)
                if "out of memory" in job.error.lower():
                    st.info(
                        "显存不够。把分辨率调到更小的一档（8 GB 显卡建议 "
                        "768×432），或勾选 Turbo 再试。"
                    )
            for item in job.files:
                _render_media(Path(item.path), item.kind)


def _media_path(record: dict[str, Any]) -> Path | None:
    """A stored path, or None for a failed shot that never wrote a file."""

    raw = str(record.get("file_path") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.exists() else None


def _render_outputs(result: dict[str, Any]) -> None:
    project_id = result.get("project_id")
    if not project_id:
        return
    records = get_repository().list_media(str(project_id))
    if not records:
        return
    section_header("已生成的文件", f"项目 {project_id[:8]} 的历史输出")
    for record in records:
        label = (
            f"镜头 {record.get('shot_number')} · {record.get('status')} · "
            f"{record.get('kind')}"
        )
        path = _media_path(record)
        with st.expander(label, expanded=False):
            if record.get("error"):
                st.error(record["error"])
            if path is not None:
                _render_media(path, str(record.get("kind") or "image"))
            elif not record.get("error"):
                st.caption("这条没有留下文件。")
            st.caption(
                f"{escape(record.get('workflow') or '')} · "
                f"{escape(record.get('backend') or '')}"
            )


def render() -> None:
    page_header(
        "本地生成",
        "提示词直接投给本机模型",
        "图片提示词走图片模型，视频提示词走视频模型，一次调用产出一个文件。",
    )
    result = st.session_state.get("current_result")
    if not result:
        empty_state(
            "还没有可生成的提示词",
            "先在创作工作台跑完一次任务，提示词写好后这里会出现生成清单。",
        )
        return

    probe = _probe()
    _render_backend(probe)
    if not probe.reachable:
        return

    kind = st.radio(
        "要生成什么",
        list(_KINDS),
        format_func=lambda value: _KINDS[value][0],
        horizontal=True,
        key="local_kind",
    )
    label, _, template_label = _KINDS[kind]

    rows = _shot_rows(result, kind)
    if not rows:
        empty_state(
            f"没有{label}提示词",
            "这一次任务没有这一类逐镜头提示词。换一种生成类型，或回到工作台重新生成。",
        )
        return

    st.markdown("---")
    requirement = result.get("structured_requirement") or {}
    aspect = str(requirement.get("aspect_ratio") or "16:9")

    template = _template_picker(
        template_label,
        probe.of_kind(kind),
        f"local_{kind}_wf",
    )
    if template is None:
        return

    seconds = 0.0
    if kind == "video":
        _render_plan(result, len(rows), template.default_seconds())
        default_seconds = float(
            requirement.get("clip_seconds")
            or template.default_seconds()
            or 5
        )
        columns = st.columns(2)
        with columns[0]:
            seconds = st.number_input(
                "每条片段秒数",
                min_value=1.0,
                max_value=60.0,
                value=default_seconds,
                step=1.0,
                key="local_seconds",
                help="必须和工作流里的时长输入一致；这是模型一次真正能生成的秒数。",
            )
        with columns[1]:
            width, height = _size_picker(probe, aspect, kind)
    else:
        st.caption(f"{len(rows)} 张图片")
        width, height = _size_picker(probe, aspect, kind)

    turbo: bool | None = None
    if template.turbo_node:
        turbo = st.checkbox(
            "Turbo 8 步（快，质量略降）",
            value=False,
            key="local_turbo",
            help=(
                "开启蒸馏 LoRA：步数从 20 降到 8，单条约 3–4 分钟；"
                "关闭则按全量步数走，单条约 25 分钟。"
            ),
        )

    if st.button(
        f"生成全部 {len(rows)} {('条' if kind == 'video' else '张')}",
        type="primary",
        key="local_render",
    ):
        total = len(rows)
        bar = st.progress(0.0, text="准备提交…")
        detail = st.empty()
        run = {
            "done": 0,
            "durations": [],
            "shot_started": time.monotonic(),
        }

        def on_event(job: ShotJob) -> None:
            if job.status in {"done", "failed"}:
                run["durations"].append(time.monotonic() - run["shot_started"])
                run["done"] += 1
                run["shot_started"] = time.monotonic()
            bar.progress(
                run["done"] / max(1, total),
                text=f"完成 {run['done']} / {total}",
            )

        def on_tick(shot_number: int, elapsed: float, phase: str) -> None:
            durations = run["durations"]
            average = sum(durations) / len(durations) if durations else None
            fraction = min(0.97, elapsed / average) if average else 0.0
            overall = (run["done"] + fraction) / max(1, total)
            eta = ""
            if average and average > elapsed:
                eta = f" · 预计还需 {_clock(average - elapsed)}"
            bar.progress(
                min(0.99, overall),
                text=(
                    f"第 {shot_number} / {total} "
                    f"{_PHASE_LABELS.get(phase, '生成中')} · "
                    f"已用 {_clock(elapsed)}{eta}"
                ),
            )

        jobs = _service().render_shots(
            project_id=str(result.get("project_id") or "adhoc"),
            shots=rows,
            template=template,
            seconds=float(seconds),
            size=(width, height),
            turbo=turbo,
            on_event=on_event,
            on_tick=on_tick,
        )
        st.session_state["local_jobs"] = jobs
        bar.empty()
        detail.empty()

    jobs = st.session_state.get("local_jobs")
    if jobs:
        section_header("本次结果", "")
        _render_jobs(list(jobs))
    _render_outputs(result)
