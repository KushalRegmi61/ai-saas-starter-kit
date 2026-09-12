"""Grade node: score retrieved context, decide whether a rewrite is needed."""

from __future__ import annotations

from agent.graph.nodes.common import MIN_RELEVANCE_SCORE, _best_score
from agent.graph.state import AgentState


def grade_context(state: AgentState) -> AgentState:
    best_score = _best_score(state["results"])
    needs_rewrite = best_score < MIN_RELEVANCE_SCORE and state["attempts"] == 0
    return {
        **state,
        "needs_rewrite": needs_rewrite,
        "workflow_steps": [
            *state["workflow_steps"],
            f"graded retrieval best_score={best_score:.3f}",
        ],
    }
