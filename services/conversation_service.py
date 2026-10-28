"""Conversation engine: the model decides, Python validates and persists.

There is deliberately **no fallback question policy**. Every question, option
and recommendation in the guided studio comes from ``AgentDirector``. If the
decision layer is missing or the call fails, the engine raises
``AgentUnavailableError`` and the UI says so instead of assembling a
plausible-looking plan from hard-coded option tables.

The deterministic code that remains is not creative judgement: it validates the
model's answers, expands option choices into brief values, composes the proposal
preview from values the user already confirmed, and persists everything.
"""

from __future__ import annotations

import math
import re
from typing import Any

from schemas.conversation import (
    FIELD_LABELS,
    SOURCE_LABELS,
    ClarifyingQuestion,
    ConversationStage,
    ConversationState,
    ConversationStatus,
    CreativeBrief,
    DecisionRow,
    FieldSource,
    Proposal,
    QuestionOption,
    VehicleAsset,
    utc_now,
)
from schemas.project import CreativeRequirement
from services.agent_director import (
    AgentDirector,
    allowed_fields,
    coerce_field_value,
    decision_confidence,
    is_automotive_brief,
)
from services.clip_plan import (
    ClipPlan,
    DurationNotPlannable,
    VideoCapability,
    capability_for,
    check_duration,
    plan_for,
)

# Fields that must be confirmed before a proposal can be built. The model asks
# until these are answered; the engine refuses to invent them.
_REQUIRED_COMMON = (
    "creative_direction",
    "scenes",
    "duration_seconds",
    "camera_language",
)

UNAVAILABLE_MESSAGE = (
    "决策层不可用：没有可调用的 DeepSeek。"
    "这个对话框不会用写死的选项表假装在工作——"
    "请先在 .env 配置 DEEPSEEK_API_KEY（或设置 AIGC_GUIDE_MODE=llm）后重试。"
)


class AgentUnavailableError(RuntimeError):
    """No decision layer is available, or the model call failed."""


class AgentContractError(RuntimeError):
    """The model answered, but the answer could not be applied safely."""


