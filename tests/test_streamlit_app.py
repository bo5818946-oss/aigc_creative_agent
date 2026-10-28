from __future__ import annotations

import time
from pathlib import Path

from streamlit.testing.v1 import AppTest

from database.repository import ProjectRepository
from services.project_service import CreativeProjectService
from tests.fakes import ScriptedDirector, car_flow_decisions
from ui import state as ui_state
from ui.pages import export as export_page
from ui.pages import history as history_page
from ui.pages import local as local_page
from ui.pages import workbench as workbench_page

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


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


def test_streamlit_app_starts_and_has_all_pages() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()

    assert not at.exception
    assert len(at.sidebar.radio) == 1
    assert at.sidebar.radio[0].options == NAV_ITEMS


def test_all_pages_render_without_exception() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()

    for page in NAV_ITEMS:
        at.sidebar.radio[0].set_value(page)
        at.run()
        assert not at.exception, f"page failed: {page}"
        page_errors = " ".join(str(item.value) for item in at.error)
        assert "页面渲染失败" not in page_errors, f"caught error: {page}"


def _click_button(at: AppTest, label: str) -> None:
    matches = [button for button in at.button if button.label == label]
    assert matches, f"button not found: {label}; have={[b.label for b in at.button]}"
    matches[0].click()
    at.run()


def _click_button_starting(at: AppTest, prefix: str) -> None:
    """Options now carry their clip arithmetic ("选择 30 秒（6 条 × 5 秒）")."""

    matches = [button for button in at.button if button.label.startswith(prefix)]
    assert matches, f"button not found: {prefix}; have={[b.label for b in at.button]}"
    matches[0].click()
    at.run()


def _wait_for_run(at: AppTest, *, attempts: int = 100) -> None:
    for _ in range(attempts):
        at.run()
        if at.session_state.get("run_status") in {"completed", "failed"}:
            return
        time.sleep(0.05)
    raise AssertionError("workflow did not finish")


def _isolate(tmp_path: Path, monkeypatch, *, agent: bool = True) -> None:
    monkeypatch.setattr(
        workbench_page,
        "model_is_configured",
        lambda: False,
    )
    monkeypatch.setattr(
        ui_state,
        "model_is_configured",
        lambda: False,
    )
    monkeypatch.setattr(
        ui_state,
        "DB_PATH",
        str(tmp_path / "ui_workbench.sqlite3"),
    )
    if agent:
        # The studio has no rule-table fallback, so UI tests inject a scripted
        # decision layer and exercise the same code path a real model drives.
        director = ScriptedDirector(car_flow_decisions())
        monkeypatch.setattr(ui_state, "guide_mode", lambda: "auto")
        monkeypatch.setattr(ui_state, "DEEPSEEK_API_KEY", "test-key")
        monkeypatch.setattr(ui_state, "_build_director", lambda: director)


