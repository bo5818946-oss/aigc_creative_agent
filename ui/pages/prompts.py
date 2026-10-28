"""Prompt package page: the primary deliverable of the workbench."""

from __future__ import annotations

from typing import Any

import streamlit as st

from config.cinematography import MODEL_PROFILES
from tools.prompt_package import (
    build_image_prompt_package,
    build_prompt_package,
    build_video_prompt_package,
    media_package_filename,
    prompt_package_filename,
)
from ui.components import render_implement_block
from ui.theme import (
    badge,
    empty_state,
    escape,
    format_timestamp,
    page_header,
    section_header,
    status_badge,
)


_NEGATIVE_SUPPORT_LABELS = {
    "dedicated": "独立负向字段",
    "inline": "写在正向提示词中",
    "partial": "视版本/入口而定",
    "none": "不支持负向提示词",
}


def _shot_label(shot: dict, index: int) -> str:
    number = shot.get("shot_number") or index
    scene = shot.get("scene") or "未命名场景"
    start = shot.get("start_seconds", 0)
    end = shot.get("end_seconds", 0)
    try:
        time_text = f"{float(start):g}–{float(end):g} 秒"
    except (TypeError, ValueError):
        time_text = "时间未知"
    return f"镜头 {number} · {scene} · {time_text}"


