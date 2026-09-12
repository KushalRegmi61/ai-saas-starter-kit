"""Generate node: answer strictly from retrieved context (or abstain)."""

from __future__ import annotations

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
    llm = common._chat_model()
    response = llm.invoke(
        common._generation_messages(state),
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
