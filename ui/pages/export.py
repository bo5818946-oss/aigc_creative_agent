"""Export page."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from config.settings import OUTPUT_DIR
from tools.export_tool import export_project
from ui.state import load_project
from ui.theme import (
    empty_state,
    escape,
    format_timestamp,
    page_header,
    section_header,
    status_badge,
)


def _clear_export() -> None:
    st.session_state.last_export_paths = None


def render() -> None:
    result = st.session_state.get("current_result")
    page_header(
        "导出结果",
        "将项目保存为可交付的 Markdown 与 JSON",
        "导出文件写入项目 output/ 目录，并使用唯一文件名，"
        "不会覆盖已有文件。",
    )

    if not result:
        empty_state(
            "还没有可导出的项目",
            "先运行一次创作任务，或在项目历史中载入已有项目。",
        )
        columns = st.columns(2)
        with columns[0]:
            if st.button("前往创作工作台", type="primary", width="stretch"):
                st.session_state.requested_nav = "创作工作台"
                st.rerun()
        with columns[1]:
            if st.button("前往项目历史", width="stretch"):
                st.session_state.requested_nav = "项目历史"
                st.rerun()
        return

    project_id = result.get("project_id")
    project, error = load_project(project_id) if project_id else (None, None)
    if error:
        st.error(error)
        return
    if project is None:
        st.error("项目不存在或无法从数据库读取。")
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
                f"ID：{project.get('project_id', '—')} · "
                f"更新：{format_timestamp(project.get('updated_at'))} · "
                f"{len(shots)} 个镜头"
            )
        with right:
            st.markdown(
                status_badge(project.get("status", "unknown")),
                unsafe_allow_html=True,
            )
        st.markdown(
            f"- 内容类型：{escape(requirement.get('content_type', '—'))}\n"
            f"- 目标时长：{requirement.get('duration_seconds', '—')} 秒\n"
            f"- 分镜来源：{escape(storyboard.get('generation_method', '—'))}"
        )

    section_header(
        "导出内容",
        "原始需求、结构化需求、任务计划、分镜、提示词、校验报告、修正记录和执行轨迹",
    )
    st.caption(
        "Markdown 适合课程报告与人工阅读；JSON 保留完整结构化数据，"
        "便于后续程序处理。"
    )

    if st.button(
        "生成导出文件",
        type="primary",
        width="stretch",
        key="generate_export",
    ):
        try:
            paths = export_project(project, OUTPUT_DIR)
        except Exception as exc:
            st.error(f"导出失败：{type(exc).__name__}: {exc}")
            _clear_export()
        else:
            st.session_state.last_export_paths = {
                "json": str(paths["json"]),
                "markdown": str(paths["markdown"]),
            }
            st.success("导出完成。文件已写入 output/ 目录。")

    paths = st.session_state.get("last_export_paths")
    if not paths:
        return

    json_path = Path(paths.get("json", ""))
    markdown_path = Path(paths.get("markdown", ""))
    missing = [
        path.name
        for path in (json_path, markdown_path)
        if not path.exists()
    ]
    if missing:
        st.warning(
            "上次导出的文件已不存在："
            + "、".join(missing)
            + "。请重新生成。"
        )
        _clear_export()
        return

    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    section_header("下载", "文件同时保留在 output/ 目录")
    left, right = st.columns(2)
    with left:
        st.download_button(
            "下载 Markdown",
            data=markdown_path.read_bytes(),
            file_name=markdown_path.name,
            mime="text/markdown",
            width="stretch",
            key="download_markdown",
        )
        st.caption(str(markdown_path))
    with right:
        st.download_button(
            "下载 JSON",
            data=json_path.read_bytes(),
            file_name=json_path.name,
            mime="application/json",
            width="stretch",
            key="download_json",
        )
        st.caption(str(json_path))

    with st.expander("预览 Markdown"):
        st.code(
            markdown_path.read_text(encoding="utf-8"),
            language="markdown",
        )
    with st.expander("预览 JSON（前 200 行）"):
        lines = json_path.read_text(encoding="utf-8").splitlines()
        st.code(
            "\n".join(lines[:200]),
            language="json",
        )
