"""Conversation-first creative director workbench.

The page is intentionally not a large form. The primary path is one sentence
plus an agent that decides what to ask next, explains its recommendation, and
persists every decision. A collapsed direct-brief form remains as a professional
fast lane and preserves the earlier capability.
"""

from __future__ import annotations

import re
from typing import Any

import streamlit as st
from pydantic import ValidationError

from config.cinematography import MODEL_PROFILES
from config.settings import DURATION_TOLERANCE_SECONDS, MAX_REVISIONS, TARGET_VIDEO_MODEL
from schemas.conversation import (
    ClarifyingQuestion,
    ConversationStage,
    ConversationState,
    ConversationStatus,
    Proposal,
    QuestionOption,
)
from schemas.project import CreativeRequirement
from services.agent_director import is_automotive_brief
from ui.components import (
    render_implement_block,
    render_live_monitor,
    render_metrics,
    render_validation_overview,
)
from ui.state import (
    agent_is_available,
    apply_asset_to_conversation,
    begin_conversation,
    conversation_autonomy,
    conversation_choose,
    conversation_confirm,
    conversation_turn,
    drain_session,
    finalize_session,
    list_conversations,
    list_vehicle_assets,
    load_conversation,
    model_is_configured,
    recover_stale_conversation,
    reset_conversation,
    save_conversation_state,
    save_vehicle_asset_from_conversation,
    session_is_active,
    start_conversation_run,
    start_run,
    sync_conversation_failure,
    sync_conversation_result,
)
from ui.theme import (
    badge,
    empty_state,
    escape,
    format_timestamp,
    hero,
    page_header,
    reasoning_block,
    section_header,
    status_badge,
    status_label,
)

_ASPECT_OPTIONS = ["16:9", "9:16", "1:1", "4:3"]

_EXAMPLES = [
    ("未来超跑广告", "我想做一个未来超级跑车的广告，要有电影感。"),
    ("校园电影短片", "我想制作一支有电影感的校园短片，讲一个毕业前的夜晚。"),
    ("高端护肤广告", "我想为一个高端护肤品制作一支极简、克制的商业广告。"),
    ("故事变分镜", "我想把一个关于末班地铁的故事创意变成完整的 AI 视频分镜。"),
]

_STAGE_ORDER = [
    ConversationStage.SUBJECT,
    ConversationStage.ASSET,
    ConversationStage.CONCEPT,
    ConversationStage.SCENES,
    ConversationStage.FORMAT,
    ConversationStage.CAMERA,
    ConversationStage.PROPOSAL,
    ConversationStage.COMPLETED,
]

_STAGE_LABELS = {
    ConversationStage.IDEA: "理解创意",
    ConversationStage.SUBJECT: "确定主体",
    ConversationStage.ASSET: "锁定资产",
    ConversationStage.CONCEPT: "确定创意",
    ConversationStage.SCENES: "设计场景",
    ConversationStage.FORMAT: "确定时长",
    ConversationStage.CAMERA: "镜头与转场",
    ConversationStage.PROPOSAL: "方案确认",
    ConversationStage.READY: "方案确认",
    ConversationStage.RUNNING: "生成中",
    ConversationStage.COMPLETED: "交付完成",
}

_SOURCE_KIND = {
    "user": "success",
    "user_selected": "info",
    "agent_inferred": "warning",
    "asset": "info",
    "system_default": "muted",
    "unknown": "muted",
}


def _split_list(value: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"[,，、;；\n]", value)
        if item.strip()
    ]


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for item in exc.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item.get("loc", ()))
        prefix = f"{location}: " if location else ""
        parts.append(f"{prefix}{item.get('msg', '字段校验失败')}")
    return "；".join(parts)


# ---------------------------------------------------------------------------
# callbacks
# ---------------------------------------------------------------------------
def _reference_names() -> list[str]:
    uploads = st.session_state.get("studio_reference_upload") or []
    if not isinstance(uploads, list):
        uploads = [uploads]
    return [
        str(getattr(item, "name", "") or "").strip()
        for item in uploads
        if getattr(item, "name", None)
    ]


def _begin_from_example(idea: str) -> None:
    try:
        begin_conversation(idea, reference_files=_reference_names())
        st.session_state.studio_idea_input = idea
    except Exception as exc:
        st.session_state.conversation_error = f"{type(exc).__name__}: {exc}"


def _begin_from_input() -> None:
    idea = str(st.session_state.get("studio_idea_input") or "").strip()
    if not idea:
        st.session_state.conversation_error = "先写一句你想创作的内容。"
        return
    try:
        begin_conversation(idea, reference_files=_reference_names())
    except Exception as exc:
        st.session_state.conversation_error = f"{type(exc).__name__}: {exc}"


