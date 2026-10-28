"""Contract tests for planning, image counts, and route-specific decisions."""

from __future__ import annotations

import pytest

from studio.api.llm import LLMContractError
from studio.api.models import PlanRequest
from studio.api.skills import (
    apply_auto_decision,
    build_auto_messages,
    build_ecom_messages,
    final_auto_decision_params,
    parse_ecom_plan,
    parse_reprompt,
)

STYLE_LOCK = "Campaign Style Lock: test lock for a neutral ecommerce set."


def _payload(count: int) -> dict:
    return {
        "title": "测试图片包",
        "summary": "用于契约测试的图片包。",
        "reasoning": "先展示商品，再解释细节。",
        "style_lock": STYLE_LOCK,
        "shots": [
            {
                "index": index,
                "title": f"画面 {index}",
                "purpose": "测试用途",
                "prompt": (
                    f"A clean product photograph for frame {index}, neutral background, "
                    "soft studio light, no text, no watermark."
                ),
                "negative": "text, watermark, logo",
                "copy": "",
                "notes": "测试备注",
            }
            for index in range(1, count + 1)
        ],
        "warnings": [],
    }


def test_ecommerce_five_pack_keeps_requested_aspect() -> None:
    req = PlanRequest(
        mode="ecommerce",
        brief="为通勤邮差包做五张独立站主图。",
        pack_size=5,
        aspect="4:5",
        product_name="通勤邮差包",
        platform="独立站",
    )
    plan = parse_ecom_plan(_payload(5), req)

    assert plan.aspect == "4:5"
    assert [shot.aspect for shot in plan.shots] == ["4:5"] * 5
    assert all(STYLE_LOCK not in shot.prompt for shot in plan.shots)
    assert plan.style_lock == STYLE_LOCK
    assert "未提供商品参考图" in "\n".join(plan.warnings)


def test_ecommerce_twelve_pack_keeps_fixed_structure() -> None:
    req = PlanRequest(
        mode="ecommerce",
        brief="为折叠露营灯做十二张淘宝主图与详情图。",
        pack_size=12,
        product_name="折叠露营灯",
        platform="淘宝",
    )
    plan = parse_ecom_plan(_payload(12), req)

    assert plan.aspect == "5×1:1 + 7×2:3"
    assert len(plan.shots) == 12
    assert [shot.aspect for shot in plan.shots[:5]] == ["1:1"] * 5
    assert [shot.aspect for shot in plan.shots[5:]] == ["2:3"] * 7
    assert all(STYLE_LOCK not in shot.prompt for shot in plan.shots)


def test_contract_text_is_stripped_before_the_renderer_sees_it() -> None:
    """Hex values and the "Campaign Style Lock" label used to be painted in."""

    payload = _payload(1)
    payload["shots"][0]["prompt"] = (
        "Campaign Style Lock: consistent premium ecommerce system, "
        "off-white background #F7F6F1, deep charcoal #2D2D2D, midnight navy #1F2A44. "
        "A cyclist wearing a navy messenger bag, real street photography, soft daylight."
    )
    req = PlanRequest(mode="ecommerce", brief="通勤邮差包主图", pack_size=1)

    plan = parse_ecom_plan(payload, req)
    prompt = plan.shots[0].prompt

    assert "Campaign Style Lock" not in prompt
    assert "#" not in prompt
    assert "F7F6F1" not in prompt
    assert "navy messenger bag" in prompt
    assert plan.style_lock  # kept for the project page and export


def test_a_prompt_that_is_only_a_style_lock_is_rejected() -> None:
    payload = _payload(1)
    payload["shots"][0]["prompt"] = "Campaign Style Lock: #F7F6F1 #2D2D2D #1F2A44"
    req = PlanRequest(mode="ecommerce", brief="通勤邮差包主图", pack_size=1)

    with pytest.raises(LLMContractError, match="只有风格锁"):
        parse_ecom_plan(payload, req)


def test_reprompt_keeps_structure_and_strips_contract_text() -> None:
    req = PlanRequest(mode="ecommerce", brief="通勤邮差包主图", pack_size=1)
    plan = parse_ecom_plan(_payload(1), req)

    shots = parse_reprompt(
        {
            "shots": [
                {
                    "index": 1,
                    "prompt": (
                        "Campaign Style Lock: #F7F6F1. A navy messenger bag worn by a "
                        "cyclist on a wet city street, soft overcast daylight, 35mm."
                    ),
                    "negative": "",
                }
            ]
        },
        plan,
    )

    assert [shot.index for shot in shots] == [1]
    assert "#" not in shots[0].prompt
    assert "Campaign Style Lock" not in shots[0].prompt
    assert "messenger bag" in shots[0].prompt
    assert shots[0].negative  # route default applied
    assert shots[0].status == "planned"


