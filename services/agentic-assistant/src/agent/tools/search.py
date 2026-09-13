"""RAG search tool — the agent's primary knowledge retrieval capability.

Wraps search_rag() (retrieve + BM25/dense hybrid + RRF + rerank) as a
LangChain @tool with two critical properties:

  1. InjectedState ABAC: access_filter is pulled from AgentState by ToolNode
     at execution time. It is stripped from the LLM-visible tool schema, so
     the model cannot see, hallucinate, or override it. Enforcement is
     deterministic and unconditional.

  2. Command return: updates AgentState with ToolMessage + sources + results
     in a single atomic step, keeping all state transitions explicit.

Self-registers in the tool registry at import time — importing this module
in tools/__init__.py is sufficient to make the tool available to the agent.

NOTE: `from __future__ import annotations` is intentionally absent here.
Postponed annotations (PEP 563) turn type hints into strings at definition
time, which breaks InjectedState/InjectedToolCallId detection inside
ToolNode._inject_tool_args(). The injection relies on inspecting live
annotations — string annotations cause silent injection failure.
"""

import logging
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from rag.retrieval.search import search_rag
from rag.types import AccessFilter, SearchMode

from agent.tools.registry import ToolEntry, register

logger = logging.getLogger(__name__)

# InjectedToolCallId is not in all langgraph versions — use a compat shim
try:
    from langchain_core.tools import InjectedToolCallId as _InjectedToolCallId
except ImportError:
    from langgraph.prebuilt import InjectedState as _InjectedToolCallId  # type: ignore[assignment]


@tool("search_knowledge_base")
def search_knowledge_base(
    question: str,
    tool_call_id: Annotated[str, _InjectedToolCallId],
    access_filter: Annotated[AccessFilter | None, InjectedState("access_filter")],
    top_k: int = 4,
    search_mode: SearchMode = "auto",
) -> Command:
    """Search the enterprise knowledge base for information about internal
    policies, procedures, documentation, and guidelines. Returns grounded
    context chunks with source citations.

    Args:
        question: The search query. Be specific and self-contained.
        top_k: Number of context chunks to retrieve (1-10, default 4).
        search_mode: Retrieval strategy — "auto", "hybrid", "semantic", or "bm25".

    Note: access_filter is injected automatically from session state.
    """
    logger.info(
        "tool search: start question=%r top_k=%d mode=%s tenant=%s filter=%s",
        question[:200],
        top_k,
        search_mode,
        getattr(access_filter, "tenant", None),
        bool(access_filter),
    )

    try:
        response = search_rag(
            question=question,
            top_k=top_k,
            search_mode=search_mode,
            access_filter=access_filter,  # injected by ToolNode — LLM never touches this
        )
    except Exception as exc:
        logger.exception("search_rag failed: %s", exc)
        error_msg = f"Knowledge base search failed: {exc}"
        return Command(update={
            "messages": [ToolMessage(content=error_msg, tool_call_id=tool_call_id)],
            "workflow_steps": [f"search_knowledge_base error: {exc}"],
        })

    if not response.results:
        content = "No relevant information found in the knowledge base for this query."
    else:
        # Format chunks as numbered context blocks for the LLM
        blocks = []
        for i, result in enumerate(response.results, start=1):
            src = result.source.source
            page = f" (page {result.source.page})" if result.source.page else ""
            score = f" [score={result.source.score:.3f}]" if result.source.score else ""
            blocks.append(f"[{i}] Source: {src}{page}{score}\n{result.text}")
        content = "\n\n".join(blocks)

    logger.info(
        "tool search: done chunks=%d mode=%s",
        len(response.results),
        response.search_mode,
    )

    return Command(update={
        "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)],
        "sources": [r.source.model_dump() for r in response.results],
        "results": response.results,
        "workflow_steps": [
            f"search_knowledge_base: {len(response.results)} chunks "
            f"mode={response.search_mode}"
        ],
    })


# Self-register at import time — importing this module is the only wiring needed
register(ToolEntry(
    name="search_knowledge_base",
    description=(
        "Search indexed enterprise documents and internal knowledge base. "
        "Returns relevant context chunks with source citations."
    ),
    when_to_use=(
        "User asks about internal policies, procedures, documentation, "
        "security guidelines, HR policies, product specs, compliance rules, "
        "or any question that requires looking up stored organisational knowledge. "
        "Also use for follow-up questions about previously retrieved documents."
    ),
    category="knowledge",
    tool_fn=search_knowledge_base,
    requires_access_filter=True,
    always_include=False,
    tags=("rag", "retrieval", "hybrid-search", "abac"),
))
