"""Unit tests for repo/ingest_client: URL building, status mapping, never-raises."""

from app.config import settings
from app.repo import ingest_client


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"purged": True}

    def json(self):
        return self._payload


def _configured(monkeypatch):
    monkeypatch.setattr(settings, "agent_service_url", "http://agent:8001/")
    monkeypatch.setattr(settings, "agent_service_token", "svc-token")


def test_index_200_true_and_posts_multipart(monkeypatch):
    _configured(monkeypatch)
    seen = {}

    def fake_post(url, files=None, data=None, headers=None, timeout=None):
        seen.update(url=url, files=files, data=data, headers=headers, timeout=timeout)
        return _Resp(200)

    monkeypatch.setattr(ingest_client.httpx, "post", fake_post)
    assert ingest_client.index_document_remote(b"bytes", "r.pdf", source="s", tenant="api") is True
    assert seen["url"] == "http://agent:8001/ingest"  # trailing slash stripped
    assert seen["files"] == {"file": ("r.pdf", b"bytes")}
    assert seen["data"] == {"source": "s", "tenant": "api"}  # Nones omitted
    assert seen["headers"] == {"Authorization": "Bearer svc-token"}


def test_index_non_200_false(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(ingest_client.httpx, "post", lambda **kw: _Resp(422))
    assert ingest_client.index_document_remote(b"b", "f", source="s") is False


def test_index_exception_false(monkeypatch):
    _configured(monkeypatch)

    def boom(**kw):
        raise RuntimeError("down")

    monkeypatch.setattr(ingest_client.httpx, "post", boom)
    assert ingest_client.index_document_remote(b"b", "f", source="s") is False


def test_index_unconfigured_false(monkeypatch):
    monkeypatch.setattr(settings, "agent_service_url", "")
    monkeypatch.setattr(settings, "agent_service_token", "")
    assert ingest_client.index_document_remote(b"b", "f", source="s") is False


def test_delete_true_only_on_purged(monkeypatch):
    _configured(monkeypatch)
    seen = {}

    def fake_delete(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params)
        return _Resp(200, {"purged": True})

    monkeypatch.setattr(ingest_client.httpx, "delete", fake_delete)
    assert ingest_client.delete_indexed_source_remote("s", tenant="api") is True
    assert seen["url"] == "http://agent:8001/sources"
    assert seen["params"] == {"source": "s", "tenant": "api"}


def test_delete_false_on_not_purged_or_error(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(ingest_client.httpx, "delete", lambda **kw: _Resp(200, {"purged": False}))
    assert ingest_client.delete_indexed_source_remote("s") is False
    monkeypatch.setattr(ingest_client.httpx, "delete", lambda **kw: _Resp(500))
    assert ingest_client.delete_indexed_source_remote("s") is False

    def boom(**kw):
        raise RuntimeError("down")

    monkeypatch.setattr(ingest_client.httpx, "delete", boom)
    assert ingest_client.delete_indexed_source_remote("s") is False