def test_local_page_without_a_backend_says_so(tmp_path: Path, monkeypatch) -> None:
    """The page must explain a dead backend instead of crashing or pretending."""

    monkeypatch.setattr(
        ui_state,
        "DB_PATH",
        str(tmp_path / "local_page.sqlite3"),
    )
    # Patch the module constant, not the environment: the suite must not depend
    # on whether a ComfyUI server happens to be running on this machine.
    monkeypatch.setattr(local_page, "COMFYUI_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()
    at.session_state["current_result"] = _prompted_result()
    at.sidebar.radio[0].set_value("本地生成")
    at.run()

    assert not at.exception
    page_errors = " ".join(str(item.value) for item in at.error)
    assert "页面渲染失败" not in page_errors
    assert "连不上 ComfyUI" in page_errors


def _prompted_result() -> dict:
    """A finished project with one image prompt and one video prompt per shot."""

    return {
        "project_id": "prompted",
        "final_status": "completed",
        "structured_requirement": {
            "project_name": "天台夜景",
            "duration_seconds": 10,
            "clip_seconds": 5,
            "clip_count": 2,
            "aspect_ratio": "16:9",
        },
        "storyboard": {
            "shots": [{"shot_number": 1}, {"shot_number": 2}],
            "director_package": {
                "global_prompt": "整片导演提示词" * 20,
                "shot_prompts": [
                    {
                        "shot_number": 1,
                        "image_prompt": "静帧：天台背影",
                        "video_prompt": "运动：缓慢推近",
                    },
                    {
                        "shot_number": 2,
                        "image_prompt": "静帧：城市灯火",
                        "video_prompt": "运动：轻微横移",
                    },
                ],
            },
        },
        "validation_report": {},
    }


def test_shot_rows_follow_the_requested_prompt_type() -> None:
    result = _prompted_result()
    assert [row[1] for row in local_page._shot_rows(result, "image")] == [
        "静帧：天台背影",
        "静帧：城市灯火",
    ]
    assert [row[1] for row in local_page._shot_rows(result, "video")] == [
        "运动：缓慢推近",
        "运动：轻微横移",
    ]


def test_failed_shot_without_a_file_is_not_rendered(tmp_path: Path) -> None:
    """The empty path of a failed shot used to reach st.video("") and crash."""

    assert local_page._media_path({"file_path": ""}) is None
    assert local_page._media_path({"file_path": "   "}) is None
    assert local_page._media_path({}) is None
    assert local_page._media_path({"file_path": str(tmp_path / "gone.png")}) is None

    real = tmp_path / "shot_01.png"
    real.write_bytes(b"x")
    assert local_page._media_path({"file_path": str(real)}) == real


def test_default_resolution_fits_each_model() -> None:
    options = local_page._size_options("16:9")
    assert options[0] == (768, 432)

    # Video on an 8 GB card: the H3 graph OOMs at 1344×768, so start small.
    assert local_page._default_size_index(options, 8192, "video") == 0
    assert local_page._default_size_index(options, 12288, "video") == 1
    assert local_page._default_size_index(options, 24576, "video") == len(options) - 1

    # The image graph finished at the native size on the same card.
    assert local_page._default_size_index(options, 8192, "image") == len(options) - 1


def test_widescreen_projects_do_not_render_at_16_9() -> None:
    """The project aspect (2.39:1 here) decides the pixels, not a fixed table."""

    options = local_page._size_options("2.39:1")
    assert options[0] == (1024, 432)
    assert options[0][0] / options[0][1] > 2.3
    assert options[2][0] > options[0][0]

    portrait = local_page._size_options("9:16")
    assert portrait[0] == (432, 768)


def test_clock_formats_minutes_and_seconds() -> None:
    assert local_page._clock(0) == "0:00"
    assert local_page._clock(59) == "0:59"
    assert local_page._clock(233.6) == "3:53"


def test_implement_block_routes_to_the_matching_kind(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """「是否实现？」 must send image prompts to the image model and video to video."""

    monkeypatch.setattr(ui_state, "DB_PATH", str(tmp_path / "implement.sqlite3"))
    monkeypatch.setattr(local_page, "COMFYUI_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()
    at.session_state["current_result"] = _prompted_result()
    at.sidebar.radio[0].set_value("提示词")
    at.run()

    labels = [button.label for button in at.button]
    assert "生成图片（2 张）" in labels
    assert "生成视频（2 条）" in labels

    _click_button(at, "生成图片（2 张）")
    assert at.session_state["nav"] == "本地生成"
    assert at.session_state["local_kind"] == "image"

    at.sidebar.radio[0].set_value("提示词")
    at.run()
    _click_button(at, "生成视频（2 条）")
    assert at.session_state["local_kind"] == "video"


def test_empty_workbench_has_inputs_and_primary_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch)
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()

    assert not at.exception
    assert any(
        item.label == "描述你想创作的内容" for item in at.text_area
    )
    assert any(button.label == "开始创作" for button in at.button)
    assert any(button.label == "未来超跑广告" for button in at.button)
    assert all("DeepSeek" not in item.label for item in at.toggle)


STALE_CHOICE_APP = """
import streamlit as st

from schemas.conversation import ConversationState
from ui import state as ui_state

# Simulate the state a queued second click lands on: the first click already
# advanced the conversation, so there is no question left to answer.
st.session_state.conversation_state = ConversationState()
ui_state.conversation_choose("__agent__")
st.write("notice=" + str(st.session_state.get("conversation_notice") or ""))
"""


def test_stale_choice_click_is_ignored_instead_of_raising(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch)
    at = AppTest.from_string(STALE_CHOICE_APP)
    at.run()

    assert not at.exception
    assert not at.error
    text = " ".join(str(item.value) for item in at.markdown)
    assert "notice=这一步已经更新过了" in text


def test_can_accept_choice_requires_a_pending_question() -> None:
    from schemas.conversation import ConversationState

    assert ui_state.can_accept_choice(ConversationState()) is False
    assert ui_state.can_accept_choice(None) is False


BUSY_CHOICE_APP = """
import streamlit as st

from schemas.conversation import (
    ClarifyingQuestion,
    ConversationState,
    QuestionOption,
)
from ui import state as ui_state

state = ConversationState()
state.pending_question = ClarifyingQuestion(
    question_id="q",
    field="creative_direction",
    stage="concept",
    prompt="选哪个方向？",
    options=[QuestionOption(option_id="a", label="A")],
)
st.session_state.conversation_state = state
st.session_state.conversation_busy = True
ui_state.conversation_choose("a")
st.write("notice=" + str(st.session_state.get("conversation_notice") or ""))
st.write("value=" + str(state.brief.get("creative_direction")))
"""


def test_choice_is_dropped_while_a_turn_is_in_flight(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch)
    at = AppTest.from_string(BUSY_CHOICE_APP)
    at.run()

    assert not at.exception
    text = " ".join(str(item.value) for item in at.markdown)
    assert "上一步还在处理" in text
    # The in-flight turn owns the state; the duplicate click must not change it.
    assert "value=None" in text


def test_workbench_says_so_when_the_decision_layer_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch, agent=False)
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()

    assert not at.exception
    errors = " ".join(str(item.value) for item in at.error)
    assert "决策层不可用" in errors
    assert not any(button.label == "开始创作" for button in at.button)


def test_minimal_idea_starts_guided_question(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch)
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()

    area = next(
        item
        for item in at.text_area
        if item.label == "描述你想创作的内容"
    )
    area.set_value("我想做一个汽车广告。")
    _click_button(at, "开始创作")

    assert not at.exception
    state = at.session_state["conversation_state"]
    assert state.pending_question is not None
    assert state.pending_question.field == "creative_direction"
    assert state.pending_question.policy_source == "llm"
    labels = [button.label for button in at.button]
    assert "选择 多地貌穿越" in labels
    assert "让 Agent 决定这一项" in labels
    assert [item.value for item in at.error] == []


def test_example_button_starts_conversation_and_skips_known_subject(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch)
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()

    _click_button(at, "未来超跑广告")

    assert not at.exception
    state = at.session_state["conversation_state"]
    assert state.brief.get("vehicle_type") == "超级跑车"
    assert state.pending_question is not None
    assert state.pending_question.field == "creative_direction"
    assert "超级跑车" in at.session_state["studio_idea_input"]


def test_direct_form_still_runs_deterministic_and_opens_prompts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch)
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()

    _click_button(at, "直接生成提示词")
    _wait_for_run(at)

    assert not at.exception
    assert at.session_state["run_status"] == "completed"
    result = at.session_state["current_result"]
    assert result is not None
    assert len(result["storyboard"]["shots"]) >= 1
    assert result.get("updated_at")

    at.sidebar.radio[0].set_value("提示词")
    at.run()
    assert not at.exception
    assert len(at.download_button) >= 1


