"""BM25 + RRF fusion, verbatim port of enterprise app/retrieval/hybrid_search.py."""

from __future__ import annotations

import re

RRF_K = 60


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def bm25_search(query: str, corpus_texts: list[str], top_k: int) -> list[tuple[int, float]]:
    if not corpus_texts:
        return []
    try:
        from rank_bm25 import BM25Okapi
    except ImportError as exc:
        raise ImportError(
            "rank-bm25 is required for hybrid search. Run: pip install rank-bm25"
        ) from exc

    tokenized_corpus = [tokenize(t) for t in corpus_texts]
    # BM25Okapi divides by corpus_size — skip if all tokens are empty
    if not any(tokenized_corpus):
        return []
    bm25 = BM25Okapi(tokenized_corpus)
    scores: list[float] = bm25.get_scores(tokenize(query))
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    return indexed[:top_k]


def reciprocal_rank_fusion(
    semantic_ranking: list[tuple[object, float]],
    keyword_ranking: list[tuple[int, float]],
    corpus_docs: list[object],
    top_k: int,
    k: int = RRF_K,
) -> list[tuple[object, float]]:
    rrf_scores: dict[str, float] = {}
    doc_map: dict[str, object] = {}

    for rank, (doc, _score) in enumerate(semantic_ranking, start=1):
        key = doc.page_content  # type: ignore[attr-defined]
        rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank)
        doc_map[key] = doc

    for rank, (corpus_idx, _bm25_score) in enumerate(keyword_ranking, start=1):
        doc = corpus_docs[corpus_idx]
        key = doc.page_content  # type: ignore[attr-defined]
        rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank)
        doc_map[key] = doc

    sorted_keys = sorted(rrf_scores, key=lambda k_: rrf_scores[k_], reverse=True)
    return [(doc_map[key], rrf_scores[key]) for key in sorted_keys[:top_k]]
