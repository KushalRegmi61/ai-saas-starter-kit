"""Request-scoped MCP project identity."""

from contextvars import ContextVar

from models.project_tokens import ProjectMcpContext

project_context_var: ContextVar[ProjectMcpContext | None] = ContextVar(
    "project_mcp_context", default=None
)


def require_project_context() -> ProjectMcpContext:
    context = project_context_var.get()
    if context is None:
        raise RuntimeError("MCP project context is unavailable")
    return context
