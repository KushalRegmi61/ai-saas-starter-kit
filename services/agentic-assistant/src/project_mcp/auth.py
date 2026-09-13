"""Bearer authentication middleware for the mounted MCP application."""

from __future__ import annotations

import json
import logging
from typing import Any

from auth.store import record_audit_event_async
from psycopg import OperationalError
from psycopg_pool import PoolTimeout
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Receive, Scope, Send

from project_mcp.context import project_context_var
from service.project_tokens import ProjectTokenExpired, authenticate_project_token

logger = logging.getLogger(__name__)


def _bearer(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"authorization":
            decoded = value.decode("latin-1")
            scheme, _, token = decoded.partition(" ")
            if scheme.lower() != "bearer" or not token.strip():
                return None
            return token.strip()
    return None


async def _audit_failure(pool: Any, reason: str) -> None:
    if pool is None:
        return
    try:
        async with pool.connection() as connection, connection.transaction():
            await record_audit_event_async(
                connection,
                actor_id=None,
                actor_email=None,
                action="project.mcp_token_auth_failed",
                resource="assistant_project_mcp_token",
                target_id=None,
                detail={"reason": reason},
            )
    except Exception:
        logger.exception("mcp authentication audit write failed reason=%s", reason)


class ProjectTokenAuthMiddleware:
    """Revalidate the project token for every HTTP request to the MCP app."""

    def __init__(self, app: ASGIApp, pool_provider):
        self.app = app
        self.pool_provider = pool_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _bearer(scope)
        pool = self.pool_provider()
        if token is None:
            await _audit_failure(pool, "missing_or_malformed_bearer")
            await self._reject(send, "Bearer token required")
            return
        if pool is None:
            await self._reject(send, "Authentication store unavailable", status_code=503)
            return
        try:
            context = await authenticate_project_token(pool, raw_token=token)
        except ProjectTokenExpired:
            await _audit_failure(pool, "invalid_or_inactive_token")
            await self._reject(send, "Invalid or inactive project credential")
            return
        except (OperationalError, PoolTimeout):
            logger.exception("mcp authentication store unavailable")
            await self._reject(send, "Authentication store unavailable", status_code=503)
            return
        token_handle = project_context_var.set(context)
        try:
            await self.app(scope, receive, send)
        except ClientDisconnect:
            logger.info("mcp client disconnected mid-request")
        finally:
            project_context_var.reset(token_handle)

    @staticmethod
    async def _reject(send: Send, detail: str, *, status_code: int = 401) -> None:
        body = json.dumps({"error": "invalid_token", "error_description": detail}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b'Bearer error="invalid_token"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
