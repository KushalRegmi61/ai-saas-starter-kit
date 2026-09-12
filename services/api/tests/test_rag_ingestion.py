"""Tests for RAG auto-index on upload finalize + purge on file delete (Phase 2).

finalize_upload best-effort indexes indexable types (pdf/txt) into RAG and
reports ``rag_indexed``; remove_file best-effort purges the indexed source.
Both degrade to success-without-RAG when unconfigured or on RAG failure.
"""

from datetime import UTC, datetime

import pytest
import rag

from app.service import files as files_service
from app.service import upload as upload_service
from app.service.upload import UploadError, finalize_upload
from app.types import FileMetadata

from .conftest import TEST_USER_ID


def _stored(key: str, *, content_type: str = "application/pdf") -> FileMetadata:
    """Build a FileMetadata as get_file_metadata would return it after a PUT."""
    return FileMetadata(
        key=key,
        filename=key.rsplit("/", 1)[-1],
        folder=key.rsplit("/", 1)[0] + "/",
        size_bytes=9,
        size_human="9 B",
        content_type=content_type,
        uploaded_at=datetime.now(UTC),
        url=None,
    )


@pytest.fixture
def rag_configured(monkeypatch):
    """Pretend Qdrant + the RAG registry are configured."""
    monkeypatch.setattr(upload_service.settings, "qdrant_url", "http://qdrant:6333")
    monkeypatch.setattr(upload_service.settings, "rag_database_url", "postgresql://rag")


@pytest.fixture
def stored_pdf(monkeypatch):
    """A finalized PDF object: valid metadata + matching magic bytes."""
    key = f"uploads/{TEST_USER_ID}/report.pdf"
    monkeypatch.setattr(upload_service, "get_file_metadata", lambda k: _stored(k))
    monkeypatch.setattr(upload_service, "get_object_head_bytes", lambda k, **kw: b"%PDF-1.7\n...")
    return key


def _mock_b2_bytes(monkeypatch, payload: bytes = b"%PDF-1.7\n..."):
    monkeypatch.setattr(upload_service, "get_object_bytes", lambda k: payload)


# --- finalize_upload auto-index ------------------------------------------------


def test_finalize_pdf_indexes_and_reports_true(monkeypatch, rag_configured, stored_pdf):
    _mock_b2_bytes(monkeypatch)
    seen: dict = {}

    def fake_index(*args, **kwargs):
        seen["_args"] = args
        seen.update(kwargs)
        return None

    monkeypatch.setattr(rag, "index_document", fake_index)

    result = finalize_upload(
        stored_pdf, user_id=TEST_USER_ID, department="hr", access_level="internal"
    )

    assert result.rag_indexed is True
    args = seen["_args"]
    assert args[0] == b"%PDF-1.7\n..."  # content bytes
    assert args[1] == "report.pdf"  # filename
    assert seen["source"] == stored_pdf  # source == key
    assert seen["department"] == "hr"
    assert seen["tenant"] == "api"
    assert seen["access_level"] == "internal"


def test_finalize_png_skips_index(monkeypatch, rag_configured):
    key = f"uploads/{TEST_USER_ID}/photo.png"
    monkeypatch.setattr(
        upload_service,
        "get_file_metadata",
        lambda k: _stored(k, content_type="image/png"),
    )
    monkeypatch.setattr(
        upload_service,
        "get_object_head_bytes",
        lambda k, **kw: b"\x89PNG\r\n\x1a\n....",
    )
    called: list = []
    monkeypatch.setattr(rag, "index_document", lambda *a, **kw: called.append(a))

    result = finalize_upload(key, user_id=TEST_USER_ID)

    assert result.rag_indexed is False
    assert called == []


