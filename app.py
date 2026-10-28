"""AIGC Studio Streamlit entry point."""

from __future__ import annotations

import traceback

import streamlit as st

from ui.components import render_sidebar_run_watcher
from ui.pages import (
    execution,
    export,
    history,
    local,
    prompts,
    storyboard,
    validation,
    workbench,
)
from ui.state import (
    agent_mode_label,
    init_state,
    model_is_configured,
    session_is_active,
)
from ui.theme import (
    apply_theme,
    badge,
    escape,
    status_badge,
)

NAV_ITEMS = [
    "创作工作台",
    "提示词",
    "本地生成",
    "分镜详情",
    "校验报告",
    "执行过程",
    "项目历史",
    "导出",
]

PAGES = {
    "创作工作台": workbench.render,
    "提示词": prompts.render,
    "本地生成": local.render,
    "分镜详情": storyboard.render,
    "校验报告": validation.render,
    "执行过程": execution.render,
    "项目历史": history.render,
    "导出": export.render,
}


def _render_sidebar() -> str:
    with st.sidebar:
        st.markdown(
            """
            <div class="app-sidebar-brand">
              <div class="app-brand-name">AIGC Studio</div>
              <div class="app-brand-sub">Creative Workflow</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            badge(
                "DeepSeek 已配置"
                if model_is_configured()
                else "演示模式",
                "success" if model_is_configured() else "warning",
            ),
            unsafe_allow_html=True,
        )
        st.caption(f"决策层：{agent_mode_label()}")
        # Page shortcut buttons write requested_nav instead of the radio's
        # widget key. Sync it before the radio is instantiated, otherwise
        # Streamlit rejects the late session-state update.
        requested = st.session_state.get("requested_nav")
        if requested in NAV_ITEMS:
            st.session_state.nav = requested
        if "requested_nav" in st.session_state:
            del st.session_state["requested_nav"]
        if st.session_state.get("nav") not in NAV_ITEMS:
            st.session_state.nav = NAV_ITEMS[0]
        nav = st.radio(
            "导航",
            NAV_ITEMS,
            key="nav",
            label_visibility="collapsed",
        )
        st.markdown(
            '<div class="app-divider" style="margin:.85rem 0;"></div>',
            unsafe_allow_html=True,
        )

        session = st.session_state.get("run_session")
        result = st.session_state.get("current_result")
        active = session_is_active(session)
        if active:
            st.markdown(badge("任务运行中", "info"), unsafe_allow_html=True)
            if session and session.project_id:
                st.caption(f"项目 {session.project_id[:8]}")
            st.caption("可切换页面；执行会在后台继续。")
        elif result:
            requirement = result.get("structured_requirement") or {}
            storyboard = result.get("storyboard") or {}
            shots = storyboard.get("shots") or []
            name = requirement.get("project_name") or "当前项目"
            st.markdown(
                f"""
                <div class="app-sidebar-project">
                  <div class="app-sidebar-project-name">{escape(name)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                status_badge(result.get("final_status", "unknown")),
                unsafe_allow_html=True,
            )
            st.caption(
                f"{len(shots)} 个镜头 · "
                f"{int(result.get('revision_count', 0))} 次修正"
            )
        else:
            conversation = st.session_state.get("conversation_state")
            if conversation is not None:
                st.markdown(badge("创作引导中", "info"), unsafe_allow_html=True)
                known = sum(
                    1
                    for row in conversation.brief.snapshot()
                    if row["value"] != "待确定"
                )
                st.caption(
                    f"{len(conversation.messages)} 条消息 · {known} 项决策"
                )
                if conversation.pending_question is not None:
                    st.caption("等待你的决定")
            else:
                st.caption("尚未运行创作任务")

        if session is not None and not session.finalized:
            render_sidebar_run_watcher()

        st.markdown(
            """
            <div class="app-sidebar-footer">
              DeepSeek · LangGraph · SQLite<br/>
              本地创作工作区
            </div>
            """,
            unsafe_allow_html=True,
        )
    return nav


def main() -> None:
    apply_theme()
    init_state()
    nav = _render_sidebar()
    try:
        PAGES[nav]()
    except Exception as exc:  # keep the UI readable on unexpected failures
        st.error(f"页面渲染失败：{type(exc).__name__}: {exc}")
        with st.expander("技术详情"):
            st.code(traceback.format_exc(), language="text")


main()
