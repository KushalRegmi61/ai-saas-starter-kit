"""Intent classifier node.

One cheap LLM call that routes the conversation before the ReAct loop.
Receives full context: rolling memory summary + conversation history +
all available tool schemas from the registry + current question.

Uses invoke_response() from agent.llm — async, no streaming (classifier
output must never reach the client as token events).

Outputs:
  state["intent"]         "chitchat" | "needs_tools" | "out_of_scope"
  state["selected_tools"] list of tool names to bind in agent_node
  state["messages"]       HumanMessage appended (reducer)
"""

from __future__ import annotations

import json
import logging
import re

# Optional[] (not `| None`): langgraph only recognises this spelling for
# runtime config injection (RunnableCallable KWARGS_CONFIG_KEYS).
from typing import Optional

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from agent.graph.nodes.routing import PROJECT_TOOL_NAMES
from agent.graph.state import AgentState
from agent.llm import LLMContext, invoke_response
from agent.tools.registry import get_tool_names, get_tool_schemas_for_classifier

logger = logging.getLogger(__name__)

_CLASSIFY_SYSTEM_TEMPLATE = """\
You are an intent classifier for an enterprise knowledge assistant agent.

{memory_block}\
Your task: classify the user's message and select the appropriate tools.

Available tools:
{tool_schemas}

Respond with ONLY a JSON object in this exact format:
{{"intent": "chitchat" | "needs_tools" | "out_of_scope", "tools": ["tool_name", ...]}}

Classification rules:
- "chitchat": greetings, farewells, thanks, small talk, or messages with no \
information need (tools must be [])
- "out_of_scope": requests unrelated to project progress, status, features, \
blockers, updates, decisions, or authorized enterprise knowledge in the \
knowledge base (tools must be [])
- "needs_tools": any question, information request, lookup, or task that \
requires retrieving data (tools must list the relevant tool names)

Tool selection rules:
- Only include tool names from the Available tools list above
- Select all tools that could be relevant — the agent decides the order
- For project questions, select the smallest relevant project tool set; each
  project tool resolves the natural-language reference server-side
- Use get_project_overview for overall state, get_project_features for feature
  queries, get_project_blockers for issues or risks, get_project_activity for
  updates/history, and search_project_knowledge for project documentation
- For a project overview, progress, work, context, or daily-update question,
  select search_project_knowledge together with the relevant structured tool.
  Knowledge search supplies narrative context while structured tools supply
  authoritative current state.
- Never invent a project_id; an optional ID is only a server-validated hint
- Independent project reads may be selected together so the tool runner can fan
  them out before the final answer is synthesized
- For ambiguous follow-up questions, prefer selecting tools over chitchat
- If unsure whether a request is supported, default to "out_of_scope"

Return ONLY the JSON. No explanation, no markdown, no extra text.\
"""


async def classify_intent(
    state: AgentState,
    config: Optional[RunnableConfig] = None,  # noqa: UP045
) -> dict:
    """Classify intent and select tools. Appends HumanMessage to messages."""
    logger.info("node classify: start question_len=%d", len(state.get("question", "")))
    memory_block = _build_memory_block(state)
    system_prompt = _CLASSIFY_SYSTEM_TEMPLATE.format(
        memory_block=memory_block,
        tool_schemas=get_tool_schemas_for_classifier(),
    )

    ctx = LLMContext(
        question=state["question"],
        system_prompt=system_prompt,
        # No history/summary here — already embedded in system_prompt above
    )

    raw = await invoke_response(ctx, config=config, route="fast")
    parsed = _enforce_project_selection(
        state["question"], _parse_response(raw), state.get("claims")
    )

    logger.info(
        "node classify: done intent=%s tools=%s question=%r",
        parsed["intent"],
        parsed["tools"],
        state["question"][:120],
    )

    return {
        **state,
        "intent": parsed["intent"],
        "selected_tools": parsed["tools"],
        "messages": [HumanMessage(content=state["question"])],  # reducer appends
        "workflow_steps": [
            *state.get("workflow_steps", []),
            f"classify: intent={parsed['intent']} tools={parsed['tools']}",
        ],
    }


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _build_memory_block(state: AgentState) -> str:
    parts: list[str] = []
    summary = state.get("memory_summary", "")
    if summary:
        parts.append(f"Conversation summary:\n{summary}\n\n")
    history = state.get("conversation_history", [])
    if history:
        lines = [
            f"{'User' if t.get('role') == 'user' else 'Assistant'}: {t.get('content', '')}"
            for t in history[-6:]
        ]
        parts.append("Recent conversation:\n" + "\n".join(lines) + "\n\n")
    return "".join(parts)


