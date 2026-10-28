from __future__ import annotations

from pathlib import Path

from database.repository import ProjectRepository
from services.llm_service import LLMService
from services.project_service import CreativeProjectService
from tests.fakes import FakeChatClient
from tools.storyboard_tool import generate_storyboard_with_llm


def _llm_payload() -> dict:
    return {
        "project_name": "LLM 汽车广告",
        "content_type": "汽车商业广告",
        "subject": "一辆哑光黑色纯电 SUV",
        "target_audience": "年轻消费者",
        "duration_seconds": 30,
        "aspect_ratio": "16:9",
        "visual_style": "电影感商业广告",
        "scene_requirements": ["森林", "草原", "沙漠", "雪地", "城市"],
        "camera_language": "航拍与低机位跟拍结合",
        "consistency_constraints": [
            "全片使用同一辆哑光黑色纯电 SUV，车头始终朝右"
        ],
        "transition_requirements": "自然动势转场",
        "output_formats": ["markdown", "json"],
        "pending_confirmations": [],
    }


def _storyboard_payload() -> dict:
    scenes = ["森林", "草原", "沙漠", "雪地", "城市"]
    shots = []
    for index, scene in enumerate(scenes):
        start = float(index * 6)
        end = float((index + 1) * 6)
        shots.append(
            {
                "shot_number": index + 1,
                "shot_id": f"SHOT-{index + 1:03d}",
                "start_seconds": start,
                "end_seconds": end,
                "scene": scene,
                "narrative_purpose": f"展示{scene}场景",
                "action_start": "车辆从画面左侧进入",
                "action_end": "车辆行驶到画面中央",
                "subject_state": "同一辆哑光黑色纯电 SUV，车头朝右",
                "continuity_locks": [
                    "全片同一辆哑光黑色纯电 SUV，车头始终朝右"
                ],
                "cinematography": {
                    "shot_size": (
                        "wide_shot" if index == 0 else "medium_shot"
                    ),
                    "camera_angle": "low_angle",
                    "camera_movement": (
                        "push_in" if index == 0 else "static"
                    ),
                    "lens": "35mm",
                    "composition": "rule_of_thirds",
                    "lighting_style": (
                        "golden_hour"
                        if index % 2 == 0
                        else "soft_window"
                    ),
                    "color_grade": "teal_orange",
                    "transition": "hard_cut",
                    "vfx": [],
                    "screen_direction": "left_to_right",
                },
                "sound": "环境声，无对白",
                "negative_prompt": "无字幕，无水印，无 Logo",
            }
        )
    return {"generation_method": "llm", "shots": shots}


def _director_payload() -> dict:
    scenes = ["森林", "草原", "沙漠", "雪地", "城市"]
    shot_prompts = []
    for index, scene in enumerate(scenes, start=1):
        shot_prompts.append(
            {
                "shot_number": index,
                "scene": scene,
                "image_prompt": (
                    f"镜头 {index}：同一辆哑光黑色纯电 SUV 在{scene}中，"
                    "车头朝右，低机位电影摄影，35mm 镜头，真实金属反射。"
                ),
                "video_prompt": (
                    f"镜头 {index}：车辆沿{scene}道路持续向右高速行驶，"
                    "轮胎接地，近景参照物快速后退，摄影机短暂落后再追赶。"
                ),
                "negative_prompt": "无字幕，无水印，无 Logo",
            }
        )
    return {
        "title": "LLM 汽车广告 · 导演版",
        "global_prompt": (
            "生成一支 30 秒、16:9 横屏的电影级汽车商业广告。"
            "全片只允许出现同一辆哑光黑色纯电 SUV，车头始终朝右，"
            "车辆沿真实道路持续向前行驶，轮胎始终接地，车头方向与"
            "运动方向一致。按时间顺序穿越森林、草原、沙漠、雪地和城市："
            "森林段用密集树干和低机位前侧追拍建立速度；草原段用开阔"
            "地平线和侧向追拍展示车身比例；沙漠段用低机位和车尾追拍"
            "表现动力；雪地段用连续弯道和外侧机位表现抓地力；城市段"
            "用建筑、路灯和隧道灯带完成收束。场景之间使用树干遮挡、"
            "甩镜、岩石前景和动作匹配硬切，切点前后保持同一方向、"
            "同一车身比例和连续轮胎旋转。摄影机不要全程固定距离，"
            "要先落后再追赶，并用近景、中景、远景的速度差证明真实"
            "高速运动。光线从森林冷光过渡到草原日光、沙漠硬光、"
            "雪地冷光和城市霓虹，车身始终保持哑光黑色金属质感。"
            "声音包含动力系统、风噪、轮胎接地和环境空间变化。"
            "结尾车辆在城市出口完成英雄镜头，出现简洁的项目名文字，"
            "不出现品牌 Logo、字幕、水印或未经指定的文字。"
        ),
        "negative_prompt": (
            "禁止车头车尾颠倒，禁止倒车式高速行驶，禁止车身变形、"
            "悬浮、轮胎穿地、背景静止、用静态展示代替高速运动。"
        ),
        "continuity_bible": [
            "全片同一辆哑光黑色纯电 SUV",
            "车头始终朝右，前进方向一致",
            "轮胎持续滚动并与道路接触",
        ],
        "shot_prompts": shot_prompts,
        "model_notes": "通用视频模型；逐镜头生成时保持同一主体和方向。",
    }