def _resume(session_id: str) -> None:
    _state, error = load_conversation(session_id)
    if error:
        st.session_state.conversation_error = error


def _reset() -> None:
    reset_conversation()


def _choose(option_id: str) -> None:
    try:
        conversation_choose(option_id)
    except Exception as exc:
        st.session_state.conversation_error = f"{type(exc).__name__}: {exc}"


def _choose_multi(question_id: str) -> None:
    state = st.session_state.get("conversation_state")
    if not isinstance(state, ConversationState):
        return
    question = state.pending_question
    if question is None or question.question_id != question_id:
        st.session_state.conversation_error = "选项已经更新，请重新选择。"
        return
    labels = st.session_state.get(f"studio_multi_{question_id}") or []
    ids = [
        option.option_id
        for option in question.options
        if option.label in labels
    ]
    if not ids:
        st.session_state.conversation_error = "请至少选择一个场景。"
        return
    try:
        conversation_choose(ids[0], selected_ids=ids)
    except Exception as exc:
        st.session_state.conversation_error = f"{type(exc).__name__}: {exc}"


def _autonomy() -> None:
    try:
        conversation_autonomy()
    except Exception as exc:
        st.session_state.conversation_error = f"{type(exc).__name__}: {exc}"


def _start_pending_run() -> bool:
    state = st.session_state.get("conversation_state")
    if not isinstance(state, ConversationState):
        return False
    if not state.generation_requested:
        return False
    try:
        start_conversation_run(
            state,
            target_video_model=st.session_state.get(
                "input_target_model", TARGET_VIDEO_MODEL
            ),
            max_revisions=int(
                st.session_state.get("input_max_revisions", MAX_REVISIONS)
            ),
            duration_tolerance_seconds=float(
                st.session_state.get(
                    "input_tolerance", DURATION_TOLERANCE_SECONDS
                )
            ),
        )
        return True
    except Exception as exc:
        state.generation_requested = False
        state.status = ConversationStatus.READY
        state.add_message(
            "assistant",
            "启动工作流失败：" + f"{type(exc).__name__}: {exc}",
        )
        save_conversation_state(state)
        st.session_state.conversation_error = (
            f"启动工作流失败：{type(exc).__name__}: {exc}"
        )
        return False


def _confirm_and_start() -> None:
    try:
        state = conversation_confirm()
        start_conversation_run(
            state,
            target_video_model=st.session_state.get(
                "input_target_model", TARGET_VIDEO_MODEL
            ),
            max_revisions=int(
                st.session_state.get("input_max_revisions", MAX_REVISIONS)
            ),
            duration_tolerance_seconds=float(
                st.session_state.get(
                    "input_tolerance", DURATION_TOLERANCE_SECONDS
                )
            ),
        )
    except Exception as exc:
        state = st.session_state.get("conversation_state")
        if isinstance(state, ConversationState):
            state.generation_requested = False
            state.status = ConversationStatus.READY
            save_conversation_state(state)
        st.session_state.conversation_error = (
            f"启动工作流失败：{type(exc).__name__}: {exc}"
        )


def _save_asset() -> None:
    name = str(st.session_state.get("studio_asset_name") or "").strip()
    asset, error = save_vehicle_asset_from_conversation(name)
    if error:
        st.session_state.conversation_error = error
    elif asset is not None:
        st.session_state.conversation_error = None
        st.session_state.studio_asset_saved = asset.name


def _use_asset(asset_id: str) -> None:
    try:
        apply_asset_to_conversation(asset_id)
    except Exception as exc:
        st.session_state.conversation_error = f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# shared rendering
# ---------------------------------------------------------------------------
def _render_idea_form(active: bool) -> None:
    st.text_area(
        "描述你想创作的内容",
        key="studio_idea_input",
        height=138,
        placeholder=(
            "可以只说一个想法，也可以详细描述。例如：\n"
            "我想做一个未来超级跑车的广告，穿越森林、沙漠和雪山，"
            "要有电影感，最后展示完整车身。"
        ),
        help="不用填写项目名称、主体、动作、场景等内部字段。Agent 会从你的话里提取，缺什么再问你。",
    )
    st.file_uploader(
        "参考图（可选）",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="studio_reference_upload",
        help=(
            "当前 DeepSeek 文本模型不做图片识别。图片只作为项目参考记录，"
            "不会上传到外部服务；请在描述里写清车型、颜色、灯组等可见特征。"
        ),
    )
    st.caption(
        "图片参考只记录文件名，不会自动识别。需要锁定外观时，请用文字写明"
        "车型、颜色、灯组、轮毂和车身套件。"
    )
    st.button(
        "开始创作",
        type="primary",
        width="stretch",
        key="studio_begin",
        on_click=_begin_from_input,
        disabled=active,
    )
    st.caption(
        "Agent 会先判断信息够不够。够就直接出方案；不够只问真正影响结果的问题，"
        "并给出专业选项和推荐理由。"
    )


