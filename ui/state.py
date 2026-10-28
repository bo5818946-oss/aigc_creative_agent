"""Session state, background workflow execution, and data helpers."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any

import streamlit as st

from config.settings import (
    DB_PATH,
    DEEPSEEK_API_KEY,
    DURATION_TOLERANCE_SECONDS,
    MAX_REVISIONS,
    TARGET_VIDEO_MODEL,
    guide_mode,
)
from database.repository import ProjectRepository
from schemas.conversation import (
    ConversationStage,
    ConversationState,
    ConversationStatus,
    VehicleAsset,
    utc_now,
)
from schemas.project import CreativeRequirement
from services.agent_director import AgentDirector
from services.conversation_service import ConversationEngine
from services.llm_service import LLMService
from services.project_service import (
    CreativeProjectService,
    build_raw_requirement,
)


@dataclass
class RunSession:
    queue: queue.Queue = field(default_factory=queue.Queue)
    latest_state: dict[str, Any] = field(default_factory=dict)
    project_id: str = ""
    execution_id: str = ""
    status: str = "running"
    result: dict[str, Any] | None = None
    error: str | None = None
    thread_done: bool = False
    finalized: bool = False
    thread: threading.Thread | None = None


def get_repository() -> ProjectRepository:
    return ProjectRepository(DB_PATH)


def model_is_configured() -> bool:
    """Whether a real DeepSeek key is available for the UI."""

    return bool(DEEPSEEK_API_KEY)


def agent_mode_label() -> str:
    """What actually decides the next question, shown in the sidebar."""

    if guide_mode() == "rules" or not DEEPSEEK_API_KEY:
        return "规则决策层"
    return "DeepSeek 决策层"


def _build_director() -> AgentDirector | None:
    """The model-backed decision layer, or ``None`` when it cannot run."""

    if guide_mode() == "rules" or not DEEPSEEK_API_KEY:
        return None
    try:
        return AgentDirector(LLMService.from_env())
    except Exception:
        return None


def agent_is_available() -> bool:
    """Whether the guided conversation can run at all.

    There is no rule-table fallback, so this is the single source of truth for
    "the studio can talk to you". It only reads configuration — building the
    client is deferred to the first real turn so this check never has side
    effects.
    """

    return guide_mode() != "rules" and bool(DEEPSEEK_API_KEY)


def get_conversation_engine() -> ConversationEngine:
    return ConversationEngine(get_repository(), director=_build_director())


def _remember_agent_meta(engine: ConversationEngine) -> None:
    st.session_state.agent_policy = engine.last_policy_source
    st.session_state.agent_error = engine.last_director_error or None


def _store_conversation(state: ConversationState) -> ConversationState:
    st.session_state.conversation_state = state
    st.session_state.conversation_error = None
    return state


def begin_conversation(
    idea: str,
    *,
    reference_files: list[str] | None = None,
) -> ConversationState:
    """Start a new guided project from one natural-language sentence."""

    engine = get_conversation_engine()
    state = engine.start(idea, reference_files=reference_files)
    _remember_agent_meta(engine)
    _store_conversation(state)
    # A new creative direction should not silently keep showing an old result.
    st.session_state.current_result = None
    st.session_state.current_project_id = None
    st.session_state.run_session = None
    st.session_state.run_status = "idle"
    st.session_state.run_error = None
    st.session_state.last_export_paths = None
    return state


def save_conversation_state(state: ConversationState) -> ConversationState:
    get_conversation_engine().save(state)
    return _store_conversation(state)


def conversation_turn(text: str) -> ConversationState:
    state = st.session_state.get("conversation_state")
    if not isinstance(state, ConversationState):
        raise ValueError("当前没有正在进行的创作对话。")
    if _turn_in_flight():
        st.session_state.conversation_notice = "上一步还在处理，请稍候。"
        return state
    engine = get_conversation_engine()
    _begin_turn()
    try:
        updated = engine.handle(state, text)
    finally:
        _end_turn()
    _remember_agent_meta(engine)
    return _store_conversation(updated)


def can_accept_choice(state: ConversationState | None) -> bool:
    """Whether a choice click can still be applied to this conversation."""

    return isinstance(state, ConversationState) and state.pending_question is not None


def _turn_in_flight() -> bool:
    return bool(st.session_state.get("conversation_busy"))


def _begin_turn() -> None:
    st.session_state.conversation_busy = True


def _end_turn() -> None:
    st.session_state.conversation_busy = False


def conversation_choose(
    option_id: str,
    *,
    selected_ids: list[str] | None = None,
) -> ConversationState:
    state = st.session_state.get("conversation_state")
    if not isinstance(state, ConversationState):
        raise ValueError("当前没有正在进行的创作对话。")
    if _turn_in_flight():
        # A queued duplicate click while the previous decision is still talking
        # to the model. Drop it: the in-flight turn will render the result.
        st.session_state.conversation_notice = "上一步还在处理，请稍候。"
        return state
    if not can_accept_choice(state):
        # A click on a question that an earlier turn already answered has
        # nothing to attach the choice to. Ignore it and refresh instead of
        # failing the turn.
        st.session_state.conversation_notice = (
            "这一步已经更新过了，页面已刷新到最新状态。"
        )
        return state
    engine = get_conversation_engine()
    _begin_turn()
    try:
        updated = engine.choose(state, option_id, selected_ids=selected_ids)
    finally:
        _end_turn()
    _remember_agent_meta(engine)
    return _store_conversation(updated)


def conversation_autonomy() -> ConversationState:
    state = st.session_state.get("conversation_state")
    if not isinstance(state, ConversationState):
        raise ValueError("当前没有正在进行的创作对话。")
    if _turn_in_flight():
        st.session_state.conversation_notice = "上一步还在处理，请稍候。"
        return state
    engine = get_conversation_engine()
    _begin_turn()
    try:
        updated = engine.handle(state, "你全部帮我决定，直接给我专业方案。")
    finally:
        _end_turn()
    _remember_agent_meta(engine)
    return _store_conversation(updated)


def conversation_confirm() -> ConversationState:
    state = st.session_state.get("conversation_state")
    if not isinstance(state, ConversationState):
        raise ValueError("当前没有正在进行的创作对话。")
    engine = get_conversation_engine()
    updated = engine.confirm(state, announce=True)
    return _store_conversation(updated)


def start_conversation_run(
    state: ConversationState,
    *,
    target_video_model: str,
    max_revisions: int,
    duration_tolerance_seconds: float,
) -> RunSession:
    """Build the real requirement and start the existing LangGraph workflow."""

    engine = get_conversation_engine()
    requirement = engine.build_requirement(state)
    raw_requirement = (
        build_raw_requirement(requirement)
        + "\n\n用户原始创意："
        + state.original_idea
    )
    # Persist the running state before the worker can attach the project ID.
    # Otherwise a very fast worker could write project_id and then be
    # overwritten by the UI's stale in-memory copy.
    state.status = ConversationStatus.RUNNING
    state.stage = ConversationStage.RUNNING
    state.generation_requested = False
    state.add_message(
        "assistant",
        "已启动真实工作流：需求解析 → 分镜 → 提示词 → 四类校验"
        "（失败时最多修正两次）→ 导演提示词。执行过程实时可见。",
    )
    engine.save(state)
    _store_conversation(state)

    session = start_run(
        requirement,
        use_llm=model_is_configured(),
        target_video_model=target_video_model,
        max_revisions=max_revisions,
        duration_tolerance_seconds=duration_tolerance_seconds,
        project_id=state.project_id,
        raw_requirement=raw_requirement,
        conversation_session_id=state.session_id,
    )
    return session


def sync_conversation_result(
    state: ConversationState | None,
    result: dict[str, Any] | None,
    *,
    active: bool,
) -> ConversationState | None:
    """Attach a finished workflow result to the guided conversation once."""

    if not isinstance(state, ConversationState) or active or not result:
        return state
    if state.status not in {ConversationStatus.RUNNING}:
        return state
    result_project_id = result.get("project_id")
    if state.project_id and result_project_id != state.project_id:
        return state
    final_status = result.get("final_status", "failed")
    state.project_id = result_project_id
    state.status = (
        ConversationStatus.COMPLETED
        if final_status == "completed"
        else ConversationStatus.FAILED
    )
    state.stage = ConversationStage.COMPLETED
    shots = (result.get("storyboard") or {}).get("shots") or []
    revisions = int(result.get("revision_count", 0) or 0)
    director = ((result.get("storyboard") or {}).get("director_package") or {})
    director_chars = len(str(director.get("global_prompt") or ""))
    if final_status == "completed":
        message = (
            f"生成完成：{len(shots)} 个镜头，{revisions} 次自动修正"
            + (f"，导演提示词 {director_chars} 字符" if director_chars else "")
            + "。你可以在“提示词”页复制或下载，也可以继续在这里修改。"
        )
    else:
        errors = result.get("errors") or []
        message = (
            "这次执行没有完全通过："
            + ("；".join(str(item) for item in errors[:3]) or final_status)
            + "。执行过程和校验报告保留了真实失败原因。"
        )
    state.add_message("assistant", message)
    get_conversation_engine().save(state)
    return _store_conversation(state)


def _reconcile_loaded_conversation(
    repository: ProjectRepository,
    state: ConversationState,
) -> ConversationState:
    if state.status != ConversationStatus.RUNNING or not state.project_id:
        return state
    project = repository.get_project(state.project_id)
    if project is None:
        return state
    project_status = project.get("status")
    if project_status not in {"completed", "validation_failed", "failed"}:
        return state
    state.status = (
        ConversationStatus.COMPLETED
        if project_status == "completed"
        else ConversationStatus.FAILED
    )
    state.stage = ConversationStage.COMPLETED
    shots = (project.get("storyboard") or {}).get("shots") or []
    if project_status == "completed":
        message = (
            f"上次执行实际上已经完成：{len(shots)} 个镜头。"
            "页面可能刷新过，结果已从 SQLite 恢复。"
        )
    else:
        message = (
            "上次执行以 " + str(project_status) + " 结束，"
            "失败原因保留在执行过程和校验报告中。"
        )
    state.add_message("assistant", message)
    repository.save_conversation(state.model_dump(mode="json"))
    return state


def load_conversation(session_id: str) -> tuple[ConversationState | None, str | None]:
    try:
        record = get_repository().get_conversation(session_id)
        if record is None:
            return None, "创作会话不存在。"
        state = ConversationState.model_validate(record.get("state") or {})
        state = _reconcile_loaded_conversation(get_repository(), state)
        _store_conversation(state)
        if state.project_id:
            project, error = load_project(state.project_id)
            if error:
                return state, error
            if project is not None:
                st.session_state.current_result = project_to_result(project)
                st.session_state.current_project_id = state.project_id
                st.session_state.run_status = project.get("status", "unknown")
                st.session_state.run_error = None
        else:
            st.session_state.current_result = None
            st.session_state.current_project_id = None
            st.session_state.run_status = "idle"
        return state, None
    except Exception as exc:
        return None, f"读取创作会话失败：{type(exc).__name__}: {exc}"


def load_conversation_for_project(
    project_id: str,
) -> tuple[ConversationState | None, str | None]:
    try:
        record = get_repository().get_conversation_for_project(project_id)
        if record is None:
            return None, "这个项目没有可恢复的创作对话。"
        state = ConversationState.model_validate(record.get("state") or {})
        state = _reconcile_loaded_conversation(get_repository(), state)
        _store_conversation(state)
        project, error = load_project(project_id)
        if error:
            return state, error
        if project is not None:
            st.session_state.current_result = project_to_result(project)
            st.session_state.current_project_id = project_id
            st.session_state.run_status = project.get("status", "unknown")
            st.session_state.run_error = None
        return state, None
    except Exception as exc:
        return None, f"恢复创作对话失败：{type(exc).__name__}: {exc}"


def recover_stale_conversation(
    state: ConversationState | None,
    *,
    active: bool,
) -> ConversationState | None:
    """Do not leave a conversation stuck in running after a page refresh."""

    if (
        not isinstance(state, ConversationState)
        or active
        or state.status != ConversationStatus.RUNNING
    ):
        return state
    state.status = ConversationStatus.FAILED
    state.stage = ConversationStage.COMPLETED
    state.add_message(
        "assistant",
        "上一次执行没有留下完成结果，可能是页面刷新或进程中断。"
        "已确认的方案仍然保留，你可以检查后重新生成。",
    )
    get_conversation_engine().save(state)
    return _store_conversation(state)


def sync_conversation_failure(
    state: ConversationState | None,
    *,
    active: bool,
) -> ConversationState | None:
    if (
        not isinstance(state, ConversationState)
        or active
        or state.status != ConversationStatus.RUNNING
    ):
        return state
    session = st.session_state.get("run_session")
    error = getattr(session, "error", None) if session is not None else None
    if not error:
        return state
    state.status = ConversationStatus.FAILED
    state.stage = ConversationStage.COMPLETED
    state.add_message(
        "assistant",
        "这次执行失败了：" + str(error)[:500]
        + "。失败阶段保留在执行过程中，你可以修改方案后重试。",
    )
    get_conversation_engine().save(state)
    return _store_conversation(state)


def list_conversations(limit: int = 12) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return get_repository().list_conversations(limit=limit), None
    except Exception as exc:
        return [], f"读取创作会话失败：{type(exc).__name__}: {exc}"


def reset_conversation() -> None:
    """Leave the current conversation in history and start a fresh page."""

    st.session_state.conversation_state = None
    st.session_state.conversation_error = None
    st.session_state.current_result = None
    st.session_state.current_project_id = None
    st.session_state.run_session = None
    st.session_state.run_status = "idle"
    st.session_state.run_error = None
    st.session_state.studio_idea_input = ""


def list_vehicle_assets() -> tuple[list[dict[str, Any]], str | None]:
    try:
        return get_repository().list_assets(kind="vehicle"), None
    except Exception as exc:
        return [], f"读取资产库失败：{type(exc).__name__}: {exc}"


def save_vehicle_asset_from_conversation(name: str) -> tuple[VehicleAsset | None, str | None]:
    state = st.session_state.get("conversation_state")
    if not isinstance(state, ConversationState):
        return None, "当前没有可保存的创作会话。"
    brief = state.brief
    description = str(brief.get("vehicle_description") or "").strip()
    vehicle_type = str(brief.get("vehicle_type") or "").strip()
    design = str(brief.get("vehicle_design") or "").strip()
    if not (description or vehicle_type):
        return None, "当前会话还没有车辆外观决策。"
    asset = VehicleAsset(
        name=(name or "未命名车辆资产").strip()[:100],
        description=description or f"一辆{vehicle_type}",
        attributes={
            "vehicle_type": vehicle_type,
            "vehicle_design": design,
            "vehicle_description": description,
        },
        rules=list(brief.get("constraints") or []),
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    try:
        get_repository().save_asset(asset.model_dump(mode="json"))
    except Exception as exc:
        return None, f"保存资产失败：{type(exc).__name__}: {exc}"
    return asset, None


def apply_asset_to_conversation(asset_id: str) -> ConversationState:
    state = st.session_state.get("conversation_state")
    if not isinstance(state, ConversationState):
        raise ValueError("当前没有正在进行的创作对话。")
    record = get_repository().get_asset(asset_id)
    if record is None:
        raise ValueError("资产不存在。")
    asset = VehicleAsset.model_validate(record)
    engine = get_conversation_engine()
    updated = engine.apply_asset(state, asset)
    return _store_conversation(updated)


def init_state() -> None:
    defaults: dict[str, Any] = {
        "current_result": None,
        "current_project_id": None,
        "run_session": None,
        "run_status": "idle",
        "run_error": None,
        "nav": "创作工作台",
        "last_export_paths": None,
        "history_selected_project": None,
        "conversation_state": None,
        "conversation_error": None,
        "conversation_notice": None,
        "conversation_busy": False,
        "agent_error": None,
        "agent_policy": "rules",
        "studio_idea_input": "",
        "studio_source_asset_id": None,
        "input_project_name": "30秒汽车品牌广告",
        "input_content_type": "汽车商业广告",
        "input_subject": "一辆银灰色流线型纯电轿车",
        "input_audience": "关注科技感与驾驶质感的年轻消费者",
        "input_duration": 30.0,
        "input_aspect": "16:9",
        "input_style": "电影感商业广告，冷暖对比光影，金属质感",
        "input_scenes": "森林,草原,沙漠,雪地,城市",
        "input_camera": "航拍、低机位跟拍与车身细节特写结合",
        "input_constraints": (
            "全片使用同一辆银灰色流线型纯电轿车，车型与车身设计特征保持一致\n"
            "明确车头与车尾方向，车辆前进方向始终一致\n"
            "避免镜头之间出现相互矛盾的车辆运动描述"
        ),
        "input_transition": "以车辆运动方向为依据的自然动势转场",
        "input_notes": "",
        "input_target_model": (
            TARGET_VIDEO_MODEL
            if TARGET_VIDEO_MODEL
            else "generic"
        ),
        "input_max_revisions": MAX_REVISIONS,
        "input_tolerance": DURATION_TOLERANCE_SECONDS,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _link_conversation_project(
    repository: ProjectRepository,
    session_id: str | None,
    project_id: str,
) -> None:
    if not session_id:
        return
    record = repository.get_conversation(session_id)
    if record is None:
        return
    state = ConversationState.model_validate(record.get("state") or {})
    if state.project_id == project_id:
        return
    state.project_id = project_id
    state.touch()
    repository.save_conversation(state.model_dump(mode="json"))


def execute_run(
    session: RunSession,
    requirement: CreativeRequirement,
    *,
    use_llm: bool,
    target_video_model: str,
    max_revisions: int,
    duration_tolerance_seconds: float,
    db_path: str | None = None,
    project_id: str | None = None,
    raw_requirement: str | None = None,
    conversation_session_id: str | None = None,
) -> None:
    """Consume the workflow stream into a session. Safe outside Streamlit."""

    llm_service: LLMService | None = None
    try:
        repository = ProjectRepository(db_path or DB_PATH)
        if use_llm:
            llm_service = LLMService.from_env()
        service = CreativeProjectService(
            repository,
            llm_service=llm_service,
        )
        for event in service.stream_run(
            requirement,
            raw_requirement=raw_requirement,
            target_video_model=target_video_model,
            max_revisions=max_revisions,
            duration_tolerance_seconds=duration_tolerance_seconds,
            project_id=project_id,
        ):
            if event.get("project_id"):
                session.project_id = event["project_id"]
                _link_conversation_project(
                    repository,
                    conversation_session_id,
                    event["project_id"],
                )
            if event.get("execution_id"):
                session.execution_id = event["execution_id"]
            if event.get("state"):
                session.latest_state = event["state"]
            if event.get("done"):
                result = event.get("result") or {}
                session.result = result
                status = result.get("final_status", "failed")
                session.status = (
                    "completed" if status == "completed" else "failed"
                )
                if status != "completed":
                    session.error = (
                        "; ".join(result.get("errors", []))
                        or "工作流未通过校验。"
                    )
            session.queue.put(event)
    except Exception as exc:
        session.status = "failed"
        session.error = f"{type(exc).__name__}: {exc}"
        session.queue.put({"worker_error": session.error})
    finally:
        if llm_service is not None:
            llm_service.close()
        session.thread_done = True
        session.queue.put({"worker_done": True})


def start_run(
    requirement: CreativeRequirement,
    *,
    use_llm: bool,
    target_video_model: str,
    max_revisions: int,
    duration_tolerance_seconds: float,
    project_id: str | None = None,
    raw_requirement: str | None = None,
    conversation_session_id: str | None = None,
) -> RunSession:
    existing = st.session_state.get("run_session")
    if existing is not None and not existing.finalized and existing.status == "running":
        raise RuntimeError("已有创作任务正在运行，请等待完成。")

    session = RunSession()
    st.session_state.run_session = session
    st.session_state.run_status = "running"
    st.session_state.run_error = None

    thread = threading.Thread(
        target=execute_run,
        kwargs={
            "session": session,
            "requirement": requirement,
            "use_llm": use_llm,
            "target_video_model": target_video_model,
            "max_revisions": max_revisions,
            "duration_tolerance_seconds": duration_tolerance_seconds,
            "project_id": project_id,
            "raw_requirement": raw_requirement,
            "conversation_session_id": conversation_session_id,
        },
        name="aigc-workflow",
        daemon=True,
    )
    session.thread = thread
    thread.start()
    return session


def drain_session(session: RunSession) -> RunSession:
    while True:
        try:
            event = session.queue.get_nowait()
        except queue.Empty:
            break
        if event.get("worker_error"):
            session.error = event["worker_error"]
            session.status = "failed"
        if event.get("worker_done"):
            session.thread_done = True
        if event.get("state"):
            session.latest_state = event["state"]
        if event.get("done"):
            result = event.get("result") or {}
            session.result = result
            status = result.get("final_status", "failed")
            session.status = (
                "completed" if status == "completed" else "failed"
            )
            if status != "completed":
                session.error = (
                    "; ".join(result.get("errors", []))
                    or "工作流未通过校验。"
                )
    return session


def finalize_session(session: RunSession) -> None:
    if session.finalized:
        return
    if session.result is not None:
        st.session_state.current_result = session.result
        st.session_state.current_project_id = session.result.get(
            "project_id", session.project_id
        )
        status = session.result.get("final_status", "failed")
        st.session_state.run_status = status
        st.session_state.run_error = (
            None
            if status == "completed"
            else (
                "; ".join(session.result.get("errors", []))
                or "工作流未通过校验。"
            )
        )
    elif session.error:
        st.session_state.run_status = "failed"
        st.session_state.run_error = session.error
    session.finalized = True


def session_is_active(session: RunSession | None) -> bool:
    return bool(
        session is not None
        and not session.finalized
        and not session.thread_done
        and session.status == "running"
    )


def load_project(
    project_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return get_repository().get_project(project_id), None
    except Exception as exc:
        return None, f"读取项目失败：{type(exc).__name__}: {exc}"


def list_projects(
    *,
    search: str = "",
    status: str = "",
    order_by: str = "updated_at_desc",
    limit: int = 100,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        repository = get_repository()
        return (
            repository.list_projects(
                search=search,
                status=status,
                order_by=order_by,
                limit=limit,
            ),
            None,
        )
    except Exception as exc:
        return [], f"读取项目列表失败：{type(exc).__name__}: {exc}"


def count_projects(*, search: str = "", status: str = "") -> int:
    try:
        return get_repository().count_projects(
            search=search,
            status=status,
        )
    except Exception:
        return 0


def _extract_llm_usage(
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    best: dict[str, Any] = {}
    for trace in traces:
        arguments = trace.get("tool_arguments")
        if not isinstance(arguments, dict):
            continue
        usage = arguments.get("usage")
        if not isinstance(usage, dict):
            continue
        if int(usage.get("calls", 0)) >= int(best.get("calls", 0)):
            best = usage
    return best


def project_to_result(project: dict[str, Any]) -> dict[str, Any]:
    executions = project.get("executions") or []
    execution = executions[-1] if executions else {}
    traces = execution.get("traces") or []
    reports = project.get("validation_reports") or []
    report = reports[-1].get("report_json") if reports else None
    status = project.get("status", "unknown")
    errors: list[str] = []
    if execution.get("error"):
        errors.append(str(execution["error"]))
    return {
        "project_id": project.get("project_id"),
        "execution_id": execution.get("execution_id"),
        "raw_requirement": project.get("raw_requirement", ""),
        "structured_requirement": project.get(
            "structured_requirement", {}
        ),
        "task_plan": project.get("task_plan", []),
        "storyboard": project.get("storyboard", {}),
        "validation_report": report,
        "trace_events": traces,
        "revision_history": project.get("revision_history", []),
        "final_status": status,
        "errors": errors,
        "llm_usage": _extract_llm_usage(traces),
        "created_at": project.get("created_at"),
        "updated_at": project.get("updated_at"),
    }


def select_project(project: dict[str, Any]) -> None:
    st.session_state.current_result = project_to_result(project)
    st.session_state.current_project_id = project.get("project_id")
    st.session_state.run_status = project.get("status", "unknown")
    st.session_state.run_error = None
    st.session_state.history_selected_project = project.get("project_id")


def navigate(page: str) -> None:
    st.session_state.requested_nav = page
    st.rerun()