def test_guided_flow_runs_and_applies_incremental_modification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate(tmp_path, monkeypatch)
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()

    _click_button(at, "未来超跑广告")
    _click_button(at, "选择 多地貌穿越")
    at.multiselect[0].set_value(
        ["森林林间公路", "沙漠戈壁公路", "雪山盘山道路", "城市隧道"]
    )
    _click_button(at, "应用场景选择")
    _click_button_starting(at, "选择 30 秒")
    _click_button(at, "选择 节奏平衡")
    _click_button(at, "选择 动作匹配")
    _click_button(at, "确认并生成分镜与提示词")
    _wait_for_run(at)

    assert not at.exception
    assert at.session_state["run_status"] == "completed"
    state = at.session_state["conversation_state"]
    assert state.status.value == "completed"
    project_id = state.project_id
    assert project_id
    assert len(at.chat_input) == 1

    at.chat_input[0].set_value(
        "把沙漠改成海岸公路，其他都不要变。"
    )
    at.run()
    state = at.session_state["conversation_state"]
    assert "海岸公路" in (state.brief.get("scenes") or [])
    assert "沙漠戈壁公路" not in (state.brief.get("scenes") or [])
    assert state.brief.get("duration_seconds") == 30
    assert state.status.value == "ready"

    _click_button(at, "确认并生成分镜与提示词")
    _wait_for_run(at)

    state = at.session_state["conversation_state"]
    assert state.status.value == "completed"
    assert state.project_id == project_id
    project = ProjectRepository(ui_state.DB_PATH).get_project(project_id)
    assert project is not None
    assert len(project["executions"]) == 2
    assert "海岸公路" in project["structured_requirement"]["scene_requirements"]


def test_storyboard_page_without_project_shows_empty_state() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value("分镜详情")
    at.run()

    assert not at.exception
    markdown_text = " ".join(str(item.value) for item in at.markdown)
    assert "还没有可查看的分镜" in markdown_text


def test_prompts_page_renders_director_package(
    tmp_path: Path,
    demo_requirement,
) -> None:
    repository = ProjectRepository(tmp_path / "ui_director.sqlite3")
    result = CreativeProjectService(repository).run(demo_requirement)
    shots = result["storyboard"]["shots"]
    result["storyboard"]["director_package"] = {
        "title": "导演测试版",
        "global_prompt": "生成一支完整的 30 秒汽车广告。" * 20,
        "negative_prompt": "无字幕，无水印",
        "continuity_bible": ["同一辆车", "车头朝右"],
        "shot_prompts": [
            {
                "shot_number": shot["shot_number"],
                "scene": shot["scene"],
                "image_prompt": "导演图片提示词",
                "video_prompt": "导演视频提示词",
                "negative_prompt": "无字幕",
            }
            for shot in shots
        ],
        "model_notes": "测试模型备注",
    }
    result["storyboard"]["prompt_generation_method"] = "llm_director"

    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()
    at.session_state["current_result"] = result
    at.session_state["current_project_id"] = result["project_id"]
    at.session_state["run_status"] = result["final_status"]
    at.sidebar.radio[0].set_value("提示词")
    at.run()

    assert not at.exception
    tab_labels = [str(tab.label) for tab in at.tabs]
    assert "导演提示词" in tab_labels
    assert "图片生成" in tab_labels
    assert "视频生成" in tab_labels
    assert len(at.download_button) >= 1


