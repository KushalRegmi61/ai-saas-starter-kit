"""Authorization for the mutation surface: service token OR admin JWT.

Two caller kinds reach POST /ingest and DELETE /sources: machine forwarders
(services/api, bearing the shared service token) and humans in a browser
(bearing an assistant JWT after frontend login). Either credential suffices;
both missing or invalid fails closed. Retrieval needs no gate here — callers
resolve role-derived filters via `claims_to_access_filter` and bind them into
tools, so visibility follows the role ladder while mutations stay admin-only.
"""

from __future__ import annotations

import logging
import secrets

from auth.mapping import UnknownRole, role_to_filter
from auth.tokens import InvalidToken, decode_assistant_token
from auth.types import AssistantClaims
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from rag.types import AccessFilter

from agent.config import get_agent_settings

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

# Project authorization policy shared by the future project API and MCP
# adapters. These are capabilities, not authentication mechanisms; callers
# must still present a verified assistant JWT before applying them.
PROJECT_ASSIGN_ROLES = frozenset({"admin"})
PROJECT_VIEW_ALL_ROLES = frozenset({"admin", "manager"})
PROJECT_VIEW_ASSIGNED_ROLES = frozenset({"lead"})
PROJECT_ACCESS_ROLES = PROJECT_ASSIGN_ROLES | PROJECT_VIEW_ALL_ROLES | PROJECT_VIEW_ASSIGNED_ROLES


def can_assign_project(role: str) -> bool:
    return role in PROJECT_ASSIGN_ROLES


def can_view_all_projects(role: str) -> bool:
    return role in PROJECT_VIEW_ALL_ROLES


def can_view_assigned_projects(role: str) -> bool:
    return role in PROJECT_VIEW_ASSIGNED_ROLES


def _service_configured() -> bool:
    return bool(get_agent_settings().agent_service_token)


def _jwt_configured() -> bool:
    return bool(get_agent_settings().assistant_jwt_secret)


def _valid_service_token(credentials: HTTPAuthorizationCredentials | None) -> bool:
    return (
        credentials is not None
        and _service_configured()
        and secrets.compare_digest(
            credentials.credentials, get_agent_settings().agent_service_token
        )
    )


def get_claims(credentials: HTTPAuthorizationCredentials | None) -> AssistantClaims:
    """Verify a bearer assistant JWT. Raises 401 when absent or invalid."""
    if credentials is None or not _jwt_configured():
        logger.warning("auth: JWT missing or unconfigured")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or unconfigured user credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_assistant_token(
            credentials.credentials, secret=get_agent_settings().assistant_jwt_secret
        )
        logger.info("auth: JWT verified role=%s subject=%s", claims.role, claims.subject)
        return claims
    except InvalidToken as exc:
        logger.warning("auth: invalid JWT: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def require_admin(claims: AssistantClaims) -> AssistantClaims:
    """Capability gate: only the admin role may mutate the corpus. The role
    ladder caps admin visibility at the shared ceiling (see libs/auth), so
    this check — not the filter — is what makes admin the upload/delete
    role. Raises 403 for every other known role."""
    if claims.role != "admin":
        logger.warning("auth: non-admin blocked role=%s subject=%s", claims.role, claims.subject)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    logger.debug("auth: admin gate passed subject=%s", claims.subject)
    return claims


def require_jwt_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AssistantClaims:
    """Require an assistant JWT with the admin role.

    This deliberately does not use ``require_service_or_admin``: machine
    callers may mutate the indexed corpus but must never manage human users.
    """
    return require_admin(get_claims(credentials))


def require_jwt_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AssistantClaims:
    """Require any valid assistant JWT; service tokens are never accepted."""
    return get_claims(credentials)


def require_service_or_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AssistantClaims | None:
    """Dual-auth dependency for the mutation routes. Returns the verified
    claims for human (JWT) callers, None for machine (service token) callers.
    Raises 503 when neither credential is configured, else 401/403."""
    if _valid_service_token(credentials):
        logger.info("auth: service-token caller accepted")
        return None
    if credentials is not None and _jwt_configured():
        try:
            claims = decode_assistant_token(
                credentials.credentials, secret=get_agent_settings().assistant_jwt_secret
            )
        except InvalidToken:
            logger.warning("auth: mutation route presented invalid JWT")
            claims = None
        if claims is not None:
            logger.info("auth: JWT caller accepted role=%s subject=%s", claims.role, claims.subject)
            return require_admin(claims)
    if not _service_configured() and not _jwt_configured():
        logger.warning("auth: mutation route hit with no credentials configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingestion not configured",
        )
    logger.warning("auth: mutation route rejected (invalid credentials)")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def claims_to_access_filter(claims: AssistantClaims, *, tenant: str) -> AccessFilter:
    """Resolve role-derived retrieval policy for a verified caller. Raises
    403 for roles outside the service policy; empty tenant fails loud (the
    caller's bug, never silently unscoped)."""
    if not tenant:
        logger.warning("auth: empty tenant for subject=%s", claims.subject)
        raise ValueError("tenant must be a non-empty string")
    try:
        spec = role_to_filter(claims.role, tenant=tenant)
    except UnknownRole as exc:
        logger.warning("auth: unknown role=%s", claims.role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from None
    logger.debug(
        "auth: filter resolved role=%s tenant=%s level=%s",
        claims.role,
        tenant,
        spec.max_access_level,
    )
    return AccessFilter(
        departments=spec.departments,
        max_access_level=spec.max_access_level,
        tenant=spec.tenant,
        attributes=spec.attributes,
    )
