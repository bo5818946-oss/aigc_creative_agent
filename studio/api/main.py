"""FastAPI entry point for Lunar Studio.

Start from the repository root:

    uvicorn studio.api.main:app --reload --port 8600

The React app in ``studio/frontend`` proxies ``/api`` and ``/media`` here.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import mimetypes
import threading
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from studio.api import config, planner, progress, store
from studio.api.comfy import ComfyUIClient, ComfyUIError, ComfyUIUnavailable
from studio.api.llm import LLMContractError, LLMUnavailable
from studio.api.models import (
    ConceptList,
    ConceptRequest,
    CustomConceptRequest,
    HealthResponse,
    PlanRequest,
    ProjectList,
    ProjectResponse,
    RenderRequest,
    ShotPatch,
    UploadRecord,
    VideoConcept,
    VideoProjectRequest,
    VideoReviseRequest,
)
from studio.api.render import (
    RenderBusy,
    RenderInputError,
    RenderService,
    render_file,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("lumen.api")

render_service = RenderService()
_launch_lock = threading.Lock()

UPLOAD_SUFFIXES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
FRONTEND_DIST = config.STUDIO_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init_db()
    interrupted = store.fail_interrupted_renders(
        "API 服务重启，上一轮生成已中断。请重新生成这一镜。"
    )
    if interrupted:
        log.warning("marked %s interrupted render(s) as failed", interrupted)
    progress.progress.start()
    yield
    progress.progress.stop()
    render_service.shutdown()


app = FastAPI(
    title="Lunar Studio API",
    version="0.1.0",
    description="Image-first creative studio: skill-driven planning + local ComfyUI rendering.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(
    "/media/uploads",
    StaticFiles(directory=config.UPLOAD_DIR),
    name="uploads",
)
app.mount(
    "/media/renders",
    StaticFiles(directory=config.MEDIA_DIR),
    name="renders",
)


# ---------------------------------------------------------------------------
# Health & local runtime
# ---------------------------------------------------------------------------


def _launch_configured() -> bool:
    try:
        from services.comfy_launcher import is_configured

        return bool(is_configured())
    except Exception:
        return False


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    client = ComfyUIClient(config.COMFYUI_URL, timeout=4)
    reachable = False
    version = ""
    devices: list[str] = []
    vram_gb = 0.0
    error = ""
    try:
        server = client.server(timeout=2.5)
        reachable = True
        version = server.version
        devices = list(server.devices)
        vram_gb = round(server.vram_total_mb / 1024, 1)
    except ComfyUIError as exc:
        error = str(exc)
    skills = [
        {
            "id": key,
            "label": str(meta["label"]),
            "version": str(meta["version"]),
            "source": str(meta["source"]),
        }
        for key, meta in config.SKILLS.items()
    ]
    return HealthResponse(
        deepseek_configured=bool(config.DEEPSEEK_API_KEY),
        deepseek_model=config.DEEPSEEK_MODEL,
        comfyui_configured=bool(config.COMFYUI_URL),
        comfyui_url=config.COMFYUI_URL,
        comfyui_reachable=reachable,
        comfyui_version=version,
        comfyui_devices=devices,
        comfyui_vram_gb=vram_gb,
        comfyui_error=error,
        skills=skills,
        project_count=store.project_count(),
        launch_configured=_launch_configured(),
    )


@app.post("/api/comfy/start")
async def start_comfy() -> dict[str, Any]:
    try:
        from services.comfy_launcher import LaunchError, launch
    except Exception as exc:  # pragma: no cover - configuration edge
        raise HTTPException(500, f"启动器不可用：{exc}") from exc
    if not _launch_lock.acquire(blocking=False):
        return {"ok": False, "message": "启动请求正在处理中。"}
    try:
        result = await asyncio.to_thread(launch)
    except LaunchError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        _launch_lock.release()
    return {"ok": bool(result.ok), "message": result.message, "pid": result.pid}


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


@app.post("/api/uploads", response_model=UploadRecord)
async def upload_image(file: UploadFile = File(...)) -> UploadRecord:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in UPLOAD_SUFFIXES:
        guessed = mimetypes.guess_extension(file.content_type or "") or ""
        if guessed in {".jpe", ".jpeg"}:
            guessed = ".jpg"
        suffix = guessed if guessed in UPLOAD_SUFFIXES else ""
    if not suffix:
        raise HTTPException(
            415,
            "只支持 PNG、JPG/JPEG 或 WebP 参考图。",
        )
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(400, "上传的文件是空的。")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"参考图不能超过 {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB。",
        )
    upload_id = uuid4().hex
    stored_name = f"{upload_id}{suffix}"
    target = config.UPLOAD_DIR / stored_name
    target.write_bytes(data)
    return store.save_upload(
        upload_id=upload_id,
        filename=file.filename or stored_name,
        mime=UPLOAD_SUFFIXES[suffix],
        path=target,
        url=f"/media/uploads/{stored_name}",
    )


@app.get("/api/uploads/{upload_id}", response_model=UploadRecord)
def get_upload(upload_id: str) -> UploadRecord:
    record = store.get_upload(upload_id)
    if record is None:
        raise HTTPException(404, "参考图不存在。")
    return record


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def _plan_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, planner.PlanInputError):
        return HTTPException(400, str(exc))
    if isinstance(exc, LLMUnavailable):
        return HTTPException(503, str(exc))
    if isinstance(exc, LLMContractError):
        return HTTPException(502, str(exc))
    log.exception("unexpected planning failure")
    return HTTPException(500, f"规划失败：{exc}")


@app.post("/api/plan", response_model=ProjectResponse)
async def create_plan(req: PlanRequest) -> ProjectResponse:
    try:
        outcome = await asyncio.to_thread(planner.generate_project, req)
    except Exception as exc:
        raise _plan_http_error(exc) from exc
    return outcome.project


def _sse(event: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {body}\n\n"


@app.post("/api/plan/stream")
async def create_plan_stream(req: PlanRequest) -> StreamingResponse:
    async def generate():
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(payload: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, dict(payload))

        def work() -> None:
            try:
                outcome = planner.generate_project(req, emit)
                emit(
                    {
                        "stage": "result",
                        "message": "方案已保存",
                        "project": outcome.project.model_dump(mode="json"),
                        "usage": outcome.usage,
                    }
                )
            except Exception as exc:  # the browser gets the real reason
                if not isinstance(
                    exc, (planner.PlanInputError, LLMUnavailable, LLMContractError)
                ):
                    log.exception("planning failed")
                emit(
                    {
                        "stage": "error",
                        "message": str(exc).strip() or exc.__class__.__name__,
                        "kind": exc.__class__.__name__,
                    }
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=work, daemon=True).start()
        yield _sse("open", {"message": "规划通道已建立"})
        while True:
            item = await queue.get()
            if item is None:
                return
            stage = item.get("stage")
            if stage == "error":
                yield _sse("error", item)
                return
            if stage == "result":
                yield _sse("result", item)
                return
            yield _sse("status", item)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Projects & renders
# ---------------------------------------------------------------------------


@app.get("/api/projects", response_model=ProjectList)
def list_projects(
    limit: int = Query(40, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> ProjectList:
    return store.list_projects(limit=limit, offset=offset)


@app.get("/api/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str) -> ProjectResponse:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, "项目不存在。")
    return project


@app.post("/api/projects/{project_id}/render")
async def start_render(
    project_id: str, req: RenderRequest
) -> dict[str, Any]:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, "项目不存在。")
    client = ComfyUIClient(config.COMFYUI_URL, timeout=4)
    try:
        await asyncio.to_thread(client.server, timeout=3.0)
    except ComfyUIError as exc:
        raise HTTPException(
            503,
            "ComfyUI 不可用，尚未开始生成。"
            f"请先在设置页启动本地模型服务。原始错误：{exc}",
        ) from exc
    try:
        selected = render_service.submit(project_id, req.shot_indices)
    except RenderBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except RenderInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    fresh = store.get_project(project_id)
    return {
        "project_id": project_id,
        "queued": selected,
        "project": fresh.model_dump(mode="json") if fresh else None,
    }


@app.patch(
    "/api/projects/{project_id}/shots/{shot_index}",
    response_model=ProjectResponse,
)
def patch_shot(
    project_id: str, shot_index: int, patch: ShotPatch
) -> ProjectResponse:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, "项目不存在。")
    if render_service.is_active(project_id):
        raise HTTPException(409, "生成进行中，暂时不能修改提示词。")
    changes = patch.changes()
    if not changes:
        raise HTTPException(400, "没有提交任何修改。")
    shot = next(
        (item for item in project.plan.shots if item.index == shot_index), None
    )
    if shot is None:
        raise HTTPException(404, "镜头不存在。")
    for key, value in changes.items():
        setattr(shot, key, value)
    shot.status = "planned"
    removed = store.delete_render(project_id, shot_index)
    if removed:
        _remove_media_file(removed)
    store.update_plan(project_id, project.plan)
    fresh = store.get_project(project_id)
    if fresh is None:
        raise HTTPException(500, "保存后无法读回项目。")
    return fresh


def _remove_media_file(raw: str) -> None:
    try:
        target = Path(raw).resolve()
        target.relative_to(config.MEDIA_DIR.resolve())
    except (OSError, ValueError):
        return
    try:
        target.unlink(missing_ok=True)
    except OSError:
        pass


@app.post("/api/projects/{project_id}/reprompt", response_model=ProjectResponse)
async def reprompt_project(project_id: str) -> ProjectResponse:
    """Rewrite stored prompts and drop the images they no longer describe."""

    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, "项目不存在。")
    if render_service.is_active(project_id):
        raise HTTPException(409, "生成进行中，暂时不能重写提示词。")
    try:
        plan = await asyncio.to_thread(planner.rewrite_prompts, project)
    except planner.PlanInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LLMUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except LLMContractError as exc:
        raise HTTPException(502, str(exc)) from exc
    store.update_plan(project_id, plan)
    for shot in plan.shots:
        removed = store.delete_render(project_id, shot.index)
        if removed:
            _remove_media_file(removed)
    fresh = store.get_project(project_id)
    if fresh is None:
        raise HTTPException(500, "重写后无法读回项目。")
    return fresh


# ---------------------------------------------------------------------------
# Video: four directions, then one clip
# ---------------------------------------------------------------------------


@app.post("/api/video/concepts", response_model=ConceptList)
async def video_concepts(req: ConceptRequest) -> ConceptList:
    """Ask the planner for exactly four single-take directions."""

    try:
        concepts, _usage = await asyncio.to_thread(planner.propose_concepts, req)
    except LLMUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except LLMContractError as exc:
        raise HTTPException(502, str(exc)) from exc
    return ConceptList(
        concepts=concepts,
        duration=req.duration,
        aspect=req.aspect,
        skill="video",
        skill_version=str(config.SKILLS["video"]["version"]),
    )


@app.post("/api/video/draft", response_model=VideoConcept)
async def video_draft(req: CustomConceptRequest) -> VideoConcept:
    """One concept written from the user's own direction."""

    try:
        concept, _usage = await asyncio.to_thread(planner.draft_concept, req)
    except LLMUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except LLMContractError as exc:
        raise HTTPException(502, str(exc)) from exc
    return concept


