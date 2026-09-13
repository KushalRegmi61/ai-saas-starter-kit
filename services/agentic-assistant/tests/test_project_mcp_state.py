"""Natural-language MCP project-state contract tests."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from models import project_state, project_state_ops
from models.project_state_contracts import ProjectToolResult
from models.project_tokens import ProjectMcpContext
from service import project_mcp_state


def _context() -> ProjectMcpContext:
    return ProjectMcpContext(
        token_id="token-1",
        project_id="project-1",
        project_name="Payments",
        lead_id="lead-1",
        token_label="laptop",
    )


def test_ambiguous_reference_returns_bounded_candidates():
    features = [
        project_state.ProjectFeature(id="f-1", project_id="p-1", name="Checkout", status="DEV"),
        project_state.ProjectFeature(id="f-2", project_id="p-1", name="Checkout API", status="QA"),
    ]
    result = project_mcp_state._resolved_or_candidates(features, feature=True)
    assert isinstance(result, ProjectToolResult)
    assert result.status == "ambiguous"
    assert [candidate.id for candidate in result.candidates] == ["f-1", "f-2"]


def test_reference_matching_ignores_punctuation_and_case():
    assert project_state_ops._matches("payment retry", "Payment-Retry API")


@pytest.mark.asyncio
async def test_get_updates_passes_project_scope_date_and_limit(monkeypatch):
    captured = {}
    stamped = datetime(2026, 9, 9, tzinfo=UTC)

    async def list_updates(connection, *, project_id, since, limit):
        captured.update(project_id=project_id, since=since, limit=limit)
        return []

    class Pool:
        @asynccontextmanager
        async def connection(self):
            yield object()

    monkeypatch.setattr(project_mcp_state.project_state, "list_project_updates_async", list_updates)
    result = await project_mcp_state.get_updates(
        Pool(), context=_context(), since=stamped, limit=20
    )
    assert result.updates == []
    assert captured == {"project_id": "project-1", "since": stamped, "limit": 20}
    assert result.since == stamped.isoformat()


@pytest.mark.asyncio
async def test_get_updates_rejects_unbounded_limit():
    with pytest.raises(project_mcp_state.McpStateValidationError):
        await project_mcp_state.get_updates(
            object(), context=_context(), since=None, limit=101
        )
