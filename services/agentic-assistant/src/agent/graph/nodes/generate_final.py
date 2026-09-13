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

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig

from agent.graph.nodes.grounding import check_grounding
from agent.graph.state import AgentState
from agent.llm import LLMContext, stream_response

logger = logging.getLogger(__name__)


async def generate_final(
    state: AgentState, config: RunnableConfig | None = None
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
        context=context or None,  # None if no tool results → honest "I don't know"
        history=state.get("conversation_history", []),
        summary=state.get("memory_summary", ""),
    )

    full = ""
    async for token in stream_response(ctx, config=config):
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
    return check_grounding(updated)


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

    return "\n\n---\n\n".join(blocks)
