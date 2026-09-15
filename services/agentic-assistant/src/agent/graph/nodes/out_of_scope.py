"""Deterministic response for requests outside the assistant's scope."""

from __future__ import annotations

from agent.graph.state import AgentState
from agent.llm import invoke_recovery_response

OUT_OF_SCOPE_RESPONSE = (
    "I'm built to help with project progress, status, features, blockers, "
    "updates, decisions, and authorized enterprise knowledge. I couldn't "
    "answer that from the information I can access. Try asking about a "
    "project or its documented work."
)


async def out_of_scope(state: AgentState, config=None) -> dict:
    """Generate a concise, low-cost response for unsupported requests."""
    answer = await invoke_recovery_response(
        question=state["question"],
        context="The request is outside the assistant's supported project and enterprise-knowledge scope.",
        config=config,
    )
    return {
        **state,
        "answer": answer,
        "sources": [],
        "results": [],
        "grounded": True,
        "workflow_steps": [
            *state.get("workflow_steps", []),
            "out_of_scope: recovery response",
        ],
    }
