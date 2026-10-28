"""Conditional routing functions for the workflow.

The first MVP only needs to stop early when input validation or storyboard
preparation fails. The revision branch will be added in a later phase.
"""

from __future__ import annotations

from agent.state import AgentState


def route_after_analysis(state: AgentState) -> str:
    return "finalize" if state.get("errors") else "plan"


def route_after_storyboard(state: AgentState) -> str:
    return "finalize" if state.get("errors") else "generate_prompts"


def route_after_prompts(state: AgentState) -> str:
    return "finalize" if state.get("errors") else "validate"


def route_after_validation(state: AgentState) -> str:
    report = state.get("validation_report")
    if report is None:
        return "finalize"
    if report.get("passed"):
        return "write_director_prompt"

    revision_count = int(state.get("revision_count", 0))
    max_revisions = int(state.get("max_revisions", 2))
    if (
        revision_count < max_revisions
        and not state.get("revision_failed")
    ):
        return "revise"
    return "finalize"


def route_after_revision(state: AgentState) -> str:
    if state.get("revision_failed"):
        return "finalize"
    return "generate_prompts"