def test_reprompt_rejects_a_changed_shot_count() -> None:
    req = PlanRequest(mode="ecommerce", brief="通勤邮差包主图", pack_size=1)
    plan = parse_ecom_plan(_payload(1), req)

    with pytest.raises(LLMContractError, match="应该还是 1 张"):
        parse_reprompt(
            {
                "shots": [
                    {"index": 1, "prompt": "a" * 40, "negative": ""},
                    {"index": 2, "prompt": "b" * 40, "negative": ""},
                ]
            },
            plan,
        )


def test_reprompt_rejects_a_missing_shot() -> None:
    req = PlanRequest(mode="ecommerce", brief="通勤邮差包主图", pack_size=1)
    plan = parse_ecom_plan(_payload(1), req)

    with pytest.raises(LLMContractError, match="缺少第 1 张"):
        parse_reprompt({"shots": [{"index": 9, "prompt": "a" * 40}]}, plan)


def test_auto_decision_must_state_the_count_it_chose() -> None:
    """A missing pack_size used to silently become 5 images."""

    with pytest.raises(LLMContractError, match="没有给出图片数量"):
        apply_auto_decision(
            PlanRequest(mode="auto", brief="给独立站做一组商品图。"),
            {"route": "ecommerce", "params": {"shot_count": 9}},
        )

    with pytest.raises(LLMContractError, match="没有给出镜头数量"):
        apply_auto_decision(
            PlanRequest(mode="auto", brief="拍一组夜班护士的静帧故事。"),
            {"route": "cinema", "params": {"pack_size": 5}},
        )


def test_auto_decision_clears_the_other_routes_parameter() -> None:
    ecommerce = apply_auto_decision(
        PlanRequest(mode="auto", brief="给一款通勤包做电商图。"),
        {
            "route": "ecommerce",
            "params": {
                "shot_count": 9,
                "pack_size": 5,
                "aspect": "4:5",
                "product_name": "通勤包",
                "platform": "独立站",
            },
        },
    )
    assert ecommerce.pack_size == 5
    assert ecommerce.shot_count is None
    assert ecommerce.product_name == "通勤包"

    cinema = apply_auto_decision(
        PlanRequest(mode="auto", brief="拍一组夜班护士的静帧故事。"),
        {
            "route": "cinema",
            "params": {
                "shot_count": 3,
                "pack_size": 12,
                "aspect": "2.39:1",
                "product_name": "",
                "platform": "",
            },
        },
    )
    assert cinema.shot_count == 3
    assert cinema.pack_size is None


def test_final_auto_params_are_derived_from_the_saved_plan() -> None:
    req = PlanRequest(
        mode="auto",
        brief="为折叠露营灯做十二张淘宝主图与详情图。",
        pack_size=12,
        product_name="折叠露营灯",
        platform="淘宝",
    )
    plan = parse_ecom_plan(_payload(12), req)
    params = final_auto_decision_params(plan, req)

    assert params == {
        "pack_size": 12,
        "aspect": "5×1:1 + 7×2:3",
        "product_name": "折叠露营灯",
        "platform": "淘宝",
    }


def test_auto_prompt_forbids_mixing_shot_count_and_pack_size() -> None:
    system, _ = build_auto_messages(
        PlanRequest(mode="auto", brief="给一款通勤包做电商图。")
    )

    assert "params.pack_size 必须是 1、5 或 12 之一" in system
    assert "params.shot_count 必须是 null" in system
    assert "选择 ecommerce 时不要提“9 镜”" in system
    assert "数字和结构必须与 params 完全一致" in system


def test_ecommerce_prompt_does_not_invent_a_missing_reference() -> None:
    system, _ = build_ecom_messages(
        PlanRequest(
            mode="ecommerce",
            brief="为折叠露营灯做五张主图。",
            pack_size=5,
        )
    )
    assert "本次没有参考图" in system
    assert "attached reference image" in system

    with_reference, _ = build_ecom_messages(
        PlanRequest(
            mode="ecommerce",
            brief="为折叠露营灯做五张主图。",
            pack_size=5,
            reference_id="upload_test",
        )
    )
    assert "每张 prompt 必须包含" in with_reference
    assert "本次没有参考图" not in with_reference
