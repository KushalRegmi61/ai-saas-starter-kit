"""Single-tool surface: search_rag(). Cache + RBAC handled internally."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from rag.config import get_rag_settings
from rag.repo import embeddings, neon_repo, qdrant_repo
from rag.retrieval import hybrid, query_cache, query_router, reranker
from rag.retrieval.formatting import source_from_metadata
from rag.types import AccessFilter, SearchMode, SearchResponse, SearchResult

logger = logging.getLogger(__name__)


def search_rag(
    question: str,
    top_k: int = 4,
    search_mode: SearchMode = "auto",
    access_filter: AccessFilter | None = None,
) -> SearchResponse:
    if not question or not question.strip():
        raise ValueError("question must be non-empty")
    top_k = max(1, min(int(top_k), 10))
    filt = access_filter or AccessFilter(departments=["all"], max_access_level=0)
    resolved_mode, _reason = query_router.resolve_search_mode(question, search_mode)
    settings = get_rag_settings()
    candidate_k = max(settings.reranker_top_n, top_k * 4, 20)

    query_vector = embeddings.embed_query(question)

    with ThreadPoolExecutor(max_workers=1) as pool:
        semantic_future = pool.submit(
            qdrant_repo.semantic_search,
            query_vector,
            candidate_k,
            list(filt.departments),
            int(filt.max_access_level),
            filt.tenant,
        )
        corpus_docs = qdrant_repo.scroll_corpus(
            list(filt.departments), int(filt.max_access_level), tenant=filt.tenant
        )
        semantic_results = semantic_future.result()

    if resolved_mode == "hybrid":
        corpus_texts = [d.page_content for d in corpus_docs]  # type: ignore[attr-defined]
        keyword_ranking = hybrid.bm25_search(question, corpus_texts, top_k=candidate_k)
        candidates = hybrid.reciprocal_rank_fusion(
            semantic_ranking=semantic_results,
            keyword_ranking=keyword_ranking,
            corpus_docs=corpus_docs,
            top_k=candidate_k,
        )
    else:
        candidates = semantic_results[:candidate_k]

    ranked = reranker.rerank(question, candidates, top_k=top_k)

    chunk_ids = [
        f"{d.metadata.get('source', '?')}:{d.metadata.get('chunk_index', '?')}"  # type: ignore[attr-defined]
        for d, _ in ranked
    ]
    ctx_hash = query_cache.context_hash(chunk_ids)

    cached_response = _cache_get(question, query_vector, ctx_hash, resolved_mode, filt.tenant)
    if cached_response is not None:
        return cached_response

    results = [
        SearchResult(text=d.page_content, source=source_from_metadata(d.metadata, score))  # type: ignore[attr-defined]
        for d, score in ranked
    ]
    response = SearchResponse(question=question, results=results, search_mode=resolved_mode)
    _cache_put(question, query_vector, response, resolved_mode, ctx_hash, filt.tenant)
    return response


def _cache_get(
    question: str, embedding: list[float], ctx_hash: str, resolved_mode: str,
    tenant: str | None = None,
) -> SearchResponse | None:
    try:
        with neon_repo.get_conn() as conn:
            neon_repo.ensure_tables(conn)
            hit = query_cache.get_cached_answer(conn, question, embedding, ctx_hash, tenant=tenant)
        if hit is None:
            return None
        return SearchResponse(**hit)
    except Exception as exc:
        logger.warning("retrieval cache lookup skipped: %s", exc)
        return None


def _cache_put(
    question: str,
    embedding: list[float],
    response: SearchResponse,
    resolved_mode: str,
    ctx_hash: str,
    tenant: str | None = None,
) -> None:
    try:
        settings = get_rag_settings()
        with neon_repo.get_conn() as conn:
            neon_repo.ensure_tables(conn)
            query_cache.store_cached_answer(
                conn,
                question=question,
                embedding=embedding,
                answer=response.model_dump(),
                search_mode=resolved_mode,
                ctx_hash=ctx_hash,
                tenant=tenant,
                ttl_hours=int(settings.cache_ttl_hours),
            )
            conn.commit()
    except Exception as exc:
        logger.warning("retrieval cache store skipped: %s", exc)
