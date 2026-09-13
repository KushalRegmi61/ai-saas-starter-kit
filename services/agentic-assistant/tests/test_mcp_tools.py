"""MCP tool registration and scope-contract tests."""

import pytest

from project_mcp.server import create_mcp_server


@pytest.mark.asyncio
async def test_mcp_exposes_exactly_five_project_tools():
    server = create_mcp_server(lambda: None)
    tools = await server.list_tools()
    assert [tool.name for tool in tools] == [
        "get_project_context",
        "get_project_updates",
        "manage_project_feature",
        "manage_project_blocker",
        "submit_daily_update",
    ]
    assert all("project_id" not in tool.input_schema.get("properties", {}) for tool in tools)


@pytest.mark.asyncio
async def test_write_tool_descriptions_require_confirmation():
    server = create_mcp_server(lambda: None)
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert "explicit lead confirmation" in tools["manage_project_feature"].description
    assert "explicit lead confirmation" in tools["manage_project_blocker"].description
    assert "explicit lead confirmation" in tools["submit_daily_update"].description