def _unique(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _find_option(
    options: list[QuestionOption],
    option_id: str,
) -> QuestionOption | None:
    for option in options:
        if option.option_id == option_id:
            return option
    return None


class ConversationEngine:
    """Stateful guide backed by a model decision layer."""

    def __init__(
        self,
        repository: Any | None = None,
        director: Any | None = None,
        capability: VideoCapability | None = None,
    ):
        self.repository = repository
        self.director = director
        self._capability = capability
        self.last_director_error = ""
        self.last_policy_source = "llm"
        #: Set when the user names a duration the generator cannot produce.
        #: The value is not applied; the notice is shown instead of silently
        #: rounding to a number that looks agreed but was never chosen.
        self.last_duration_notice = ""

    @property
    def capability(self) -> VideoCapability:
        if self._capability is None:
            self._capability = capability_for()
        return self._capability

    def _plan_or_notice(self, value: Any, *, min_clips: int = 1) -> ClipPlan | None:
        """Validate a duration against the generator and remember the refusal."""

        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None
        check = check_duration(seconds, self.capability, min_clips=min_clips)
        if check.ok:
            return check.plan
        self.last_duration_notice = check.message
        return None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start(
        self,
        idea: str,
        *,
        session_id: str | None = None,
        reference_files: list[str] | None = None,
    ) -> ConversationState:
        idea = (idea or "").strip()
        if not idea:
            raise ValueError("请先描述你想创作的内容。")

        state = ConversationState(
            original_idea=idea,
            session_id=session_id or ConversationState().session_id,
            reference_files=list(reference_files or []),
        )
        if state.reference_files:
            state.add_message(
                "assistant",
                "已记录参考文件："
                + "、".join(state.reference_files)
                + "。当前 DeepSeek 文本模型不做图片识别；"
                "请确认描述中写明了需要锁定的外观特征。",
            )
        state.add_message("user", idea)
        state.turn_count = 1

        decision = self._decide(state, idea)
        return self._finish(state, decision, source_text=idea)

    def handle(self, state: ConversationState, text: str) -> ConversationState:
        text = (text or "").strip()
        if not text:
            raise ValueError("请输入你的想法或选择。")

        state.add_message("user", text)
        state.turn_count += 1

        if state.status == ConversationStatus.RUNNING:
            state.add_message(
                "assistant",
                "当前任务正在生成中。我会在完成后把结果和修改入口一起给你。",
            )
            self._save(state)
            return state

        decision = self._decide(state, text)
        return self._finish(state, decision, source_text=text)

    def choose(
        self,
        state: ConversationState,
        option_id: str,
        *,
        selected_ids: list[str] | None = None,
    ) -> ConversationState:
        question = state.pending_question
        if question is None:
            raise ValueError("当前没有等待回答的问题。")

        # The question the user actually saw is the only source of options.
        available = list(question.options)

        if option_id == "__agent__":
            chosen = self._agent_choice(state, question.field)
            self._set_choice(state, question.field, chosen)
        elif question.multi_select:
            ids = selected_ids or [option_id]
            by_id = {option.option_id: option for option in available}
            values = [by_id[item].label for item in ids if item in by_id]
            if not values:
                raise ValueError("请至少选择一个有效选项。")
            self._set_choice(state, question.field, values)
        else:
            option = _find_option(available, option_id)
            if option is None:
                raise ValueError("选项不存在或已经失效，请重新选择。")
            self._set_choice(
                state,
                question.field,
                self._option_value(question.field, option),
            )

        chosen_text = state.brief.field(question.field).display_value()
        # A click is a user decision: record it and let the model decide what to
        # ask next, exactly like a typed answer.
        state.add_message("user", f"我选：{chosen_text}")
        # ``pending_question`` stays set until the model answers: if a second
        # click arrives while this call is still in flight, the UI must still
        # see a question to show instead of an empty workbench.
        decision = self._decide(
            state,
            f"我选择：{chosen_text}",
        )
        return self._finish(state, decision, source_text=f"我选择：{chosen_text}")

    def confirm(
        self,
        state: ConversationState,
        *,
        announce: bool = True,
    ) -> ConversationState:
        if state.proposal is None:
            raise ValueError("当前还没有可确认的方案。")
        state.status = ConversationStatus.READY
        state.stage = ConversationStage.READY
        state.generation_requested = True
        if announce:
            state.add_message(
                "assistant",
                "方案已确认。现在开始生成结构化分镜、图片/视频提示词，"
                "并运行四类确定性校验。",
            )
        self._save(state)
        return state

    def apply_asset(
        self,
        state: ConversationState,
        asset: VehicleAsset,
    ) -> ConversationState:
        description = asset.description or asset.name
        is_vehicle_asset = asset.kind == "vehicle" or bool(
            asset.attributes.get("vehicle_type")
        )
        if is_vehicle_asset:
            state.brief.set("vehicle_description", description, FieldSource.ASSET)
        else:
            state.brief.set("subject", description, FieldSource.ASSET)
        if asset.attributes.get("vehicle_type"):
            state.brief.set(
                "vehicle_type",
                asset.attributes["vehicle_type"],
                FieldSource.ASSET,
            )
        if asset.attributes.get("vehicle_design"):
            state.brief.set(
                "vehicle_design",
                asset.attributes["vehicle_design"],
                FieldSource.ASSET,
            )
        if asset.rules:
            state.brief.set("constraints", list(asset.rules), FieldSource.ASSET)
        state.brief.set(
            "vehicle_reference",
            f"创作资产：{asset.name}",
            FieldSource.ASSET,
        )
        state.proposal = None
        state.pending_question = None
        state.status = ConversationStatus.GUIDING
        state.add_message(
            "assistant",
            f"已载入创作资产“{asset.name}”。后续镜头会锁定这套设定，"
            "不会要求你重新描述外观。",
        )
        state.add_message("user", f"使用创作资产：{asset.name}")

        decision = self._decide(state, f"使用创作资产：{asset.name}")
        return self._finish(state, decision, source_text=f"使用创作资产：{asset.name}")

    def save(self, state: ConversationState) -> None:
        self._save(state)

    # ------------------------------------------------------------------
    # decision plumbing
    # ------------------------------------------------------------------
    def _require_director(self) -> None:
        if self.director is None:
            raise AgentUnavailableError(UNAVAILABLE_MESSAGE)

    def _decide(
        self,
        state: ConversationState,
        text: str,
        *,
        force_action: str | None = None,
    ):
        self._require_director()
        pending = state.pending_question
        tail = [
            (message.role, message.content)
            for message in state.messages[-8:]
            if message.kind != "question"
        ]
        try:
            decision = self.director.decide(
                idea=state.original_idea,
                brief_snapshot=state.brief.snapshot(),
                pending_field=pending.field if pending else "",
                pending_prompt=pending.prompt if pending else "",
                user_text=text,
                tail=tail,
                force_action=force_action,
            )
        except AgentUnavailableError:
            raise
        except Exception as exc:  # network, timeout, invalid JSON, bad contract
            self.last_director_error = f"{type(exc).__name__}: {exc}"
            raise AgentUnavailableError(
                f"决策层调用失败：{type(exc).__name__}: {exc}"
            ) from exc

        self.last_director_error = ""
        return decision

    def _finish(
        self,
        state: ConversationState,
        decision,
        *,
        source_text: str = "",
    ) -> ConversationState:
        applied = self._apply_understood(state, decision)
        if self.last_duration_notice:
            state.add_message(
                "assistant",
                self.last_duration_notice,
                kind="notice",
            )
            self.last_duration_notice = ""
        state.last_change = (
            "、".join(FIELD_LABELS.get(key, key) for key in applied)
            if applied
            else decision_confidence(decision)
        )

        model_name = str(getattr(self.director, "model", ""))
        action_label = decision_confidence(decision)

        if decision.action == "confirm":
            if state.proposal is None:
                self._build_proposal(state, announce=False)
            state.status = ConversationStatus.READY
            state.stage = ConversationStage.READY
            state.generation_requested = True
            self._add_reply(state, decision, model_name, action_label, applied)
            return self._done(state)

        if decision.action in {"propose", "revise"}:
            state.pending_question = None
            if not self._critical_complete(state):
                # The model thought it had enough. Ask it once more, explicitly,
                # for the next question instead of inventing the missing values.
                retry = self._decide(state, source_text, force_action="ask")
                if not self._ask_with(state, retry):
                    raise AgentContractError(
                        "决策层认为信息已足够，但关键决策仍缺失，且没有给出可用的追问。"
                    )
                return self._done(state)
            self._build_proposal(state, announce=False)
            if decision.revision_summary:
                state.last_change = decision.revision_summary
            self._add_reply(state, decision, model_name, action_label, applied)
            return self._done(state)

        # action == "ask"
        if decision.reply:
            state.add_message(
                "assistant",
                decision.reply,
                kind="director",
                payload={
                    "action": decision.action,
                    "action_label": action_label,
                    "model": model_name,
                    "understood": applied,
                },
            )
        if not self._ask_with(state, decision):
            retry = self._decide(state, source_text, force_action="ask")
            if not self._ask_with(state, retry):
                raise AgentContractError(
                    "决策层没有给出可用的下一个问题（缺少选项或字段无法归位）。"
                )
        return self._done(state)

    def _done(self, state: ConversationState) -> ConversationState:
        self._remember_assistant_message(state)
        self._save(state)
        return state

    def _add_reply(
        self,
        state: ConversationState,
        decision,
        model_name: str,
        action_label: str,
        applied: list[str],
    ) -> None:
        if not decision.reply:
            return
        state.add_message(
            "assistant",
            decision.reply,
            kind="director",
            payload={
                "reasoning": decision.reasoning,
                "action": decision.action,
                "action_label": action_label,
                "model": model_name,
                "understood": applied,
                "revision_summary": decision.revision_summary,
            },
        )

    def _ask_with(self, state: ConversationState, decision) -> bool:
        question = AgentDirector.to_question(decision)
        if question is None or not question.options:
            return False
        if question.field == "duration_seconds":
            question = self._constrain_duration_question(
                question,
                min_clips=len(state.brief.get("scenes") or []) or 1,
            )
            if question is None or not question.options:
                return False
        state.proposal = None
        state.pending_question = question
        state.stage = question.stage
        state.status = ConversationStatus.GUIDING
        state.question_count += 1
        state.add_message(
            "assistant",
            question.prompt,
            kind="question",
            payload=question.model_dump(mode="json"),
        )
        return True

    def _constrain_duration_question(
        self,
        question: ClarifyingQuestion,
        *,
        min_clips: int = 1,
    ) -> ClarifyingQuestion | None:
        """Keep only durations this generator can actually produce.

        Offering "90 秒" on a 5-second backend is not a choice, it is a
        guaranteed failure later. Options are validated against the capability
        and relabelled with the clip arithmetic so the user sees the real cost.
        """

        kept: list[QuestionOption] = []
        for option in question.options:
            try:
                seconds = float(self._option_value(question.field, option))
            except (TypeError, ValueError):
                continue
            check = check_duration(
                seconds,
                self.capability,
                min_clips=min_clips,
            )
            if not check.ok or check.plan is None:
                continue
            if "条" not in option.label:
                option.label = (
                    f"{option.label}（{check.plan.clip_count} 条 × "
                    f"{check.plan.clip_seconds:g} 秒）"
                )
            kept.append(option)
        if not kept:
            return None
        question.options = kept
        question.helper = f"生成能力：{self.capability.quote()}"
        if not any(
            item.option_id == question.recommended_option_id for item in kept
        ):
            question.recommended_option_id = kept[0].option_id
        return question

    # ------------------------------------------------------------------
    # applying the model's answers
    # ------------------------------------------------------------------
    def _apply_understood(self, state: ConversationState, decision) -> list[str]:
        applied: list[str] = []
        # Vehicle fields only exist for automotive projects. A model that
        # mentions "车" in a campus film must not be able to write them into
        # the brief.
        automotive = is_automotive_brief(
            state.original_idea,
            str(state.brief.get("content_type") or ""),
        )
        allowed = set(allowed_fields(automotive))
        for field, raw_value in decision.understood.items():
            if field not in allowed:
                continue
            value = coerce_field_value(field, raw_value)
            if value is None or value == "" or value == []:
                continue
            if field == "duration_seconds":
                plan = self._plan_or_notice(
                    value,
                    min_clips=len(state.brief.get("scenes") or []) or 1,
                )
                if plan is None:
                    continue
                value = plan.total_seconds
            existing = state.brief.field(field)
            # Re-stating the value the user just confirmed must not downgrade its
            # provenance from "user selected" back to "user said".
            if existing.has_value() and existing.value == value:
                continue
            if field == "constraints":
                current = existing.value or []
                if isinstance(current, str):
                    current = [current]
                value = _unique(list(current) + list(value))
            state.brief.set(field, value, FieldSource.USER)
            applied.append(field)
        state.touch()
        return applied

    def _set_choice(self, state: ConversationState, field: str, value: Any) -> None:
        if field == "scenes" and not isinstance(value, list):
            value = [value]
        if field == "duration_seconds":
            plan = self._plan_or_notice(
                value,
                min_clips=len(state.brief.get("scenes") or []) or 1,
            )
            if plan is None:
                state.add_message(
                    "assistant",
                    self.last_duration_notice,
                    kind="notice",
                )
                self.last_duration_notice = ""
                return
            value = plan.total_seconds
        state.brief.set(field, value, FieldSource.USER_SELECTED)
        state.touch()

    def _option_value(self, field: str, option: QuestionOption) -> Any:
        if field == "duration_seconds":
            # The option id is an opaque ``duration_seconds_2``; the human label
            # carries the number.
            match = re.search(r"(\d+(?:\.\d+)?)", option.label)
            if match:
                return float(match.group(1))
            return option.label
        if field in {"camera_language", "transition_requirements"}:
            return option.description or option.label
        return option.label

    def _agent_choice(self, state: ConversationState, field: str) -> Any:
        """Resolve "let the agent decide" for the option the user is looking at."""

        question = state.pending_question
        if question is not None and question.options:
            recommended = next(
                (option for option in question.options if option.recommended),
                question.options[0],
            )
            return self._option_value(field, recommended)
        raise ValueError("这个问题没有可用的推荐项。")

    def _critical_complete(self, state: ConversationState) -> bool:
        content_type = str(state.brief.get("content_type") or "")
        is_car = "汽车" in content_type or state.brief.has("vehicle_type")
        required = list(_REQUIRED_COMMON)
        required.append("vehicle_type" if is_car else "subject")
        return all(state.brief.has(key) for key in required)

    # ------------------------------------------------------------------
    # requirement
    # ------------------------------------------------------------------
    def build_requirement(self, state: ConversationState) -> CreativeRequirement:
        if not self._critical_complete(state):
            missing = [
                FIELD_LABELS.get(key, key)
                for key in (*_REQUIRED_COMMON, "subject")
                if not state.brief.has(key)
            ]
            raise AgentContractError(
                "还有关键决策未确定：" + "、".join(_unique(missing))
            )

        proposal = state.proposal or self._build_proposal(state, announce=False)
        brief = state.brief
        content_type = str(brief.get("content_type") or "商业广告")
        is_car = "汽车" in content_type or brief.has("vehicle_type")

        if is_car:
            vehicle_type = str(brief.get("vehicle_type") or "汽车")
            design = str(brief.get("vehicle_design") or "")
            description = str(brief.get("vehicle_description") or "").strip()
            subject = description or f"一辆{vehicle_type}"
            if design and design not in subject:
                subject = f"{subject}，{design}"
            if brief.has("vehicle_reference"):
                subject = f"{subject}（参考：{brief.get('vehicle_reference')}）"
            consistency = [
                f"全片主体锁定：{subject}；车身颜色、轮廓、灯组、轮毂和空气动力学套件保持一致。",
                "车辆前进方向与屏幕方向保持一致，禁止镜头间反向行驶、车头车尾颠倒或不合理倒车。",
            ]
        else:
            subject = str(brief.get("subject") or "创作主体")
            consistency = [
                f"全片主体锁定：{subject}；外观、服装、材质和关键识别特征保持一致。",
                "不添加用户未要求的品牌 Logo、字幕或水印。",
            ]

        user_constraints = brief.get("constraints") or []
        if isinstance(user_constraints, str):
            user_constraints = [user_constraints]
        for item in user_constraints:
            if item and item not in consistency:
                consistency.append(str(item))

        scenes = [str(item) for item in (proposal.scene_order or [])]
        if not scenes:
            raise AgentContractError("场景决策为空，无法生成分镜。")

        duration = float(brief.get("duration_seconds") or 0)
        if duration <= 0:
            raise AgentContractError("时长决策无效，无法生成分镜。")

        try:
            plan = plan_for(duration, self.capability, min_clips=len(scenes))
        except DurationNotPlannable as exc:
            raise AgentContractError(str(exc)) from exc

        pending: list[str] = []
        for key, field in brief.fields.items():
            if field.source == FieldSource.AGENT_INFERRED:
                pending.append(
                    f"{FIELD_LABELS.get(key, key)}采用 Agent 推断值“{field.display_value()}”，"
                    "用户可在方案确认前修改。"
                )

        kwargs: dict[str, Any] = {
            "project_name": proposal.title[:100],
            "content_type": content_type,
            "subject": subject[:300],
            "duration_seconds": duration,
            "clip_seconds": plan.clip_seconds,
            "clip_count": plan.clip_count,
            "scene_requirements": _unique(scenes),
            "consistency_constraints": consistency,
            "output_formats": ["markdown", "json"],
            "notes": (
                f"原始创意：{state.original_idea}\n"
                f"广告创意：{brief.get('creative_direction') or '—'}\n"
                f"声音设计：{brief.get('sound_design') or '未指定'}\n"
                f"生成单元：{plan.brief_line()}\n"
                f"Agent 方案：{proposal.one_liner}\n"
                "决策来源：" + "；".join(
                    f"{row.label}={row.source}" for row in proposal.decisions
                )
            )[:1000],
            "pending_confirmations": _unique(pending)[:20],
        }
        optional = {
            "target_audience": brief.get("target_audience"),
            "aspect_ratio": brief.get("aspect_ratio"),
            "visual_style": brief.get("visual_style"),
            "camera_language": brief.get("camera_language"),
            "transition_requirements": brief.get("transition_requirements"),
        }
        for key, value in optional.items():
            if value:
                kwargs[key] = value
        return CreativeRequirement(**kwargs)

    # ------------------------------------------------------------------
    # proposal
    # ------------------------------------------------------------------
    def _build_proposal(
        self,
        state: ConversationState,
        *,
        announce: bool = True,
    ) -> Proposal:
        if not self._critical_complete(state):
            raise AgentContractError("关键决策未齐，不能生成方案。")

        brief = state.brief
        content_type = str(brief.get("content_type") or "")
        is_car = "汽车" in content_type or brief.has("vehicle_type")
        subject = str(
            brief.get("vehicle_description")
            or brief.get("subject")
            or brief.get("vehicle_type")
            or "核心主体"
        )
        direction = str(brief.get("creative_direction") or "")
        scenes = [str(item) for item in (brief.get("scenes") or [])]
        duration = float(brief.get("duration_seconds") or 0)
        if not scenes:
            raise AgentContractError("场景决策为空，不能生成方案。")
        if duration <= 0:
            raise AgentContractError("时长决策无效，不能生成方案。")

        try:
            plan = plan_for(duration, self.capability, min_clips=len(scenes))
        except DurationNotPlannable as exc:
            raise AgentContractError(str(exc)) from exc

        estimated_shots = plan.clip_count
        camera_text = str(brief.get("camera_language") or "")
        transition_text = str(brief.get("transition_requirements") or "")
        sound_text = str(brief.get("sound_design") or "")

        kind = "商业广告" if "广告" in content_type or is_car else "短片"
        title = f"{subject} · {duration:g} 秒{kind}"
        ending = (
            "最后以完整车身英雄镜头收束。"
            if is_car
            else "最后用一个可记住的画面收束，不用信息堆叠结尾。"
        )
        lead = (
            f"{len(scenes)} 个画面空间、{plan.clip_count} 条片段"
            f"（每条 {plan.clip_seconds:g} 秒）拼成 {duration:g} 秒"
        )
        one_liner = f"{lead}：{direction}。{ending}" if direction else f"{lead}。{ending}"
        if len(one_liner) > 260:
            one_liner = one_liner[:259] + "…"

        rationale = (
            f"决策来自对话确认：{len(scenes)} 个画面空间按已确认顺序推进；"
            f"镜头语言以“{camera_text[:60] or '未指定'}”为准；"
            "主体一致性由资产锁定约束保证，不依赖模型即兴发挥。"
        )

        proposal = Proposal(
            title=title,
            one_liner=one_liner,
            concept_summary=direction,
            vehicle_summary=self._asset_summary(brief),
            creative_rationale=rationale,
            scene_order=scenes,
            shot_strategy=self._shot_strategy(scenes, plan, is_car=is_car),
            camera_plan=self._camera_plan(camera_text),
            transition_plan=self._transition_plan(transition_text, len(scenes)),
            sound_plan=sound_text or "未指定",
            risks=self._risks(
                plan,
                len(scenes),
                str(brief.get("vehicle_design") or ""),
                is_car=is_car,
            ),
            decisions=self._decision_rows(state),
            total_duration=duration,
            clip_seconds=plan.clip_seconds,
            clip_count=plan.clip_count,
            estimated_shots=estimated_shots,
            output_summary=[
                "结构化分镜（镜头时长、景别、机位、运镜、屏幕方向）",
                "逐镜头图片提示词、视频提示词与负向提示词",
                "整片导演提示词、连续性圣经与全片负向约束",
                "四类确定性校验报告；失败会进入有限修正",
                f"可直接投喂本地生成后端的生成清单（{plan.clip_count} 条 × "
                f"{plan.clip_seconds:g} 秒）",
            ],
        )
        state.proposal = proposal
        state.stage = ConversationStage.PROPOSAL
        state.status = ConversationStatus.READY
        state.pending_question = None
        if announce:
            state.add_message(
                "assistant",
                f"我整理了一版可执行方案：{one_liner} 你可以确认，也可以继续改任意一项。",
                kind="proposal",
                payload=proposal.model_dump(mode="json"),
            )
        state.touch()
        return proposal

    @staticmethod
    def _shot_strategy(
        scenes: list[str],
        plan: ClipPlan,
        *,
        is_car: bool,
    ) -> list[str]:
        beats: list[str] = []
        base, extra = divmod(plan.clip_count, max(1, len(scenes)))
        cursor = 0.0
        for index, scene in enumerate(scenes):
            count = base + (1 if index < extra else 0)
            if count == 0:
                continue
            start = cursor
            end = cursor + count * plan.clip_seconds
            cursor = end
            detail = (
                "至少一条承载环境、车辆动作和方向。"
                if is_car
                else "至少一条承载空间、主体动作或产品信息。"
            )
            beats.append(
                f"{start:g}–{end:g} 秒：{scene}，{count} 条 × "
                f"{plan.clip_seconds:g} 秒，{detail}"
            )
        ending = (
            "最后一条必须是完整车身英雄展示，不要用局部细节收尾。"
            if is_car
            else "最后一条要留下清楚的记忆点，不要用信息堆叠收尾。"
        )
        beats.append(
            f"共 {plan.clip_count} 条 × {plan.clip_seconds:g} 秒 = "
            f"{plan.generated_seconds:g} 秒素材，按 {plan.total_seconds:g} 秒成片剪辑；{ending}"
        )
        return beats

    @staticmethod
    def _split_bullets(text: str) -> list[str]:
        parts = [
            item.strip(" 。．")
            for item in text.replace("；", "、").replace(";", "、").split("、")
            if item.strip(" 。．")
        ]
        return _unique(parts)

    def _camera_plan(self, camera_text: str) -> list[str]:
        bullets = self._split_bullets(camera_text)
        if not bullets:
            return ["镜头语言尚未确定，生成前需要补齐。"]
        return [f"总体：{bullets[0]}"] + [f"分项：{item}" for item in bullets[1:]]

    def _transition_plan(self, transition_text: str, scene_count: int) -> list[str]:
        bullets = self._split_bullets(transition_text)
        if scene_count <= 1:
            return ["单场景内以镜头内部运动为主，不需要额外场景转场。"]
        if not bullets:
            return ["转场方式尚未确定，生成前需要补齐。"]
        return bullets

    @staticmethod
    def _asset_summary(brief: CreativeBrief) -> str:
        if not brief.has("vehicle_type"):
            return f"主体：{brief.get('subject') or '待确定'}"
        parts = [str(brief.get("vehicle_type") or "未指定车型")]
        for key in ("vehicle_design", "vehicle_description"):
            value = brief.get(key)
            if value:
                parts.append(str(value))
        if brief.has("vehicle_reference"):
            parts.append(f"参考：{brief.get('vehicle_reference')}")
        return "；".join(parts)

    @staticmethod
    def _risks(
        plan: ClipPlan,
        scene_count: int,
        design: str,
        *,
        is_car: bool,
    ) -> list[str]:
        risks: list[str] = []
        if scene_count and plan.total_seconds / scene_count < 4:
            risks.append(
                f"场景密度偏高：{scene_count} 个场景只有 "
                f"{plan.total_seconds:g} 秒，每个场景平均不足 4 秒，"
                "建议减少场景或延长时长。"
            )
        if not plan.exact:
            risks.append(
                f"时长不是整条片段：{plan.clip_count} 条 × "
                f"{plan.clip_seconds:g} 秒会生成 {plan.generated_seconds:g} 秒素材，"
                f"需要剪掉 {plan.overrun_seconds:g} 秒。"
            )
        if plan.clip_count > 8:
            risks.append(
                f"需要 {plan.clip_count} 次独立生成，主体一致性靠资产锁定，"
                "建议先做 1–2 条试片再批量。"
            )
        if is_car:
            if "原创" in design or "概念" in design:
                risks.append(
                    "原创概念车没有真实参考，跨镜头外观漂移风险更高，必须依赖资产锁定。"
                )
            risks.append(
                "AI 视频模型对车辆方向、轮毂和灯组的一致性有限，"
                "建议分段生成并逐段验收。"
            )
        else:
            risks.append(
                "AI 视频模型对主体身份、材质和空间关系的一致性有限，"
                "建议固定主体描述并逐镜头验收。"
            )
        return risks

    @staticmethod
    def _decision_rows(state: ConversationState) -> list[DecisionRow]:
        rows: list[DecisionRow] = []
        # Iterate the field registry so the rows keep a stable, meaningful order.
        for key, label in FIELD_LABELS.items():
            field = state.brief.field(key)
            if not field.has_value():
                continue
            rows.append(
                DecisionRow(
                    label=label,
                    value=field.display_value(),
                    source=SOURCE_LABELS.get(field.source, field.source.value),
                )
            )
        return rows

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------
    def _remember_assistant_message(self, state: ConversationState) -> None:
        if state.pending_question is not None:
            return
        if state.proposal is not None:
            return
        if state.last_assistant_message is not None:
            return
        state.add_message("assistant", "我在。告诉我你想改哪一项，或者让我直接决定。")

    def _save(self, state: ConversationState) -> None:
        state.touch()
        if self.repository is not None:
            self.repository.save_conversation(state.model_dump(mode="json"))


def brief_from_state(state: ConversationState) -> dict[str, Any]:
    """Small helper used by UI and tests to expose a readable snapshot."""

    return {
        "stage": state.stage.value,
        "status": state.status.value,
        "snapshot": state.brief.snapshot(),
        "question": state.pending_question.model_dump(mode="json")
        if state.pending_question
        else None,
        "proposal": state.proposal.model_dump(mode="json")
        if state.proposal
        else None,
    }


__all__ = [
    "AgentContractError",
    "AgentUnavailableError",
    "ConversationEngine",
    "UNAVAILABLE_MESSAGE",
    "brief_from_state",
]
