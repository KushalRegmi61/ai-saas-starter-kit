"""Ingest/purge HTTP: token gate, 422 mapping, best-effort purge."""

from rag.types import IngestionResult

import api.ingest as ingest_mod
from agent.config import get_agent_settings
from main import app


def _client():
    from fastapi.testclient import TestClient

    return TestClient(app, raise_server_exceptions=False)


def _authed(monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "agent_service_token", "svc-test-token")
    return {"Authorization": "Bearer svc-test-token"}


def test_health_open():
    assert _client().get("/health").json() == {"status": "ok", "service": "agentic-assistant"}


def test_ingest_503_without_token(monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "agent_service_token", "")
    resp = _client().post(
        "/ingest",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"source": "uploads/u-1/doc.pdf"},
    )
    assert resp.status_code == 503


def test_ingest_401_on_bad_token(monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "agent_service_token", "svc-test-token")
    resp = _client().post(
        "/ingest",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"source": "s"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


def test_ingest_200_passthrough(monkeypatch):
    headers = _authed(monkeypatch)
    seen = {}

    def fake_index(content, filename, source, department=None, access_level=None, tenant=None):
        seen.update(
            content=content,
            filename=filename,
            source=source,
            department=department,
            access_level=access_level,
            tenant=tenant,
        )
        return IngestionResult(
            documents_loaded=1, chunks_created=2, chunks_indexed=2, sources=[source]
        )

    monkeypatch.setattr(ingest_mod, "index_document", fake_index)
    resp = _client().post(
        "/ingest",
        files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"source": "uploads/u-1/report.pdf", "department": "hr", "tenant": "api"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert seen == {
        "content": b"%PDF-1.4 fake",
        "filename": "report.pdf",
        "source": "uploads/u-1/report.pdf",
        "department": "hr",
        "access_level": None,
        "tenant": "api",
    }
    assert resp.json()["chunks_indexed"] == 2


def test_ingest_422_on_bad_content(monkeypatch):
    headers = _authed(monkeypatch)

    def boom(*a, **kw):
        raise ValueError("unsupported type")

    monkeypatch.setattr(ingest_mod, "index_document", boom)
    resp = _client().post(
        "/ingest",
        files={"file": ("x.bin", b"\x00", "application/octet-stream")},
        data={"source": "s"},
        headers=headers,
    )
    assert resp.status_code == 422


def test_delete_purges_and_reports(monkeypatch):
    headers = _authed(monkeypatch)
    purged = []
    monkeypatch.setattr(
        ingest_mod, "delete_indexed_source", lambda s, tenant=None: purged.append((s, tenant))
    )
    resp = _client().delete("/sources", params={"source": "s", "tenant": "api"}, headers=headers)
    assert resp.json() == {"purged": True}
    assert purged == [("s", "api")]


def test_delete_failure_returns_purged_false(monkeypatch):
    headers = _authed(monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(ingest_mod, "delete_indexed_source", boom)
    resp = _client().delete("/sources", params={"source": "s"}, headers=headers)
    assert resp.json() == {"purged": False}
