"""Response formatting: single source of truth ported from enterprise-rag-assistant.

Copied verbatim from app/graph/nodes.py (_format_context, _format_history,
_answer_sources, _best_score) and app/retrieval/qa.py (_source_from_metadata).
Every present and future surface (search, answer, streaming) reuses these.
"""

from rag.types import SearchResult, Source

MIN_RELEVANCE_SCORE = 0.25


def source_from_metadata(metadata: dict, score: float | None = None) -> Source:
    return Source(
        source=str(metadata.get("source", "unknown")),
        page=metadata.get("page"),
        chunk_index=metadata.get("chunk_index"),
        score=score,
    )


def format_context(results: list[SearchResult]) -> str:
    blocks = []
    for index, result in enumerate(results, start=1):
        source = result.source.source
        page = f", page {result.source.page}" if result.source.page else ""
        blocks.append(f"[{index}] Source: {source}{page}\n{result.text}")
    return "\n\n".join(blocks)


def answer_sources(answer: str, results: list[SearchResult]) -> list[dict]:
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


def best_score(results: list[SearchResult]) -> float:
    scores = [r.source.score for r in results if r.source.score is not None]
    return max(scores, default=0.0)


def format_history(history: list[dict]) -> str:
    """Format conversation turns into a readable block for the LLM prompt."""
    if not history:
        return ""
    lines = []
    for turn in history:
        role = "User" if turn["role"] == "user" else "Assistant"
        lines.append(f"{role}: {turn['content']}")
    return "\n".join(lines)
