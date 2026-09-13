"""Project credential lifecycle and authorization orchestration."""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from auth.store import record_audit_event_async
from auth.types import AssistantClaims
from psycopg import OperationalError

from models import project_tokens, projects

logger = logging.getLogger(__name__)

TOKEN_LIFETIME = timedelta(days=30)
TOKEN_PREFIX = "prj_"
# Managed Postgres may hand the pool a socket the server already closed. The
# pool discards it, so one immediate retry on a fresh connection recovers the
# first request after an idle stretch instead of surfacing a 500.
_AUTH_DB_ATTEMPTS = 2


class ProjectTokenForbidden(PermissionError):
    """Raised when an actor cannot manage a project's credentials."""


class ProjectTokenExpired(ProjectTokenForbidden):
    """Raised when a project credential is expired, revoked, or stale."""


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _new_raw_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


async def _get_project(connection: Any, project_id: str) -> projects.Project:
    project = await projects.get_project_async(connection, project_id)
    if project is None:
        raise projects.ProjectNotFound(project_id)
    return project


def _require_admin_or_lead(claims: AssistantClaims) -> None:
    if claims.role not in {"admin", "lead"}:
        raise ProjectTokenForbidden("Project credential access denied")


async def _require_project_access(
    connection: Any, *, claims: AssistantClaims, project_id: str, create: bool = False
) -> projects.Project:
    _require_admin_or_lead(claims)
    project = await _get_project(connection, project_id)
    if create and claims.role != "lead":
        raise ProjectTokenForbidden("Only the assigned lead may create credentials")
    if claims.role == "lead" and project.lead_id != claims.subject:
        raise ProjectTokenForbidden("Only the assigned lead may manage credentials")
    return project


async def create_project_token(
    pool: Any, *, claims: AssistantClaims, project_id: str, label: str
) -> tuple[project_tokens.ProjectToken, str]:
    normalized_label = label.strip()
    if not normalized_label:
        raise ValueError("token label must not be empty")
    if len(normalized_label) > 100:
        raise ValueError("token label must be 100 characters or fewer")

    raw_token = _new_raw_token()
    now = datetime.now(UTC)
    async with pool.connection() as connection, connection.transaction():
        project = await _require_project_access(
            connection, claims=claims, project_id=project_id, create=True
        )
        token = await project_tokens.create_project_token_async(
            connection,
            token_id=str(uuid.uuid4()),
            project_id=project.id,
            token_hash=_hash_token(raw_token),
            created_by=claims.subject,
            label=normalized_label,
            expires_at=now + TOKEN_LIFETIME,
        )
        await record_audit_event_async(
            connection,
            actor_id=claims.subject,
            actor_email=None,
            action="project.mcp_token_created",
            resource="assistant_project_mcp_token",
            target_id=token.id,
            detail={"project_id": project.id, "label": token.label},
        )
    logger.info("project token created token_id=%s project_id=%s", token.id, project.id)
    return token, raw_token


async def list_project_tokens(
    pool: Any, *, claims: AssistantClaims, project_id: str
) -> list[project_tokens.ProjectToken]:
    async with pool.connection() as connection:
        await _require_project_access(connection, claims=claims, project_id=project_id)
        return await project_tokens.list_project_tokens_async(connection, project_id=project_id)


async def revoke_project_token(
    pool: Any, *, claims: AssistantClaims, project_id: str, token_id: str
) -> project_tokens.ProjectToken:
    async with pool.connection() as connection, connection.transaction():
        await _require_project_access(connection, claims=claims, project_id=project_id)
        token = await project_tokens.revoke_project_token_async(
            connection, project_id=project_id, token_id=token_id
        )
        if token is None:
            raise project_tokens.ProjectTokenNotFound(token_id)
        await record_audit_event_async(
            connection,
            actor_id=claims.subject,
            actor_email=None,
            action="project.mcp_token_revoked",
            resource="assistant_project_mcp_token",
            target_id=token.id,
            detail={"project_id": project_id, "label": token.label},
        )
        return token


async def authenticate_project_token(
    pool: Any, *, raw_token: str
) -> project_tokens.ProjectMcpContext:
    if not raw_token.startswith(TOKEN_PREFIX):
        raise ProjectTokenExpired("Invalid project credential")
    last_error: Exception | None = None
    for _ in range(_AUTH_DB_ATTEMPTS):
        try:
            async with pool.connection() as connection, connection.transaction():
                return await _authenticate_once(connection, raw_token=raw_token)
        except ProjectTokenExpired:
            raise
        except OperationalError as exc:
            last_error = exc
            logger.warning("project token auth hit stale db connection, retrying")
    logger.exception("project token authentication db failure")
    raise (
        last_error if last_error is not None else ProjectTokenExpired("Invalid project credential")
    )


async def _authenticate_once(
    connection: Any, *, raw_token: str
) -> project_tokens.ProjectMcpContext:
    result = await project_tokens.find_active_project_token_async(
        connection, token_hash=_hash_token(raw_token)
    )
    if result is None:
        logger.warning("project token authentication failed")
        raise ProjectTokenExpired("Invalid, expired, or revoked project credential")
    token, project_name, lead_id = result
    if not lead_id or token.created_by != lead_id:
        logger.warning("project token ownership check failed token_id=%s", token.id)
        raise ProjectTokenExpired("Project credential is no longer assigned")
    await project_tokens.touch_project_token_last_used_async(connection, token_id=token.id)
    return project_tokens.ProjectMcpContext(
        token_id=token.id,
        project_id=token.project_id,
        project_name=project_name,
        lead_id=lead_id,
        token_label=token.label,
    )
