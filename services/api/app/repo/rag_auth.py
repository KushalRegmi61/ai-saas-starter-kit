"""Temporary enterprise-JWT adapter for RAG routes.

TODO(auth-package): extract to services/auth (ai-saas-auth) when it ships.
Verbatim port of enterprise-rag-assistant app/auth/jwt.py +
app/auth/dependencies.py + app/auth/rate_limit.py — do not diverge.

Starter files/billing keep Supabase auth; only /retrieval/* uses this chain:
require_rag_rate_limit -> decode_token -> claims_to_access_filter.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from rag.types import AccessFilter

from app.config import settings

_ACTION_LEVEL: dict[str, int] = {
    "read:public": 0,
    "read:internal": 1,
    "read:confidential": 2,
    "read:restricted": 3,
}

_GLOBAL_DOMAINS = {"admin", "all", "*"}


@dataclass(frozen=True)
class RagTokenClaims:
    subject: str
    domain: str
    max_access_level: int
    raw_actions: list[str]


def decode_rag_token(token: str) -> RagTokenClaims:
    payload = jwt.decode(token, settings.rag_jwt_secret, algorithms=[settings.rag_jwt_algorithm])
    subject = payload.get("sub")
    domain = payload.get("domain")
    actions = payload.get("actions", [])
    if not subject or not domain:
        raise JWTError("token missing required claims: sub, domain")
    if not isinstance(actions, list):
        raise JWTError("actions must be a list")
    max_level = max((_ACTION_LEVEL[a] for a in actions if a in _ACTION_LEVEL), default=0)
    return RagTokenClaims(
        subject=subject, domain=domain, max_access_level=max_level, raw_actions=actions
    )


def claims_to_access_filter(claims: RagTokenClaims) -> AccessFilter:
    if claims.domain in _GLOBAL_DOMAINS:
        departments = ["public", "internal", "confidential", "restricted", "all", "general"]
    else:
        departments = [claims.domain, "all", "general"]
    return AccessFilter(departments=departments, max_access_level=claims.max_access_level)


_bearer = HTTPBearer(auto_error=False)


def require_rag_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> RagTokenClaims:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_rag_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def require_rag_rate_limit(claims: RagTokenClaims = Depends(require_rag_auth)) -> RagTokenClaims:
    if not settings.rag_database_url:
        return claims
    from rag.repo import neon_repo

    limit = settings.rag_rate_limit_requests
    window_seconds = settings.rag_rate_limit_window_seconds
    now = int(time.time())
    window_key = math.floor(now / window_seconds) * window_seconds
    with neon_repo.get_conn() as conn:
        neon_repo.ensure_tables(conn)
        row = conn.execute(
            """
            INSERT INTO rate_limit_counters (subject, window_key, request_count)
            VALUES (%s, %s, 1)
            ON CONFLICT (subject, window_key)
            DO UPDATE SET request_count = rate_limit_counters.request_count + 1
            RETURNING request_count
            """,
            (claims.subject, window_key),
        ).fetchone()
        conn.commit()
    count = row[0]
    if count > limit:
        retry_after = window_seconds - (now - window_key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {limit} requests per {window_seconds}s.",
            headers={"Retry-After": str(retry_after)},
        )
    return claims
