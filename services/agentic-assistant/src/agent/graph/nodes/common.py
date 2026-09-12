"""Shared node utilities: LLM factory, scoring, formatting, source extraction.

One home for logic used by more than one node. Node modules import from
here; tests patch `agent.graph.nodes.common._chat_model` to fake the LLM.
"""

from __future__ import annotations

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


def sources_from_state(state) -> list[Source]:
    return [Source(**source) for source in state["sources"]]
