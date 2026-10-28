"""Planning pipeline: skill text in, validated project out."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from studio.api import store
from studio.api.llm import (
    DeepSeekClient,
    LLMContractError,
    LLMUnavailable,
    Usage,
)
from studio.api.models import (
    ConceptRequest,
    CustomConceptRequest,
    Plan,
    PlanRequest,
    ProjectRecord,
    ProjectResponse,
    VideoConcept,
    VideoProjectRequest,
)
from studio.api.skills import (
    apply_auto_decision,
    build_auto_messages,
    build_cinema_messages,
    build_ecom_messages,
    build_reprompt_messages,
    final_auto_decision_params,
    parse_auto_decision,
    parse_cinema_plan,
    parse_ecom_plan,
    parse_concepts,
    parse_reprompt,
    parse_video_revision,
    build_concept_messages,
    build_custom_concept_messages,
    parse_custom_concept,
    build_video_plan,
    build_video_revise_messages,
)

Emitter = Callable[[dict[str, Any]], None]


class PlanInputError(RuntimeError):
    """The request itself is invalid (missing upload, bad route parameters)."""


@dataclass
class PlanOutcome:
    project: ProjectResponse
    usage: dict[str, int] = field(default_factory=dict)
    decision: dict[str, Any] | None = None


def _emit(emitter: Emitter | None, **payload: Any) -> None:
    if emitter is None:
        return
    try:
        emitter(payload)
    except Exception:
        # A disconnected browser must not abort a plan the provider already
        # returned. The plan is persisted below regardless.
        pass


def _validate_auto_limits(req: PlanRequest, decision: dict[str, Any]) -> None:
    route = decision["route"]
    if route == "cinema":
        if req.shot_count not in {1, 3, 9}:
            raise LLMContractError(
                "自主决策返回了不支持的镜头数量 "
                f"{req.shot_count}；影视图只能是 1、3 或 9。"
            )
    else:
        if req.pack_size not in {1, 5, 12}:
            raise LLMContractError(
                "自主决策返回了不支持的图片包数量 "
                f"{req.pack_size}；电商图只能是 1、5 或 12。"
            )


def _merge_warnings(*groups: Any) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        if isinstance(group, str):
            group = [group]
        if not isinstance(group, list):
            continue
        for item in group:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    return merged


def rewrite_prompts(project: ProjectRecord) -> Plan:
    """Rewrite one project's prompts in place, keeping its structure.

    Used to pull old projects onto the current renderer rules (no layout specs,
    hex values or style-lock labels in the text the image model sees).
    """

    client = DeepSeekClient()
    system, user = build_reprompt_messages(project.plan)
    payload, _usage = client.complete_json(
        system=system,
        user=user,
        temperature=0.35,
        max_tokens=8192,
    )
    shots = parse_reprompt(payload, project.plan)
    return project.plan.model_copy(update={"shots": shots})


def generate_project(
    req: PlanRequest, emitter: Emitter | None = None
) -> PlanOutcome:
    if req.reference_id:
        upload = store.get_upload(req.reference_id)
        if upload is None or store.upload_path(req.reference_id) is None:
            raise PlanInputError(
                "参考图不存在或文件已丢失，请重新上传后再规划。"
            )

    _emit(emitter, stage="validating", message="正在核对需求与参考图")
    client = DeepSeekClient()
    usage = Usage()
    decision: dict[str, Any] | None = None
    effective = req

    if req.mode == "auto":
        _emit(emitter, stage="deciding", message="Agent 正在判断创作路线")
        system, user = build_auto_messages(req)
        payload, call_usage = client.complete_json(
            system=system,
            user=user,
            temperature=0.2,
            max_tokens=2200,
        )
        usage.add(call_usage)
        decision = parse_auto_decision(payload)
        effective = apply_auto_decision(req, decision)
        _validate_auto_limits(effective, decision)
        route = decision["route"]
        _emit(
            emitter,
            stage="routing",
            message=(
                "Agent 选择影视图路线"
                if route == "cinema"
                else "Agent 选择电商图路线"
            ),
            route=route,
            reasoning=decision.get("reasoning", ""),
            params=decision.get("params", {}),
        )

    route = (
        decision["route"]
        if decision
        else ("cinema" if effective.mode == "cinema" else "ecommerce")
    )
    if route == "cinema":
        count = effective.shot_count or 3
        _emit(
            emitter,
            stage="planning",
            message=f"正在执行 Cinema DNA，规划 {count} 个镜头",
            route=route,
        )
        system, user = build_cinema_messages(effective)
        payload, call_usage = client.complete_json(
            system=system,
            user=user,
            temperature=0.7,
            max_tokens=8192,
        )
        usage.add(call_usage)
        _emit(emitter, stage="validating_plan", message="正在校验镜头契约")
        plan = parse_cinema_plan(payload, effective)
    else:
        pack = effective.pack_size or 5
        _emit(
            emitter,
            stage="planning",
            message=f"正在执行电商视觉技能，规划 {pack} 张图片",
            route=route,
        )
        system, user = build_ecom_messages(effective)
        payload, call_usage = client.complete_json(
            system=system,
            user=user,
            temperature=0.65,
            max_tokens=8192,
        )
        usage.add(call_usage)
        _emit(emitter, stage="validating_plan", message="正在校验图片包契约")
        plan = parse_ecom_plan(payload, effective)

    if decision is not None:
        plan.agent_decision = {
            "route": decision["route"],
            "reasoning": decision.get("reasoning", ""),
            "params": final_auto_decision_params(plan, effective),
            "title_hint": decision.get("title_hint", ""),
            "warnings": decision.get("warnings", []),
        }
        plan.warnings = _merge_warnings(
            decision.get("warnings"), plan.warnings
        )
    plan.warnings = _merge_warnings(plan.warnings)

    project_id = uuid4().hex
    _emit(emitter, stage="saving", message="正在保存项目与提示词")
    store.save_project(
        project_id=project_id,
        brief=req.brief,
        plan=plan,
        reference_id=req.reference_id,
    )
    project = store.get_project(project_id)
    if project is None:
        raise RuntimeError("项目保存后无法读回，请检查数据库。")
    _emit(
        emitter,
        stage="done",
        message="方案已就绪",
        project_id=project_id,
        route=plan.route,
        shots=len(plan.shots),
    )
    return PlanOutcome(
        project=project, usage=usage.as_dict(), decision=decision
    )

# ---------------------------------------------------------------------------
# Video: propose four directions, then keep revising the chosen one
# ---------------------------------------------------------------------------


def propose_concepts(req: ConceptRequest) -> tuple[list[VideoConcept], dict[str, int]]:
    """Four different single-take directions for one H3 clip."""

    client = DeepSeekClient()
    system, user = build_concept_messages(req)
    payload, usage = client.complete_json(
        system=system,
        user=user,
        temperature=0.9,
        max_tokens=6000,
    )
    return parse_concepts(payload, req), usage.as_dict()


def create_video_project(req: VideoProjectRequest) -> ProjectResponse:
    """Persist the direction the user picked (or wrote themselves)."""

    plan = build_video_plan(
        brief=req.brief,
        concept=req.concept,
        duration=int(req.duration),
        aspect=req.aspect,
    )
    project_id = uuid4().hex
    store.save_project(
        project_id=project_id,
        brief=req.brief,
        plan=plan,
        reference_id=None,
    )
    project = store.get_project(project_id)
    if project is None:
        raise RuntimeError("项目保存后无法读回，请检查数据库。")
    return project


def revise_video(project: ProjectRecord, feedback: str) -> Plan:
    """Apply a follow-up note to a video prompt without changing its shape."""

    if project.plan.kind != "video":
        raise PlanInputError("这个项目不是视频项目，追加要求只对视频生效。")
    client = DeepSeekClient()
    system, user = build_video_revise_messages(project.plan, feedback)
    payload, _usage = client.complete_json(
        system=system,
        user=user,
        temperature=0.55,
        max_tokens=3000,
    )
    return parse_video_revision(payload, project.plan)

def draft_concept(
    req: CustomConceptRequest,
) -> tuple[VideoConcept, dict[str, int]]:
    """Turn the user's own idea into one renderable single-take prompt."""

    client = DeepSeekClient()
    system, user = build_custom_concept_messages(req)
    payload, usage = client.complete_json(
        system=system,
        user=user,
        temperature=0.7,
        max_tokens=3000,
    )
    return parse_custom_concept(payload, req), usage.as_dict()