def _director_map(director: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(director.get("shot_prompts") or []):
        try:
            number = int(item.get("shot_number") or index + 1)
        except (TypeError, ValueError):
            number = index + 1
        result[number] = item
    return result


def _render_empty() -> None:
    empty_state(
        "还没有可复制的提示词",
        "先完成一次创作任务，Agent 会把整片导演提示词和逐镜头提示词整理到这里。",
    )
    if st.button("去创作工作台", type="primary"):
        st.session_state.requested_nav = "创作工作台"
        st.rerun()


def _render_metrics(
    shots: list[dict],
    report: dict,
    profile,
) -> None:
    columns = st.columns(4)
    with columns[0]:
        st.markdown(
            f"""
            <div class="app-stat">
              <div class="app-stat-label">镜头数量</div>
              <div class="app-stat-value">{len(shots)}</div>
              <div class="app-stat-hint">可直接生成提示词</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with columns[1]:
        try:
            last_end = float(shots[-1].get("end_seconds", 0))
        except (TypeError, ValueError):
            last_end = 0.0
        st.markdown(
            f"""
            <div class="app-stat">
              <div class="app-stat-label">总时长</div>
              <div class="app-stat-value">{last_end:g}s</div>
              <div class="app-stat-hint">最后一个镜头结束时间</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with columns[2]:
        if not report:
            validation, kind = "未执行", "muted"
        elif report.get("passed"):
            validation, kind = "通过", "success"
        else:
            validation, kind = "未通过", "warning"
        st.markdown(
            f"""
            <div class="app-stat">
              <div class="app-stat-label">四类校验</div>
              <div style="margin-top:.5rem;">{badge(validation, kind)}</div>
              <div class="app-stat-hint">校验报告可查看细节</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with columns[3]:
        st.markdown(
            f"""
            <div class="app-stat">
              <div class="app-stat-label">目标模型</div>
              <div class="app-stat-value" style="font-size:1rem;">
                {profile.display_name}
              </div>
              <div class="app-stat-hint">提示词适配参考</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_download_button(
    project_name: str,
    package: str,
    *,
    label: str = "下载完整提示词包 .txt",
    file_name: str | None = None,
) -> None:
    st.download_button(
        label,
        data=package.encode("utf-8"),
        file_name=file_name or prompt_package_filename(project_name),
        mime="text/plain; charset=utf-8",
        width="stretch",
    )


def _render_media_tab(
    kind: str,
    project_name: str,
    requirement: dict[str, Any],
    storyboard: dict[str, Any],
    shots: list[dict],
    director: dict[str, Any],
    target_model: str,
    result: dict,
) -> None:
    """One section per medium: still images and motion are different jobs."""

    is_image = kind == "image"
    title = "图片生成" if is_image else "视频生成"
    field = "image_prompt" if is_image else "video_prompt"
    builder = (
        build_image_prompt_package if is_image else build_video_prompt_package
    )
    question = (
        "这一镜最有信息量的那一帧长什么样：景别、构图、光位、材质、画幅。"
        if is_image
        else "这一镜里画面怎么变：时长、起止状态、摄影机运动、主体运动。"
    )

    package = builder(project_name, requirement, storyboard, target_model)
    director_shots = _director_map(director)
    audit = director.get("image_audit" if is_image else "video_audit") or []

    section_header(
        f"{title}提示词",
        question,
        badge(f"{len(shots)} 条", "info"),
    )
    if audit:
        st.warning("格式审计：" + "、".join(str(item) for item in audit))

    _render_download_button(
        project_name,
        package,
        label=f"下载{title}提示词 .txt",
        file_name=media_package_filename(project_name, kind),
    )
    st.code(package, language="text", wrap_lines=True, height=420)
    st.caption(
        "代码块右上角可直接复制整包；下载文件只包含这一种提示词。"
    )

    with st.expander("逐条查看与复制", expanded=False):
        for index, shot in enumerate(shots, start=1):
            number = int(shot.get("shot_number") or index)
            director_shot = director_shots.get(number) or {}
            prompt = (
                director_shot.get(field)
                or shot.get(field)
                or ""
            )
            scene = shot.get("scene") or "未命名场景"
            st.markdown(f"**镜头 {number} · {escape(str(scene))}**")
            st.code(prompt or "（未生成）", language="text", wrap_lines=True)


def _render_director_tab(
    project_name: str,
    director: dict[str, Any],
    package: str,
    result: dict,
) -> None:
    title = director.get("title") or "整片导演提示词"
    dialect_label = str(director.get("dialect_label") or "")
    section_header(
        title,
        (
            f"体裁：{dialect_label} · " if dialect_label else ""
        )
        + "这是整片级提示词，可直接复制到视频模型；逐镜头版本在下一个标签页",
        badge(dialect_label, "info") if dialect_label else None,
    )
    _render_download_button(project_name, package)
    global_prompt = director.get("global_prompt") or ""
    st.code(
        global_prompt,
        language="text",
        wrap_lines=True,
        height=520,
    )
    st.caption(
        f"导演提示词 {len(global_prompt)} 字符 · 生成于 "
        f"{format_timestamp(result.get('updated_at'))} · "
        "代码块自带复制按钮。"
    )

    audit = director.get("dialect_audit") or []
    if audit:
        st.warning(
            f"体裁审计发现 {len(audit)} 项没在文本里找到，建议人工复核："
            + "、".join(str(item) for item in audit)
        )
    elif dialect_label:
        st.caption(f"体裁审计通过：{dialect_label}的必备信息都已出现在文本里。")

    continuity = director.get("continuity_bible") or []
    negative = director.get("negative_prompt") or ""
    if continuity or negative:
        with st.expander("查看连续性圣经与全片负向提示词", expanded=False):
            if continuity:
                st.markdown("**连续性圣经**")
                for item in continuity:
                    st.markdown(f"- {item}")
            if negative:
                st.markdown("**全片负向提示词**")
                st.code(negative, language="text", wrap_lines=True)


def _render_fallback_package_tab(
    project_name: str,
    package: str,
    result: dict,
    *,
    director_failed: bool,
) -> None:
    if director_failed:
        st.warning(
            "导演提示词生成失败。下面是 Python 规则拼装的兜底提示词，"
            "质量低于导演提示词；请查看执行过程和错误信息。"
        )
    else:
        st.info(
            "当前项目没有导演级提示词（演示模式或尚未生成）。"
            "下面是 Python 规则拼装的兜底提示词。"
        )
    section_header(
        "兜底提示词包",
        "点击代码块右上角的复制图标，或下载 .txt 文件",
    )
    _render_download_button(project_name, package)
    st.code(
        package,
        language="text",
        wrap_lines=True,
        height=460,
    )
    st.caption(
        f"生成于 {format_timestamp(result.get('updated_at'))} · "
        "代码块自带复制按钮。"
    )


def _render_shots_tab(
    shots: list[dict],
    result: dict,
    director: dict[str, Any] | None = None,
) -> None:
    selected_index = st.selectbox(
        "选择镜头",
        options=list(range(len(shots))),
        format_func=lambda index: _shot_label(shots[index], index),
        key=f"prompt_shot_{result.get('project_id', 'current')}",
    )
    shot = shots[selected_index]
    director_shots = _director_map(director or {})
    try:
        shot_number = int(shot.get("shot_number") or selected_index + 1)
    except (TypeError, ValueError):
        shot_number = selected_index + 1
    director_shot = director_shots.get(shot_number) or {}

    image_prompt = (
        director_shot.get("image_prompt")
        or shot.get("image_prompt")
        or ""
    )
    video_prompt = (
        director_shot.get("video_prompt")
        or shot.get("video_prompt")
        or ""
    )
    negative_prompt = (
        director_shot.get("negative_prompt")
        or shot.get("negative_prompt")
        or ""
    )

    image_tab, video_tab, negative_tab = st.tabs(
        ["图片提示词", "视频提示词", "负向提示词"]
    )
    with image_tab:
        st.caption(
            f"{_shot_label(shot, selected_index)} · "
            f"{len(image_prompt)} 字符"
        )
        st.code(
            image_prompt or "（未生成图片提示词）",
            language="text",
            wrap_lines=True,
            height=240,
        )
    with video_tab:
        st.caption(
            f"{_shot_label(shot, selected_index)} · "
            f"{len(video_prompt)} 字符"
        )
        st.code(
            video_prompt or "（未生成视频提示词）",
            language="text",
            wrap_lines=True,
            height=240,
        )
    with negative_tab:
        st.caption("用于支持独立负向字段的模型；不支持时改用正向描述。")
        st.code(
            negative_prompt or "（无负向提示词）",
            language="text",
            wrap_lines=True,
            height=180,
        )


def _render_model_tab(
    profile,
    director: dict[str, Any] | None = None,
) -> None:
    support = _NEGATIVE_SUPPORT_LABELS.get(
        profile.negative_prompt_support,
        profile.negative_prompt_support,
    )
    st.markdown(
        f"- **{profile.display_name}**（{profile.provider}）\n"
        f"- 单镜头建议上限：{profile.max_single_shot_seconds:g} 秒\n"
        f"- 负向提示词：{support}\n"
        f"- 偏好语言：{profile.preferred_language}"
    )
    notes = (director or {}).get("model_notes") or profile.notes
    st.markdown("**导演提示词的模型提醒**")
    st.write(notes)
    st.caption(
        "模型能力档案是参考值，接入具体供应商前请按最新官方文档复核。"
    )


def render() -> None:
    result = st.session_state.get("current_result")
    if not result:
        page_header(
            "提示词包",
            "把分镜变成可直接复制的生成指令",
            "生成成功后，这里会出现整片导演提示词和逐镜头提示词。",
        )
        _render_empty()
        return

    requirement = result.get("structured_requirement") or {}
    storyboard = result.get("storyboard") or {}
    shots = storyboard.get("shots") or []
    project_name = requirement.get("project_name") or "未命名项目"
    target_model = result.get("target_video_model") or "generic"
    profile = MODEL_PROFILES.get(
        target_model,
        MODEL_PROFILES["generic"],
    )
    report = result.get("validation_report") or {}
    final_status = result.get("final_status", "unknown")
    director = storyboard.get("director_package") or {}
    if hasattr(director, "model_dump"):
        director = director.model_dump(mode="json")
    director_failed = any(
        "导演提示词" in str(error)
        for error in (result.get("errors") or [])
    )

    page_header(
        "提示词包",
        project_name,
        "整片导演提示词、逐镜头提示词、负向约束和模型适配都在一起。",
        status_badge(final_status),
    )

    if not shots:
        st.warning(
            "当前项目没有可用分镜，因此没有提示词。"
            "请查看执行过程或校验报告，确认工作流在哪里停止。"
        )
        if st.button("查看执行过程", type="primary"):
            st.session_state.requested_nav = "执行过程"
            st.rerun()
        return

    prompts = [
        shot
        for shot in shots
        if shot.get("image_prompt") or shot.get("video_prompt")
    ]
    if not director.get("global_prompt") and not prompts:
        st.warning(
            "分镜已生成，但提示词尚未生成。"
            "请查看校验报告或执行过程。"
        )
        if st.button("查看校验报告", type="primary"):
            st.session_state.requested_nav = "校验报告"
            st.rerun()
        return

    _render_metrics(shots, report, profile)
    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)

    package = build_prompt_package(
        project_name,
        requirement,
        storyboard,
        target_model,
    )
    has_director = bool(director.get("global_prompt"))
    if has_director:
        director_tab, image_tab, video_tab, model_tab = st.tabs(
            ["导演提示词", "图片生成", "视频生成", "模型适配"]
        )
        with director_tab:
            _render_director_tab(
                project_name,
                director,
                package,
                result,
            )
        with image_tab:
            _render_media_tab(
                "image",
                project_name,
                requirement,
                storyboard,
                shots,
                director,
                target_model,
                result,
            )
        with video_tab:
            _render_media_tab(
                "video",
                project_name,
                requirement,
                storyboard,
                shots,
                director,
                target_model,
                result,
            )
        with model_tab:
            _render_model_tab(profile, director)
    else:
        package_tab, image_tab, video_tab, model_tab = st.tabs(
            ["完整提示词包", "图片生成", "视频生成", "模型适配"]
        )
        with package_tab:
            _render_fallback_package_tab(
                project_name,
                package,
                result,
                director_failed=director_failed,
            )
        with image_tab:
            _render_media_tab(
                "image",
                project_name,
                requirement,
                storyboard,
                shots,
                director,
                target_model,
                result,
            )
        with video_tab:
            _render_media_tab(
                "video",
                project_name,
                requirement,
                storyboard,
                shots,
                director,
                target_model,
                result,
            )
        with model_tab:
            _render_model_tab(profile)

    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    render_implement_block(result, key_prefix="prompts")
    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    columns = st.columns(3)
    with columns[0]:
        if st.button(
            "查看分镜详情",
            width="stretch",
            key="prompts_storyboard",
        ):
            st.session_state.requested_nav = "分镜详情"
            st.rerun()
    with columns[1]:
        if st.button(
            "查看校验报告",
            width="stretch",
            key="prompts_validation",
        ):
            st.session_state.requested_nav = "校验报告"
            st.rerun()
    with columns[2]:
        if st.button(
            "导出项目",
            width="stretch",
            key="prompts_export",
        ):
            st.session_state.requested_nav = "导出"
            st.rerun()
