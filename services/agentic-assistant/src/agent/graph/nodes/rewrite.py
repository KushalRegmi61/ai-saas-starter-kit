"""Rewrite node: resolve the question against history into a standalone query."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from agent.config import get_agent_settings
from agent.graph.nodes import common
from agent.graph.state import AgentState
from agent.tracing import get_langchain_callbacks


def rewrite_query(state: AgentState) -> AgentState:
    settings = get_agent_settings()
    llm = common._chat_model()
    history_block = common._format_history(state.get("conversation_history", []))
    system_prompt = (
        "You are a query rewriter for a project knowledge assistant.\n"
        "Rewrite the user's question into a self-contained search query that can be "
        "understood without any conversation context.\n"
        "Resolve pronouns and references like 'it', 'that', 'what about X' using the "
        "conversation history below.\n"
        "Return only the rewritten query, nothing else."
    )
    if history_block:
        system_prompt += f"\n\nConversation so far:\n{history_block}"
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=state["question"]),
        ],
        config={"callbacks": get_langchain_callbacks()},
    )
    rewritten = str(response.content).strip() or state["question"]
    return {
        **state,
        "active_question": rewritten,
        "attempts": state["attempts"] + 1,
        "workflow_steps": [
            *state["workflow_steps"],
            f"rewrote query: '{rewritten}' (model={settings.openai_chat_model})",
        ],
    }
