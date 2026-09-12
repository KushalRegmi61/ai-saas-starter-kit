"""index_document() + delete_indexed_source() (mock registry/embed/qdrant).

Real loaders, chunker, and metadata inference; registry, embedding, and
qdrant boundaries are monkeypatched.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock

import rag.ingestion.index as idx


def _fake_conn_ctx(conn: MagicMock):
    @contextmanager
    def _ctx() -> Iterator[MagicMock]:
        yield conn

    return _ctx


def _patch_registry(monkeypatch, conn: MagicMock, existing: dict | None):
    monkeypatch.setattr(idx, "get_conn", _fake_conn_ctx(conn))
    monkeypatch.setattr(idx, "ensure_tables", MagicMock())
    monkeypatch.setattr(idx, "get_document", MagicMock(return_value=existing))
    monkeypatch.setattr(idx, "upsert_document", MagicMock())
    monkeypatch.setattr(idx, "delete_document", MagicMock())
    monkeypatch.setattr(idx, "delete_chunks_by_source", MagicMock())
    monkeypatch.setattr(idx, "ensure_collection", MagicMock())
    monkeypatch.setattr(idx, "flush_cache", MagicMock())
    monkeypatch.setattr(idx, "embed_texts", MagicMock(side_effect=lambda ts: [[0.1]] * len(ts)))
    monkeypatch.setattr(idx, "upsert_chunks", MagicMock(side_effect=lambda c, v: len(c)))


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_unchanged_bytes_short_circuit(monkeypatch):
    conn = MagicMock()
    content = b"hello world"
    _patch_registry(monkeypatch, conn, {"content_hash": _content_hash("hello world")})
    result = idx.index_document(content, "notes.txt", "notes.txt")
    assert result.documents_loaded == 0
    assert result.chunks_created == 0
    assert result.chunks_indexed == 0
    assert result.sources == ["notes.txt"]
    assert isinstance(idx.upsert_chunks, MagicMock)
    idx.upsert_chunks.assert_not_called()
    idx.delete_chunks_by_source.assert_not_called()


def test_empty_load_returns_all_zero(monkeypatch):
    conn = MagicMock()
    _patch_registry(monkeypatch, conn, None)
    result = idx.index_document(b"", "empty.txt", "empty.txt")
    # Empty txt decodes to empty text -> one doc with empty text; chunker yields no chunks.
    # Either way nothing may be indexed.
    assert result.sources == ["empty.txt"]
    assert result.chunks_indexed == 0


def test_changed_bytes_delete_before_upsert(monkeypatch):
    conn = MagicMock()
    _patch_registry(monkeypatch, conn, {"content_hash": "stale-hash"})
    order: list[str] = []
    assert isinstance(idx.delete_chunks_by_source, MagicMock)
    assert isinstance(idx.upsert_chunks, MagicMock)
    idx.delete_chunks_by_source.side_effect = lambda _s, **kw: order.append("delete")
    idx.upsert_chunks.side_effect = lambda _c, _v: (order.append("upsert"), 1)[1]
    result = idx.index_document(b"fresh content here", "notes.txt", "notes.txt")
    assert order == ["delete", "upsert"]
    assert result.documents_loaded == 1
    assert result.chunks_indexed == 1
    assert result.sources == ["notes.txt"]
    idx.ensure_collection.assert_called_once()
    idx.flush_cache.assert_called_once_with(conn, tenant="default")


def test_explicit_metadata_beats_inference(monkeypatch):
    conn = MagicMock()
    _patch_registry(monkeypatch, conn, None)
    idx.index_document(
        b"policy text",
        "hr_policy.txt",
        "hr_policy.txt",
        department="finance",
        access_level="public",
    )
    assert isinstance(idx.upsert_document, MagicMock)
    _, kwargs = idx.upsert_document.call_args
    assert kwargs["department"] == "finance"
    assert kwargs["access_level"] == "public"


def test_inferred_metadata_used_by_default(monkeypatch):
    conn = MagicMock()
    _patch_registry(monkeypatch, conn, None)
    idx.index_document(b"policy text", "hr_policy.txt", "hr_policy.txt")
    _, kwargs = idx.upsert_document.call_args
    assert kwargs["department"] == "hr"
    assert kwargs["access_level"] == "confidential"


def test_delete_indexed_source_purges_all_three(monkeypatch):
    conn = MagicMock()
    _patch_registry(monkeypatch, conn, None)
    idx.delete_indexed_source("notes.txt")
    idx.delete_chunks_by_source.assert_called_once_with("notes.txt", tenant="default")
    assert isinstance(idx.ensure_tables, MagicMock)
    idx.ensure_tables.assert_called_once_with(conn)
    idx.delete_document.assert_called_once_with(conn, "notes.txt", tenant="default")
    idx.flush_cache.assert_called_once_with(conn, tenant="default")