@app.post("/api/video/projects", response_model=ProjectResponse)
async def create_video_project(req: VideoProjectRequest) -> ProjectResponse:
    """Store the direction the user picked (from the four, or their own)."""

    try:
        project = await asyncio.to_thread(planner.create_video_project, req)
    except planner.PlanInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    return project


@app.post(
    "/api/projects/{project_id}/video/revise", response_model=ProjectResponse
)
async def revise_video(project_id: str, req: VideoReviseRequest) -> ProjectResponse:
    """Apply a follow-up note and drop the clip it no longer describes."""

    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, "项目不存在。")
    if project.plan.kind != "video":
        raise HTTPException(400, "这个项目不是视频项目。")
    if render_service.is_active(project_id):
        raise HTTPException(409, "生成进行中，暂时不能改提示词。")
    try:
        plan = await asyncio.to_thread(planner.revise_video, project, req.feedback)
    except planner.PlanInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LLMUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except LLMContractError as exc:
        raise HTTPException(502, str(exc)) from exc
    store.update_plan(project_id, plan)
    for shot in plan.shots:
        removed = store.delete_render(project_id, shot.index)
        if removed:
            _remove_media_file(removed)
    fresh = store.get_project(project_id)
    if fresh is None:
        raise HTTPException(500, "改写后无法读回项目。")
    return fresh


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _route_label(route: str) -> str:
    if route == "video":
        return "视频"
    return "影视图" if route == "cinema" else "电商图"