def _render_examples(active: bool) -> None:
    section_header("可以这样开始", "点一个示例，或直接写自己的")
    columns = st.columns(2)
    for index, (label, idea) in enumerate(_EXAMPLES):
        with columns[index % 2]:
            st.button(
                label,
                width="stretch",
                key=f"studio_example_{index}",
                on_click=_begin_from_example,
                args=(idea,),
                disabled=active,
                help=idea,
            )


def _render_recent(active: bool = False) -> None:
    summaries, error = list_conversations(limit=8)
    if error:
        st.warning(error)
        return
    if not summaries:
        return
    section_header("最近的创作", "从 SQLite 恢复对话和已确认的决策")
    for item in summaries:
        title = item.get("proposal_title") or item.get("original_idea_preview") or "未命名创作"
        with st.container(border=True):
            left, right = st.columns([5, 1.2])
            with left:
                st.markdown(f"**{escape(title)}**")
                st.caption(
                    f"{status_label(item.get('status', 'unknown'))} · "
                    f"{item.get('message_count', 0)} 条消息 · "
                    f"{format_timestamp(item.get('updated_at'))}"
                )
                if item.get("original_idea_preview"):
                    st.caption(str(item["original_idea_preview"])[:120])
            with right:
                st.button(
                    "继续",
                    width="stretch",
                    key=f"resume_{item.get('session_id')}",
                    on_click=_resume,
                    args=(item.get("session_id"),),
                    disabled=active,
                )


def _render_direct_form(active: bool) -> None:
    with st.expander("专业快速通道：直接填写完整简报", expanded=False):
        st.caption(
            "适合已经知道自己要什么的专业用户。它仍然会走同一套工作流、"
            "四类校验和修正；不会绕过质量检查。"
        )
        with st.form("direct_brief_form", clear_on_submit=False):
            columns = st.columns([1.1, 1.0])
            with columns[0]:
                st.text_input(
                    "项目名称",
                    key="direct_project_name",
                    value="30秒汽车品牌广告",
                )
            with columns[1]:
                st.text_input(
                    "内容类型",
                    key="direct_content_type",
                    value="汽车商业广告",
                )
            st.text_area(
                "主体描述",
                key="direct_subject",
                height=72,
                value="一辆银灰色流线型纯电轿车",
            )
            columns = st.columns(2)
            with columns[0]:
                st.number_input(
                    "目标时长（秒）",
                    min_value=1.0,
                    max_value=600.0,
                    value=30.0,
                    step=1.0,
                    key="direct_duration",
                )
            with columns[1]:
                st.selectbox(
                    "画面比例",
                    _ASPECT_OPTIONS,
                    key="direct_aspect",
                )
            columns = st.columns(2)
            with columns[0]:
                st.text_input(
                    "场景要求（逗号分隔）",
                    key="direct_scenes",
                    value="森林,沙漠,雪山,城市隧道",
                )
            with columns[1]:
                st.text_input(
                    "视觉风格",
                    key="direct_style",
                    value="电影感商业广告，真实汽车物理，金属质感",
                )
            st.text_input(
                "镜头语言",
                key="direct_camera",
                value="航拍建立、贴地追拍、侧向跟拍、结尾英雄展示",
            )
            submitted = st.form_submit_button(
                "直接生成提示词",
                type="primary",
                width="stretch",
                disabled=active,
            )
            if submitted and not active:
                try:
                    requirement = CreativeRequirement(
                        project_name=st.session_state.direct_project_name,
                        content_type=st.session_state.direct_content_type,
                        subject=st.session_state.direct_subject,
                        duration_seconds=float(st.session_state.direct_duration),
                        aspect_ratio=st.session_state.direct_aspect,
                        visual_style=st.session_state.direct_style,
                        scene_requirements=_split_list(
                            st.session_state.direct_scenes
                        ),
                        camera_language=st.session_state.direct_camera,
                        consistency_constraints=[
                            "全片使用同一辆银灰色流线型纯电轿车，外观与设计特征保持一致。",
                            "车辆前进方向与屏幕方向保持一致，禁止反向行驶。",
                        ],
                        transition_requirements="以车辆运动方向为依据的动作匹配转场。",
                        output_formats=["markdown", "json"],
                    )
                    start_run(
                        requirement,
                        use_llm=model_is_configured(),
                        target_video_model=st.session_state.get(
                            "input_target_model", TARGET_VIDEO_MODEL
                        ),
                        max_revisions=int(
                            st.session_state.get(
                                "input_max_revisions", MAX_REVISIONS
                            )
                        ),
                        duration_tolerance_seconds=float(
                            st.session_state.get(
                                "input_tolerance", DURATION_TOLERANCE_SECONDS
                            )
                        ),
                    )
                except (ValidationError, ValueError) as exc:
                    message = (
                        _format_validation_error(exc)
                        if isinstance(exc, ValidationError)
                        else str(exc)
                    )
                    st.error(f"需求校验失败：{message}")
                except Exception as exc:
                    st.error(f"无法启动创作任务：{type(exc).__name__}: {exc}")
                else:
                    st.rerun()


