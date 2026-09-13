"""Minimal project-scoped MCP tool adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from models.project_state import BlockerSeverity, FeatureStatus
from project_mcp.context import require_project_context
from service import project_mcp_state, project_state


def register_tools(server: MCPServer, pool_provider: Any) -> None:
    @server.tool(
        description=(
            "Read the complete authoritative snapshot for the authenticated project: "
            "status, completion, features, open blockers, and latest update."
        )
    )
    async def get_project_context() -> dict[str, Any]:
        context = require_project_context()
        async with pool_provider().connection() as connection:
            result = await project_state.get_project_context(connection, context=context)
        return result.model_dump(mode="json")

    @server.tool(
        description="List bounded daily updates for the authenticated project since a date/time."
    )
    async def get_project_updates(
        since: datetime | None = None, limit: int = 50
    ) -> dict[str, Any]:
        context = require_project_context()
        result = await project_mcp_state.get_updates(
            pool_provider(), context=context, since=since, limit=limit
        )
        return result.model_dump(mode="json")

    @server.tool(
        description=(
            "Create a feature or update a feature status using a natural-language reference. "
            "Writes require explicit lead confirmation; ambiguous references require clarification."
        )
    )
    async def manage_project_feature(
        action: Literal["create", "update_status"],
        feature_reference: str | None = None,
        name: str | None = None,
        description: str | None = None,
        new_status: FeatureStatus | None = None,
    ) -> dict[str, Any]:
        context = require_project_context()
        result = await project_mcp_state.manage_feature(
            pool_provider(),
            context=context,
            action=action,
            feature_reference=feature_reference,
            name=name,
            description=description,
            new_status=new_status,
        )
        return result.model_dump(mode="json")

    @server.tool(
        description=(
            "Create or resolve a blocker using a natural-language reference. "
            "Writes require explicit lead confirmation; ambiguous references require clarification."
        )
    )
    async def manage_project_blocker(
        action: Literal["create", "resolve"],
        blocker_reference: str | None = None,
        title: str | None = None,
        description: str | None = None,
        severity: BlockerSeverity = BlockerSeverity.MEDIUM,
    ) -> dict[str, Any]:
        context = require_project_context()
        result = await project_mcp_state.manage_blocker(
            pool_provider(),
            context=context,
            action=action,
            blocker_reference=blocker_reference,
            title=title,
            description=description,
            severity=severity,
        )
        return result.model_dump(mode="json")

    @server.tool(
        description=(
            "Submit a daily update after explicit lead confirmation for the authenticated project. "
            "Blockers are identified by natural-language references, not invented IDs."
        )
    )
    async def submit_daily_update(
        summary: str, completion_percentage: int, blocker_references: list[str] | None = None
    ) -> dict[str, Any]:
        context = require_project_context()
        result = await project_mcp_state.submit_update(
            pool_provider(),
            context=context,
            summary=summary,
            completion_percentage=completion_percentage,
            blocker_references=blocker_references or [],
        )
        return result.model_dump(mode="json")
