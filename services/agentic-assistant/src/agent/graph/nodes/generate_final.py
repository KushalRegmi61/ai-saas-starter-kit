"""Final answer generation node.

Called when the agent ReAct loop ends (no more tool calls or budget hit).
Synthesises a final streaming answer from all accumulated tool results
in the message history.

Uses stream_response(context=tool_context) from agent.llm — the same
streaming path as chitchat, but with retrieved context assembled from
ToolMessage results in state["messages"]. This is the single generation
point for all knowledge-grounded answers regardless of which tools ran.

Runs check_grounding after accumulating the full answer.
"""

from __future__ import annotations

import logging

# Optional[] (not `| None`): langgraph only recognises this spelling for
# runtime config injection (RunnableCallable KWARGS_CONFIG_KEYS).
from typing import Optional

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig

from agent.graph.nodes.grounding import check_grounding
from agent.graph.state import AgentState
from agent.llm import LLMContext, stream_response

logger = logging.getLogger(__name__)


async def generate_final(
    state: AgentState, config: Optional[RunnableConfig] = None  # noqa: UP045
) -> dict:
    """Stream final answer from accumulated tool results.

    Assembles context from all ToolMessages in state["messages"] then calls
    stream_response with the grounded system prompt. Works identically
    whether the context came from RAG, web search, or any future tool.
    """
    logger.info("node generate_final: start")
    context = _assemble_context(state)
    logger.debug("node generate_final: context_len=%d", len(context) if context else 0)

    ctx = LLMContext(
        question=state["question"],
        context=context or None,  # None if no tool results -> honest "I don't know"
        history=state.get("conversation_history", []),
        summary=state.get("memory_summary", ""),
    )

    full = ""
    async for token in stream_response(ctx, config=config, route="reasoning"):
        full += token

    logger.info(
        "node generate_final: done context_len=%d answer_len=%d",
        len(context) if context else 0,
        len(full),
    )

    updated = {
        **state,
        "answer": full,
        "workflow_steps": [
            *state.get("workflow_steps", []),
            f"generate_final: answer_len={len(full)} "
            f"context_len={len(context) if context else 0}",
        ],
    }
    return await check_grounding(updated, config=config)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _assemble_context(state: AgentState) -> str:
    """Collect all ToolMessage content from message history as a single
    context string. Preserves order — later tool results appear last.

    Each block is prefixed with the tool name for traceability.
    """
    messages = state.get("messages", [])
    blocks: list[str] = []

    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.content:
            content = msg.content
            if isinstance(content, list):
                content = "\n".join(
                    item.get("text", str(item)) if isinstance(item, dict) else str(item)
                    for item in content
                )
            blocks.append(str(content))

    project_guidance = (
        "Project-answer rules: structured project results are authoritative for "
        "status, completion, blockers, feature counts, and history. Treat RAG "
        "results as supporting context only. If resolution is ambiguous, ask "
        "the user to choose from the returned candidates. Do not expose IDs, "
        "claims, pool details, token data, or authorization internals. "
        "When a project is resolved, use its exact resolved name and mention "
        "that project in the opening sentence of the answer. Tie every "
        "blocker, feature, update, and status claim to that named project. "
        "Summarize the retrieved context in plain, human-friendly language; "
        "do not copy raw tool JSON, field labels, internal tool names, or "
        "repeated descriptions into the answer. Lead with the direct takeaway, "
        "then briefly explain the impact and relevant next step when known. "
        "If a resolved project has empty features, blockers, updates, or "
        "knowledge results, explain warmly that no records were found and "
        "summarize any remaining project facts. Distinguish not-found, "
        "ambiguous, forbidden, and tool-error outcomes. Do not say 'I don't "
        "know' when a meaningful project result or empty-record explanation "
        "is available."
    )
    if (
        state.get("resolved_project")
        or state.get("project_candidates")
        or state.get("project_tool_outcomes")
        or any(
            name.startswith("get_project_") or name == "search_project_knowledge"
            for name in state.get("selected_tools", [])
        )
    ):
        blocks.insert(0, project_guidance)
        resolved = state.get("resolved_project")
        if resolved:
            name = resolved.name if hasattr(resolved, "name") else resolved.get("name")
            if name:
                blocks.insert(1, f"Resolved project identity: {name}. Name this project in the opening sentence.")
        evidence_context = _format_project_evidence(state.get("project_evidence", []))
        if evidence_context:
            blocks.insert(1, evidence_context)
        outcomes = state.get("project_tool_outcomes", [])
        if outcomes:
            blocks.insert(1, "Project tool outcome summary:\n" + str(outcomes))
    return "\n\n---\n\n".join(blocks)


def _format_project_evidence(evidence: list[object]) -> str:
    """Create deterministic semantics for empty project collections."""
    lines = ["Authoritative project evidence:"]
    for item in evidence:
        data = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        if not isinstance(data, dict):
            continue
        project = data.get("project_name") or "the requested project"
        tool = data.get("tool", "project tool")
        status = data.get("status")
        count = data.get("result_count", 0)
        if status == "resolved" and tool == "get_project_blockers" and count == 0:
            lines.append(
                f"No blockers are currently reported for {project} based on current project records."
            )
        elif status == "resolved" and tool == "get_project_features" and count == 0:
            lines.append(f"No features are currently recorded for {project}.")
        elif status == "resolved" and tool == "get_project_activity" and count == 0:
            lines.append(f"No daily updates or feature history are currently recorded for {project}.")
        elif status == "resolved" and tool == "search_project_knowledge" and count == 0:
            lines.append(
                f"No supporting project knowledge was found for {project}; use structured project records when available."
            )
        elif status == "ambiguous":
            lines.append("The project reference is ambiguous; ask the user to choose a matching project.")
        elif status == "not_found":
            lines.append("No authorized project matched the requested reference.")
        elif status == "forbidden":
            lines.append("Project details are unavailable because the current user cannot access them.")
        elif status not in ("resolved", None):
            lines.append(f"{tool} returned status {status}; do not present the result as confirmed project data.")
    return "\n".join(lines) if len(lines) > 1 else ""
