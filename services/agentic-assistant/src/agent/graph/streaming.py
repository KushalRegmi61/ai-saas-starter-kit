"""Async token streaming for the assistant graph."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from rag.types import AccessFilter, SearchMode

from agent.config import get_agent_settings
from agent.graph.nodes import (
    check_grounding,
    common,
    grade_context,
    retrieve_context,
    rewrite_query,
)
from agent.graph.state import AgentState
from agent.tracing import get_langchain_callbacks, trace_span


async def stream_answer(
    question: str,
    *,
    top_k: int = 4,
    search_mode: SearchMode = "auto",
    access_filter: AccessFilter | None = None,
    conversation_history: list[dict] | None = None,
    memory_summary: str = "",
) -> AsyncIterator[dict]:
    """Yield workflow steps, answer tokens, and a private final result event."""
    settings = get_agent_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is missing. Set it before asking questions.")

    with trace_span(
        name="agent_ask_stream",
        input_data={"question": question, "top_k": top_k},
        metadata={"operation": "agent_ask_stream", "top_k": top_k},
    ) as span:
        state: AgentState = {
            "question": question,
            "active_question": question,
            "top_k": top_k,
            "search_mode": search_mode,
            "access_filter": access_filter,
            "conversation_history": conversation_history or [],
            "memory_summary": memory_summary,
            "attempts": 0,
            "results": [],
            "answer": "",
            "sources": [],
            "needs_rewrite": False,
            "grounded": False,
            "workflow_steps": ["started streaming agent workflow"],
        }
        yield {"type": "step", "text": state["workflow_steps"][0]}

        before = list(state["workflow_steps"])
        state = await asyncio.to_thread(retrieve_context, state)
        for step in state["workflow_steps"][len(before) :]:
            yield {"type": "step", "text": step}

        state = grade_context(state)
        yield {"type": "step", "text": state["workflow_steps"][-1]}
        if state["needs_rewrite"]:
            before = list(state["workflow_steps"])
            state = await asyncio.to_thread(rewrite_query, state)
            for step in state["workflow_steps"][len(before) :]:
                yield {"type": "step", "text": step}

            before = list(state["workflow_steps"])
            state = await asyncio.to_thread(retrieve_context, state)
            for step in state["workflow_steps"][len(before) :]:
                yield {"type": "step", "text": step}

        if not state["results"]:
            state = {
                **state,
                "answer": "I do not know because no relevant context was found.",
                "sources": [],
                "workflow_steps": [
                    *state["workflow_steps"],
                    "skipped generation because no context was found",
                ],
            }
            yield {"type": "token", "text": state["answer"]}
            state = check_grounding(state)
            result = _result_event(state)
            span["output"] = _trace_output(result)
            yield result
            return

        llm = common._chat_model()
        full_answer = ""
        async for chunk in llm.astream(
            common._generation_messages(state),
            config={"callbacks": get_langchain_callbacks()},
        ):
            token = common._content_text(chunk.content)
            if token:
                full_answer += token
                yield {"type": "token", "text": token}

        state = {
            **state,
            "answer": full_answer,
            "sources": common._answer_sources(full_answer, state["results"]),
            "workflow_steps": [*state["workflow_steps"], "generated streaming answer"],
        }
        state = check_grounding(state)
        result = _result_event(state)
        span["output"] = _trace_output(result)
        yield result


def _result_event(state: AgentState) -> dict:
    return {
        "type": "done",
        "answer": state["answer"],
        "sources": state["sources"],
        "grounded": state["grounded"],
        "rewritten_question": (
            state["active_question"] if state["active_question"] != state["question"] else None
        ),
        "workflow_steps": state["workflow_steps"],
    }


def _trace_output(result: dict) -> dict:
    return {
        "answer_length": len(result["answer"]),
        "sources_count": len(result["sources"]),
        "grounded": result["grounded"],
        "workflow_steps": len(result["workflow_steps"]),
    }
