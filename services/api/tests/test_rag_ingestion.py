"""Tests for ingest forwarding on upload finalize + purge on file delete.

finalize_upload best-effort forwards indexable types (pdf/txt) to the
agentic-assistant ``POST /ingest`` via ``repo/ingest_client`` and reports
``rag_indexed``; remove_file best-effort purges via ``DELETE /sources``.
Both degrade to success-without-indexing when the agent service is
unconfigured or the forward fails.
"""

from datetime import UTC, datetime

import pytest

from app.repo import ingest_client
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
def agent_configured(monkeypatch):
    """Pretend the agentic-assistant ingest surface is configured."""
    monkeypatch.setattr(upload_service.settings, "agent_service_url", "http://agent:8001")
    monkeypatch.setattr(upload_service.settings, "agent_service_token", "svc-token")


@pytest.fixture
def stored_pdf(monkeypatch):
    """A finalized PDF object: valid metadata + matching magic bytes."""
    key = f"uploads/{TEST_USER_ID}/report.pdf"
    monkeypatch.setattr(upload_service, "get_file_metadata", lambda k: _stored(k))
    monkeypatch.setattr(upload_service, "get_object_head_bytes", lambda k, **kw: b"%PDF-1.7\n...")
    return key


def _mock_b2_bytes(monkeypatch, payload: bytes = b"%PDF-1.7\n..."):
    monkeypatch.setattr(upload_service, "get_object_bytes", lambda k: payload)


# --- finalize_upload forward -------------------------------------------------


def test_finalize_pdf_indexes_and_reports_true(monkeypatch, agent_configured, stored_pdf):
    _mock_b2_bytes(monkeypatch)
    seen: dict = {}

    def fake_forward(content, filename, source, department=None, access_level=None, tenant=None):
        seen.update(
            content=content,
            filename=filename,
            source=source,
            department=department,
            access_level=access_level,
            tenant=tenant,
        )
        return True

    monkeypatch.setattr(ingest_client, "index_document_remote", fake_forward)

    result = finalize_upload(
        stored_pdf, user_id=TEST_USER_ID, department="hr", access_level="internal"
    )

    assert result.rag_indexed is True
    assert seen["content"] == b"%PDF-1.7\n..."  # content bytes
    assert seen["filename"] == "report.pdf"  # filename
    assert seen["source"] == stored_pdf  # source == key
    assert seen["department"] == "hr"
    assert seen["tenant"] == "api"
    assert seen["access_level"] == "internal"


def test_finalize_png_skips_forward(monkeypatch, agent_configured):
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
    monkeypatch.setattr(
        ingest_client, "index_document_remote", lambda *a, **kw: called.append(a) or True
    )

    result = finalize_upload(key, user_id=TEST_USER_ID)

    assert result.rag_indexed is False
    assert called == []


def test_finalize_forward_failure_still_succeeds(monkeypatch, agent_configured, stored_pdf):
    _mock_b2_bytes(monkeypatch)
    monkeypatch.setattr(ingest_client, "index_document_remote", lambda *a, **kw: False)

    result = finalize_upload(stored_pdf, user_id=TEST_USER_ID)

    assert result.key == stored_pdf
    assert result.rag_indexed is False


def test_finalize_forward_exception_still_succeeds(monkeypatch, agent_configured, stored_pdf):
    _mock_b2_bytes(monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("agent down")

    monkeypatch.setattr(ingest_client, "index_document_remote", boom)

    result = finalize_upload(stored_pdf, user_id=TEST_USER_ID)

    assert result.rag_indexed is False


def test_finalize_unconfigured_agent_skips_forward(monkeypatch, stored_pdf):
    # Real adapter, empty settings: returns False with no HTTP attempt.
    monkeypatch.setattr(upload_service.settings, "agent_service_url", "")
    monkeypatch.setattr(upload_service.settings, "agent_service_token", "")

    result = finalize_upload(stored_pdf, user_id=TEST_USER_ID)

    assert result.rag_indexed is False


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
    auth_client, monkeypatch, agent_configured, stored_pdf
):
    _mock_b2_bytes(monkeypatch)
    monkeypatch.setattr(ingest_client, "index_document_remote", lambda *a, **kw: True)

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
async def test_complete_endpoint_forward_failure_still_200(
    auth_client, monkeypatch, agent_configured, stored_pdf
):
    _mock_b2_bytes(monkeypatch)
    monkeypatch.setattr(ingest_client, "index_document_remote", lambda *a, **kw: False)

    resp = await auth_client.post("/upload/complete", json={"key": stored_pdf})
    assert resp.status_code == 200
    assert resp.json()["rag_indexed"] is False


@pytest.mark.asyncio
async def test_complete_endpoint_rejects_unknown_department(auth_client, stored_pdf):
    resp = await auth_client.post("/upload/complete", json={"key": stored_pdf, "department": "foo"})
    assert resp.status_code == 400


# --- remove_file purge ----------------------------------------------------------


def test_remove_file_purges_indexed_source(monkeypatch):
    monkeypatch.setattr(files_service.settings, "agent_service_url", "http://agent:8001")
    monkeypatch.setattr(files_service.settings, "agent_service_token", "svc-token")
    monkeypatch.setattr(files_service, "delete_file", lambda k: None)
    purged: list[str] = []
    purged_tenant: list[str] = []

    def fake_purge(source, tenant=None):
        purged.append(source)
        purged_tenant.append(tenant)
        return True

    monkeypatch.setattr(ingest_client, "delete_indexed_source_remote", fake_purge)

    files_service.remove_file(TEST_USER_ID, f"uploads/{TEST_USER_ID}/report.pdf")

    assert purged == [f"uploads/{TEST_USER_ID}/report.pdf"]
    assert purged_tenant == ["api"]


def test_remove_file_purge_failure_still_deletes(monkeypatch):
    monkeypatch.setattr(files_service.settings, "agent_service_url", "http://agent:8001")
    monkeypatch.setattr(files_service.settings, "agent_service_token", "svc-token")
    monkeypatch.setattr(files_service, "delete_file", lambda k: None)

    def boom(source, tenant=None):
        raise RuntimeError("agent down")

    monkeypatch.setattr(ingest_client, "delete_indexed_source_remote", boom)

    # Must not raise — the B2 delete already succeeded.
    files_service.remove_file(TEST_USER_ID, f"uploads/{TEST_USER_ID}/report.pdf")


def test_remove_file_unconfigured_skips_purge(monkeypatch):
    # Real adapter, empty settings: returns False with no HTTP attempt.
    monkeypatch.setattr(files_service.settings, "agent_service_url", "")
    monkeypatch.setattr(files_service.settings, "agent_service_token", "")
    monkeypatch.setattr(files_service, "delete_file", lambda k: None)

    files_service.remove_file(TEST_USER_ID, f"uploads/{TEST_USER_ID}/report.pdf")
