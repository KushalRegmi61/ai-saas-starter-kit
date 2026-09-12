"""Retrieve node: runs the bound RAG tool, never the library directly."""

from __future__ import annotations

from rag.types import SearchResult

from agent import tools as tools_mod
from agent.graph.state import AgentState


def retrieve_context(state: AgentState) -> AgentState:
    filt = state.get("access_filter")
    search_tool = tools_mod.make_rag_tools(filt)[0]
    payload = search_tool.invoke(
        {
            "question": state["active_question"],
            "top_k": state["top_k"],
            "search_mode": state.get("search_mode", "auto"),
        }
    )
    results = [SearchResult(**r) for r in payload.get("results", [])]
    return {
        **state,
        "results": results,
        "workflow_steps": [
            *state["workflow_steps"],
            f"retrieved {len(results)} chunks via tool search_knowledge_base",
        ],
    }
