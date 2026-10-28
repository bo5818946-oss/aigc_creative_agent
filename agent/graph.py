"""LangGraph workflow assembly."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent.nodes import (
    finalize_result,
    generate_prompts,
    make_analyze_requirements_node,
    make_generate_storyboard_node,
    make_revise_output_node,
    make_write_director_prompt_node,
    plan_workflow,
    validate_output,
)
from agent.routing import (
    route_after_analysis,
    route_after_prompts,
    route_after_revision,
    route_after_storyboard,
    route_after_validation,
)
from agent.state import AgentState
from services.llm_service import LLMService


def build_workflow(llm_service: LLMService | None = None):
    builder = StateGraph(AgentState)

    builder.add_node(
        "analyze_requirements",
        make_analyze_requirements_node(llm_service),
    )
    builder.add_node("plan_workflow", plan_workflow)
    builder.add_node(
        "generate_storyboard",
        make_generate_storyboard_node(llm_service),
    )
    builder.add_node("generate_prompts", generate_prompts)
    builder.add_node("validate_output", validate_output)
    builder.add_node(
        "write_director_prompt",
        make_write_director_prompt_node(llm_service),
    )
    builder.add_node(
        "revise_output",
        make_revise_output_node(llm_service),
    )
    builder.add_node("finalize_result", finalize_result)

    builder.add_edge(START, "analyze_requirements")
    builder.add_conditional_edges(
        "analyze_requirements",
        route_after_analysis,
        {
            "plan": "plan_workflow",
            "finalize": "finalize_result",
        },
    )
    builder.add_edge("plan_workflow", "generate_storyboard")
    builder.add_conditional_edges(
        "generate_storyboard",
        route_after_storyboard,
        {
            "generate_prompts": "generate_prompts",
            "finalize": "finalize_result",
        },
    )
    builder.add_conditional_edges(
        "generate_prompts",
        route_after_prompts,
        {
            "validate": "validate_output",
            "finalize": "finalize_result",
        },
    )
    builder.add_conditional_edges(
        "validate_output",
        route_after_validation,
        {
            "write_director_prompt": "write_director_prompt",
            "finalize": "finalize_result",
            "revise": "revise_output",
        },
    )
    builder.add_edge("write_director_prompt", "finalize_result")
    builder.add_conditional_edges(
        "revise_output",
        route_after_revision,
        {
            "generate_prompts": "generate_prompts",
            "finalize": "finalize_result",
        },
    )
    builder.add_edge("finalize_result", END)

    return builder.compile()
