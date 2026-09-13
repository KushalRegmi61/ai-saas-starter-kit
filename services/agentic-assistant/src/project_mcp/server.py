"""MCP server factory mounted by the assistant FastAPI application."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import URLPath
from starlette.requests import ClientDisconnect
from starlette.routing import BaseRoute, Match
from starlette.types import ASGIApp, Receive, Scope, Send

from project_mcp.auth import ProjectTokenAuthMiddleware
from project_mcp.tools import register_tools


def create_mcp_server(pool_provider: Any) -> MCPServer:
    server = MCPServer(
        name="project-status",
        title="Project Status MCP",
        description="Minimal project-scoped status, update, feature, and blocker tools.",
        instructions=(
            "The bearer credential already defines the project scope. Use the context and "
            "updates tools for reads. Refer to features and blockers by natural language; "
            "never invent IDs, and ask for clarification when a reference is ambiguous. "
            "Before calling any write action, show the proposed change and obtain explicit "
            "confirmation from the tech lead in the conversation."
        ),
    )
    register_tools(server, pool_provider)
    return server


def create_mcp_app(pool_provider: Any) -> ASGIApp:
    server = create_mcp_server(pool_provider)
    mcp_app = server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=False,
        json_response=False,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    mcp_app.add_middleware(ProjectTokenAuthMiddleware, pool_provider=pool_provider)
    return mcp_app


class McpRoute(BaseRoute):
    """Serve the SDK app without Starlette Mount's nested-lifespan traversal."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self.path = "/mcp"

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        path = scope.get("path", "")
        if scope.get("type") != "http" or not (path == self.path or path.startswith("/mcp/")):
            return Match.NONE, {}
        child_scope = dict(scope)
        child_scope["root_path"] = scope.get("root_path", "") + self.path
        child_scope["path"] = path[len(self.path) :] or "/"
        return Match.FULL, child_scope

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        raise NoReverseMatch(name)

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await self.app(scope, receive, send)
        except ClientDisconnect:
            # Benign: browser/MCP client cancelled the request (e.g. closed
            # the tab or timed out waiting). Swallow so uvicorn does not log
            # an ASGI traceback for a client-side cancel.
            return


class NoReverseMatch(LookupError):
    """MCP is an externally mounted endpoint without URL reversing."""


def mount_mcp_app(app: Any) -> McpRoute:
    return McpRoute(app)
