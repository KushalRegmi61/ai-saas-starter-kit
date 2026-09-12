"""Generate node: answer strictly from retrieved context (or abstain)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from agent.graph.nodes import common
from agent.graph.state import AgentState
from agent.tracing import get_langchain_callbacks


def generate_answer(state: AgentState) -> AgentState:
    if not state["results"]:
        return {
            **state,
            "answer": "I do not know because no relevant context was found.",
            "sources": [],
            "workflow_steps": [
                *state["workflow_steps"],
                "skipped generation because no context was found",
            ],
        }
    context = common._format_context(state["results"])
    history_block = common._format_history(state.get("conversation_history", []))
    system_content = (
        "You are a project knowledge assistant.\n"
        "Answer only from the provided context. If the context does not contain the "
        "answer, say you do not know.\n"
        "Include concise citations using the source names from the context.\n"
        "When a conversation history is provided, maintain continuity — refer back "
        "to prior answers when relevant, but never invent facts not in the context."
    )
    if history_block:
        system_content += f"\n\nConversation history:\n{history_block}"
    llm = common._chat_model()
    response = llm.invoke(
        [
            SystemMessage(content=system_content),
            HumanMessage(content=f"Question: {state['active_question']}\n\nContext:\n{context}"),
        ],
        config={"callbacks": get_langchain_callbacks()},
    )
    return {
        **state,
        "answer": str(response.content),
        "sources": common._answer_sources(str(response.content), state["results"]),
        "workflow_steps": [
            *state["workflow_steps"],
            "generated answer from retrieved context",
        ],
    }