def _llm_service(
    responses: list,
    *,
    max_retries: int = 2,
) -> LLMService:
    return LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        max_retries=max_retries,
        client=FakeChatClient(responses),
        retry_backoff_seconds=0,
    )


def test_workflow_uses_llm_and_persists_updated_requirement(
    tmp_path: Path,
    demo_requirement,
) -> None:
    repository = ProjectRepository(tmp_path / "llm_workflow.sqlite3")
    client = FakeChatClient(
        [
            _llm_payload(),
            _storyboard_payload(),
            _director_payload(),
        ]
    )
    llm_service = LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        client=client,
        retry_backoff_seconds=0,
    )
    service = CreativeProjectService(repository, llm_service=llm_service)

    result = service.run(
        demo_requirement,
        raw_requirement="自然语言需求：做一支 30 秒汽车广告，黑色纯电 SUV。",
    )

    assert result["final_status"] == "completed"
    assert result["structured_requirement"]["subject"] == (
        "一辆哑光黑色纯电 SUV"
    )
    assert result["llm_usage"]["calls"] == 3
    assert result["llm_usage"]["total_tokens"] == 90
    assert result["validation_report"]["passed"] is True
    assert result["storyboard"]["generation_method"] == "llm"
    assert result["storyboard"]["prompt_generation_method"] == (
        "llm_director"
    )
    assert len(result["storyboard"]["shots"]) == 5
    assert all(
        shot["image_prompt"] and shot["video_prompt"]
        for shot in result["storyboard"]["shots"]
    )
    assert all(
        "哑光黑色纯电 SUV" in shot["subject_state"]
        for shot in result["storyboard"]["shots"]
    )
    director = result["storyboard"]["director_package"]
    assert director is not None
    assert director["title"] == "LLM 汽车广告 · 导演版"
    assert len(director["global_prompt"]) >= 200
    assert len(director["shot_prompts"]) == 5

    analyze_events = [
        event
        for event in result["trace_events"]
        if event["node_name"] == "analyze_requirements"
    ]
    assert len(analyze_events) == 1
    assert analyze_events[0]["tool_name"] == (
        "services.llm_service.LLMService.parse_requirement"
    )
    assert analyze_events[0]["tool_arguments"]["model"] == "deepseek-chat"
    assert analyze_events[0]["tool_arguments"]["usage"]["calls"] == 1

    storyboard_events = [
        event
        for event in result["trace_events"]
        if event["node_name"] == "generate_storyboard"
    ]
    assert len(storyboard_events) == 1
    assert storyboard_events[0]["tool_name"] == (
        "tools.storyboard_tool.generate_storyboard_with_llm"
    )
    assert storyboard_events[0]["tool_arguments"]["usage"]["calls"] == 2

    director_events = [
        event
        for event in result["trace_events"]
        if event["node_name"] == "write_director_prompt"
    ]
    assert len(director_events) == 1
    assert director_events[0]["tool_name"] == (
        "tools.prompt_writer.write_director_package"
    )
    assert director_events[0]["tool_arguments"]["usage"]["calls"] == 3

    requirement_prompt = client.calls[0]["messages"][1]["content"]
    storyboard_prompt = client.calls[1]["messages"][1]["content"]
    director_prompt = client.calls[2]["messages"][1]["content"]
    assert "自然语言需求" in requirement_prompt
    assert "请为下面的创作需求生成分镜" in storyboard_prompt
    assert "请为下面的项目写导演级提示词" in director_prompt

    project = repository.get_project(result["project_id"])
    assert project is not None
    assert project["project_name"] == "LLM 汽车广告"
    assert project["structured_requirement"]["subject"] == (
        "一辆哑光黑色纯电 SUV"
    )
    assert project["status"] == "completed"
    assert project["validation_reports"][0]["passed"] == 1
    assert project["storyboard"]["generation_method"] == "llm"
    assert project["storyboard"]["prompt_generation_method"] == (
        "llm_director"
    )
    assert project["storyboard"]["director_package"]["title"] == (
        "LLM 汽车广告 · 导演版"
    )
    assert all(
        shot["image_prompt"] and shot["video_prompt"]
        for shot in project["storyboard"]["shots"]
    )
    assert project["executions"][0]["traces"][0]["tool_name"] == (
        "services.llm_service.LLMService.parse_requirement"
    )
    assert project["executions"][0]["traces"][2]["tool_name"] == (
        "tools.storyboard_tool.generate_storyboard_with_llm"
    )


