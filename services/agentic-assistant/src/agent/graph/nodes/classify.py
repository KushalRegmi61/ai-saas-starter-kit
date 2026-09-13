"""Intent classifier node.

One cheap LLM call that routes the conversation before the ReAct loop.
Receives full context: rolling memory summary + conversation history +
all available tool schemas from the registry + current question.

Uses invoke_response() from agent.llm — async, no streaming (classifier
output must never reach the client as token events).

Outputs:
  state["intent"]         "chitchat" | "needs_tools"
  state["selected_tools"] list of tool names to bind in agent_node
  state["messages"]       HumanMessage appended (reducer)
"""

from __future__ import annotations

import json
import logging

# Optional[] (not `| None`): langgraph only recognises this spelling for
# runtime config injection (RunnableCallable KWARGS_CONFIG_KEYS).
from typing import Optional

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

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
{{"intent": "chitchat" | "needs_tools", "tools": ["tool_name", ...]}}

Classification rules:
- "chitchat": greetings, farewells, thanks, small talk, or messages with no \
information need (tools must be [])
- "needs_tools": any question, information request, lookup, or task that \
requires retrieving data (tools must list the relevant tool names)

Tool selection rules:
- Only include tool names from the Available tools list above
- Select all tools that could be relevant — the agent decides the order
- For project questions, select resolve_project when the project is not already
  identified, then select the independent project reads needed by the question
- Never invent a project_id; use the ID returned by an authorized resolution
- Independent project reads may be selected together so the tool runner can fan
  them out before the final answer is synthesized
- For ambiguous follow-up questions, prefer selecting tools over chitchat
- If unsure, default to "needs_tools" with all available tools

Return ONLY the JSON. No explanation, no markdown, no extra text.\
"""


async def classify_intent(
    state: AgentState, config: Optional[RunnableConfig] = None  # noqa: UP045
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

    raw = await invoke_response(ctx, config=config)
    parsed = _parse_response(raw)

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
    """Parse classifier JSON. Fails closed to needs_tools + all tools."""
    all_tools = get_tool_names()
    fallback = {"intent": "needs_tools", "tools": all_tools}

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

    intent = data.get("intent", "")
    if intent not in ("chitchat", "needs_tools"):
        logger.warning("classify_intent: unknown intent %r — defaulting to needs_tools", intent)
        intent = "needs_tools"

    if intent == "chitchat":
        return {"intent": "chitchat", "tools": []}

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