def test_finalize_index_failure_still_succeeds(monkeypatch, rag_configured, stored_pdf):
    _mock_b2_bytes(monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(rag, "index_document", boom)

    result = finalize_upload(stored_pdf, user_id=TEST_USER_ID)

    assert result.key == stored_pdf
    assert result.rag_indexed is False


def test_finalize_index_value_error_still_succeeds(monkeypatch, rag_configured, stored_pdf):
    _mock_b2_bytes(monkeypatch)

    def boom(*a, **kw):
        raise ValueError("unsupported bytes")

    monkeypatch.setattr(rag, "index_document", boom)

    result = finalize_upload(stored_pdf, user_id=TEST_USER_ID)

    assert result.rag_indexed is False


def test_finalize_unconfigured_rag_skips_index(monkeypatch, stored_pdf):
    monkeypatch.setattr(upload_service.settings, "qdrant_url", "")
    monkeypatch.setattr(upload_service.settings, "rag_database_url", "")
    called: list = []
    monkeypatch.setattr(rag, "index_document", lambda *a, **kw: called.append(a))

    result = finalize_upload(stored_pdf, user_id=TEST_USER_ID)

    assert result.rag_indexed is False
    assert called == []


def test_finalize_rejects_unknown_department(monkeypatch, stored_pdf):
    with pytest.raises(UploadError) as exc:
        finalize_upload(stored_pdf, user_id=TEST_USER_ID, department="foo")
    assert exc.value.status_code == 400


def test_finalize_rejects_unknown_access_level(monkeypatch, stored_pdf):
    with pytest.raises(UploadError) as exc:
        finalize_upload(stored_pdf, user_id=TEST_USER_ID, access_level="foo")
    assert exc.value.status_code == 400


# --- endpoints -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_endpoint_reports_rag_indexed(
    auth_client, monkeypatch, rag_configured, stored_pdf
):
    _mock_b2_bytes(monkeypatch)
    monkeypatch.setattr(rag, "index_document", lambda *a, **kw: None)

    resp = await auth_client.post(
        "/upload/complete",
        json={
            "key": stored_pdf,
            "department": "hr",
            "access_level": "internal",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["rag_indexed"] is True


@pytest.mark.asyncio
async def test_complete_endpoint_index_failure_still_200(
    auth_client, monkeypatch, rag_configured, stored_pdf
):
    _mock_b2_bytes(monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(rag, "index_document", boom)

    resp = await auth_client.post("/upload/complete", json={"key": stored_pdf})
    assert resp.status_code == 200
    assert resp.json()["rag_indexed"] is False


@pytest.mark.asyncio
async def test_complete_endpoint_rejects_unknown_department(auth_client, stored_pdf):
    resp = await auth_client.post("/upload/complete", json={"key": stored_pdf, "department": "foo"})
    assert resp.status_code == 400


# --- remove_file purge ----------------------------------------------------------


def test_remove_file_purges_indexed_source(monkeypatch):
    monkeypatch.setattr(files_service.settings, "qdrant_url", "http://qdrant:6333")
    monkeypatch.setattr(files_service.settings, "rag_database_url", "postgresql://rag")
    deleted: list[str] = []
    monkeypatch.setattr(files_service, "delete_file", lambda k: deleted.append(k))
    purged: list[str] = []
    purged_tenant: list[str] = []
    def fake_purge(source, *, tenant):
        purged.append(source)
        purged_tenant.append(tenant)
    monkeypatch.setattr(rag, "delete_indexed_source", fake_purge)

    files_service.remove_file(TEST_USER_ID, f"uploads/{TEST_USER_ID}/report.pdf")

    assert deleted == [f"uploads/{TEST_USER_ID}/report.pdf"]
    assert purged == [f"uploads/{TEST_USER_ID}/report.pdf"]
    assert purged_tenant == ["api"]


def test_remove_file_purge_failure_still_deletes(monkeypatch):
    monkeypatch.setattr(files_service.settings, "qdrant_url", "http://qdrant:6333")
    monkeypatch.setattr(files_service.settings, "rag_database_url", "postgresql://rag")
    monkeypatch.setattr(files_service, "delete_file", lambda k: None)

    def boom(source, **kw):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(rag, "delete_indexed_source", boom)

    # Must not raise — the B2 delete already succeeded.
    files_service.remove_file(TEST_USER_ID, f"uploads/{TEST_USER_ID}/report.pdf")


def test_remove_file_unconfigured_skips_purge(monkeypatch):
    monkeypatch.setattr(files_service.settings, "qdrant_url", "")
    monkeypatch.setattr(files_service.settings, "rag_database_url", "")
    monkeypatch.setattr(files_service, "delete_file", lambda k: None)
    purged: list[str] = []
    monkeypatch.setattr(rag, "delete_indexed_source", lambda s, **kw: purged.append(s))

    files_service.remove_file(TEST_USER_ID, f"uploads/{TEST_USER_ID}/report.pdf")

    assert purged == []
