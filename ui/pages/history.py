"""Project history page backed by SQLite."""

from __future__ import annotations

import streamlit as st

from ui.state import (
    count_projects,
    list_projects,
    load_conversation_for_project,
    load_project,
    navigate,
    select_project,
)
from ui.theme import (
    empty_state,
    escape,
    format_duration,
    format_timestamp,
    page_header,
    section_header,
    stat_card,
    status_badge,
    status_label,
    truncate,
)

_STATUS_OPTIONS = {
    "全部状态": "",
    "已完成": "completed",
    "校验未通过": "validation_failed",
    "失败": "failed",
    "运行中": "running",
}

_ORDER_OPTIONS = {
    "最近更新": "updated_at_desc",
    "最近创建": "created_at_desc",
    "名称 A-Z": "name_asc",
    "名称 Z-A": "name_desc",
}


def render() -> None:
    page_header(
        "项目历史",
        "从 SQLite 读取已保存的创作项目",
        "项目列表来自现有数据库，只读展示，不会修改或清空历史数据。",
    )

    search = st.text_input(
        "搜索项目",
        placeholder="输入项目名称或原始需求关键词",
        key="history_search",
    )
    columns = st.columns([2, 2, 1])
    with columns[0]:
        status_label_choice = st.selectbox(
            "状态筛选",
            list(_STATUS_OPTIONS.keys()),
            key="history_status",
        )
    with columns[1]:
        order_label_choice = st.selectbox(
            "排序",
            list(_ORDER_OPTIONS.keys()),
            key="history_order",
        )
    with columns[2]:
        st.write("")
        st.write("")
        if st.button("刷新", width="stretch"):
            st.rerun()

    status_filter = _STATUS_OPTIONS[status_label_choice]
    summaries, error = list_projects(
        search=search,
        status=status_filter,
        order_by=_ORDER_OPTIONS[order_label_choice],
        limit=100,
    )
    if error:
        st.error(error)
        return

    total = count_projects(search=search, status=status_filter)
    columns = st.columns(3)
    with columns[0]:
        stat_card("匹配项目", total, "当前筛选条件下")
    with columns[1]:
        stat_card("当前显示", len(summaries), "最多显示 100 个")
    with columns[2]:
        stat_card(
            "数据库",
            "已连接",
            "SQLite 本地存储",
        )

    if not summaries:
        st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
        empty_state(
            "没有匹配的项目",
            "尝试清空搜索词或切换状态筛选。"
            if total == 0 and (search or status_filter)
            else "数据库中还没有已保存的创作项目。",
        )
        return

    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    section_header(
        "项目列表",
        "显示最近更新项目；点击下方选择器查看完整内容",
    )
    rows = []
    for summary in summaries:
        rows.append(
            {
                "项目": summary.get("project_name", "未命名项目"),
                "状态": status_label(summary.get("status", "unknown")),
                "时长": format_duration(summary.get("duration_seconds")),
                "场景": summary.get("scene_count", 0),
                "镜头": summary.get("shot_count", 0),
                "分镜来源": (
                    "DeepSeek"
                    if summary.get("generation_method") == "llm"
                    else (
                        "确定性占位"
                        if summary.get("generation_method")
                        else "—"
                    )
                ),
                "更新时间": format_timestamp(summary.get("updated_at")),
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)

    labels = {
        f"{summary.get('project_name', '未命名项目')} · "
        f"{summary.get('project_id', '')[:8]}": summary.get(
            "project_id", ""
        )
        for summary in summaries
    }
    select_key = (
        "history_project_select_"
        f"{abs(hash((search, status_filter, order_label_choice))) % 1_000_000}"
    )
    if st.session_state.get(select_key) not in labels:
        st.session_state[select_key] = list(labels.keys())[0]
    selected_label = st.selectbox(
        "选择项目查看详情",
        list(labels.keys()),
        key=select_key,
    )
    selected_id = labels[selected_label]
    project, project_error = load_project(selected_id)
    if project_error:
        st.error(project_error)
        return
    if project is None:
        st.error("项目不存在或已被删除。")
        return

    requirement = project.get("structured_requirement") or {}
    storyboard = project.get("storyboard") or {}
    shots = storyboard.get("shots") or []
    with st.container(border=True):
        left, right = st.columns([4, 1.2])
        with left:
            st.markdown(
                f"**{escape(project.get('project_name', '未命名项目'))}**"
            )
            st.caption(
                f"项目 ID：{project.get('project_id', '—')} · "
                f"创建：{format_timestamp(project.get('created_at'))} · "
                f"更新：{format_timestamp(project.get('updated_at'))}"
            )
        with right:
            st.markdown(
                status_badge(project.get("status", "unknown")),
                unsafe_allow_html=True,
            )
        st.markdown(
            f"- 内容类型：{escape(requirement.get('content_type', '—'))}\n"
            f"- 时长：{format_duration(requirement.get('duration_seconds'))}\n"
            f"- 场景：{len(requirement.get('scene_requirements', []))} 个\n"
            f"- 镜头：{len(shots)} 个\n"
            f"- 分镜来源：{escape(storyboard.get('generation_method', '—'))}"
        )
        preview = project.get("raw_requirement", "")
        if preview:
            with st.expander("查看原始需求"):
                st.text(preview)

        buttons = st.columns(5)
        with buttons[0]:
            if st.button(
                "提示词包",
                type="primary",
                width="stretch",
                key="history_view_prompts",
            ):
                select_project(project)
                navigate("提示词")
        with buttons[1]:
            if st.button(
                "分镜详情",
                width="stretch",
                key="history_view_storyboard",
            ):
                select_project(project)
                navigate("分镜详情")
        with buttons[2]:
            if st.button(
                "校验报告",
                width="stretch",
                key="history_view_validation",
            ):
                select_project(project)
                navigate("校验报告")
        with buttons[3]:
            if st.button(
                "执行过程",
                width="stretch",
                key="history_view_execution",
            ):
                select_project(project)
                navigate("执行过程")
        with buttons[4]:
            if st.button(
                "导出",
                width="stretch",
                key="history_view_export",
            ):
                select_project(project)
                navigate("导出")

        if st.button(
            "继续创作对话",
            width="stretch",
            key="history_resume_conversation",
        ):
            _conversation, conversation_error = (
                load_conversation_for_project(project.get("project_id", ""))
            )
            if conversation_error:
                st.info(conversation_error)
            else:
                navigate("创作工作台")

    st.caption(
        truncate(
            f"原始需求预览：{project.get('raw_requirement', '')}",
            180,
        )
    )
