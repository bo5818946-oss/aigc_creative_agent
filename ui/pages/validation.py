"""Validation report page."""

from __future__ import annotations

import streamlit as st

from ui.components import (
    render_revision_history,
    render_validation_cards,
    render_validation_overview,
)
from ui.theme import (
    empty_state,
    page_header,
    section_header,
    status_badge,
)


def _checks(report: dict | None) -> dict[str, dict | None]:
    if not report:
        return {
            "duration": None,
            "scene": None,
            "consistency": None,
            "prompt": None,
        }
    if report.get("check_type") == "aggregate":
        return {
            "duration": report.get("duration"),
            "scene": report.get("scene"),
            "consistency": report.get("consistency"),
            "prompt": report.get("prompt"),
        }
    return {
        "duration": report,
        "scene": None,
        "consistency": None,
        "prompt": None,
    }


def _suggestions(checks: dict[str, dict | None]) -> list[str]:
    suggestions: list[str] = []
    duration = checks["duration"]
    if duration is None:
        suggestions.append(
            "时长检查未执行：重新运行项目以生成时长时间线。"
        )
    elif not duration.get("passed"):
        suggestions.append(
            "时长未通过：调整镜头起止时间，使总时间线落在目标时长"
            "与容差范围内；可以启用自动修正。"
        )

    scene = checks["scene"]
    if scene is None:
        suggestions.append(
            "场景检查未执行：旧报告或当前项目没有场景覆盖数据。"
        )
    elif not scene.get("passed"):
        suggestions.append(
            "场景覆盖未通过：补齐缺失场景的镜头，"
            "或明确记录该场景不拍及理由。"
        )

    consistency = checks["consistency"]
    if consistency is None:
        suggestions.append(
            "一致性检查未执行：无法判断主体锁和车辆方向是否完整。"
        )
    elif not consistency.get("passed"):
        suggestions.append(
            "一致性未通过：统一车头/前进方向，补齐连续性锁，"
            "并同步修改文本方向与 screen_direction。"
        )

    prompt = checks["prompt"]
    if prompt is None:
        suggestions.append(
            "提示词检查未执行：无法判断必要字段和约束是否完整。"
        )
    elif not prompt.get("passed"):
        suggestions.append(
            "提示词未通过：补齐主体、场景、动作、摄影、光线和负向约束，"
            "移除互相矛盾的风格词。"
        )
    return suggestions


def render() -> None:
    result = st.session_state.get("current_result")
    if not result:
        page_header(
            "校验报告",
            "查看项目是否真的满足创作约束",
            "四类校验分别展示通过、警告、失败和未执行状态。",
        )
        empty_state(
            "还没有可查看的校验报告",
            "先运行一次创作任务，或在项目历史中载入已有项目。",
        )
        if st.button("前往创作工作台", type="primary"):
            st.session_state.requested_nav = "创作工作台"
            st.rerun()
        return

    report = result.get("validation_report")
    checks = _checks(report)
    final_status = result.get("final_status", "unknown")
    page_header(
        "校验报告",
        "查看项目是否真的满足创作约束",
        "确定性检查覆盖时长、场景、主体一致性和提示词质量；"
        "未执行的检查不会被标成通过。",
        status_badge(final_status),
    )

    render_validation_overview(report)
    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    render_validation_cards(report)

    if report is None:
        st.warning(
            "当前项目没有校验报告。可能是旧数据，或工作流在生成分镜前失败。"
        )
    elif report.get("check_type") != "aggregate":
        st.info(
            "当前展示的是旧版时长报告；场景、一致性和提示词检查未执行，"
            "不能视为通过。"
        )

    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    section_header(
        "处理建议",
        "根据校验类型给出的具体修正方向，不替代人工判断",
    )
    suggestions = _suggestions(checks)
    if suggestions:
        with st.container(border=True):
            for suggestion in suggestions:
                st.markdown(f"- {suggestion}")
    else:
        st.caption("所有已执行检查通过，无需处理建议。")

    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    render_revision_history(result.get("revision_history") or [])

    st.markdown("<div class='app-divider'></div>", unsafe_allow_html=True)
    section_header("最终结果", "项目状态与仍未解决的问题")
    with st.container(border=True):
        st.markdown(status_badge(final_status), unsafe_allow_html=True)
        errors = result.get("errors") or []
        if errors:
            for error in errors[:20]:
                st.markdown(f"- {error}")
        elif final_status == "completed":
            st.caption("项目已完成；所有已执行的确定性检查通过。")
        else:
            st.caption("项目未完成，但没有保存具体错误。")

    st.caption(
        "边界说明：文本与结构化字段检查不能保证最终生成视频中的"
        "车型、车漆、灯组等细节完全一致；视觉一致性仍需人工验收。"
    )

    left, middle, right = st.columns(3)
    with left:
        if st.button(
            "查看提示词包",
            type="primary",
            width="stretch",
            key="validation_prompts",
        ):
            st.session_state.requested_nav = "提示词"
            st.rerun()
    with middle:
        if st.button(
            "查看执行过程",
            width="stretch",
            key="validation_execution",
        ):
            st.session_state.requested_nav = "执行过程"
            st.rerun()
    with right:
        if st.button(
            "查看分镜详情",
            width="stretch",
            key="validation_storyboard",
        ):
            st.session_state.requested_nav = "分镜详情"
            st.rerun()
