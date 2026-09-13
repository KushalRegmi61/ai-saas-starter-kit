"""Shared node utilities: scoring, formatting, source extraction.

LLM factory and message building have moved to agent/llm.py.
This module keeps the pure-logic helpers used across multiple nodes:
  - _content_text   — extract plain text from any content shape
  - _best_score     — relevance scoring for results
  - _format_context — format SearchResult list into a context string
  - _answer_sources — extract cited sources from an answer string
  - sources_from_state — deserialise sources from state dict
"""

from __future__ import annotations

import logging

from rag.types import SearchResult, Source

logger = logging.getLogger(__name__)

MIN_RELEVANCE_SCORE = 0.25


def _content_text(content: object) -> str:
    """Extract plain text from any LangChain message content shape."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content)


def _best_score(results: list[SearchResult]) -> float:
    scores = [r.source.score for r in results if r.source.score is not None]
    return max(scores, default=0.0)


def _format_context(results: list[SearchResult]) -> str:
    blocks = []
    for i, result in enumerate(results, start=1):
        source = result.source.source
        page = f", page {result.source.page}" if result.source.page else ""
        blocks.append(f"[{i}] Source: {source}{page}\n{result.text}")
    return "\n\n".join(blocks)


def _answer_sources(answer: str, results: list[SearchResult]) -> list[dict]:
    logger.debug(
        "common: extracting sources answer_len=%d results=%d", len(answer), len(results)
    )
    lower = answer.lower()
    cited = [
        r.source.model_dump()
        for r in results
        if r.source.source.lower() in lower
    ]
    if cited:
        return cited
    return [
        r.source.model_dump()
        for r in results
        if r.source.score is not None and r.source.score >= MIN_RELEVANCE_SCORE
    ][:2]


def sources_from_state(state: object) -> list[Source]:
    sources = state.get("sources", []) if isinstance(state, dict) else []  # type: ignore[union-attr]
    return [Source(**s) for s in sources]