def test_page_shortcut_navigation_uses_requested_nav() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value("校验报告")
    at.run()

    buttons = [
        button
        for button in at.button
        if button.label == "前往创作工作台"
    ]
    assert buttons
    buttons[0].click()
    at.run()

    assert not at.exception
    assert at.session_state["nav"] == "创作工作台"
    page_text = " ".join(str(item.value) for item in at.markdown)
    assert "创作工作台" in page_text


def test_storyboard_and_validation_render_real_result(
    tmp_path: Path,
    demo_requirement,
) -> None:
    repository = ProjectRepository(tmp_path / "ui_content.sqlite3")
    result = CreativeProjectService(repository).run(demo_requirement)

    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()
    at.session_state["current_result"] = result
    at.session_state["current_project_id"] = result["project_id"]
    at.session_state["run_status"] = result["final_status"]

    at.sidebar.radio[0].set_value("分镜详情")
    at.run()
    assert not at.exception
    assert len(at.dataframe) >= 1
    storyboard_text = " ".join(str(item.value) for item in at.markdown)
    assert "分镜表" in storyboard_text

    at.sidebar.radio[0].set_value("提示词")
    at.run()
    assert not at.exception
    assert len(at.download_button) >= 1
    prompt_text = " ".join(str(item.value) for item in at.markdown)
    assert "兜底提示词包" in prompt_text
    tab_labels = [str(tab.label) for tab in at.tabs]
    assert "完整提示词包" in tab_labels
    assert "图片生成" in tab_labels
    assert "视频生成" in tab_labels
    assert "模型适配" in tab_labels

    at.sidebar.radio[0].set_value("校验报告")
    at.run()
    assert not at.exception
    validation_text = " ".join(str(item.value) for item in at.markdown)
    assert "时长检查" in validation_text
    assert "场景覆盖" in validation_text

    at.sidebar.radio[0].set_value("执行过程")
    at.run()
    assert not at.exception
    execution_text = " ".join(str(item.value) for item in at.markdown)
    assert "执行摘要" in execution_text


def test_history_page_renders_from_repository(
    tmp_path: Path,
    demo_requirement,
    monkeypatch,
) -> None:
    repository = ProjectRepository(tmp_path / "ui_history.sqlite3")
    result = CreativeProjectService(repository).run(demo_requirement)
    project = repository.get_project(result["project_id"])
    assert project is not None
    summaries = repository.list_projects()
    assert summaries

    monkeypatch.setattr(
        history_page,
        "list_projects",
        lambda **kwargs: (summaries, None),
    )
    monkeypatch.setattr(
        history_page,
        "count_projects",
        lambda **kwargs: len(summaries),
    )
    monkeypatch.setattr(
        history_page,
        "load_project",
        lambda project_id: (project, None),
    )

    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value("项目历史")
    at.run()

    assert not at.exception
    assert len(at.dataframe) >= 1
    page_text = " ".join(str(item.value) for item in at.markdown)
    assert "30秒汽车品牌广告" in page_text


def test_export_page_generates_files(
    tmp_path: Path,
    demo_requirement,
    monkeypatch,
) -> None:
    repository = ProjectRepository(tmp_path / "ui_export.sqlite3")
    result = CreativeProjectService(repository).run(demo_requirement)
    project = repository.get_project(result["project_id"])
    assert project is not None
    output_dir = tmp_path / "ui_output"

    monkeypatch.setattr(
        export_page,
        "load_project",
        lambda project_id: (project, None),
    )
    monkeypatch.setattr(export_page, "OUTPUT_DIR", output_dir)

    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()
    at.session_state["current_result"] = result
    at.session_state["current_project_id"] = result["project_id"]
    at.sidebar.radio[0].set_value("导出")
    at.run()

    generate_buttons = [
        button
        for button in at.button
        if button.label == "生成导出文件"
    ]
    assert generate_buttons
    generate_buttons[0].click()
    at.run()

    assert not at.exception
    exported = list(output_dir.glob("*"))
    assert len(exported) == 2
    assert any(path.suffix == ".json" for path in exported)
    assert any(path.suffix == ".md" for path in exported)
