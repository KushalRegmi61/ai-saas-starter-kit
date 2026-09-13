"""Thin MCP tool adapters over the project-state service."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from project_mcp.context import require_project_context
from service import project_state


def register_tools(server: MCPServer, pool_provider: Any) -> None:
    @server.tool(
        description=(
            "Read the authoritative status for the authenticated project. "
            "Project scope comes from the bearer credential."
        )
    )
    async def get_project_context() -> dict[str, Any]:
        context = require_project_context()
        async with pool_provider().connection() as connection:
            result = await project_state.get_project_context(connection, context=context)
        return result.model_dump(mode="json")

    @server.tool(description="List features and statuses for the authenticated project only.")
    async def get_project_features() -> list[dict[str, Any]]:
        context = require_project_context()
        async with pool_provider().connection() as connection:
            result = await project_state.get_project_features(connection, context=context)
        return [feature.model_dump(mode="json") for feature in result]

    @server.tool(
        description="Read the latest confirmed daily update for the authenticated project."
    )
    async def get_previous_update() -> dict[str, Any] | None:
        context = require_project_context()
        async with pool_provider().connection() as connection:
            result = await project_state.get_previous_update(connection, context=context)
        return result.model_dump(mode="json") if result is not None else None

    @server.tool(
        description=(
            "After explicit lead confirmation, move one feature to a validated status. "
            "This mutation is audited and applies only to the authenticated project."
        )
    )
    async def update_feature_status(feature_id: str, new_status: str) -> dict[str, Any]:
        context = require_project_context()
        result = await project_state.update_feature_status(
            pool_provider(), context=context, feature_id=feature_id, new_status=new_status
        )
        return result.model_dump(mode="json")

    @server.tool(
        description=(
            "After explicit lead confirmation, submit a daily update. "
            "This mutation is audited and applies only to the authenticated project."
        )
    )
    async def submit_daily_update(
        summary: str, completion_percentage: int, blocker_ids: list[str]
    ) -> dict[str, Any]:
        context = require_project_context()
        result = await project_state.submit_daily_update(
            pool_provider(),
            context=context,
            summary=summary,
            completion_percentage=completion_percentage,
            blocker_ids=blocker_ids,
        )
        return result.model_dump(mode="json")
