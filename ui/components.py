"""Reusable Streamlit components for the workbench."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.state import (
    RunSession,
    drain_session,
    finalize_session,
    session_is_active,
)
from ui.theme import (
    badge,
    escape,
    format_timestamp,
    section_header,
    status_badge,
    status_kind,
    status_label,
)


def _task_row(task: dict[str, Any]) -> None:
    left, right = st.columns([5, 1.1])
    with left:
        st.markdown(
            f"**{escape(task.get('name', task.get('task_id', '')))}**  \n"
            f"<span class='app-tiny app-muted'>"
            f"{escape(task.get('task_id', ''))} · "
            f"{escape(format_timestamp(task.get('started_at')))} → "
            f"{escape(format_timestamp(task.get('finished_at')))}"
            f"</span>",
            unsafe_allow_html=True,
        )
        if task.get("error"):
            st.caption(f"错误：{task['error']}")
    with right:
        st.markdown(
            status_badge(task.get("status", "pending")),
            unsafe_allow_html=True,
        )


def render_task_plan(
    task_plan: list[dict[str, Any]],
    *,
    title: str = "任务计划",
    description: str | None = None,
) -> None:
    section_header(title, description)
    if not task_plan:
        st.caption("任务计划尚未生成。")
        return
    with st.container(border=True):
        for task in task_plan:
            _task_row(task)
            st.markdown(
                '<div class="app-divider" style="margin:.45rem 0;"></div>',
                unsafe_allow_html=True,
            )


def render_event_log(
    events: list[dict[str, Any]],
    *,
    max_events: int = 20,
    title: str = "执行日志",
) -> None:
    section_header(
        title,
        f"显示最近 {min(len(events), max_events)} / {len(events)} 条事件",
    )
    if not events:
        st.caption("尚未产生执行事件。")
        return
    displayed = events[-max_events:]
    for event in displayed:
        node = event.get("node_name", "unknown")
        tool = event.get("tool_name") or "无工具"
        label = (
            f"{node} · {tool} · "
            f"{status_label(event.get('status', 'pending'))}"
        )
        with st.expander(label, expanded=False):
            st.markdown(
                status_badge(event.get("status", "pending")),
                unsafe_allow_html=True,
            )
            st.caption(f"时间：{format_timestamp(event.get('created_at'))}")
            if event.get("input_summary"):
                st.markdown("**输入摘要**")
                st.write(event["input_summary"])
            if event.get("output_summary"):
                st.markdown("**输出摘要**")
                st.write(event["output_summary"])
            if event.get("tool_arguments"):
                st.markdown("**工具参数**")
                st.json(event["tool_arguments"])
            if event.get("error"):
                st.error(event["error"])


def render_metrics(result: dict[str, Any]) -> None:
    storyboard = result.get("storyboard") or {}
    shots = storyboard.get("shots") or []
    traces = result.get("trace_events") or []
    usage = result.get("llm_usage") or {}
    tool_calls = sum(1 for event in traces if event.get("tool_name"))
    columns = st.columns(4)
    with columns[0]:
        stat_value = status_label(result.get("final_status", "unknown"))
        st.markdown(
            f"""
            <div class="app-stat">
              <div class="app-stat-label">当前状态</div>
              <div class="app-stat-value" style="font-size:1.1rem;">
                {escape(stat_value)}
              </div>
              <div class="app-stat-hint">项目执行结果</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with columns[1]:
        st.markdown(
            f"""
            <div class="app-stat">
              <div class="app-stat-label">分镜镜头</div>
              <div class="app-stat-value">{len(shots)}</div>
              <div class="app-stat-hint">已生成的结构化镜头</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with columns[2]:
        st.markdown(
            f"""
            <div class="app-stat">
              <div class="app-stat-label">自动修正</div>
              <div class="app-stat-value">{int(result.get("revision_count", 0))}</div>
              <div class="app-stat-hint">最多 2 次</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with columns[3]:
        st.markdown(
            f"""
            <div class="app-stat">
              <div class="app-stat-label">模型与工具</div>
              <div class="app-stat-value">{int(usage.get("calls", 0))} / {tool_calls}</div>
              <div class="app-stat-hint">模型调用 / 工具事件</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_validation_overview(
    report: dict[str, Any] | None,
) -> None:
    section_header("校验概览")
    aggregate = bool(report and report.get("check_type") == "aggregate")
    duration = report.get("duration") if aggregate else None
    scene = report.get("scene") if aggregate else None
    consistency = report.get("consistency") if aggregate else None
    prompt = report.get("prompt") if aggregate else None
    if report and not aggregate and report.get("passed") is not None:
        duration = report
    checks = [
        ("时长", duration),
        ("场景覆盖", scene),
        ("主体一致性", consistency),
        ("提示词质量", prompt),
    ]
    columns = st.columns(4)
    for column, (label, check) in zip(columns, checks):
        status_label_text, kind = _check_status(check)
        with column:
            st.markdown(
                f"""
                <div class="app-stat">
                  <div class="app-stat-label">{escape(label)}</div>
                  <div style="margin-top:.5rem;">{badge(status_label_text, kind)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _check_status(check: dict[str, Any] | None) -> tuple[str, str]:
    if check is None:
        return "未执行", "muted"
    if check.get("passed"):
        if check.get("warnings"):
            return "通过（有警告）", "warning"
        return "通过", "success"
    return "未通过", "error"


def _check_card_header(
    title: str,
    subtitle: str,
    check: dict[str, Any] | None,
) -> None:
    label, kind = _check_status(check)
    left, right = st.columns([5, 1.2])
    with left:
        st.markdown(f"**{escape(title)}**")
        st.caption(subtitle)
    with right:
        st.markdown(badge(label, kind), unsafe_allow_html=True)


def _error_list(errors: list[str], warnings: list[str]) -> None:
    if errors:
        st.markdown("**错误**")
        for error in errors:
            st.markdown(f"- {escape(error)}")
    if warnings:
        st.markdown("**警告**")
        for warning in warnings:
            st.markdown(f"- {escape(warning)}")


def render_validation_cards(report: dict[str, Any] | None) -> None:
    aggregate = bool(report and report.get("check_type") == "aggregate")
    duration = report.get("duration") if aggregate else None
    scene = report.get("scene") if aggregate else None
    consistency = report.get("consistency") if aggregate else None
    prompt = report.get("prompt") if aggregate else None

    if report and not aggregate and report.get("passed") is not None:
        duration = {
            "passed": report.get("passed"),
            "target_duration_seconds": report.get(
                "target_duration_seconds"
            ),
            "timeline_end_seconds": report.get("timeline_end_seconds"),
            "errors": report.get("errors", []),
            "warnings": report.get("warnings", []),
        }

    rows = [
        (
            "时长检查",
            "镜头时间线、重叠、空档与目标时长",
            duration,
        ),
        (
            "场景覆盖",
            "用户要求场景是否都有镜头承载",
            scene,
        ),
        (
            "主体一致性",
            "连续性锁、主体描述、车头与屏幕方向",
            consistency,
        ),
        (
            "提示词质量",
            "必要字段、矛盾约束、模型负向提示词差异",
            prompt,
        ),
    ]

    for index in range(0, len(rows), 2):
        columns = st.columns(2)
        for column, (title, subtitle, check) in zip(
            columns, rows[index : index + 2]
        ):
            with column:
                with st.container(border=True):
                    _check_card_header(title, subtitle, check)
                    if check is None:
                        st.caption(
                            "本类校验未执行或旧数据中没有该字段，"
                            "不能视为通过。"
                        )
                        continue
                    if title == "时长检查":
                        st.markdown(
                            f"- 目标：{check.get('target_duration_seconds', '—')} 秒\n"
                            f"- 实际终点：{check.get('timeline_end_seconds', '—')} 秒"
                        )
                    elif title == "场景覆盖":
                        st.markdown(
                            f"- 覆盖率：{float(check.get('coverage_ratio', 0)):.0%}\n"
                            f"- 缺失：{'、'.join(check.get('missing_scenes', [])) or '无'}\n"
                            f"- 重复：{'、'.join(check.get('duplicate_scenes', [])) or '无'}"
                        )
                    elif title == "主体一致性":
                        notes = check.get("semantic_notes") or []
                        st.markdown(
                            f"- 检查项：{len(check.get('checks', []))}\n"
                            f"- 错误：{len(check.get('errors', []))}\n"
                            f"- 警告：{len(check.get('warnings', []))}"
                        )
                        if notes:
                            with st.expander("语义边界说明"):
                                for note in notes:
                                    st.markdown(f"- {escape(note)}")
                    elif title == "提示词质量":
                        st.markdown(
                            f"- 镜头数：{len(check.get('per_shot', []))}\n"
                            f"- 错误：{len(check.get('errors', []))}\n"
                            f"- 警告：{len(check.get('warnings', []))}"
                        )
                    with st.expander("查看错误与警告", expanded=False):
                        _error_list(
                            check.get("errors", []),
                            check.get("warnings", []),
                        )


def render_revision_history(
    revisions: list[dict[str, Any]],
) -> None:
    section_header("修正记录", "每次自动修正的原因、结果和工具")
    if not revisions:
        st.caption("未触发自动修正。")
        return
    for record in revisions:
        details = record.get("details_json") or record
        number = details.get("revision_number", "?")
        status = details.get("status", "unknown")
        with st.container(border=True):
            left, right = st.columns([5, 1.2])
            with left:
                st.markdown(f"**第 {escape(number)} 次修正**")
                st.caption(
                    f"{escape(details.get('tool', '未知工具'))} · "
                    f"{escape(format_timestamp(details.get('created_at')))}"
                )
            with right:
                st.markdown(
                    status_badge(status),
                    unsafe_allow_html=True,
                )
            if details.get("reason"):
                st.markdown("**原因**")
                st.write(details["reason"])
            before = details.get("before") or {}
            after = details.get("after") or {}
            if before or after:
                st.caption(
                    "修改前：{before_shots} 个镜头 / {before_end} 秒 → "
                    "修改后：{after_shots} 个镜头 / {after_end} 秒".format(
                        before_shots=before.get("shot_count", "—"),
                        before_end=before.get(
                            "timeline_end_seconds", "—"
                        ),
                        after_shots=after.get("shot_count", "—"),
                        after_end=after.get(
                            "timeline_end_seconds", "—"
                        ),
                    )
                )
            usage = details.get("llm_usage") or {}
            if usage:
                st.caption(
                    f"模型调用 {usage.get('calls', 0)} 次，"
                    f"tokens {usage.get('total_tokens', 0)}"
                )


@st.fragment(run_every=1.0)
def _prompt_counts(result: dict[str, Any]) -> tuple[int, int]:
    storyboard = result.get("storyboard") or {}
    director = storyboard.get("director_package") or {}
    if hasattr(director, "model_dump"):
        director = director.model_dump(mode="json")
    prompts = director.get("shot_prompts") or []
    images = sum(
        1 for item in prompts if str(item.get("image_prompt") or "").strip()
    )
    videos = sum(
        1 for item in prompts if str(item.get("video_prompt") or "").strip()
    )
    return images, videos


def render_implement_block(
    result: dict[str, Any],
    *,
    key_prefix: str = "implement",
) -> None:
    """The one question left once prompts exist: do you want the files?"""

    images, videos = _prompt_counts(result)
    if not images and not videos:
        return
    section_header("是否实现？", "提示词已经写好，交给本机 ComfyUI 直接出片")
    columns = st.columns(2)
    with columns[0]:
        if st.button(
            f"生成图片（{images} 张）",
            width="stretch",
            disabled=not images,
            key=f"{key_prefix}_image",
        ):
            st.session_state["local_kind"] = "image"
            st.session_state.requested_nav = "本地生成"
            st.rerun()
    with columns[1]:
        if st.button(
            f"生成视频（{videos} 条）",
            width="stretch",
            disabled=not videos,
            key=f"{key_prefix}_video",
        ):
            st.session_state["local_kind"] = "video"
            st.session_state.requested_nav = "本地生成"
            st.rerun()
    st.caption("图片走图片模型，视频走视频模型，按分镜逐条生成。")


def render_sidebar_run_watcher() -> None:
    """Finalize a background run even when the user is on another page."""

    session: RunSession | None = st.session_state.get("run_session")
    if session is None or session.finalized:
        return
    drain_session(session)
    if session.thread_done and not session.finalized:
        finalize_session(session)
        st.rerun()
    st.caption("后台任务运行中…")


@st.fragment(run_every=0.5)
def render_live_monitor() -> None:
    session: RunSession | None = st.session_state.get("run_session")
    if session is None or session.finalized:
        return
    drain_session(session)
    if session.thread_done and not session.finalized:
        finalize_session(session)
        st.rerun()
    state = session.latest_state or {}
    task_plan = state.get("task_plan") or []
    events = state.get("trace_events") or []
    status = session.status

    with st.container(border=True):
        left, right = st.columns([5, 1.2])
        with left:
            st.markdown("**执行过程**")
            st.caption(
                "事件来自真实工作流流式输出；当前面板每 0.5 秒刷新。"
            )
        with right:
            if session_is_active(session):
                st.markdown(
                    badge("运行中", "info"),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    status_badge(status),
                    unsafe_allow_html=True,
                )
        if session.error:
            st.error(session.error)
        if task_plan:
            st.markdown("**任务计划**")
            for task in task_plan:
                _task_row(task)
        if events:
            st.markdown("**最近事件**")
            for event in events[-8:]:
                st.markdown(
                    f"<div class='app-event app-event-"
                    f"{status_kind(event.get('status', 'pending'))}'>"
                    f"<div class='app-event-title'>"
                    f"{escape(event.get('node_name', 'unknown'))} · "
                    f"{escape(event.get('tool_name') or '无工具')}</div>"
                    f"<div class='app-event-meta'>"
                    f"{escape(status_label(event.get('status', 'pending')))}"
                    f" · {escape(format_timestamp(event.get('created_at')))}"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )
                summary = event.get("output_summary") or event.get(
                    "error"
                )
                if summary:
                    st.caption(summary)
        else:
            st.caption("等待第一个节点完成。")
