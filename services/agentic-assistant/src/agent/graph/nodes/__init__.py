"""Node registry: one file per node, wired here.

Adding a node:
  1. Create `nodes/<name>.py` with `def <name>(state: AgentState) -> AgentState`.
  2. Export it below (keeps `agent.graph.nodes.<name>` importable for tests).
  3. Register it in `workflow.py` (`add_node` + edges). Branch decisions go
     in `nodes/routing.py` and are referenced by key in `add_conditional_edges`.
Shared logic (LLM factory, scoring, formatting) lives in `nodes/common.py` —
never duplicated across node files.
"""

from agent.graph.nodes.common import sources_from_state
from agent.graph.nodes.generate import generate_answer
from agent.graph.nodes.grade import grade_context
from agent.graph.nodes.grounding import check_grounding
from agent.graph.nodes.retrieve import retrieve_context
from agent.graph.nodes.rewrite import rewrite_query
from agent.graph.nodes.routing import route_after_grade

__all__ = [
    "check_grounding",
    "generate_answer",
    "grade_context",
    "retrieve_context",
    "rewrite_query",
    "route_after_grade",
    "sources_from_state",
]