def _render_landing(result: dict | None, active: bool) -> None:
    left, right = st.columns([1.55, 1.0], gap="large")
    with left:
        if agent_is_available():
            with st.container(border=True):
                _render_idea_form(active)
            _render_examples(active)
        else:
            st.error(
                "决策层不可用：没有可调用的 DeepSeek。"
                "这里不会退回到写死的选项表——那样只是看起来能用。"
                "请先在 .env 配置 DEEPSEEK_API_KEY 后重启。"
            )
            st.caption(
                "你仍然可以浏览项目历史、查看提示词与校验报告；"
                "下方的专业快速通道是显式的非 Agent 路径，会直接进入确定性工作流。"
            )
        _render_direct_form(active)
    with right:
        with st.container(border=True):
            section_header("Agent 会怎么工作", "模型决定下一步，规则负责验收")
            st.markdown(
                "1. **读**：从一句话里提取车型、场景、时长、约束。\n"
                "2. **想**：还缺什么？现在这一问真的影响成片吗？\n"
                "3. **问**：为这次创意现场生成 2–4 个专业选项，并说明取舍。\n"
                "4. **验收**：分镜、提示词、四类校验、最多两次修正。"
            )
            st.caption(
                "每一轮模型给出的判断依据都会显示在对话里，可逐条检查。"
            )
            st.caption(
                "模型已配置：决策层、需求解析、分镜和导演提示词都会调用 DeepSeek。"
                if model_is_configured()
                else "未配置 DeepSeek 密钥：对话层不可用，不会退回规则问卷；"
                "工作流仍可用，但分镜是确定性占位并会明确标注。"
            )
        if result:
            _render_result_panel(result)
    _render_recent(active)


