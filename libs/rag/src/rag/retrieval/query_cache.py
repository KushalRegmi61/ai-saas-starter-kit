"""Two-tier answer cache, ported from enterprise app/cache/query_cache.py.

Key = SHA-256(question + context_hash); Tier-1 exact, Tier-2 semantic (>=0.92,
same context_hash). Backend is Neon Postgres (+pgvector); SQL shape unchanged.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from rag.retrieval.rbac import normalize_tenant

SEMANTIC_THRESHOLD = 0.92


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()


def context_hash(chunk_ids: list[str]) -> str:
    key = "|".join(sorted(chunk_ids))
    return hashlib.sha256(key.encode()).hexdigest()


def make_cache_key(question: str, ctx_hash: str, tenant: str | None = None) -> str:
    scope = normalize_tenant(tenant) if tenant is not None else None
    preimage = f"{question.strip()}|CTX:{ctx_hash}" if scope is None else f"{scope}|{question.strip()}|CTX:{ctx_hash}"
    return _hash(preimage)


def ensure_cache_table(connection, dims: int) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS query_cache (
            question_hash  TEXT PRIMARY KEY,
            question_text  TEXT NOT NULL,
            context_hash   TEXT,
            question_vec   VECTOR({dims}),
            answer_json    TEXT NOT NULL,
            search_mode    TEXT,
            created_at     TIMESTAMPTZ DEFAULT NOW(),
            expires_at     TIMESTAMPTZ,
            hit_count      INTEGER DEFAULT 0,
            tenant         TEXT DEFAULT 'default'
        )
        """
    )
    connection.execute(
        "ALTER TABLE query_cache ADD COLUMN IF NOT EXISTS tenant TEXT DEFAULT 'default'"
    )
    connection.execute("UPDATE query_cache SET tenant = 'default' WHERE tenant IS NULL")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS query_cache_vec_idx
        ON query_cache USING hnsw (question_vec vector_cosine_ops)
        """
    )


async def ensure_cache_table_async(connection, dims: int) -> None:
    """Provision the cache schema using an async psycopg connection."""
    await connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS query_cache (
            question_hash TEXT PRIMARY KEY, question_text TEXT NOT NULL,
            context_hash TEXT, question_vec VECTOR({int(dims)}), answer_json TEXT NOT NULL,
            search_mode TEXT, created_at TIMESTAMPTZ DEFAULT NOW(), expires_at TIMESTAMPTZ,
            hit_count INTEGER DEFAULT 0, tenant TEXT DEFAULT 'default'
        )
        """
    )
    await connection.execute(
        "ALTER TABLE query_cache ADD COLUMN IF NOT EXISTS tenant TEXT DEFAULT 'default'"
    )
    await connection.execute("UPDATE query_cache SET tenant = 'default' WHERE tenant IS NULL")
    await connection.execute(
        """
        CREATE INDEX IF NOT EXISTS query_cache_vec_idx
        ON query_cache USING hnsw (question_vec vector_cosine_ops)
        """
    )


def get_cached_answer(
    connection, question: str, embedding: list[float], ctx_hash: str,
    tenant: str | None = None,
) -> dict | None:
    question_hash = make_cache_key(question, ctx_hash, tenant=tenant)
    row = connection.execute(
        "SELECT answer_json, expires_at FROM query_cache WHERE question_hash = %s",
        (question_hash,),
    ).fetchone()
    if row:
        answer_json, expires_at = row
        if expires_at is None or expires_at > _now():
            connection.execute(
                "UPDATE query_cache SET hit_count = hit_count + 1 WHERE question_hash = %s",
                (question_hash,),
            )
            return json.loads(answer_json)

    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    row = connection.execute(
        """
        SELECT question_hash, answer_json, expires_at,
               1 - (question_vec <=> %s::vector) AS similarity
        FROM query_cache
        WHERE (expires_at IS NULL OR expires_at > NOW())
          AND context_hash = %s
          AND tenant = %s
        ORDER BY question_vec <=> %s::vector
        LIMIT 1
        """,
        (vec_str, ctx_hash, normalize_tenant(tenant), vec_str),
    ).fetchone()
    if row:
        cached_hash, answer_json, _expires_at, similarity = row
        if similarity >= SEMANTIC_THRESHOLD:
            connection.execute(
                "UPDATE query_cache SET hit_count = hit_count + 1 WHERE question_hash = %s",
                (cached_hash,),
            )
            return json.loads(answer_json)
    return None


