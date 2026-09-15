"""Node registry: one file per node, wired here.

Adding a node:
  1. Create nodes/<name>.py with async def <name>(state) -> dict
  2. Export it below
  3. Register it in workflow.py (add_node + edges)
  4. Branch decisions go in nodes/routing.py

Shared logic lives in nodes/common.py (formatters, scoring, sources).
LLM calls live in agent/llm.py (stream_response, invoke_response, invoke_with_tools).
"""

from agent.graph.nodes.agent import agent_node
from agent.graph.nodes.chitchat import chitchat_respond
from agent.graph.nodes.classify import classify_intent
from agent.graph.nodes.common import _content_text, sources_from_state
from agent.graph.nodes.generate_final import generate_final
from agent.graph.nodes.grounding import check_grounding
from agent.graph.nodes.out_of_scope import out_of_scope
from agent.graph.nodes.routing import route_after_agent, route_after_classify

__all__ = [
    "_content_text",
    "agent_node",
    "check_grounding",
    "chitchat_respond",
    "classify_intent",
    "generate_final",
    "out_of_scope",
    "route_after_agent",
    "route_after_classify",
    "sources_from_state",
]