def _prompts_markdown(project: ProjectResponse) -> str:
    plan = project.plan
    lines = [
        f"# {plan.title}",
        "",
        f"- 路线：{_route_label(plan.route)}"
        + ("（Agent 自主决策）" if plan.mode == "auto" else ""),
        f"- 技能：{plan.skill} {plan.skill_version}".strip(),
        f"- 画幅：{plan.aspect}",
        f"- 镜头：{len(plan.shots)}",
        f"- 创建时间：{plan.created_at}",
        "",
        "## 方案说明",
        "",
        plan.summary or "（未提供）",
        "",
        "## 判断与排镜理由",
        "",
        plan.reasoning or "（未提供）",
        "",
    ]
    decision = plan.agent_decision or {}
    if decision:
        lines += [
            "## Agent 自主决策",
            "",
            f"- 路线：{_route_label(str(decision.get('route', plan.route)))}",
            f"- 理由：{decision.get('reasoning', '（未提供）')}",
            "",
        ]
    lines += ["## Style Lock", "", plan.style_lock or "（未提供）", ""]
    if plan.continuity:
        lines += ["## 连续性", "", plan.continuity, ""]
    if plan.warnings:
        lines += ["## 待确认与风险", ""]
        lines += [f"- {item}" for item in plan.warnings]
        lines.append("")
    for shot in plan.shots:
        lines += [
            f"## {shot.index:02d} · {shot.title or '未命名'}",
            "",
            f"- 画幅：{shot.aspect or plan.aspect}",
            f"- 状态：{shot.status}",
            f"- 用途：{shot.purpose or '（未提供）'}",
            f"- 机位：{shot.camera or '（未提供）'}",
            f"- 备注：{shot.notes or '（未提供）'}",
            "",
            "### Prompt",
            "",
            "```text",
            shot.prompt,
            "```",
            "",
            "### Negative",
            "",
            "```text",
            shot.negative or "（未提供）",
            "```",
            "",
        ]
        if shot.caption:
            lines += ["### 图片内文案建议", "", shot.caption, ""]
    lines += [
        "---",
        "",
        "由 Lunar Studio 导出。图片由本地 ComfyUI / Z-Image Turbo 生成。",
        "",
    ]
    return "\n".join(lines)


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str) -> Response:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, "项目不存在。")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "plan.json", project.plan.model_dump_json(indent=2)
        )
        archive.writestr("prompts.md", _prompts_markdown(project))
        lines = [
            "Lunar Studio export",
            f"project_id: {project.project_id}",
            f"title: {project.title}",
            f"route: {project.route}",
            f"status: {project.status}",
            "",
            "Rendered images:",
        ]
        for render in project.renders:
            path = render_file(project_id, render)
            if path is None:
                lines.append(
                    f"- shot {render.shot_index:02d}: not available ({render.status})"
                )
                continue
            archive.write(path, f"images/{path.name}")
            lines.append(f"- shot {render.shot_index:02d}: {path.name}")
        lines += [
            "",
            "The plan and every prompt above are the exact text sent to the",
            "local image model. Images are only included when a render succeeded.",
            "",
        ]
        archive.writestr("README.txt", "\n".join(lines))
    payload = buffer.getvalue()
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="lumen-{project_id[:8]}.zip"'
            )
        },
    )


