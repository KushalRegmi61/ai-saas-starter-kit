"""Deterministic response for requests outside the assistant's scope."""

from __future__ import annotations

from agent.graph.state import AgentState

OUT_OF_SCOPE_RESPONSE = (
    "I'm built to help with project progress, status, features, blockers, "
    "updates, decisions, and authorized enterprise knowledge. I couldn't "
    "answer that from the information I can access. Try asking about a "
    "project or its documented work."
)


def out_of_scope(state: AgentState) -> dict:
    """Return a safe, stable rejection without another model call."""
    return {
        **state,
        "answer": OUT_OF_SCOPE_RESPONSE,
        "sources": [],
        "results": [],
        "grounded": True,
        "workflow_steps": [
            *state.get("workflow_steps", []),
            "out_of_scope: deterministic rejection",
        ],
    }
