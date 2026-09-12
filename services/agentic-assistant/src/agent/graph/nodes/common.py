"""Shared node utilities: LLM factory, scoring, formatting, source extraction.

One home for logic used by more than one node. Node modules import from
here; tests patch `agent.graph.nodes.common._chat_model` to fake the LLM.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from rag.types import SearchResult, Source

from agent.config import get_agent_settings

MIN_RELEVANCE_SCORE = 0.25


def _chat_model() -> ChatOpenAI:
    settings = get_agent_settings()
    kwargs: dict = {
        "model": settings.openai_chat_model,
        "temperature": 0,
        "api_key": settings.openai_api_key,
    }
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return ChatOpenAI(**kwargs)


def _best_score(results: list[SearchResult]) -> float:
    scores = [result.source.score for result in results if result.source.score is not None]
    return max(scores, default=0.0)


def _format_context(results: list[SearchResult]) -> str:
    blocks = []
    for index, result in enumerate(results, start=1):
        source = result.source.source
        page = f", page {result.source.page}" if result.source.page else ""
        blocks.append(f"[{index}] Source: {source}{page}\n{result.text}")
    return "\n\n".join(blocks)


def _answer_sources(answer: str, results: list[SearchResult]) -> list[dict]:
    answer_lower = answer.lower()
    cited_sources = [
        result.source.model_dump()
        for result in results
        if result.source.source.lower() in answer_lower
    ]
    if cited_sources:
        return cited_sources
    confident_sources = [
        result.source.model_dump()
        for result in results
        if result.source.score is not None and result.source.score >= MIN_RELEVANCE_SCORE
    ]
    return confident_sources[:2]


def _format_history(history: list[dict]) -> str:
    """Format conversation turns into a readable block for the LLM prompt."""
    if not history:
        return ""
    lines = []
    for turn in history:
        role = "User" if turn["role"] == "user" else "Assistant"
        lines.append(f"{role}: {turn['content']}")
    return "\n".join(lines)


def _format_memory_summary(summary: str) -> str:
    if not summary:
        return ""
    return f"Rolling conversation summary:\n{summary}"


def _generation_messages(state) -> list:
    """Build the shared generation prompt for sync and streaming workflows."""
    context = _format_context(state["results"])
    history_block = _format_history(state.get("conversation_history", []))
    summary_block = _format_memory_summary(state.get("memory_summary", ""))
    system_content = (
        "You are a project knowledge assistant.\n"
        "Answer only from the provided context. If the context does not contain the "
        "answer, say you do not know.\n"
        "Include concise citations using the source names from the context.\n"
        "When conversation memory is provided, maintain continuity — refer back to "
        "prior answers when relevant, but never invent facts not in the context."
    )
    memory_blocks = [block for block in (summary_block, history_block) if block]
    if memory_blocks:
        system_content += "\n\n" + "\n\n".join(memory_blocks)
    return [
        SystemMessage(content=system_content),
        HumanMessage(content=f"Question: {state['active_question']}\n\nContext:\n{context}"),
    ]


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item) for item in content
        )
    return str(content)


def sources_from_state(state) -> list[Source]:
    return [Source(**source) for source in state["sources"]]
