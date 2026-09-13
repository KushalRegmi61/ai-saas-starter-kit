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


def test_list_sources_returns_registry_rows(monkeypatch):
    headers = _authed(monkeypatch)
    seen = {}

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=()):
            seen["sql"] = sql
            seen["params"] = params

            class Result:
                def fetchall(self):
                    return [
                        ("api", "b.pdf", "hr", "internal", 2, None, "indexed"),
                    ]

            return Result()

    monkeypatch.setattr(ingest_mod, "get_conn", lambda: FakeConn())
    monkeypatch.setattr(ingest_mod, "ensure_tables", lambda conn: None)
    resp = _client().get("/sources", headers=headers)
    assert resp.status_code == 200
    assert "FROM documents" in seen["sql"]
    assert resp.json() == [
        {
            "tenant": "api",
            "source": "b.pdf",
            "department": "hr",
            "access_level": "internal",
            "chunks_count": 2,
            "indexed_at": None,
            "status": "indexed",
        }
    ]


def test_list_sources_401_on_bad_token(monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "agent_service_token", "svc-test-token")
    resp = _client().get("/sources", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_ingest_401_on_bad_token(monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "agent_service_token", "svc-test-token")
    resp = _client().post(
        "/ingest",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"source": "s"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


def test_ingest_202_queues_and_completes(monkeypatch):
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

    monkeypatch.setattr("service.ingest_jobs.index_document", fake_index)
    client = _client()
    resp = client.post(
        "/ingest",
        files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"source": "uploads/u-1/report.pdf", "department": "hr", "tenant": "api"},
        headers=headers,
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert resp.json()["status"] == "queued"
    assert seen == {
        "content": b"%PDF-1.4 fake",
        "filename": "report.pdf",
        "source": "uploads/u-1/report.pdf",
        "department": "hr",
        "access_level": None,
        "tenant": "api",
    }
    status = client.get(f"/ingest/{job_id}", headers=headers).json()
    assert status["status"] == "done"
    assert status["result"]["chunks_indexed"] == 2


def test_ingest_job_failed_status(monkeypatch):
    headers = _authed(monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr("service.ingest_jobs.index_document", boom)
    client = _client()
    resp = client.post(
        "/ingest",
        files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"source": "s"},
        headers=headers,
    )
    assert resp.status_code == 202
    status = client.get(f"/ingest/{resp.json()['job_id']}", headers=headers).json()
    assert status["status"] == "failed"
    assert "qdrant down" in (status["error"] or "")


def test_ingest_job_inherits_host_tenant_when_absent(monkeypatch):
    from types import SimpleNamespace

    import service.ingest_jobs as jobs

    seen = {}

    def fake_index(content, filename, source, department=None, access_level=None, tenant=None):
        seen["tenant"] = tenant
        return IngestionResult(documents_loaded=1, chunks_created=1, sources=[source])

    monkeypatch.setattr(jobs, "index_document", fake_index)
    monkeypatch.setattr(jobs, "get_agent_settings", lambda: SimpleNamespace(default_tenant="host"))
    job_id = jobs.create_job("s")
    jobs.run_index_job(job_id, b"x", "d.pdf", "s", None, None, None)
    assert seen["tenant"] == "host"


def test_ingest_job_keeps_explicit_tenant(monkeypatch):
    from types import SimpleNamespace

    import service.ingest_jobs as jobs

    seen = {}

    def fake_index(content, filename, source, department=None, access_level=None, tenant=None):
        seen["tenant"] = tenant
        return IngestionResult(documents_loaded=1, chunks_created=1, sources=[source])

    monkeypatch.setattr(jobs, "index_document", fake_index)
    monkeypatch.setattr(jobs, "get_agent_settings", lambda: SimpleNamespace(default_tenant="host"))
    job_id = jobs.create_job("s")
    jobs.run_index_job(job_id, b"x", "d.pdf", "s", None, None, "api")
    assert seen["tenant"] == "api"


def test_ingest_job_404_unknown(monkeypatch):
    headers = _authed(monkeypatch)
    resp = _client().get("/ingest/does-not-exist", headers=headers)
    assert resp.status_code == 404


def test_ingest_422_on_bad_content(monkeypatch):
    headers = _authed(monkeypatch)

    def boom(*a, **kw):
        raise AssertionError("indexing must not start for rejected content")

    monkeypatch.setattr("service.ingest_jobs.index_document", boom)
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
