"""Neon adapter for assistant users + audit events.

Every function takes the caller's DB connection (duck-typed `execute`) — the
lib owns no pool and no settings. Rows are tuples, mirroring the
libs/rag registry style; only public shapes (no password hash) are returned.
"""

from __future__ import annotations

import json


def ensure_assistant_tables(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'employee',
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_audit_events (
            id SERIAL PRIMARY KEY,
            actor_id TEXT,
            actor_email TEXT,
            action TEXT NOT NULL,
            resource TEXT NOT NULL,
            target_id TEXT,
            detail JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )


def _public_shape(row: tuple) -> dict:
    return {
        "id": row[0],
        "email": row[1],
        "role": row[3],
        "created_at": row[4].isoformat() if row[4] is not None else None,
    }


def find_user_by_email(connection, email: str) -> dict | None:
    row = connection.execute(
        "SELECT id, email, password_hash, role, created_at, updated_at "
        "FROM assistant_users WHERE email = %s",
        (email.lower(),),
    ).fetchone()
    if not row:
        return None
    return {**_public_shape(row), "password_hash": row[2]}


def find_user_by_id(connection, user_id: str) -> dict | None:
    row = connection.execute(
        "SELECT id, email, password_hash, role, created_at, updated_at "
        "FROM assistant_users WHERE id = %s",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return {**_public_shape(row), "password_hash": row[2]}


def insert_user(connection, *, email: str, password_hash: str, role: str) -> dict:
    import uuid

    row = connection.execute(
        "INSERT INTO assistant_users (id, email, password_hash, role) "
        "VALUES (%s, %s, %s, %s) "
        "RETURNING id, email, password_hash, role, created_at, updated_at",
        (str(uuid.uuid4()), email.lower(), password_hash, role),
    ).fetchone()
    return _public_shape(row)


def list_users(connection, *, limit: int = 200) -> list[dict]:
    rows = connection.execute(
        "SELECT id, email, password_hash, role, created_at, updated_at "
        "FROM assistant_users ORDER BY created_at DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return [_public_shape(row) for row in rows]


def set_user_role(connection, *, user_id: str, role: str) -> dict | None:
    row = connection.execute(
        "UPDATE assistant_users SET role = %s, updated_at = now() "
        "WHERE id = %s "
        "RETURNING id, email, password_hash, role, created_at, updated_at",
        (role, user_id),
    ).fetchone()
    if not row:
        return None
    return _public_shape(row)


def record_audit_event(
    connection,
    *,
    actor_id: str | None,
    actor_email: str | None,
    action: str,
    resource: str,
    target_id: str | None,
    detail: dict | None = None,
) -> None:
    try:
        from psycopg.types.json import Json
        payload = Json(detail or {})
    except ImportError:
        payload = json.dumps(detail or {})  # type: ignore[assignment]

    connection.execute(
        "INSERT INTO assistant_audit_events "
        "(actor_id, actor_email, action, resource, target_id, detail) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (actor_id, actor_email, action, resource, target_id, payload),
    )