# ---------------------------------------------------------------------------
# Live render progress
# ---------------------------------------------------------------------------


def _elapsed_seconds(started_at: str | None) -> float:
    if not started_at:
        return 0.0
    try:
        from datetime import datetime

        started = datetime.fromisoformat(started_at)
        return max(0.0, (datetime.now(started.tzinfo) - started).total_seconds())
    except (TypeError, ValueError):
        return 0.0


@app.get("/api/projects/{project_id}/progress")
async def project_progress(project_id: str) -> dict[str, Any]:
    """Real sampler steps for whatever this project is rendering right now."""

    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, "项目不存在。")
    items: list[dict[str, Any]] = []
    for render in project.renders:
        if render.status not in {"queued", "running"}:
            continue
        snap = progress.progress.snapshot(render.prompt_id)
        elapsed = _elapsed_seconds(render.started_at) or _elapsed_seconds(
            render.updated_at
        )
        value = int(snap["value"]) if snap else 0
        total = int(snap["max"]) if snap else 0
        phase = str(snap["phase"]) if snap else (
            "running" if render.status == "running" else "queued"
        )
        percent = 0.0
        if total > 0:
            percent = min(100.0, round(value / total * 100, 1))
        elif phase == "finishing":
            percent = 100.0
        eta: float | None = None
        if value > 0 and total > value and elapsed > 1:
            eta = round(elapsed * (total - value) / value, 1)
        items.append(
            {
                "shot_index": render.shot_index,
                "status": render.status,
                "phase": phase,
                "value": value,
                "max": total,
                "percent": percent,
                "elapsed_seconds": round(elapsed, 1),
                "eta_seconds": eta,
                "connected": progress.progress.connected,
            }
        )
    return {"active": bool(items), "items": items}


