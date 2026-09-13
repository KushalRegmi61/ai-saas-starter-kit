"""Streamable HTTP MCP authentication tests."""

from contextlib import asynccontextmanager

import httpx
import pytest

from models.project_tokens import ProjectMcpContext
from project_mcp.server import create_mcp_app


class Pool:
    @asynccontextmanager
    async def connection(self):
        yield None


def _initialize_request():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1"},
        },
    }


@pytest.mark.asyncio
async def test_mcp_without_bearer_returns_401():
    app = create_mcp_app(lambda: None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post("/", json=_initialize_request())
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


@pytest.mark.asyncio
async def test_valid_mcp_token_initializes_and_revalidation_is_per_request(monkeypatch):
    async def authenticate(pool, raw_token):
        assert raw_token == "prj_test"
        return ProjectMcpContext(
            token_id="token-1",
            project_id="project-1",
            project_name="Payments",
            lead_id="lead-1",
            token_label="test",
        )

    monkeypatch.setattr("project_mcp.auth.authenticate_project_token", authenticate)
    app = create_mcp_app(lambda: Pool())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        response = await client.post(
            "/",
            headers={
                "Authorization": "Bearer prj_test",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json=_initialize_request(),
        )
        session_id = response.headers["mcp-session-id"]
        unauthorized = await client.get("/", headers={"Mcp-Session-Id": session_id})
    assert response.status_code == 200
    assert unauthorized.status_code == 401


@pytest.mark.asyncio
async def test_mcp_db_outage_returns_503_not_500(monkeypatch):
    from psycopg import OperationalError

    async def authenticate(pool, raw_token):
        raise OperationalError("SSL connection has been closed unexpectedly")

    monkeypatch.setattr("project_mcp.auth.authenticate_project_token", authenticate)
    app = create_mcp_app(lambda: Pool())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/",
            headers={"Authorization": "Bearer prj_test"},
            json=_initialize_request(),
        )
    assert response.status_code == 503
    assert response.json()["error"] == "invalid_token"


@pytest.mark.asyncio
async def test_mcp_client_disconnect_does_not_raise(monkeypatch):
    from starlette.requests import ClientDisconnect

    from project_mcp.auth import ProjectTokenAuthMiddleware
    from project_mcp.server import McpRoute

    async def authenticate(pool, raw_token):
        return ProjectMcpContext(
            token_id="token-1",
            project_id="project-1",
            project_name="Payments",
            lead_id="lead-1",
            token_label="test",
        )

    async def disconnect_app(scope, receive, send):
        raise ClientDisconnect()

    monkeypatch.setattr("project_mcp.auth.authenticate_project_token", authenticate)
    middleware = ProjectTokenAuthMiddleware(disconnect_app, pool_provider=lambda: Pool())
    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer prj_test")],
    }
    await middleware(scope, None, None)

    route = McpRoute(disconnect_app)
    await route.handle(scope, None, None)
