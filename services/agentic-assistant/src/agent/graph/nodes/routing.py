"""Conditional edges: every branch decision lives here, not in workflow.py.

Return the exact key from the mapping passed to `add_conditional_edges`.
"""

from __future__ import annotations

from agent.graph.state import AgentState


def route_after_grade(state: AgentState) -> str:
    if state["needs_rewrite"]:
        return "rewrite"
    return "generate"
