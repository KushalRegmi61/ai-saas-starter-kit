"""Agent graph state. AccessFilter (with tenant) rides along; nodes never resolve identity."""

from typing import TypedDict

from rag.types import AccessFilter, SearchMode, SearchResult


class AgentState(TypedDict):
    question: str
    active_question: str  # may be rewritten; used for retrieval
    top_k: int
    search_mode: SearchMode
    access_filter: AccessFilter | None
    conversation_history: list[dict]  # [{"role": "user"|"assistant", "content": "..."}]
    attempts: int
    results: list[SearchResult]
    answer: str
    sources: list[dict]
    needs_rewrite: bool
    grounded: bool
    workflow_steps: list[str]
