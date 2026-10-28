"""Video contracts: four directions, 5/10 s clips, and the H3 graph."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from studio.api import config, store
from studio.api.llm import LLMContractError
from studio.api.main import app
from studio.api.models import ConceptRequest, Plan, Shot, VideoConcept
from studio.api.render import bind_video_workflow, load_video_workflow, video_size
from studio.api.skills import build_video_plan, parse_concepts, parse_video_revision

PROMPT = (
    "A slow handheld push-in on a nurse at a street-side stall before dawn, "
    "steam curling through tungsten light, quiet room tone, no music. "
)


def _payload(**overrides) -> dict:
    items = []
    for title in ("蒸汽与疲惫", "雨夜回程", "霓虹倒影", "清晨第一口"):
        item = {
            "title": title,
            "logline": "一个人在一个地点完成一个动作",
            "treatment": "缓慢推近，从手到脸，蒸汽在光里飘",
            "prompt": PROMPT,
            "negative": "text, watermark",
            "sound": "蒸汽声和远处车流",
            "risk": "手部可能崩",
        }
        item.update(overrides)
        items.append(item)
    return {"concepts": items}


def _request(duration: int = 5, aspect: str = "16:9") -> ConceptRequest:
    return ConceptRequest(brief="凌晨的早餐铺，护士下夜班", duration=duration, aspect=aspect)


def _plan(seconds: float = 5.0, shots: int = 1) -> Plan:
    return Plan(
        kind="video",
        mode="video",
        route="video",
        title="蒸汽与疲惫",
        aspect="16:9",
        shots=[
            Shot(
                index=index,
                title="蒸汽与疲惫",
                prompt=PROMPT,
                negative="text",
                aspect="16:9",
                seconds=seconds,
            )
            for index in range(1, shots + 1)
        ],
        skill="Video Clip",
        skill_version="1.0.0",
    )


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "lumen-test.sqlite3")
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path / "media")
    config.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    store.init_db()
    return tmp_path


# -- concepts ---------------------------------------------------------------


def test_parse_four_concepts() -> None:
    concepts = parse_concepts(_payload(), _request())
    assert [concept.concept_id for concept in concepts] == ["a", "b", "c", "d"]
    assert all(concept.prompt.startswith("A slow handheld") for concept in concepts)


def test_three_concepts_is_a_contract_error() -> None:
    payload = _payload()
    payload["concepts"] = payload["concepts"][:3]
    with pytest.raises(LLMContractError):
        parse_concepts(payload, _request())


def test_chinese_prompt_is_rejected() -> None:
    with pytest.raises(LLMContractError):
        parse_concepts(_payload(prompt=PROMPT + "护士抬头看向镜头，蒸汽升起。"), _request())


def test_duplicate_titles_are_not_four_directions() -> None:
    payload = _payload()
    for item in payload["concepts"]:
        item["title"] = "同一个方向"
    with pytest.raises(LLMContractError):
        parse_concepts(payload, _request())


# -- plans ------------------------------------------------------------------


def test_video_plan_carries_seconds_and_single_shot() -> None:
    concept = parse_concepts(_payload(), _request(10))[0]
    plan = build_video_plan(
        brief="凌晨的早餐铺", concept=concept, duration=10, aspect="16:9"
    )
    assert plan.kind == "video"
    assert plan.route == "video"
    assert len(plan.shots) == 1
    assert plan.shots[0].seconds == 10.0
    assert plan.skill == "Video Clip"


@pytest.mark.parametrize("seconds", [3, 7, 12])
def test_only_five_or_ten_seconds(seconds: float) -> None:
    with pytest.raises(ValidationError):
        _plan(seconds=seconds)


def test_video_plan_has_exactly_one_clip() -> None:
    with pytest.raises(ValidationError):
        _plan(seconds=5.0, shots=2)


# -- graph ------------------------------------------------------------------


def test_binding_fills_by_role_and_keeps_the_frame_math() -> None:
    graph = bind_video_workflow(
        load_video_workflow(),
        prompt="a slow push-in",
        width=640,
        height=368,
        seconds=10,
        seed=7,
        turbo=True,
    )
    assert graph["5"]["inputs"]["prompt"] == "a slow push-in"
    assert (graph["5"]["inputs"]["width"], graph["5"]["inputs"]["height"]) == (640, 368)
    assert graph["10"]["inputs"]["value"] == 10.0
    assert graph["16"]["inputs"]["noise_seed"] == 7
    assert graph["7"]["inputs"]["value"] is True
    # length must keep following the seconds -> frames expression
    assert graph["5"]["inputs"]["length"] == ["9", 1]


def test_ten_seconds_takes_the_smaller_size() -> None:
    assert video_size("16:9", 5) == (768, 432)
    assert video_size("16:9", 10) == (640, 368)
    assert video_size("9:16", 10) == (368, 640)


# -- revision ---------------------------------------------------------------


def test_revision_keeps_duration_and_records_the_note() -> None:
    plan = _plan(seconds=10.0)
    revised = parse_video_revision(
        {
            "title": "更暖的版本",
            "prompt": "Warm tungsten light floods the stall as the nurse lifts the spoon, slow push-in, steam, no music. "
            * 2,
            "negative": "flicker",
            "notes": "把光调暖了",
        },
        plan,
    )
    assert revised.title == "更暖的版本"
    assert revised.shots[0].seconds == 10.0
    assert revised.shots[0].negative == "flicker"
    assert "把光调暖了" in revised.warnings


# -- API --------------------------------------------------------------------


def test_video_project_round_trip(isolated_db) -> None:
    concept = VideoConcept(
        title="蒸汽与疲惫",
        logline="护士在早餐铺吃粥",
        treatment="缓慢推近，蒸汽在光里飘",
        prompt=PROMPT,
        negative="text",
        sound="蒸汽声",
    )
    client = TestClient(app)
    created = client.post(
        "/api/video/projects",
        json={
            "brief": "凌晨的早餐铺",
            "duration": 5,
            "aspect": "16:9",
            "concept": concept.model_dump(),
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["plan"]["kind"] == "video"
    assert body["route"] == "video"
    assert body["plan"]["shots"][0]["seconds"] == 5.0

    listed = client.get("/api/projects").json()
    assert listed["total"] == 1
    assert listed["items"][0]["route"] == "video"


def test_revise_rejects_image_projects(isolated_db) -> None:
    project = _plan()
    store.save_project(project_id="vid1", brief="x", plan=project, reference_id=None)
    revised = _plan(seconds=5.0)
    revised.kind = "image"
    store.update_plan("vid1", revised)
    client = TestClient(app)
    response = client.post(
        "/api/projects/vid1/video/revise", json={"feedback": "再暖一点"}
    )
    assert response.status_code == 400
