"""Single-document direct ingestion + source deletion (Phase 2).

Bytes arrive directly from the caller — no S3, no Lambda triggers.
"""

from __future__ import annotations

import hashlib

from rag.ingestion.chunking import chunk_documents
from rag.ingestion.loaders import load_bytes
from rag.repo.embeddings import embed_texts
from rag.repo.neon_repo import (
    delete_document,
    ensure_tables,
    get_conn,
    get_document,
    upsert_document,
)
from rag.repo.qdrant_repo import (
    delete_chunks_by_source,
    ensure_collection,
    upsert_chunks,
)
from rag.retrieval.query_cache import flush_cache
from rag.retrieval.rbac import infer_document_metadata, normalize_tenant
from rag.types import IngestionResult

EMBED_BATCH_SIZE = 64


def index_document(
    content: bytes,
    filename: str,
    source: str,
    department: str | None = None,
    access_level: str | None = None,
    tenant: str | None = None,
) -> IngestionResult:
    """Load, chunk, embed, and upsert one document. Content-hash deduped.

    Tenant is stamped on every chunk payload and the registry row. Explicit
    department/access_level win over filename inference for BOTH payload and
    registry (previously the payload kept the inferred values — fixed here).
    """
    tn = normalize_tenant(tenant)
    docs = load_bytes(content, filename)
    if not docs:
        return IngestionResult(
            documents_loaded=0, chunks_created=0, chunks_indexed=0, sources=[source]
        )
    meta = infer_document_metadata(filename)
    if department:
        meta["department"] = department
    if access_level:
        meta["access_level"] = access_level
    for d in docs:
        d.metadata["source"] = source
        d.metadata["department"] = meta["department"]
        d.metadata["access_level"] = meta["access_level"]
        d.metadata["tenant"] = tn
    content_hash = hashlib.sha256("\n".join(d.text for d in docs).encode()).hexdigest()
    with get_conn() as conn:
        ensure_tables(conn)
        existing = get_document(conn, source, tenant=tn)
        if existing and existing["content_hash"] == content_hash:
            return IngestionResult(
                documents_loaded=0, chunks_created=0, chunks_indexed=0, sources=[source]
            )
        delete_chunks_by_source(source, tenant=tn)
        flush_cache(conn, tenant=tn)
    chunks = chunk_documents(docs)
    vectors: list[list[float]] = []
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        vectors.extend(embed_texts([c.text for c in chunks[i : i + EMBED_BATCH_SIZE]]))
    ensure_collection()
    indexed = upsert_chunks(chunks, vectors)
    with get_conn() as conn:
        upsert_document(
            conn,
            source=source,
            content_hash=content_hash,
            chunks_count=indexed,
            department=meta["department"],
            access_level=meta["access_level"],
            tenant=tn,
        )
    return IngestionResult(
        documents_loaded=len(docs),
        chunks_created=len(chunks),
        chunks_indexed=indexed,
        sources=[source],
    )


def delete_indexed_source(source: str) -> None:
    """Remove all chunks, the registry row, and cached answers for a source."""
    delete_chunks_by_source(source)
    with get_conn() as conn:
        ensure_tables(conn)
        delete_document(conn, source)
        flush_cache(conn)
