"""Knowledge-base search tool, bound to the host-resolved access filter."""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from rag.retrieval.search import search_rag
from rag.types import AccessFilter, SearchMode


def make_search_tool(access_filter: AccessFilter | None) -> BaseTool:
    """Build the `search_knowledge_base` tool with the caller's filter baked in."""

    @tool("search_knowledge_base")
    def search_knowledge_base(
        question: str, top_k: int = 4, search_mode: SearchMode = "auto"
    ) -> dict:
        """Search the project knowledge base. Returns top-k grounded chunks
        with sources. Use for any question about indexed documents."""
        response = search_rag(
            question=question,
            top_k=top_k,
            search_mode=search_mode,
            access_filter=access_filter,
        )
        return response.model_dump()

    search_knowledge_base.metadata = {"tenant": getattr(access_filter, "tenant", None)}
    return search_knowledge_base
