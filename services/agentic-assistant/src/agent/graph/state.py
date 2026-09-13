"""Agent graph state.

The parent ReAct agent graph carries both the session-level fields (access
filter, conversation history) and the per-turn ReAct loop fields (messages,
tool_call_count, loop_tokens_used). AccessFilter (with tenant) rides along
immutably — it is set once from verified JWT claims and never mutated by any
node. Tools receive it via InjectedState, invisible to the LLM.
"""

from __future__ import annotations

import logging
import operator
from typing import Annotated

from langchain_core.messages import BaseMessage
from rag.types import AccessFilter, SearchMode, SearchResult

logger = logging.getLogger(__name__)


class AgentState(dict):
    """TypedDict-compatible state for the parent ReAct agent graph.

    Using a plain dict subclass so LangGraph's Annotated reducer on `messages`
    works correctly with the append-only operator.add reducer.
    """

    # ------------------------------------------------------------------ #
    # Session-level — set at request start, never mutated by nodes        #
    # ------------------------------------------------------------------ #
    question: str                          # original user question
    access_filter: AccessFilter | None     # ABAC — injected into tools, LLM never sees it
    conversation_history: list[dict]       # prior turns: [{"role": ..., "content": ...}]
    memory_summary: str                    # rolling compacted summary
    search_mode: SearchMode                # passed through to tool

    # ------------------------------------------------------------------ #
    # ReAct loop — mutated each iteration                                 #
    # ------------------------------------------------------------------ #
    messages: Annotated[list[BaseMessage], operator.add]  # append-only reducer
    intent: str           # "chitchat" | "needs_tools" — set by classify node
    selected_tools: list[str]   # tool names chosen by classifier
    tool_call_count: int        # iteration counter — hard cap enforcement
    loop_tokens_used: int       # cumulative tokens across loop LLM calls

    # ------------------------------------------------------------------ #
    # Result accumulation — written by tool + streaming                   #
    # ------------------------------------------------------------------ #
    results: list[SearchResult]   # chunks from last tool call (grounding input)
    answer: str                   # final answer text
    sources: list[dict]           # serialised Source objects
    grounded: bool                # grounding check result
    workflow_steps: list[str]     # audit trail of node transitions


def make_initial_state(
    question: str,
    *,
    access_filter: AccessFilter | None = None,
    conversation_history: list[dict] | None = None,
    memory_summary: str = "",
    search_mode: SearchMode = "auto",
) -> dict:
    """Construct a fully-initialised AgentState dict for a new request."""
    logger.info(
        "state: init question_len=%d history_turns=%d summary_len=%d mode=%s filter=%s",
        len(question),
        len(conversation_history or []),
        len(memory_summary),
        search_mode,
        bool(access_filter),
    )
    return {
        # session
        "question": question,
        "access_filter": access_filter,
        "conversation_history": conversation_history or [],
        "memory_summary": memory_summary,
        "search_mode": search_mode,
        # react loop
        "messages": [],
        "intent": "",
        "selected_tools": [],
        "tool_call_count": 0,
        "loop_tokens_used": 0,
        # results
        "results": [],
        "answer": "",
        "sources": [],
        "grounded": False,
        "workflow_steps": [],
    }
