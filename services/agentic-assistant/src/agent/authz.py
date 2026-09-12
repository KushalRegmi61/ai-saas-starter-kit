"""Authorization for the mutation surface: service token OR admin JWT.

Two caller kinds reach POST /ingest and DELETE /sources: machine forwarders
(services/api, bearing the shared service token) and humans in a browser
(bearing an assistant JWT after frontend login). Either credential suffices;
both missing or invalid fails closed. Retrieval needs no gate here — callers
resolve role-derived filters via `claims_to_access_filter` and bind them into
tools, so visibility follows the role ladder while mutations stay admin-only.
"""

from __future__ import annotations

import secrets

from auth.mapping import UnknownRole, role_to_filter
from auth.tokens import InvalidToken, decode_assistant_token
from auth.types import AssistantClaims
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from rag.types import AccessFilter

from agent.config import get_agent_settings

_bearer = HTTPBearer(auto_error=False)


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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or unconfigured user credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_assistant_token(
            credentials.credentials, secret=get_agent_settings().assistant_jwt_secret
        )
    except InvalidToken as exc:
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return claims


def require_jwt_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AssistantClaims:
    """Require an assistant JWT with the admin role.

    This deliberately does not use ``require_service_or_admin``: machine
    callers may mutate the indexed corpus but must never manage human users.
    """
    return require_admin(get_claims(credentials))


def require_service_or_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AssistantClaims | None:
    """Dual-auth dependency for the mutation routes. Returns the verified
    claims for human (JWT) callers, None for machine (service token) callers.
    Raises 503 when neither credential is configured, else 401/403."""
    if _valid_service_token(credentials):
        return None
    if credentials is not None and _jwt_configured():
        try:
            claims = decode_assistant_token(
                credentials.credentials, secret=get_agent_settings().assistant_jwt_secret
            )
        except InvalidToken:
            claims = None
        if claims is not None:
            return require_admin(claims)
    if not _service_configured() and not _jwt_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ingestion not configured",
        )
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
        raise ValueError("tenant must be a non-empty string")
    try:
        spec = role_to_filter(claims.role, tenant=tenant)
    except UnknownRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from None
    return AccessFilter(
        departments=spec.departments,
        max_access_level=spec.max_access_level,
        tenant=spec.tenant,
        attributes=spec.attributes,
    )