# ---------------------------------------------------------------------------
# Optional access password
# ---------------------------------------------------------------------------

#: Set ``STUDIO_PASSWORD`` before exposing the app to the internet. Local use
#: leaves it empty, so nothing changes on 127.0.0.1.
STUDIO_PASSWORD = os.getenv("STUDIO_PASSWORD", "").strip()
STUDIO_USER = os.getenv("STUDIO_USER", "lunar").strip() or "lunar"


@app.middleware("http")
async def _guard(request: Request, call_next):
    if not STUDIO_PASSWORD:
        return await call_next(request)
    # Health is open so a reverse proxy can probe the app; everything else,
    # including media files, needs the password.
    if request.url.path == "/api/health":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - malformed header is just a failed login
            decoded = ""
        user, _, password = decoded.partition(":")
        if user == STUDIO_USER and password == STUDIO_PASSWORD:
            return await call_next(request)
    return JSONResponse(
        {"detail": "需要访问密码。"},
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Lunar Studio", charset="UTF-8"'},
    )


# ---------------------------------------------------------------------------
# Cache policy
# ---------------------------------------------------------------------------


@app.middleware("http")
async def _cache_headers(request: Request, call_next):
    """Never let the browser reuse a stale SPA shell.

    The build rewrites ``index.html`` with new hashed asset names. If the shell
    is cached, a reload asks for a script that no longer exists and the tab
    stays blank white. Hashed assets and media can be cached instead.
    """

    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/"):
        response.headers.setdefault(
            "Cache-Control", "public, max-age=31536000, immutable"
        )
    elif path.startswith("/media/"):
        response.headers.setdefault("Cache-Control", "public, max-age=3600")
    elif path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    else:
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


# ---------------------------------------------------------------------------
# SPA (production build)
# ---------------------------------------------------------------------------

if (FRONTEND_DIST / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="frontend-assets",
    )


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    if full_path.startswith(("api/", "media/")):
        raise HTTPException(404, "Not found")
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        return JSONResponse(
            {
                "name": "Lunar Studio API",
                "status": "ok",
                "docs": "/docs",
                "ui": "run `npm run dev` in studio/frontend (http://localhost:5173)",
            }
        )
    if full_path:
        candidate = (FRONTEND_DIST / full_path).resolve()
        try:
            candidate.relative_to(FRONTEND_DIST.resolve())
        except ValueError:
            candidate = index
        if candidate.is_file():
            return FileResponse(candidate)
    return FileResponse(index, headers={"Cache-Control": "no-store, must-revalidate"})
