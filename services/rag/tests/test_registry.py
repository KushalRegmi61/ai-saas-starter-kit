"""Registry + cache-flush SQL assertions (mock connection)."""

from unittest.mock import MagicMock

from rag.repo.neon_repo import (
    delete_document,
    ensure_tables,
    get_document,
    update_mtime,
    upsert_document,
)
from rag.retrieval.query_cache import flush_cache


def _mock_conn(fetchone=None):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = fetchone
    return conn


def test_upsert_document_uses_on_conflict_source():
    conn = _mock_conn()
    upsert_document(conn, "s.pdf", "abc123", 3)
    sql = conn.execute.call_args.args[0]
    assert "ON CONFLICT (source)" in sql


def test_get_document_returns_none_when_missing():
    conn = _mock_conn(fetchone=None)
    assert get_document(conn, "missing.pdf") is None


def test_update_mtime_issues_update():
    conn = _mock_conn()
    update_mtime(conn, "s.pdf", 123.0)
    sql = conn.execute.call_args.args[0]
    assert "UPDATE documents" in sql


def test_delete_document_issues_delete():
    conn = _mock_conn()
    delete_document(conn, "s.pdf")
    sql = conn.execute.call_args.args[0]
    assert "DELETE FROM documents" in sql


def test_ensure_tables_includes_file_mtime():
    conn = _mock_conn()
    ensure_tables(conn)
    statements = [c.args[0] for c in conn.execute.call_args_list]
    assert any("file_mtime" in s for s in statements)


def test_ensure_tables_enables_pgvector_first():
    conn = _mock_conn()
    ensure_tables(conn)
    statements = [c.args[0] for c in conn.execute.call_args_list]
    assert statements[0] == "CREATE EXTENSION IF NOT EXISTS vector"


def test_flush_cache_deletes_from_cache_table():
    conn = _mock_conn()
    flush_cache(conn)
    sql = conn.execute.call_args.args[0]
    assert "DELETE FROM query_cache" in sql


def test_flush_cache_expired_only_filters_expiry():
    conn = _mock_conn()
    flush_cache(conn, expired_only=True)
    sql = conn.execute.call_args.args[0]
    assert "DELETE FROM query_cache" in sql
    assert "expires_at" in sql