async def get_cached_answer_async(
    connection, question: str, embedding: list[float], ctx_hash: str,
    tenant: str | None = None,
) -> dict | None:
    """Async equivalent of get_cached_answer."""
    question_hash = make_cache_key(question, ctx_hash, tenant=tenant)
    cursor = await connection.execute(
        "SELECT answer_json, expires_at FROM query_cache WHERE question_hash = %s",
        (question_hash,),
    )
    row = await cursor.fetchone()
    if row:
        answer_json, expires_at = row
        if expires_at is None or expires_at > _now():
            await connection.execute(
                "UPDATE query_cache SET hit_count = hit_count + 1 WHERE question_hash = %s",
                (question_hash,),
            )
            return json.loads(answer_json)

    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    cursor = await connection.execute(
        """
        SELECT question_hash, answer_json, expires_at,
               1 - (question_vec <=> %s::vector) AS similarity
        FROM query_cache
        WHERE (expires_at IS NULL OR expires_at > NOW())
          AND context_hash = %s AND tenant = %s
        ORDER BY question_vec <=> %s::vector LIMIT 1
        """,
        (vec_str, ctx_hash, normalize_tenant(tenant), vec_str),
    )
    row = await cursor.fetchone()
    if row:
        cached_hash, answer_json, _expires_at, similarity = row
        if similarity >= SEMANTIC_THRESHOLD:
            await connection.execute(
                "UPDATE query_cache SET hit_count = hit_count + 1 WHERE question_hash = %s",
                (cached_hash,),
            )
            return json.loads(answer_json)
    return None


def store_cached_answer(
    connection,
    question: str,
    embedding: list[float],
    answer: dict,
    search_mode: str,
    ctx_hash: str,
    tenant: str | None = None,
    ttl_hours: int = 24,
) -> None:
    question_hash = make_cache_key(question, ctx_hash, tenant=tenant)
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    expires_at = _now() + timedelta(hours=ttl_hours)
    connection.execute(
        """
        INSERT INTO query_cache
            (question_hash, question_text, context_hash, question_vec, answer_json, search_mode, expires_at, tenant)
        VALUES (%s, %s, %s, %s::vector, %s, %s, %s, %s)
        ON CONFLICT (question_hash) DO UPDATE SET
            answer_json  = EXCLUDED.answer_json,
            search_mode  = EXCLUDED.search_mode,
            expires_at   = EXCLUDED.expires_at,
            hit_count    = query_cache.hit_count + 1
        """,
        (
            question_hash,
            question.strip(),
            ctx_hash,
            vec_str,
            json.dumps(answer),
            search_mode,
            expires_at,
            normalize_tenant(tenant),
        ),
    )


async def store_cached_answer_async(
    connection,
    question: str,
    embedding: list[float],
    answer: dict,
    search_mode: str,
    ctx_hash: str,
    tenant: str | None = None,
    ttl_hours: int = 24,
) -> None:
    """Async equivalent of store_cached_answer."""
    question_hash = make_cache_key(question, ctx_hash, tenant=tenant)
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    expires_at = _now() + timedelta(hours=ttl_hours)
    await connection.execute(
        """
        INSERT INTO query_cache
            (question_hash, question_text, context_hash, question_vec, answer_json,
             search_mode, expires_at, tenant)
        VALUES (%s, %s, %s, %s::vector, %s, %s, %s, %s)
        ON CONFLICT (question_hash) DO UPDATE SET
            answer_json = EXCLUDED.answer_json,
            search_mode = EXCLUDED.search_mode,
            expires_at = EXCLUDED.expires_at,
            hit_count = query_cache.hit_count + 1
        """,
        (
            question_hash,
            question.strip(),
            ctx_hash,
            vec_str,
            json.dumps(answer),
            search_mode,
            expires_at,
            normalize_tenant(tenant),
        ),
    )


def flush_cache(
    connection, expired_only: bool = False, tenant: str | None = None
) -> int:
    """Delete cache entries. Returns count of rows deleted."""
    if tenant is None:
        if expired_only:
            result = connection.execute(
                "DELETE FROM query_cache WHERE expires_at IS NOT NULL AND expires_at <= NOW()"
            )
        else:
            result = connection.execute("DELETE FROM query_cache")
    else:
        scope = normalize_tenant(tenant)
        if expired_only:
            result = connection.execute(
                "DELETE FROM query_cache WHERE tenant = %s AND expires_at IS NOT NULL AND expires_at <= NOW()",
                (scope,),
            )
        else:
            result = connection.execute(
                "DELETE FROM query_cache WHERE tenant = %s",
                (scope,),
            )
    return result.rowcount
