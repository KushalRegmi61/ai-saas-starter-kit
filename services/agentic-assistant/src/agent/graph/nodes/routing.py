"""Conditional edge routing functions.

Every branch decision lives here. workflow.py references these by name in
add_conditional_edges — no routing logic in the graph assembly itself.

Two routers:
  route_after_classify  → "chitchat" | "needs_tools" | "out_of_scope"
  route_after_agent     → "tools" | "force_project_search" | "force_global_search"
                         | "generate"   (dual budget enforcement)
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, ToolMessage

from agent.graph.state import AgentState

logger = logging.getLogger(__name__)

_PROJECT_TOOL_NAMES = frozenset(
    {
        "get_project_overview",
        "get_project_features",
        "get_project_blockers",
        "get_project_activity",
        "search_project_knowledge",
    }
)


def route_after_classify(state: AgentState) -> str:
    """Route based on intent classifier output.

    Returns:
        "chitchat"    → chitchat_respond node
        "needs_tools"  → agent node (ReAct loop)
        "out_of_scope" → deterministic rejection node
    """
    intent = state.get("intent", "needs_tools")
    if intent not in ("chitchat", "needs_tools", "out_of_scope"):
        logger.warning("route_after_classify: unknown intent %r — failing closed", intent)
        return "out_of_scope"
    logger.info("route: classify -> %s", intent)
    return intent


def route_after_agent(state: AgentState) -> str:
    """Route based on last AIMessage + dual budget check.

    Dual budget:
      - Iteration cap: tool_call_count >= MAX_ITERATIONS
      - Token cap:     loop_tokens_used >= MAX_LOOP_TOKENS

    Either cap forces routing to "generate" so the final answer node
    synthesises from whatever context was already retrieved.

    Returns:
        "tools"                → ToolNode (execute the pending tool calls)
        "force_project_search" → bounded fallback call to search_project_knowledge
        "force_global_search"  → bounded fallback call to search_knowledge_base
                                  after denied project access
        "generate"             → generate_final node (stream final answer)
    """
    from agent.graph.nodes.agent import MAX_ITERATIONS, MAX_LOOP_TOKENS

    messages = state.get("messages", [])
    if not messages:
        logger.info("route: agent -> generate (no messages)")
        return "generate"

    last = messages[-1]
    has_tool_calls = isinstance(last, AIMessage) and bool(getattr(last, "tool_calls", []))

    if not has_tool_calls and _needs_project_search_fallback(state):
        logger.info("route: agent -> force_project_search before final answer")
        return "force_project_search"

    if not has_tool_calls and _needs_global_search_fallback(state):
        logger.info("route: agent -> force_global_search after denied project access")
        return "force_global_search"

    if not has_tool_calls:
        logger.info("route: agent -> generate (no tool calls)")
        return "generate"

    iterations = state.get("tool_call_count", 0)
    tokens = state.get("loop_tokens_used", 0)

    if iterations >= MAX_ITERATIONS:
        logger.warning(
            "route_after_agent: iteration cap (%d/%d) → generate", iterations, MAX_ITERATIONS
        )
        return "generate"

    if tokens >= MAX_LOOP_TOKENS:
        logger.warning(
            "route_after_agent: token budget (%d/%d) → generate", tokens, MAX_LOOP_TOKENS
        )
        return "generate"

    if _needs_project_search_fallback(state) and state.get("tool_call_count", 0) >= MAX_ITERATIONS:
        logger.info("route: agent -> force_project_search after empty structured result")
        return "force_project_search"

    logger.info("route: agent -> tools (iteration=%d tokens=%d)", iterations, tokens)
    return "tools"


def _needs_project_search_fallback(state: AgentState) -> bool:
    """Guarantee the selected project RAG tool runs before final generation."""
    selected = state.get("selected_tools", [])
    if "search_project_knowledge" not in selected:
        return False
    outcomes = state.get("project_tool_outcomes", [])
    if any(item.get("tool") == "search_project_knowledge" for item in outcomes):
        return False
    if not outcomes:
        return True
    return any(item.get("tool", "").startswith("get_project_") for item in outcomes)


def project_access_denied(state: AgentState) -> bool:
    """True when project tools ran and every outcome was access-denied.

    Shared by routing (fallback trigger), generate_final (answer guidance),
    and grounding (audit scope) so all three agree on what "denied" means.
    """
    outcomes = state.get("project_tool_outcomes", [])
    if not outcomes:
        return False
    if not any(item.get("tool", "") in _PROJECT_TOOL_NAMES for item in outcomes):
        return False
    return all(item.get("status") == "forbidden" for item in outcomes)


def global_search_completed(state: AgentState) -> bool:
    """True once a search_knowledge_base result is in the message history."""
    return any(
        isinstance(msg, ToolMessage) and msg.name == "search_knowledge_base"
        for msg in state.get("messages", [])
    )


def _needs_global_search_fallback(state: AgentState) -> bool:
    """Fall back to the global knowledge base after denied project access.

    Project-scoped tools are ABAC-gated per project; the global RAG index may
    still hold accessible content about the topic. Fire once: after the global
    search has run, its results (or honest empty result) flow to generate_final.
    """
    from agent.graph.nodes.agent import MAX_ITERATIONS

    if not project_access_denied(state):
        return False
    if global_search_completed(state):
        return False
    return state.get("tool_call_count", 0) < MAX_ITERATIONS
