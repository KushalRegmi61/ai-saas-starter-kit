"""Agentic-assistant user persistence and identity orchestration.

The shared auth library owns SQL primitives and password/token mechanics. This
module owns the service's Neon pool, transactions, audit semantics, and the
bootstrap policy for the first admin.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from auth.crypto import hash_password, verify_password
from auth.store import (
    ensure_assistant_tables,
    ensure_assistant_tables_async,
    find_user_by_email,
    find_user_by_email_async,
    find_user_by_id,
    find_user_by_id_async,
    insert_user,
    insert_user_async,
    record_audit_event,
    record_audit_event_async,
    set_user_role,
    set_user_role_async,
)
from auth.store import list_users as store_list_users
from auth.store import list_users_async as store_list_users_async
from auth.types import ASSISTANT_ROLES
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)


def get_pool(database_url: str) -> ConnectionPool:
    """Open and synchronously validate the process-wide assistant pool."""
    if not database_url:
        logger.warning("models: pool open rejected, database URL missing")
        raise ValueError("AGENTIC_ASSISTANT_DATABASE_URL is missing")
    logger.info("models: opening assistant pool")
    pool = ConnectionPool(conninfo=database_url, min_size=1, max_size=10, open=True)
    try:
        pool.wait()
    except Exception:
        logger.exception("models: pool wait failed")
        pool.close()
        raise
    logger.info("models: assistant pool ready")
    return pool


async def get_async_pool(database_url: str):
    """Open and validate the assistant's non-blocking database pool."""
    from psycopg_pool import AsyncConnectionPool

    if not database_url:
        raise ValueError("AGENTIC_ASSISTANT_DATABASE_URL is missing")
    pool = AsyncConnectionPool(conninfo=database_url, min_size=1, max_size=10, open=False)
    await pool.open(wait=True)
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
    logger.info("models: ensure identity tables + seed check")
    ensure_assistant_tables(connection)
    if not admin_email and not admin_password:
        logger.info("models: no seed credentials, skipping")
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
        logger.info("models: seed admin already exists email=%s", email)
        return {key: value for key, value in existing.items() if key != "password_hash"}
    logger.info("models: seeding admin email=%s", email)

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
    logger.info("models: authenticate email=%s", normalized_email)
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

    logger.info("models: authenticate success email=%s", normalized_email)
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
    logger.info("models: create user email=%s role=%s", _normalize_email(email), role)
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
    logger.debug("models: list users")
    result = store_list_users(connection, limit=200)
    logger.debug("models: list users done count=%d", len(result))
    return result


def set_role(
    connection: Any,
    *,
    user_id: str,
    role: str,
    actor_id: str,
    actor_email: str | None = None,
) -> dict | None:
    _require_role(role)
    logger.info("models: set role user_id=%s role=%s", user_id, role)
    existing = find_user_by_id(connection, user_id)
    if existing is None:
        logger.warning("models: set role user not found user_id=%s", user_id)
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


async def ensure_and_seed_async(connection: Any, admin_email: str, admin_password: str) -> dict | None:
    await ensure_assistant_tables_async(connection)
    if not admin_email and not admin_password:
        return None
    if bool(admin_email) != bool(admin_password):
        raise ValueError(
            "AGENTIC_ASSISTANT_ADMIN_EMAIL and AGENTIC_ASSISTANT_ADMIN_PASSWORD must be set together"
        )
    email = _normalize_email(admin_email)
    existing = await find_user_by_email_async(connection, email)
    if existing is not None:
        return existing
    password_hash = await asyncio.to_thread(hash_password, admin_password)
    user = await insert_user_async(connection, email=email, password_hash=password_hash, role="admin")
    await record_audit_event_async(
        connection,
        actor_id=None,
        actor_email=email,
        action="admin.seeded",
        resource="assistant_user",
        target_id=user["id"],
        detail={"role": "admin"},
    )
    return user


async def authenticate_async(connection: Any, email: str, password: str) -> dict | None:
    normalized_email = _normalize_email(email)
    user = await find_user_by_email_async(connection, normalized_email)
    valid = user is not None and await asyncio.to_thread(
        verify_password, password, user["password_hash"]
    )
    if not valid:
        await record_audit_event_async(
            connection,
            actor_id=user["id"] if user else None,
            actor_email=normalized_email,
            action="login.failed",
            resource="assistant_user",
            target_id=user["id"] if user else None,
            detail={"reason": "invalid_credentials"},
        )
        return None
    await record_audit_event_async(
        connection,
        actor_id=user["id"],
        actor_email=user["email"],
        action="login.success",
        resource="assistant_user",
        target_id=user["id"],
    )
    return {key: value for key, value in user.items() if key != "password_hash"}


async def create_user_async(connection: Any, *, email: str, password: str, role: str, actor_id: str):
    _require_role(role)
    password_hash = await asyncio.to_thread(hash_password, password)
    user = await insert_user_async(
        connection, email=_normalize_email(email), password_hash=password_hash, role=role
    )
    await record_audit_event_async(
        connection,
        actor_id=actor_id,
        actor_email=None,
        action="user.created",
        resource="assistant_user",
        target_id=user["id"],
        detail={"role": role},
    )
    return user


async def list_users_async(connection: Any) -> list[dict]:
    return await store_list_users_async(connection, limit=200)


async def set_role_async(
    connection: Any, *, user_id: str, role: str, actor_id: str
) -> dict | None:
    _require_role(role)
    existing = await find_user_by_id_async(connection, user_id)
    if existing is None:
        return None
    updated = await set_user_role_async(connection, user_id=user_id, role=role)
    if updated is not None:
        await record_audit_event_async(
            connection,
            actor_id=actor_id,
            actor_email=None,
            action="user.role_changed",
            resource="assistant_user",
            target_id=user_id,
            detail={"old_role": existing["role"], "new_role": role},
        )
    return updated
