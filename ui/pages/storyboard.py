"""Storyboard and prompt page."""

from __future__ import annotations

import streamlit as st

from config.cinematography import (
    CAMERA_ANGLE_LABELS,
    CAMERA_MOVEMENT_LABELS,
    COLOR_GRADE_LABELS,
    LIGHTING_LABELS,
    SHOT_SIZE_LABELS,
    TRANSITION_LABELS,
)
from ui.theme import (
    empty_state,
    escape,
    format_duration,
    page_header,
    section_header,
    stat_card,
    truncate,
)


def _label(mapping: dict, value, fallback: str = "") -> str:
    if value is None:
        return fallback or "—"
    normalized = {str(key.value): label for key, label in mapping.items()}
    return normalized.get(str(value), str(value))


def _cinematography_text(shot: dict) -> str:
    cin = shot.get("cinematography") or {}
    if not cin:
        return " / ".join(
            part
            for part in (
                shot.get("framing"),
                shot.get("camera_position"),
                shot.get("camera_movement"),
            )
            if part
        ) or "—"
    return " / ".join(
        part
        for part in (
            _label(SHOT_SIZE_LABELS, cin.get("shot_size")),
            _label(CAMERA_ANGLE_LABELS, cin.get("camera_angle")),
            _label(CAMERA_MOVEMENT_LABELS, cin.get("camera_movement")),
        )
        if part
    )


def _render_prompt(label: str, text: str) -> None:
    st.markdown(f"**{label}**")
    if text:
        st.code(text, language="text")
        st.caption("代码块右上角可复制完整提示词。")
    else:
        st.caption("未生成。")


def render() -> None:
    result = st.session_state.get("current_result")
    if not result:
        page_header(
            "分镜详情",
            "查看每个镜头的完整创作方案",
            "分镜表、摄影参数、图片提示词和视频提示词都来自当前项目。",
        )
        empty_state(
            "还没有可查看的分镜",
            "先运行一次创作任务，或在项目历史中载入已有项目。",
        )
        if st.button("前往创作工作台", type="primary"):
            st.session_state.requested_nav = "创作工作台"
            st.rerun()
        return

    storyboard = result.get("storyboard") or {}
    shots = storyboard.get("shots") or []
    requirement = result.get("structured_requirement") or {}
    total_duration = 0.0
    if shots:
        total_duration = float(shots[-1].get("end_seconds", 0)) - float(
            shots[0].get("start_seconds", 0)
        )
    prompt_count = sum(
        1
        for shot in shots
        if shot.get("image_prompt") and shot.get("video_prompt")
    )

    page_header(
        "分镜详情",
        "查看每个镜头的完整创作方案",
        "先看分镜表，再选择镜头查看摄影参数、连续性约束和可复制提示词。",
    )

    columns = st.columns(4)
    with columns[0]:
        stat_card("镜头数量", len(shots), "结构化分镜")
    with columns[1]:
        stat_card("时间线", format_duration(total_duration), "首镜到末镜")
    with columns[2]:
        stat_card(
            "分镜来源",
            "DeepSeek" if storyboard.get("generation_method") == "llm" else "确定性占位",
            storyboard.get("generation_method", "—"),
        )
    with columns[3]:
        stat_card(
            "提示词覆盖",
            f"{prompt_count}/{len(shots)}",
            "图片与视频均生成的数量",
        )

    if prompt_count:
        if st.button(
            "打开提示词包（可直接复制）",
            type="primary",
            key="storyboard_open_prompts",
        ):
            st.session_state.requested_nav = "提示词"
            st.rerun()

    if not shots:
        st.markdown(
            "<div class='app-divider'></div>", unsafe_allow_html=True
        )
        empty_state(
            "项目中没有分镜",
            "该项目可能尚未完成分镜生成，或旧数据没有分镜字段。",
        )
        return

    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    section_header(
        "分镜表",
        "长文本已截断；完整内容在下方镜头详情中查看",
    )
    rows = []
    for shot in shots:
        rows.append(
            {
                "镜头": shot.get("shot_number"),
                "时间": (
                    f"{shot.get('start_seconds', 0):g}–"
                    f"{shot.get('end_seconds', 0):g}s"
                ),
                "场景": shot.get("scene", ""),
                "叙事职责": truncate(
                    shot.get("narrative_purpose") or "—", 30
                ),
                "景别 / 机位 / 运镜": _cinematography_text(shot),
                "动作": truncate(
                    shot.get("action_start")
                    or shot.get("action")
                    or "—",
                    42,
                ),
            }
        )
    st.dataframe(
        rows,
        width="stretch",
        hide_index=True,
    )

    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    section_header(
        "镜头详情",
        f"项目 {requirement.get('project_name', '')}",
    )
    options = [
        f"镜头 {shot.get('shot_number')} · {shot.get('scene', '')}"
        for shot in shots
    ]
    selected = st.selectbox(
        "选择镜头",
        options,
        key=f"storyboard_shot_{result.get('project_id', 'current')}",
        label_visibility="collapsed",
    )
    index = options.index(selected)
    shot = shots[index]
    cin = shot.get("cinematography") or {}

    with st.container(border=True):
        left, right = st.columns([4, 1.2])
        with left:
            st.markdown(
                f"**镜头 {shot.get('shot_number')} · "
                f"{escape(shot.get('scene', ''))}**"
            )
            st.caption(
                f"{shot.get('start_seconds', 0):g}–"
                f"{shot.get('end_seconds', 0):g}s · "
                f"{shot.get('narrative_purpose', '—')}"
            )
        with right:
            st.caption(
                "LLM 分镜"
                if storyboard.get("generation_method") == "llm"
                else "确定性分镜"
            )

        columns = st.columns(2)
        with columns[0]:
            st.markdown("**起点状态**")
            st.write(shot.get("action_start") or "—")
            st.markdown("**主体状态**")
            st.write(shot.get("subject_state") or "—")
        with columns[1]:
            st.markdown("**终点状态**")
            st.write(shot.get("action_end") or "—")
            st.markdown("**动作链**")
            st.write(shot.get("action") or "—")

        if cin:
            st.markdown("**摄影参数**")
            st.markdown(
                f"- 景别：{_label(SHOT_SIZE_LABELS, cin.get('shot_size'))}\n"
                f"- 机位：{_label(CAMERA_ANGLE_LABELS, cin.get('camera_angle'))}\n"
                f"- 运镜：{_label(CAMERA_MOVEMENT_LABELS, cin.get('camera_movement'))}\n"
                f"- 镜头：{cin.get('lens', '—')} · 构图：{cin.get('composition', '—')}\n"
                f"- 光线：{_label(LIGHTING_LABELS, cin.get('lighting_style'))}\n"
                f"- 色彩：{_label(COLOR_GRADE_LABELS, cin.get('color_grade'))}\n"
                f"- 转场：{_label(TRANSITION_LABELS, cin.get('transition'))}\n"
                f"- 屏幕方向：{cin.get('screen_direction', '—')}"
            )

        locks = shot.get("continuity_locks") or []
        if locks:
            st.markdown("**连续性锁**")
            for lock in locks:
                st.markdown(f"- {escape(lock)}")

        if shot.get("sound"):
            st.markdown("**声音**")
            st.write(shot["sound"])

        tabs = st.tabs(
            ["图片提示词", "视频提示词", "负向提示词"]
        )
        with tabs[0]:
            _render_prompt("图片提示词", shot.get("image_prompt", ""))
        with tabs[1]:
            _render_prompt("视频提示词", shot.get("video_prompt", ""))
        with tabs[2]:
            _render_prompt(
                "负向提示词", shot.get("negative_prompt", "")
            )
