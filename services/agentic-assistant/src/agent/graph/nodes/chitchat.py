"""Chitchat response node.

Direct conversational reply with no tools. Called when classify_intent
outputs intent="chitchat".

Uses stream_response(context=None) from agent.llm — async token streaming.
LangGraph astream_events picks up on_chat_model_stream events automatically,
stream_graph() in workflow.py forwards them as WebSocket token events.

Runs check_grounding after accumulating the full answer.
"""

from __future__ import annotations

import logging

from agent.graph.nodes.grounding import check_grounding
from agent.graph.state import AgentState
from agent.llm import LLMContext, stream_response
from agent.tracing import get_langchain_callbacks

logger = logging.getLogger(__name__)


async def chitchat_respond(state: AgentState) -> dict:
    """Stream a direct conversational reply. No tools, no retrieval."""
    logger.info("node chitchat: start question_len=%d", len(state.get("question", "")))
    ctx = LLMContext(
        question=state["question"],
        context=None,           # chitchat — no retrieved context
        history=state.get("conversation_history", []),
        summary=state.get("memory_summary", ""),
    )

    full = ""
    async for token in stream_response(ctx, callbacks=get_langchain_callbacks()):
        full += token

    logger.info("node chitchat: done answer_len=%d", len(full))

    updated = {
        **state,
        "answer": full,
        "sources": [],
        "results": [],
        "workflow_steps": [
            *state.get("workflow_steps", []),
            "chitchat_respond: direct reply (no retrieval)",
        ],
    }
    return check_grounding(updated)
