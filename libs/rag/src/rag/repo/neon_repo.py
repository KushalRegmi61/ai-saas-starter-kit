"""Neon Postgres adapter: documents registry + query cache + rate-limit counters."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from rag.config import get_rag_settings
from rag.retrieval.rbac import normalize_tenant

_pool = None


@dataclass
class SimpleDoc:
    """Minimal Document shape (page_content/metadata) without langchain dependency."""

    text: str
    metadata: dict

    @property
    def page_content(self) -> str:
        return self.text


def init_pool() -> None:
    global _pool
    if _pool is not None:
        return
    try:
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise ImportError("psycopg-pool is required. Run: pip install psycopg-pool") from exc
    s = get_rag_settings()
    if not s.rag_database_url:
        raise ValueError("RAG_DATABASE_URL is missing. Set it before retrieval.")
    _pool = ConnectionPool(conninfo=s.rag_database_url, min_size=2, max_size=10, open=True)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn():
    if _pool is None:
        init_pool()
    assert _pool is not None
    with _pool.connection() as conn:
        yield conn


def _now() -> datetime:
    return datetime.now(UTC)


def ensure_tables(connection) -> None:
    from rag.retrieval.query_cache import ensure_cache_table

    # pgvector backs query_cache.question_vec + its HNSW index. Self-provision
    # so a fresh database works without manual setup; no-op when installed.
    connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            source TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            file_mtime DOUBLE PRECISION,
            department TEXT,
            access_level TEXT,
            chunks_count INTEGER DEFAULT 0,
            indexed_at TIMESTAMPTZ,
            status TEXT DEFAULT 'indexed'
        )
        """
    )
    connection.execute(
        """
        ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_mtime DOUBLE PRECISION
        """
    )
    connection.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS tenant TEXT DEFAULT 'default'"
    )
    connection.execute("UPDATE documents SET tenant = 'default' WHERE tenant IS NULL")
    connection.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_pkey")
    connection.execute(
        """
        DO $$ BEGIN
            ALTER TABLE documents ADD PRIMARY KEY (tenant, source);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    ensure_cache_table(connection, dims=get_rag_settings().embedding_dimensions)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_limit_counters (
            subject TEXT NOT NULL,
            window_key BIGINT NOT NULL,
            request_count INTEGER DEFAULT 1,
            PRIMARY KEY (subject, window_key)
        )
        """
    )


def get_document(connection, source: str, tenant: str | None = None) -> dict | None:
    tn = normalize_tenant(tenant)
    row = connection.execute(
        "SELECT source, content_hash, file_mtime, department, access_level, "
        "chunks_count, indexed_at, status FROM documents WHERE tenant = %s AND source = %s",
        (tn, source),
    ).fetchone()
    if not row:
        return None
    return {
        "source": row[0],
        "content_hash": row[1],
        "file_mtime": row[2],
        "department": row[3],
        "access_level": row[4],
        "chunks_count": row[5],
        "indexed_at": row[6].isoformat() if row[6] else None,
        "status": row[7],
    }


def upsert_document(
    connection,
    source: str,
    content_hash: str,
    chunks_count: int,
    department: str = "general",
    access_level: str = "internal",
    file_mtime: float | None = None,
    tenant: str = "default",
) -> None:
    tn = normalize_tenant(tenant)
    connection.execute(
        """
        INSERT INTO documents
            (tenant, source, content_hash, file_mtime, department, access_level,
             chunks_count, indexed_at, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'indexed')
        ON CONFLICT (tenant, source) DO UPDATE SET
            content_hash  = EXCLUDED.content_hash,
            file_mtime    = EXCLUDED.file_mtime,
            department    = EXCLUDED.department,
            access_level  = EXCLUDED.access_level,
            chunks_count  = EXCLUDED.chunks_count,
            indexed_at    = EXCLUDED.indexed_at,
            status        = 'indexed'
        """,
        (tn, source, content_hash, file_mtime, department, access_level, chunks_count, _now()),
    )


def update_mtime(
    connection, source: str, file_mtime: float, tenant: str | None = None
) -> None:
    tn = normalize_tenant(tenant)
    connection.execute(
        "UPDATE documents SET file_mtime = %s WHERE source = %s AND tenant = %s",
        (file_mtime, source, tn),
    )


def delete_document(connection, source: str, tenant: str | None = None) -> None:
    tn = normalize_tenant(tenant)
    connection.execute(
        "DELETE FROM documents WHERE source = %s AND tenant = %s", (source, tn)
    )
