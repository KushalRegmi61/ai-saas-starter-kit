"""Grounding node: verify the answer cites retrieved sources (or abstains)."""

from __future__ import annotations

from agent.graph.state import AgentState


def check_grounding(state: AgentState) -> AgentState:
    answer = state["answer"].lower()
    source_names = {
        str(source.get("source", "")).lower() for source in state["sources"] if source.get("source")
    }
    cites_source = any(source_name in answer for source_name in source_names)
    says_unknown = "do not know" in answer or "don't know" in answer
    grounded = bool(state["results"]) and (cites_source or says_unknown)
    return {
        **state,
        "grounded": grounded,
        "workflow_steps": [
            *state["workflow_steps"],
            f"grounding_check grounded={grounded}",
        ],
    }