def _parse_response(raw: str) -> dict:
    """Parse classifier JSON. Invalid output fails closed to out_of_scope."""
    all_tools = get_tool_names()
    fallback = {"intent": "out_of_scope", "tools": []}

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            line for line in cleaned.splitlines() if not line.startswith("```")
        ).strip()

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        logger.warning("classify_intent: failed to parse JSON: %r", raw[:200])
        return fallback
    if not isinstance(data, dict):
        logger.warning("classify_intent: parsed JSON is not an object")
        return fallback

    intent = data.get("intent", "")
    if intent not in ("chitchat", "needs_tools", "out_of_scope"):
        logger.warning("classify_intent: unknown intent %r — failing closed", intent)
        return fallback

    if intent in ("chitchat", "out_of_scope"):
        return {"intent": intent, "tools": []}

    raw_tools = data.get("tools", [])
    if not isinstance(raw_tools, list):
        raw_tools = []

    valid = set(all_tools)
    tools = [t for t in raw_tools if t in valid]
    unknown = [t for t in raw_tools if t not in valid]
    if unknown:
        logger.warning("classify_intent: unknown tools filtered: %s", unknown)
    if not tools:
        tools = all_tools

    return {"intent": "needs_tools", "tools": tools}


_PROJECT_SIGNALS = re.compile(
    r"\b(project|feature|blocker|risk|daily update|progress|delivery|"
    r"documentation|decision|context|workstream|work update|history)\b",
    re.IGNORECASE,
)
def _enforce_project_selection(question: str, parsed: dict, claims=None) -> dict:
    """Make project routing deterministic after the classifier responds."""
    if parsed.get("intent") == "out_of_scope":
        return parsed
    if _lacks_project_access(claims):
        return _route_without_project_tools(question, parsed)
    if not _PROJECT_SIGNALS.search(question):
        return parsed

    names = list(parsed.get("tools", []))
    project_tools = PROJECT_TOOL_NAMES
    if not names or parsed.get("intent") == "chitchat":
        names = ["get_project_overview"]

    lowered = question.casefold()
    if "blocker" in lowered or "risk" in lowered:
        primary = "get_project_blockers"
    elif "feature" in lowered:
        primary = "get_project_features"
    elif any(term in lowered for term in ("update", "history", "daily")):
        primary = "get_project_activity"
    else:
        primary = "get_project_overview"

    selected = [name for name in names if name not in project_tools]
    if primary not in selected:
        selected.append(primary)

    # Every project question gets the knowledge search. Structured records are
    # authoritative for current state, while RAG may contain the explanation,
    # decisions, and documents that are absent from project tables.
    if "search_project_knowledge" not in selected:
        selected.append("search_project_knowledge")

    return {"intent": "needs_tools", "tools": selected}


def _lacks_project_access(claims) -> bool:
    """True when the caller's role can never view project SQL data.

    Employees (and unknown roles) fail _require_project_viewer for every
    project, so each project tool call would return forbidden. Claims of
    None means the identity is unknown (tests, internal callers) — fail open
    to the normal path and let the reactive global-search fallback cover a
    denial. Leads keep project tools: their access is per-project and only
    knowable by resolving the reference server-side.
    """
    from agent.authz import can_view_all_projects, can_view_assigned_projects

    if claims is None:
        return False
    role = claims.role if hasattr(claims, "role") else claims.get("role")
    return not (can_view_all_projects(role) or can_view_assigned_projects(role))


def _route_without_project_tools(question: str, parsed: dict) -> dict:
    """Route roles with no project visibility straight to the knowledge base.

    Project SQL tools are skipped upfront — they would only return forbidden
    evidence cards. The ABAC-filtered global RAG supplies whatever the caller
    may see; an empty result yields the honest unknown-answer path.
    """
    if parsed.get("intent") == "chitchat" and not _PROJECT_SIGNALS.search(question):
        return parsed
    names = [name for name in parsed.get("tools", []) if name not in PROJECT_TOOL_NAMES]
    if "search_knowledge_base" not in names:
        names.append("search_knowledge_base")
    return {"intent": "needs_tools", "tools": names}
