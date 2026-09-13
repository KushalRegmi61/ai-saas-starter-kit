"""Qdrant write path: payload keys, deterministic ids, delete filter, dimension guard."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import rag.repo.qdrant_repo as qr
from rag.config import RagSettings
from rag.repo.neon_repo import SimpleDoc

PAYLOAD_KEYS = {"text", "source", "page", "chunk_index", "department", "access_level", "tenant"}


def _settings(dims: int = 4) -> RagSettings:
    return RagSettings(
        qdrant_url="http://localhost:6333",
        qdrant_collection="chunks",
        embedding_dimensions=dims,
    )


def _doc(text="hello", **meta) -> SimpleDoc:
    base = {
        "source": "hr_policy.pdf",
        "page": 2,
        "chunk_index": 0,
        "department": "hr",
        "access_level": "confidential",
    }
    base.update(meta)
    return SimpleDoc(text=text, metadata=base)


def _mock_client(monkeypatch, settings) -> MagicMock:
    client = MagicMock()
    monkeypatch.setattr(qr, "_cached_client", lambda: client)
    monkeypatch.setattr(qr, "get_rag_settings", lambda: settings)
    return client


def test_chunk_id_deterministic():
    first = qr._chunk_id("s.pdf", 0, "hello")
    assert first == qr._chunk_id("s.pdf", 0, "hello")
    assert len(first) == 36
    assert first.count("-") == 4
    assert qr._chunk_id("s.pdf", 1, "hello") != first
    assert qr._chunk_id("s.pdf", 0, "other") != first


def test_upsert_payload_keys_exact(monkeypatch):
    client = _mock_client(monkeypatch, _settings())
    chunks = [_doc(), _doc(text="second", chunk_index=1, page=3)]
    vectors = [[0.1] * 4, [0.2] * 4]
    assert qr.upsert_chunks(chunks, vectors) == 2
    _, kwargs = client.upsert.call_args
    assert kwargs["collection_name"] == "chunks"
    points = kwargs["points"]
    assert len(points) == 2
    for point, chunk in zip(points, chunks, strict=True):
        assert set(point.payload.keys()) == PAYLOAD_KEYS
        assert point.payload["text"] == chunk.text
        assert point.payload["source"] == "hr_policy.pdf"
        assert point.payload["page"] == chunk.metadata["page"]
        assert point.payload["chunk_index"] == chunk.metadata["chunk_index"]
        assert point.payload["department"] == "hr"
        assert point.payload["access_level"] == "confidential"
        assert point.payload["tenant"] == chunk.metadata.get("tenant", "default")
        assert list(point.vector) == [0.1] * 4 or list(point.vector) == [0.2] * 4


def test_upsert_ids_stable_across_calls(monkeypatch):
    client = _mock_client(monkeypatch, _settings())
    chunks = [_doc()]
    vectors = [[0.1] * 4]
    qr.upsert_chunks(chunks, vectors)
    first_ids = [p.id for p in client.upsert.call_args[1]["points"]]
    qr.upsert_chunks(chunks, vectors)
    second_ids = [p.id for p in client.upsert.call_args[1]["points"]]
    assert first_ids == second_ids


def test_upsert_empty_returns_zero(monkeypatch):
    client = _mock_client(monkeypatch, _settings())
    assert qr.upsert_chunks([], []) == 0
    client.upsert.assert_not_called()


def test_upsert_length_mismatch_raises(monkeypatch):
    _mock_client(monkeypatch, _settings())
    with pytest.raises(ValueError, match="same length"):
        qr.upsert_chunks([_doc()], [[0.1] * 4, [0.2] * 4])


def test_delete_builds_source_filter(monkeypatch):
    from qdrant_client.http.models import FieldCondition, Filter, MatchValue

    client = _mock_client(monkeypatch, _settings())
    qr.delete_chunks_by_source("hr_policy.pdf")
    _, kwargs = client.delete.call_args
    assert kwargs["collection_name"] == "chunks"
    selector = kwargs["points_selector"]
    assert isinstance(selector, Filter)
    assert selector.must == [
        FieldCondition(key="source", match=MatchValue(value="hr_policy.pdf")),
    ]


def test_dimensions_noop_when_collection_missing(monkeypatch):
    client = _mock_client(monkeypatch, _settings())
    client.collection_exists.return_value = False
    qr.assert_collection_dimensions()  # must not raise
    client.scroll.assert_not_called()


def test_dimensions_noop_when_collection_empty(monkeypatch):
    client = _mock_client(monkeypatch, _settings())
    client.collection_exists.return_value = True
    client.scroll.return_value = ([], None)
    qr.assert_collection_dimensions()  # must not raise
    _, kwargs = client.scroll.call_args
    assert kwargs["limit"] == 1
    assert kwargs["with_vectors"] is True


def test_dimensions_raises_on_mismatch(monkeypatch):
    client = _mock_client(monkeypatch, _settings(dims=4))
    client.collection_exists.return_value = True
    client.scroll.return_value = ([SimpleNamespace(vector=[0.1] * 8, payload={})], None)
    with pytest.raises(ValueError, match="dimension"):
        qr.assert_collection_dimensions()


def test_dimensions_passes_on_match(monkeypatch):
    client = _mock_client(monkeypatch, _settings(dims=4))
    client.collection_exists.return_value = True
    client.scroll.return_value = ([SimpleNamespace(vector=[0.1] * 4, payload={})], None)
    qr.assert_collection_dimensions()  # must not raise


def test_ensure_collection_creates_when_missing(monkeypatch):
    from qdrant_client.http.models import Distance

    client = _mock_client(monkeypatch, _settings(dims=4))
    client.collection_exists.return_value = False
    qr.ensure_collection()
    _, kwargs = client.create_collection.call_args
    assert kwargs["collection_name"] == "chunks"
    assert kwargs["vectors_config"].size == 4
    assert kwargs["vectors_config"].distance == Distance.COSINE


def test_ensure_collection_noop_when_exists(monkeypatch):
    client = _mock_client(monkeypatch, _settings())
    client.collection_exists.return_value = True
    client.scroll.return_value = ([], None)
    qr.ensure_collection()
    client.create_collection.assert_not_called()
