"""Reranker dispatch, ported from enterprise app/retrieval/reranker.py.

Phase 1 default backend is "none" (RRF order passthrough) to avoid ML weight
downloads. "local" uses a sentence-transformers cross-encoder when installed.
"""

from __future__ import annotations

from rag.config import get_rag_settings

_local_model_cache: dict[str, object] = {}


def rerank(
    question: str, candidates: list[tuple[object, float]], top_k: int
) -> list[tuple[object, float]]:
    if not candidates:
        return candidates
    backend = get_rag_settings().reranker_backend
    if backend == "local":
        return _rerank_local(question, candidates, top_k)
    return candidates[:top_k]


def _rerank_local(
    question: str, candidates: list[tuple[object, float]], top_k: int
) -> list[tuple[object, float]]:
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise ImportError(
            "sentence-transformers is required for local reranking. Run: pip install sentence-transformers"
        ) from exc

    from rag.config import get_rag_settings as _settings

    model_name = (
        _settings().reranker_model
        if hasattr(_settings(), "reranker_model")
        else "cross-encoder/ms-marco-MiniLM-L-6-v2"
    )
    if model_name not in _local_model_cache:
        _local_model_cache[model_name] = CrossEncoder(model_name)
    model = _local_model_cache[model_name]
    texts = [doc.page_content for doc, _ in candidates]  # type: ignore[attr-defined]
    pairs = [[question, text] for text in texts]
    scores: list[float] = model.predict(pairs).tolist()  # type: ignore[attr-defined]
    docs = [doc for doc, _ in candidates]
    return sorted(zip(docs, scores, strict=False), key=lambda x: x[1], reverse=True)[:top_k]
