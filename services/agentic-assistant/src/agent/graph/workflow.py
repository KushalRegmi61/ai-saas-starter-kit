"""Assistant workflow entrypoint: retrieve -> grade -> rewrite/generate -> grounding."""

from functools import lru_cache

from langgraph.graph import END, StateGraph
from rag.types import AccessFilter, SearchMode

from agent.config import get_agent_settings
from agent.graph.nodes import (
    check_grounding,
    generate_answer,
    grade_context,
    retrieve_context,
    rewrite_query,
    route_after_grade,
    sources_from_state,
)
from agent.graph.state import AgentState
from agent.tracing import trace_span
from agent.types import AskResponse


def ask(
    question: str,
    top_k: int = 4,
    search_mode: SearchMode = "auto",
    access_filter: AccessFilter | None = None,
    conversation_history: list[dict] | None = None,
) -> AskResponse:
    """Run the assistant workflow. Auth lives outside: pass a host-resolved filter."""
    settings = get_agent_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is missing. Set it before asking questions.")
    with trace_span(
        name="agent_ask",
        input_data={"question": question, "top_k": top_k},
        metadata={"operation": "agent_ask", "top_k": top_k},
    ) as span:
        initial_state: AgentState = {
            "question": question,
            "active_question": question,
            "top_k": top_k,
            "search_mode": search_mode,
            "access_filter": access_filter,
            "conversation_history": conversation_history or [],
            "attempts": 0,
            "results": [],
            "answer": "",
            "sources": [],
            "needs_rewrite": False,
            "grounded": False,
            "workflow_steps": ["started agent workflow"],
        }
        final_state = get_agent_graph().invoke(initial_state)
        response = AskResponse(
            answer=final_state["answer"],
            sources=sources_from_state(final_state),
            rewritten_question=(
                final_state["active_question"]
                if final_state["active_question"] != final_state["question"]
                else None
            ),
            grounded=final_state["grounded"],
            workflow_steps=final_state["workflow_steps"],
        )
        span["output"] = {
            "answer_length": len(response.answer),
            "sources_count": len(response.sources),
            "grounded": response.grounded,
            "workflow_steps": len(response.workflow_steps),
        }
        return response


@lru_cache
def get_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve_context)
    graph.add_node("grade", grade_context)
    graph.add_node("rewrite", rewrite_query)
    graph.add_node("generate", generate_answer)
    graph.add_node("grounding_check", check_grounding)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges(
        "grade",
        route_after_grade,
        {"rewrite": "rewrite", "generate": "generate"},
    )
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("generate", "grounding_check")
    graph.add_edge("grounding_check", END)
    return graph.compile()
