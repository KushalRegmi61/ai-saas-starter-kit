"""Agentic-assistant user persistence and identity orchestration.

The shared auth library owns SQL primitives and password/token mechanics. This
module owns the service's Neon pool, transactions, audit semantics, and the
bootstrap policy for the first admin.
"""

from __future__ import annotations

from typing import Any

from auth.crypto import hash_password, verify_password
from auth.store import (
    ensure_assistant_tables,
    find_user_by_email,
    find_user_by_id,
    insert_user,
    record_audit_event,
    set_user_role,
)
from auth.store import list_users as store_list_users
from auth.types import ASSISTANT_ROLES
from psycopg_pool import ConnectionPool


def get_pool(database_url: str) -> ConnectionPool:
    """Open and synchronously validate the process-wide assistant pool."""
    if not database_url:
        raise ValueError("AGENTIC_ASSISTANT_DATABASE_URL is missing")
    pool = ConnectionPool(conninfo=database_url, min_size=1, max_size=10, open=True)
    try:
        pool.wait()
    except Exception:
        pool.close()
        raise
    return pool


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _require_role(role: str) -> None:
    if role not in ASSISTANT_ROLES:
        raise ValueError(f"unknown role: {role}")


def ensure_and_seed(connection: Any, admin_email: str, admin_password: str) -> dict | None:
    """Create the identity tables and insert the seed admin if configured.

    Existing rows are never overwritten, including a row with the same email
    carrying a non-admin role. Empty credentials mean that operators are
    expected to provision an admin through another trusted database path.
    """
    ensure_assistant_tables(connection)
    if not admin_email and not admin_password:
        return None
    if bool(admin_email) != bool(admin_password):
        raise ValueError(
            "AGENTIC_ASSISTANT_ADMIN_EMAIL and "
            "AGENTIC_ASSISTANT_ADMIN_PASSWORD must be set together"
        )

    email = _normalize_email(admin_email)
    if not email:
        raise ValueError("AGENTIC_ASSISTANT_ADMIN_EMAIL must not be empty")
    existing = find_user_by_email(connection, email)
    if existing is not None:
        return {key: value for key, value in existing.items() if key != "password_hash"}

    user = insert_user(
        connection,
        email=email,
        password_hash=hash_password(admin_password),
        role="admin",
    )
    record_audit_event(
        connection,
        actor_id=None,
        actor_email=email,
        action="admin.seeded",
        resource="assistant_user",
        target_id=user["id"],
        detail={"role": "admin"},
    )
    return user


def authenticate(connection: Any, email: str, password: str) -> dict | None:
    """Return a public user after recording a success or generic failure."""
    normalized_email = _normalize_email(email)
    user = find_user_by_email(connection, normalized_email)
    if user is None or not verify_password(password, user["password_hash"]):
        record_audit_event(
            connection,
            actor_id=user["id"] if user else None,
            actor_email=normalized_email,
            action="login.failed",
            resource="assistant_user",
            target_id=user["id"] if user else None,
            detail={"reason": "invalid_credentials"},
        )
        return None

    record_audit_event(
        connection,
        actor_id=user["id"],
        actor_email=user["email"],
        action="login.success",
        resource="assistant_user",
        target_id=user["id"],
    )
    return {key: value for key, value in user.items() if key != "password_hash"}


def create_user(
    connection: Any,
    *,
    email: str,
    password: str,
    role: str,
    actor_id: str,
    actor_email: str | None = None,
) -> dict:
    _require_role(role)
    user = insert_user(
        connection,
        email=_normalize_email(email),
        password_hash=hash_password(password),
        role=role,
    )
    record_audit_event(
        connection,
        actor_id=actor_id,
        actor_email=actor_email,
        action="user.created",
        resource="assistant_user",
        target_id=user["id"],
        detail={"role": role},
    )
    return user


def list_users(connection: Any) -> list[dict]:
    return store_list_users(connection, limit=200)


def set_role(
    connection: Any,
    *,
    user_id: str,
    role: str,
    actor_id: str,
    actor_email: str | None = None,
) -> dict | None:
    _require_role(role)
    existing = find_user_by_id(connection, user_id)
    if existing is None:
        return None
    updated = set_user_role(connection, user_id=user_id, role=role)
    if updated is None:
        return None
    record_audit_event(
        connection,
        actor_id=actor_id,
        actor_email=actor_email,
        action="user.role_changed",
        resource="assistant_user",
        target_id=user_id,
        detail={"old_role": existing["role"], "new_role": role},
    )
    return updated