def _render_user_message(content: str) -> None:
    st.markdown(
        f"""
        <div class="app-chat-row app-chat-row-user">
          <div class="app-chat-bubble app-chat-bubble-user">
            {escape(content).replace(chr(10), "<br/>")}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_agent_message(
    content: str,
    payload: dict[str, Any] | None = None,
) -> None:
    st.markdown(
        f"""
        <div class="app-chat-row">
          <div class="app-chat-avatar">CD</div>
          <div class="app-chat-bubble">
            {escape(content).replace(chr(10), "<br/>")}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    payload = payload or {}
    reasoning = str(payload.get("reasoning") or "")
    if reasoning:
        block = reasoning_block(
            reasoning,
            model=str(payload.get("model") or ""),
            action_label=str(payload.get("action_label") or ""),
            source="llm",
        )
        if block:
            st.markdown(block, unsafe_allow_html=True)


def _render_transcript(state: ConversationState) -> None:
    messages = state.messages[-40:]
    if not messages:
        return
    for message in messages:
        # The pending question is rendered once, by _render_question() below its
        # own card. Rendering the message too duplicated the prompt and its
        # reasoning block.
        if message.kind == "question":
            continue
        if message.role == "user":
            _render_user_message(message.content)
        elif message.role == "assistant":
            _render_agent_message(message.content, message.payload)


def _render_option_card(option: QuestionOption, question: ClarifyingQuestion) -> None:
    with st.container(border=True):
        recommended = " " + badge("推荐", "success") if option.recommended else ""
        st.markdown(f"**{escape(option.label)}**{recommended}", unsafe_allow_html=True)
        if option.technique:
            st.markdown(
                f'<div class="app-technique">{escape(option.technique)}</div>',
                unsafe_allow_html=True,
            )
        if option.description:
            st.caption(option.description)
        if option.best_for:
            st.caption(f"适合：{option.best_for}")
        if option.reference:
            st.markdown(
                f'<div class="app-reference">参考：{escape(option.reference)}</div>',
                unsafe_allow_html=True,
            )
        if option.visual_note:
            st.caption(f"画面：{option.visual_note}")
        if option.challenge:
            st.caption(f"代价：{option.challenge}")
        st.button(
            f"选择 {option.label}",
            key=f"opt_{question.question_id}_{option.option_id}",
            on_click=_choose,
            args=(option.option_id,),
            type="primary" if option.recommended else "secondary",
            width="stretch",
        )


def _render_question(question: ClarifyingQuestion) -> None:
    mode = "llm" if question.policy_source == "llm" else "rules"
    section_header(
        "下一步决策",
        f"{_STAGE_LABELS.get(question.stage, question.stage.value)} · "
        f"{'模型判断' if mode == 'llm' else '规则判断'} · 只问真正影响结果的一项",
        badge("Agent 决策", "info") if mode == "llm" else None,
    )
    st.markdown(f"**{escape(question.prompt)}**")
    if question.why_it_matters:
        st.caption(question.why_it_matters)
    if question.reasoning:
        block = reasoning_block(
            question.reasoning,
            action_label="选择这一问的理由",
            source=mode,
        )
        if block:
            st.markdown(block, unsafe_allow_html=True)
    if question.recommendation_reason:
        recommended_label = next(
            (
                option.label
                for option in question.options
                if option.recommended
            ),
            "",
        )
        st.markdown(
            f"""
            <div class="app-recommendation">
              <div class="app-recommendation-label">Agent 推荐{('：' + escape(recommended_label)) if recommended_label else ''}</div>
              <div>{escape(question.recommendation_reason)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if question.multi_select:
        labels = [option.label for option in question.options]
        recommended_labels = [
            option.label for option in question.options if option.recommended
        ]
        key = f"studio_multi_{question.question_id}"
        st.multiselect(
            "选择场景（可多选）",
            labels,
            default=recommended_labels,
            key=key,
            help=question.helper or "可以多选，也可以直接在下方输入自定义场景。",
        )
        columns = st.columns(2)
        for index, option in enumerate(question.options):
            with columns[index % 2]:
                with st.container(border=True):
                    st.markdown(
                        f"**{escape(option.label)}**"
                        + (" " + badge("推荐", "success") if option.recommended else ""),
                        unsafe_allow_html=True,
                    )
                    if option.technique:
                        st.markdown(
                            f'<div class="app-technique">{escape(option.technique)}</div>',
                            unsafe_allow_html=True,
                        )
                    st.caption(option.description)
                    if option.reference:
                        st.markdown(
                            f'<div class="app-reference">参考：{escape(option.reference)}</div>',
                            unsafe_allow_html=True,
                        )
                    if option.visual_note:
                        st.caption(f"画面：{option.visual_note}")
                    if option.challenge:
                        st.caption(f"代价：{option.challenge}")
        st.button(
            "应用场景选择",
            type="primary",
            width="stretch",
            key=f"apply_{question.question_id}",
            on_click=_choose_multi,
            args=(question.question_id,),
        )
    else:
        columns = st.columns(2)
        for index, option in enumerate(question.options):
            with columns[index % 2]:
                _render_option_card(option, question)

    columns = st.columns(2)
    with columns[0]:
        st.button(
            "让 Agent 决定这一项",
            width="stretch",
            key=f"agent_{question.question_id}",
            on_click=_choose,
            args=("__agent__",),
        )
    with columns[1]:
        st.caption("没有合适的？直接在下方输入你的想法。")
    if question.helper:
        st.caption(question.helper)


def _render_decision_list(proposal: Proposal) -> None:
    if not proposal.decisions:
        return
    rows = [
        {
            "决策": row.label,
            "内容": row.value,
            "来源": row.source,
        }
        for row in proposal.decisions
    ]
    st.dataframe(rows, width="stretch", hide_index=True)


def _render_proposal(proposal: Proposal, active: bool) -> None:
    with st.container(border=True):
        left, right = st.columns([4, 1.1])
        with left:
            st.markdown(f"### {escape(proposal.title)}")
            st.write(proposal.one_liner)
            st.markdown(
                badge(
                    f"生成 {proposal.clip_count} 条 × "
                    f"{proposal.clip_seconds:g} 秒 = "
                    f"{proposal.total_duration:g} 秒素材",
                    "info",
                ),
                unsafe_allow_html=True,
            )
        with right:
            st.markdown(badge("待确认", "warning"), unsafe_allow_html=True)
        st.markdown("**创意理由**")
        st.write(proposal.creative_rationale)
        st.markdown(
            f"**场景顺序**  \n{' → '.join(proposal.scene_order)}"
        )
        st.markdown("**镜头结构**")
        for item in proposal.shot_strategy:
            st.markdown(f"- {escape(item)}")
        columns = st.columns(2)
        with columns[0]:
            st.markdown("**镜头语言**")
            for item in proposal.camera_plan:
                st.markdown(f"- {escape(item)}")
            st.markdown(f"**声音**  \n{escape(proposal.sound_plan)}")
        with columns[1]:
            st.markdown("**转场原则**")
            for item in proposal.transition_plan:
                st.markdown(f"- {escape(item)}")
            st.markdown("**资产锁定**")
            st.write(proposal.vehicle_summary)
        if proposal.risks:
            st.markdown("**风险与边界**")
            for risk in proposal.risks:
                st.warning(risk)
        with st.expander("查看全部决策与来源", expanded=False):
            _render_decision_list(proposal)
        st.markdown("**确认后会得到**")
        for item in proposal.output_summary:
            st.markdown(f"- {escape(item)}")
        columns = st.columns([1.4, 1])
        with columns[0]:
            st.button(
                "确认并生成分镜与提示词",
                type="primary",
                width="stretch",
                key="studio_confirm_generate",
                on_click=_confirm_and_start,
                disabled=active,
            )
        with columns[1]:
            st.caption("确认前可以继续改任意一项；未受影响的决策会保留。")


def _render_result_panel(result: dict) -> None:
    requirement = result.get("structured_requirement") or {}
    storyboard = result.get("storyboard") or {}
    shots = storyboard.get("shots") or []
    with st.container(border=True):
        left, right = st.columns([4, 1.1])
        with left:
            st.markdown(
                f"**{escape(requirement.get('project_name', '当前项目'))}**"
            )
            st.caption(
                f"{len(shots)} 个镜头 · "
                f"{int(result.get('revision_count', 0))} 次修正 · "
                f"{format_timestamp(result.get('updated_at'))}"
            )
            if requirement.get("clip_seconds") and requirement.get("clip_count"):
                st.caption(
                    f"生成清单：{int(requirement['clip_count'])} 条 × "
                    f"{float(requirement['clip_seconds']):g} 秒"
                )
        with right:
            st.markdown(
                status_badge(result.get("final_status", "unknown")),
                unsafe_allow_html=True,
            )
        if result.get("final_status") != "completed":
            errors = result.get("errors") or []
            if errors:
                st.warning("；".join(str(item) for item in errors[:3]))
        render_implement_block(result, key_prefix="workbench")
        columns = st.columns(3)
        with columns[0]:
            if st.button("打开提示词包", type="primary", width="stretch"):
                st.session_state.requested_nav = "提示词"
                st.rerun()
        with columns[1]:
            if st.button("查看分镜详情", width="stretch"):
                st.session_state.requested_nav = "分镜详情"
                st.rerun()
        with columns[2]:
            if st.button("查看校验报告", width="stretch"):
                st.session_state.requested_nav = "校验报告"
                st.rerun()


def _render_status_rail(state: ConversationState) -> None:
    if state.stage in _STAGE_ORDER:
        current_index = _STAGE_ORDER.index(state.stage)
    elif state.stage in {ConversationStage.READY, ConversationStage.RUNNING}:
        current_index = _STAGE_ORDER.index(ConversationStage.PROPOSAL)
    else:
        current_index = 0
    rows = []
    for index, stage in enumerate(_STAGE_ORDER):
        if index < current_index:
            kind = "done"
        elif index == current_index:
            kind = "active"
        else:
            kind = ""
        rows.append(
            f'<div class="app-stage-row {kind}">'
            f'<span class="app-stage-dot"></span>'
            f'<span>{escape(_STAGE_LABELS.get(stage, stage.value))}</span>'
            f"</div>"
        )
    st.markdown(
        '<div class="app-stage-rail">' + "".join(rows) + "</div>",
        unsafe_allow_html=True,
    )


def _render_decision_panel(state: ConversationState) -> None:
    snapshot = state.brief.snapshot()
    automotive = is_automotive_brief(
        state.original_idea,
        str(state.brief.get("content_type") or ""),
    )
    known = [
        row
        for row in snapshot
        if row["value"] != "待确定"
        and (automotive or not str(row["key"]).startswith("vehicle_"))
    ]
    with st.container(border=True):
        section_header("创作状态", f"已确定 {len(known)} 项")
        _render_status_rail(state)
        if known:
            for row in known[:8]:
                kind = _SOURCE_KIND.get(row["source"], "muted")
                st.markdown(
                    f"**{escape(row['label'])}**  \n"
                    f"{escape(row['value'])}  \n"
                    f"{badge(row['source_label'], kind)}",
                    unsafe_allow_html=True,
                )
            if len(known) > 8:
                with st.expander(f"查看其余 {len(known) - 8} 项"):
                    for row in known[8:]:
                        st.markdown(
                            f"- **{escape(row['label'])}**：{escape(row['value'])}"
                        )
        else:
            st.caption("还没有确认的决策。先回答 Agent 的第一个问题。")

        if state.reference_files:
            st.caption(
                "参考文件："
                + "、".join(state.reference_files)
                + "（仅记录，未做图片识别）"
            )

        if state.proposal is not None:
            with st.expander("查看方案决策来源", expanded=False):
                _render_decision_list(state.proposal)

        st.markdown(
            f"<span class='app-tiny app-muted'>"
            f"{state.turn_count} 轮对话 · {state.question_count} 个问题 · "
            f"更新于 {format_timestamp(state.updated_at)}</span>",
            unsafe_allow_html=True,
        )

        columns = st.columns(2)
        with columns[0]:
            st.button(
                "让 Agent 接管剩余决策",
                width="stretch",
                key="studio_panel_autonomy",
                on_click=_autonomy,
                disabled=state.status == ConversationStatus.RUNNING,
            )
        with columns[1]:
            st.button(
                "重新开始",
                width="stretch",
                key="studio_panel_reset",
                on_click=_reset,
            )


def _render_asset_panel(state: ConversationState) -> None:
    with st.expander("车辆资产库", expanded=False):
        st.caption(
            "把当前车辆设定保存为可复用资产。下次说“用之前那辆银灰色跑车”"
            "时，可以从这里恢复，不用重新描述外观。"
        )
        st.text_input(
            "资产名称",
            key="studio_asset_name",
            placeholder="例如：钢铁掠食者",
        )
        st.button(
            "保存当前车辆为资产",
            width="stretch",
            key="studio_save_asset",
            on_click=_save_asset,
        )
        saved = st.session_state.get("studio_asset_saved")
        if saved:
            st.success(f"已保存资产：{saved}")
        assets, error = list_vehicle_assets()
        if error:
            st.warning(error)
        elif assets:
            options = {
                f"{asset.get('name', '未命名')} · {asset.get('asset_id', '')[:6]}": asset.get(
                    "asset_id"
                )
                for asset in assets
            }
            selected = st.selectbox(
                "载入已有车辆资产",
                list(options.keys()),
                key="studio_asset_select",
            )
            st.button(
                "使用这个资产",
                width="stretch",
                key="studio_use_asset",
                on_click=_use_asset,
                args=(options[selected],),
            )
        else:
            st.caption("还没有保存的车辆资产。")


def _render_advanced_settings() -> None:
    with st.expander("执行设置（不影响创意决策）", expanded=False):
        columns = st.columns(3)
        with columns[0]:
            st.selectbox(
                "目标视频模型",
                list(MODEL_PROFILES.keys()),
                format_func=lambda key: MODEL_PROFILES[key].display_name,
                key="input_target_model",
            )
        with columns[1]:
            st.select_slider(
                "最大自动修正次数",
                options=[0, 1, 2],
                key="input_max_revisions",
            )
        with columns[2]:
            st.number_input(
                "时长容差（秒）",
                min_value=0.0,
                max_value=5.0,
                step=0.1,
                key="input_tolerance",
            )
        st.caption(
            "这些是执行参数，不是创作决策。模型密钥只从环境变量读取，"
            "不会写进项目、导出文件或日志。"
        )


def _render_conversation(
    state: ConversationState,
    active: bool,
    result: dict | None,
) -> None:
    left, right = st.columns([1.65, 1.0], gap="large")
    with left:
        with st.container(border=True):
            _render_transcript(state)
            if state.pending_question is not None and not active:
                st.markdown(
                    '<div class="app-divider" style="margin:.8rem 0;"></div>',
                    unsafe_allow_html=True,
                )
                _render_question(state.pending_question)
            if (
                state.proposal is not None
                and not active
                and state.status
                not in {ConversationStatus.COMPLETED, ConversationStatus.FAILED}
            ):
                st.markdown(
                    '<div class="app-divider" style="margin:.8rem 0;"></div>',
                    unsafe_allow_html=True,
                )
                _render_proposal(state.proposal, active)
            elif state.proposal is not None and not active:
                with st.expander("查看本案已执行的创作方案", expanded=False):
                    st.markdown(f"**{escape(state.proposal.title)}**")
                    st.write(state.proposal.one_liner)
                    st.markdown(
                        f"场景：{' → '.join(state.proposal.scene_order)}"
                    )
                    _render_decision_list(state.proposal)
        if active:
            render_live_monitor()
        if result and not active:
            _render_result_panel(result)
        if state.status == ConversationStatus.FAILED and result is None:
            st.error("上一次执行失败，尚未返回结果。查看“执行过程”或重新确认方案。")

    with right:
        _render_decision_panel(state)
        if (
            state.brief.has("vehicle_type")
            or "汽车" in str(state.brief.get("content_type") or "")
        ):
            _render_asset_panel(state)
        _render_advanced_settings()
        with st.container(border=True):
            section_header("交付边界", "真实能力与未实现能力")
            st.markdown(
                "- 生成结构化分镜与可复制提示词\n"
                "- 真实调用 DeepSeek（配置密钥时）\n"
                "- 四类确定性校验与最多两次修正\n"
                "- 不生成实际视频；不伪造视频结果\n"
                "- 不做人脸/品牌识别；不会编造参考图内容"
            )


def _render_composer(state: ConversationState, active: bool) -> None:
    if active:
        st.caption("Agent 正在执行工作流。执行过程来自真实 LangGraph 流式状态。")
        return
    placeholder = (
        "直接说你的想法，或回答上面的问题…"
        if state.pending_question is not None
        else "想改哪里？例如：把沙漠改成海岸公路，其他都不要变。"
    )
    prompt = st.chat_input(placeholder, key="studio_chat_input")
    if prompt:
        try:
            conversation_turn(prompt)
        except Exception as exc:
            st.session_state.conversation_error = f"{type(exc).__name__}: {exc}"
        else:
            st.rerun()


def render() -> None:
    state = st.session_state.get("conversation_state")
    if not isinstance(state, ConversationState):
        state = None
    result = st.session_state.get("current_result")
    session = st.session_state.get("run_session")
    if session is not None:
        drain_session(session)
        if session.thread_done and not session.finalized:
            finalize_session(session)
            result = st.session_state.get("current_result")
    active = session_is_active(session)
    if state is not None:
        sync_conversation_result(state, result, active=active)
        state = st.session_state.get("conversation_state")
        sync_conversation_failure(state, active=active)
        state = st.session_state.get("conversation_state")
        if session is None or (session is not None and session.thread_done):
            recover_stale_conversation(state, active=active)
            state = st.session_state.get("conversation_state")
        result = st.session_state.get("current_result")

    if state is None:
        hero(
            "创作工作台 · AGENTIC CREATIVE DIRECTOR",
            "说一句话，导演接手",
            "Agent 会读完你的原话，自己判断还缺哪一项、该问什么、给哪些选项和推荐理由，"
            "然后拆解分镜、写导演提示词、跑四类确定性校验。你不填表，它做决策。",
            chips=[
                "DeepSeek 推理决策",
                "LangGraph 有状态工作流",
                "四类确定性校验",
                "真实工具调用轨迹",
            ],
        )
        _render_landing(result, active)
    else:
        page_header(
            "创作工作台 · AI CREATIVE DIRECTOR",
            "导演正在推进这支片子",
            "Agent 已经接管：它决定下一个问题、现场生成专业选项并给出判断依据，"
            f"你只需要确认或直接说想改什么。原始创意：{state.original_idea[:60]}",
            status_badge(state.status.value),
        )
        if _start_pending_run():
            st.rerun()
        state = st.session_state.get("conversation_state")
        result = st.session_state.get("current_result")
        if isinstance(state, ConversationState):
            _render_conversation(state, active, result)
            _render_composer(state, active)
        else:
            _render_landing(result, active)

    if st.session_state.get("conversation_error"):
        st.error(st.session_state.conversation_error)
        st.session_state.conversation_error = None

    if st.session_state.get("conversation_notice"):
        st.info(st.session_state.conversation_notice)
        st.session_state.conversation_notice = None

    if result and state is None and not active:
        st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
        render_metrics(result)
        with st.expander("查看四类校验摘要", expanded=False):
            render_validation_overview(result.get("validation_report"))
