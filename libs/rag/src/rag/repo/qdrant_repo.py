"""Qdrant adapter: chunk vectors + RBAC-filtered search + corpus scroll."""

from __future__ import annotations

import hashlib
from functools import lru_cache

from rag.config import get_rag_settings
from rag.retrieval.rbac import allowed_level_labels


def _client():
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise ImportError("qdrant-client is required. Run: pip install qdrant-client") from exc
    s = get_rag_settings()
    if not s.qdrant_url:
        raise ValueError("QDRANT_URL is missing. Set it before retrieval.")
    return QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None)


@lru_cache(maxsize=1)
def _cached_client():
    return _client()


def _chunk_id(source: str, chunk_index: int, text: str, tenant: str = "default") -> str:
    raw = f"{tenant}:{source}:{chunk_index}:{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def assert_collection_dimensions() -> None:
    """Raise ValueError when the stored vector size differs from settings.

    No-op when the collection is missing or empty.
    """
    client = _cached_client()
    s = get_rag_settings()
    if not client.collection_exists(collection_name=s.qdrant_collection):
        return
    points, _ = client.scroll(
        collection_name=s.qdrant_collection,
        limit=1,
        with_payload=False,
        with_vectors=True,
    )
    if not points:
        return
    vector = points[0].vector
    if isinstance(vector, dict):
        vector = next(iter(vector.values()))
    size = len(vector) if vector is not None else 0
    if size != s.embedding_dimensions:
        raise ValueError(
            f"Qdrant collection {s.qdrant_collection!r} has dimension {size}, "
            f"expected {s.embedding_dimensions}."
        )


def ensure_collection() -> None:
    """Create the chunks collection when missing (dimension-checked first)."""
    assert_collection_dimensions()  # no-op when missing/empty
    from qdrant_client.http.models import Distance, VectorParams

    client = _cached_client()
    s = get_rag_settings()
    if client.collection_exists(collection_name=s.qdrant_collection):
        return
    client.create_collection(
        collection_name=s.qdrant_collection,
        vectors_config=VectorParams(size=s.embedding_dimensions, distance=Distance.COSINE),
    )


def upsert_chunks(chunks: list[object], vectors: list[list[float]]) -> int:
    """Upsert chunk texts + vectors with Phase 1 read payload keys. Returns count."""
    from qdrant_client.http.models import PointStruct

    if len(chunks) != len(vectors):
        raise ValueError(
            f"chunks ({len(chunks)}) and vectors ({len(vectors)}) must have same length."
        )
    if not chunks:
        return 0
    s = get_rag_settings()
    points = []
    for chunk, vector in zip(chunks, vectors, strict=False):
        meta = chunk.metadata
        source = str(meta.get("source", "unknown"))
        chunk_index = int(meta.get("chunk_index") or 0)
        tn = str(meta.get("tenant", "default"))
        points.append(
            PointStruct(
                id=_chunk_id(source, chunk_index, chunk.text, tenant=tn),
                vector=vector,
                payload={
                    "text": chunk.text,
                    "source": source,
                    "page": meta.get("page"),
                    "chunk_index": chunk_index,
                    "department": meta.get("department", "general"),
                    "access_level": meta.get("access_level", "internal"),
                    "tenant": tn,
                },
            )
        )
    _cached_client().upsert(collection_name=s.qdrant_collection, points=points)
    return len(points)


def delete_chunks_by_source(source: str) -> None:
    """Delete every point whose payload source equals the given source."""
    from qdrant_client.http.models import FieldCondition, Filter, MatchValue

    _cached_client().delete(
        collection_name=get_rag_settings().qdrant_collection,
        points_selector=Filter(must=[FieldCondition(key="source", match=MatchValue(value=source))]),
    )


def _qdrant_filter(
    departments: list[str], max_access_level: int, tenant: str | None = None
):
    from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue

    must = []
    if "all" not in departments:
        must.append(FieldCondition(key="department", match=MatchAny(any=list(departments))))
    if tenant is not None:
        must.append(FieldCondition(key="tenant", match=MatchValue(value=tenant)))
    must.append(
        FieldCondition(
            key="access_level", match=MatchAny(any=list(allowed_level_labels(max_access_level)))
        )
    )
    return Filter(must=must)


def semantic_search(
    query_vector: list[float],
    top_k: int,
    departments: list[str],
    max_access_level: int,
    tenant: str | None = None,
) -> list[tuple[object, float]]:
    """Filtered cosine search. Returns (doc-like, score) with page_content/metadata attrs."""
    from rag.repo.neon_repo import SimpleDoc

    client = _cached_client()
    s = get_rag_settings()
    points = client.query_points(
        collection_name=s.qdrant_collection,
        query=query_vector,
        query_filter=_qdrant_filter(departments, max_access_level, tenant),
        limit=top_k,
        with_payload=True,
    ).points
    results = []
    for p in points:
        payload = p.payload or {}
        results.append(
            (
                SimpleDoc(
                    text=str(payload.get("text", "")),
                    metadata={
                        "source": payload.get("source", "unknown"),
                        "page": payload.get("page"),
                        "chunk_index": payload.get("chunk_index"),
                        "department": payload.get("department", "general"),
                        "access_level": payload.get("access_level", "internal"),
                        "tenant": payload.get("tenant", "default"),
                    },
                ),
                float(p.score or 0.0),
            )
        )
    return results


def scroll_corpus(
    departments: list[str],
    max_access_level: int,
    limit: int = 10000,
    tenant: str | None = None,
) -> list[object]:
    """Load accessible chunk texts for BM25. Filtered in Python via RBAC."""
    from rag.repo.neon_repo import SimpleDoc
    from rag.retrieval.rbac import passes_access_filter

    client = _cached_client()
    s = get_rag_settings()
    docs: list[object] = []
    offset = None
    while len(docs) < limit:
        batch, offset = client.scroll(
            collection_name=s.qdrant_collection,
            limit=min(1000, limit - len(docs)),
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not batch:
            break
        for p in batch:
            payload = p.payload or {}
            meta = {
                "source": payload.get("source", "unknown"),
                "page": payload.get("page"),
                "chunk_index": payload.get("chunk_index"),
                "department": payload.get("department", "general"),
                "access_level": payload.get("access_level", "internal"),
                "tenant": payload.get("tenant", "default"),
            }
            if passes_access_filter(meta, departments, max_access_level, tenant):
                docs.append(SimpleDoc(text=str(payload.get("text", "")), metadata=meta))
        if offset is None:
            break
    return docs
