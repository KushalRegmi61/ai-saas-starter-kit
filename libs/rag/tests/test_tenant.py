from rag.repo.neon_repo import SimpleDoc as _SimpleDoc
from rag.retrieval.rbac import normalize_tenant, passes_access_filter
from rag.types import AccessFilter


def SimpleDocForTest(**kw):
    meta = {"source": "s", "department": "general", "access_level": "internal"}
    meta.update(kw.pop("metadata", {}))
    return _SimpleDoc(text=kw.pop("text", "hello"), metadata=meta)


class _FakeConnCtx:
    def __init__(self):
        self.conn = object()

    def __call__(self):
        return self

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


class FakeConn:
    """Mock connection recording execute(sql, params) calls (test_registry.py style)."""

    def __init__(self, fetchone=None):
        self.executed = []
        self._fetchone = fetchone

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def fetchone(self):
        return self._fetchone

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


def test_access_filter_carries_tenant_and_attributes():
    filt = AccessFilter(
        departments=["hr", "all", "general"],
        max_access_level=1,
        tenant="api",
        attributes={"project": "knowledge-assistant"},
    )
    assert filt.tenant == "api"
    assert filt.attributes == {"project": "knowledge-assistant"}


def test_access_filter_defaults_preserve_legacy_behavior():
    filt = AccessFilter(departments=["all"], max_access_level=0)
    assert filt.tenant is None
    assert filt.attributes == {}


def test_normalize_tenant():
    assert normalize_tenant(None) == "default"
    assert normalize_tenant("") == "default"
    assert normalize_tenant("api") == "api"


def test_passes_access_filter_enforces_tenant():
    meta = {"department": "hr", "access_level": "internal", "tenant": "api"}
    assert passes_access_filter(meta, ["hr"], 3, tenant="api") is True
    assert passes_access_filter(meta, ["hr"], 3, tenant="other") is False
    # Legacy points without a tenant key read as "default"
    legacy = {"department": "hr", "access_level": "internal"}
    assert passes_access_filter(legacy, ["hr"], 3, tenant="default") is True
    assert passes_access_filter(legacy, ["hr"], 3, tenant="api") is False
    # No tenant in filter disables the check (legacy behavior)
    assert passes_access_filter(meta, ["hr"], 3) is True


def test_qdrant_filter_includes_tenant():
    from rag.repo import qdrant_repo

    f = qdrant_repo._qdrant_filter(["hr"], 1, tenant="api")
    keys = [c.key for c in f.must]
    assert "tenant" in keys
    tenant_cond = next(c for c in f.must if c.key == "tenant")
    assert tenant_cond.match.value == "api"


def test_qdrant_filter_without_tenant_unchanged():
    from rag.repo import qdrant_repo

    f = qdrant_repo._qdrant_filter(["hr"], 1)
    assert [c.key for c in f.must] == ["department", "access_level"]


def test_index_document_stamps_tenant_and_explicit_metadata(monkeypatch):
    import rag.ingestion.index as idx

    captured = {}

    monkeypatch.setattr(idx, "load_bytes", lambda content, filename: [SimpleDocForTest()])
    monkeypatch.setattr(idx, "chunk_documents", lambda docs: docs)
    monkeypatch.setattr(idx, "embed_texts", lambda texts: [[0.0] * 4 for _ in texts])
    monkeypatch.setattr(idx, "ensure_collection", lambda: None)
    def fake_upsert(chunks, vectors):
        captured["payload"] = dict(chunks[0].metadata)
        return 1

    monkeypatch.setattr(idx, "upsert_chunks", fake_upsert)
    monkeypatch.setattr(idx, "get_conn", _FakeConnCtx())
    monkeypatch.setattr(idx, "ensure_tables", lambda conn: None)
    monkeypatch.setattr(idx, "get_document", lambda conn, source, tenant="default": None)
    monkeypatch.setattr(idx, "delete_chunks_by_source", lambda source, tenant="default": None)
    monkeypatch.setattr(idx, "flush_cache", lambda conn, tenant=None: 0)
    monkeypatch.setattr(idx, "upsert_document", lambda conn, **kw: captured.update(registry=kw))

    from rag.ingestion.index import index_document

    index_document(b"x", "hr_policy.pdf", source="s", department="hr", access_level="confidential", tenant="api")
    assert captured["payload"]["tenant"] == "api"
    assert captured["payload"]["department"] == "hr"
    assert captured["payload"]["access_level"] == "confidential"
    assert captured["registry"]["tenant"] == "api"


def test_semantic_search_meta_carries_tenant(monkeypatch):
    from types import SimpleNamespace

    import rag.repo.qdrant_repo as qr

    point = SimpleNamespace(
        payload={
            "text": "hello",
            "source": "s",
            "page": 1,
            "chunk_index": 0,
            "department": "hr",
            "access_level": "internal",
            "tenant": "api",
        },
        score=0.9,
    )
    client = SimpleNamespace(
        query_points=lambda **kw: SimpleNamespace(points=[point]),
    )
    monkeypatch.setattr(qr, "_cached_client", lambda: client)
    monkeypatch.setattr(
        qr, "get_rag_settings", lambda: SimpleNamespace(qdrant_collection="chunks")
    )
    results = qr.semantic_search([0.1] * 4, 5, ["hr"], 3, tenant="api")
    assert results[0][0].metadata["tenant"] == "api"


def test_scroll_corpus_meta_carries_tenant(monkeypatch):
    from types import SimpleNamespace

    import rag.repo.qdrant_repo as qr

    point = SimpleNamespace(
        payload={
            "text": "hello",
            "source": "s",
            "page": 1,
            "chunk_index": 0,
            "department": "hr",
            "access_level": "internal",
            "tenant": "api",
        },
    )
    client = SimpleNamespace(
        scroll=lambda **kw: ([point], None),
    )
    monkeypatch.setattr(qr, "_cached_client", lambda: client)
    monkeypatch.setattr(
        qr, "get_rag_settings", lambda: SimpleNamespace(qdrant_collection="chunks")
    )
    docs = qr.scroll_corpus(["hr"], 3, limit=10, tenant="api")
    assert docs[0].metadata["tenant"] == "api"


def test_ensure_tables_adds_tenant_column_and_composite_key():
    from rag.repo import neon_repo

    conn = FakeConn()
    neon_repo.ensure_tables(conn)
    stmts = [sql for sql, _ in conn.executed]
    assert any("ADD COLUMN IF NOT EXISTS tenant" in s for s in stmts)
    assert any("tenant" in s and "source" in s and "PRIMARY KEY" in s for s in stmts)


def test_upsert_document_scopes_conflict_to_tenant():
    from rag.repo import neon_repo

    conn = FakeConn()
    neon_repo.upsert_document(conn, source="s", content_hash="h", chunks_count=1, tenant="api")
    sql, params = conn.executed[-1]
    assert "ON CONFLICT (tenant, source)" in sql
    assert params[0] == "api"  # tenant is the FIRST bound param after the column reorder
    assert params[1] == "s"


def test_get_and_delete_document_filter_by_tenant():
    from rag.repo import neon_repo

    conn = FakeConn()
    neon_repo.get_document(conn, "s", tenant="api")
    assert "tenant = %s" in conn.executed[-1][0]
    assert conn.executed[-1][1] == ("api", "s")
    neon_repo.delete_document(conn, "s", tenant="api")
    assert "tenant = %s" in conn.executed[-1][0]
