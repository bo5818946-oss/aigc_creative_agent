"""Execution process page."""

from __future__ import annotations

import streamlit as st

from ui.components import (
    render_event_log,
    render_live_monitor,
    render_metrics,
    render_revision_history,
    render_task_plan,
)
from ui.state import session_is_active
from ui.theme import (
    divider,
    empty_state,
    format_timestamp,
    page_header,
    section_header,
    status_badge,
)


def render() -> None:
    result = st.session_state.get("current_result")
    session = st.session_state.get("run_session")
    active = session_is_active(session)
    status = (
        result.get("final_status", "unknown")
        if result
        else ("running" if active else "idle")
    )

    page_header(
        "执行过程",
        "查看工作流真实走过的节点与工具",
        "任务状态、工具调用、校验和修正来自执行轨迹与流式状态，"
        "不是预设动画或静态日志。",
        status_badge(status) if status != "idle" else None,
    )

    if active or (session is not None and not session.finalized):
        render_live_monitor()

    run_error = st.session_state.get("run_error")
    if run_error and not active:
        st.error(run_error)

    if not result:
        empty_state(
            "还没有可查看的执行记录",
            "先在创作工作台启动一次任务，执行过程会自动出现在这里。",
        )
        if st.button("前往创作工作台", type="primary"):
            st.session_state.requested_nav = "创作工作台"
            st.rerun()
        return

    render_metrics(result)
    st.markdown(
        "<div class='app-divider'></div>", unsafe_allow_html=True
    )

    requirement = result.get("structured_requirement") or {}
    left, right = st.columns([2.2, 1.0])
    with left:
        with st.container(border=True):
            section_header(
                "执行摘要",
                "项目与执行标识用于复盘和数据库检索",
            )
            st.markdown(
                f"**{requirement.get('project_name', '未命名项目')}**"
            )
            st.markdown(
                f"- 项目 ID：`{result.get('project_id', '—')}`\n"
                f"- 执行 ID：`{result.get('execution_id', '—')}`\n"
                f"- 最终状态：{result.get('final_status', '—')}\n"
                f"- 修正次数：{result.get('revision_count', 0)}"
            )
            updated = result.get("updated_at") or result.get("created_at")
            if updated:
                st.caption(f"时间：{format_timestamp(updated)}")
    with right:
        with st.container(border=True):
            section_header("快捷入口")
            if st.button(
                "查看提示词包",
                type="primary",
                width="stretch",
                key="execution_prompts",
            ):
                st.session_state.requested_nav = "提示词"
                st.rerun()
            if st.button(
                "分镜详情",
                width="stretch",
                key="execution_storyboard",
            ):
                st.session_state.requested_nav = "分镜详情"
                st.rerun()
            if st.button(
                "校验报告",
                width="stretch",
                key="execution_validation",
            ):
                st.session_state.requested_nav = "校验报告"
                st.rerun()
            if st.button(
                "导出结果",
                width="stretch",
                key="execution_export",
            ):
                st.session_state.requested_nav = "导出"
                st.rerun()

    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    render_task_plan(result.get("task_plan") or [])

    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    traces = result.get("trace_events") or []
    show_all = st.toggle(
        "显示全部事件",
        value=False,
        key="execution_show_all_events",
        help="默认只显示最近 20 条；全部事件仍保存在数据库中。",
    )
    render_event_log(
        traces,
        max_events=len(traces) if show_all else 20,
    )

    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    render_revision_history(result.get("revision_history") or [])

    errors = result.get("errors") or []
    if errors:
        st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
        section_header("未解决问题", "最终状态不是 completed 时保留的问题")
        for error in errors[:20]:
            st.markdown(f"- {error}")