def test_workflow_llm_invalid_storyboard_retries_once_then_fails(
    tmp_path: Path,
    demo_requirement,
) -> None:
    repository = ProjectRepository(tmp_path / "llm_bad_storyboard.sqlite3")
    client = FakeChatClient([_llm_payload(), "这不是 JSON", "这也不是 JSON"])
    llm_service = LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        client=client,
        retry_backoff_seconds=0,
    )
    service = CreativeProjectService(repository, llm_service=llm_service)

    result = service.run(
        demo_requirement,
        raw_requirement="分镜必须失败的需求",
    )

    assert result["final_status"] == "failed"
    # 需求解析 + 第一次分镜 + 一次带错误信息的纠正重试。
    assert result["llm_usage"]["calls"] == 3
    assert result["llm_usage"]["errors"] == 2
    assert any("分镜生成失败" in error for error in result["errors"])


def test_invalid_storyboard_is_retried_once_with_the_validation_error(
    demo_requirement,
) -> None:
    """The corrective retry must carry the validation complaint to the model."""

    client = FakeChatClient(
        [
            "这不是 JSON",
            _storyboard_payload(),
        ]
    )
    llm_service = LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        client=client,
        retry_backoff_seconds=0,
    )

    storyboard = generate_storyboard_with_llm(llm_service, demo_requirement)

    assert len(storyboard.shots) >= 1
    assert len(client.calls) == 2
    retry_prompt = client.calls[1]["messages"][1]["content"]
    assert "上一次输出被校验拒绝" in retry_prompt
    assert "枚举值" in retry_prompt


def test_workflow_llm_storyboard_missing_times_fails_cleanly(
    tmp_path: Path,
    demo_requirement,
) -> None:
    repository = ProjectRepository(tmp_path / "llm_missing_times.sqlite3")
    client = FakeChatClient(
        [_llm_payload(), {"shots": [{"scene": "森林"}]}]
    )
    llm_service = LLMService(
        api_key="sk-test-key",
        base_url="https://example.invalid",
        model="deepseek-chat",
        client=client,
        retry_backoff_seconds=0,
    )
    service = CreativeProjectService(repository, llm_service=llm_service)

    result = service.run(
        demo_requirement,
        raw_requirement="缺少时间的分镜测试",
    )

    assert result["final_status"] == "failed"
    assert any(
        "缺少 start_seconds" in error for error in result["errors"]
    )
    assert all(
        event.get("tool_name") != "tools.duration_checker.check_duration"
        for event in result["trace_events"]
    )


def test_workflow_llm_invalid_json_fails_without_running_tools(
    tmp_path: Path,
    demo_requirement,
) -> None:
    repository = ProjectRepository(tmp_path / "llm_invalid.sqlite3")
    llm_service = _llm_service(["这不是 JSON"])
    service = CreativeProjectService(repository, llm_service=llm_service)

    result = service.run(
        demo_requirement,
        raw_requirement="无法解析的需求",
    )

    assert result["final_status"] == "failed"
    assert result["llm_usage"]["errors"] == 1
    assert any("需求解析失败" in error for error in result["errors"])
    assert [event["node_name"] for event in result["trace_events"]] == [
        "analyze_requirements",
        "finalize_result",
    ]
    assert all(
        event.get("tool_name") != "tools.duration_checker.check_duration"
        for event in result["trace_events"]
    )

    project = repository.get_project(result["project_id"])
    assert project is not None
    assert project["status"] == "failed"
    assert project["structured_requirement"]["subject"] == (
        "一辆银灰色流线型纯电轿车"
    )
    assert project["executions"][0]["traces"][0]["status"] == "error"


def test_workflow_llm_retry_exhaustion_fails_cleanly(
    tmp_path: Path,
    demo_requirement,
) -> None:
    repository = ProjectRepository(tmp_path / "llm_timeout.sqlite3")
    llm_service = _llm_service(
        [TimeoutError("1"), TimeoutError("2"), TimeoutError("3")],
        max_retries=2,
    )
    service = CreativeProjectService(repository, llm_service=llm_service)

    result = service.run(
        demo_requirement,
        raw_requirement="超时测试",
    )

    assert result["final_status"] == "failed"
    assert result["llm_usage"]["calls"] == 3
    assert result["llm_usage"]["retries"] == 2
    assert result["llm_usage"]["errors"] == 3
    assert any("DeepSeek 调用失败" in error for error in result["errors"])
    assert all(
        event.get("tool_name") != "tools.duration_checker.check_duration"
        for event in result["trace_events"]
    )

    project = repository.get_project(result["project_id"])
    assert project is not None
    assert project["status"] == "failed"


def test_workflow_without_llm_stays_deterministic(
    tmp_path: Path,
    demo_requirement,
) -> None:
    repository = ProjectRepository(tmp_path / "no_llm.sqlite3")
    service = CreativeProjectService(repository)

    result = service.run(
        demo_requirement,
        raw_requirement="确定性模式",
    )

    assert result["final_status"] == "completed"
    assert result["llm_usage"] == {}
    analyze_event = next(
        event
        for event in result["trace_events"]
        if event["node_name"] == "analyze_requirements"
    )
    assert analyze_event["tool_name"] is None
