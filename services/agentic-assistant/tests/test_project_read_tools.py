"""Focused contracts for the minimal project read service."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from agent.types import ProjectCandidate, ProjectResolution
from models import project_state
from models.projects import ProjectStatus
from service import project_read_tools


class Pool:
    @asynccontextmanager
    async def connection(self):
        yield object()


def _resolution() -> ProjectResolution:
    return ProjectResolution(
        status="resolved",
        project=ProjectCandidate(project_id="p-1", name="Payments"),
        message="resolved",
    )


@pytest.mark.asyncio
async def test_overview_groups_features_and_uses_aggregate_counts(monkeypatch):
    stamped = datetime(2026, 9, 13, tzinfo=UTC)
    project = type("Project", (), {
        "status": ProjectStatus.AT_RISK,
        "completion_percentage": 72,
    })()
    features = [
        project_state.ProjectFeature(id="f-1", project_id="p-1", name="Checkout", status="QA"),
        project_state.ProjectFeature(id="f-2", project_id="p-1", name="Refunds", status="DEV"),
    ]
    latest = project_state.DailyProjectUpdate(
        id="u-1",
        project_id="p-1",
        submitted_by="lead-1",
        summary="Checkout moved to QA",
        completion_percentage=72,
        created_at=stamped,
    )

    async def resolve(*args, **kwargs):
        return _resolution()

    async def authorized(*args, **kwargs):
        return project

    async def list_features(*args, **kwargs):
        return features

    async def latest_update(*args, **kwargs):
        return latest

    async def feature_counts(*args, **kwargs):
        return _counts()

    async def blocker_count(*args, **kwargs):
        return _count()

    monkeypatch.setattr(project_read_tools, "resolve_project_for_actor", resolve)
    monkeypatch.setattr(project_read_tools.project_access, "get_project_for_actor", authorized)
    monkeypatch.setattr(project_read_tools.project_queries, "list_features_async", list_features)
    monkeypatch.setattr(project_read_tools.project_queries, "feature_counts_async", feature_counts)
    monkeypatch.setattr(project_read_tools.project_queries, "open_blocker_count_async", blocker_count)
    monkeypatch.setattr(project_read_tools.project_state, "get_latest_project_update_async", latest_update)

    result = await project_read_tools.get_overview(
        Pool(), claims=object(), project_reference="Payments", project_id=None
    )
    assert result.status == "AT_RISK"
    assert result.features_by_status["QA"] == ["Checkout"]
    assert result.feature_counts["DEV"] == 1
    assert result.open_blocker_count == 2
    assert result.latest_update.summary == "Checkout moved to QA"


def _counts():
    return {"DEV": 1, "QA": 1}


def _count():
    return 2


@pytest.mark.asyncio
async def test_feature_query_passes_text_status_and_limit(monkeypatch):
    captured = {}

    async def resolve(*args, **kwargs):
        return _resolution()

    async def list_features(connection, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(project_read_tools, "resolve_project_for_actor", resolve)
    monkeypatch.setattr(project_read_tools.project_queries, "list_features_async", list_features)
    result = await project_read_tools.get_features(
        Pool(),
        claims=object(),
        project_reference="Payments",
        project_id=None,
        feature_query="checkout",
        statuses=["QA"],
        limit=20,
    )
    assert result.total_returned == 0
    assert captured["query"] == "checkout"
    assert captured["statuses"] == ["QA"]
    assert captured["limit"] == 20


@pytest.mark.asyncio
async def test_blocker_query_defaults_to_open(monkeypatch):
    captured = {}

    async def resolve(*args, **kwargs):
        return _resolution()

    async def list_blockers(connection, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(project_read_tools, "resolve_project_for_actor", resolve)
    monkeypatch.setattr(project_read_tools.project_queries, "list_blockers_async", list_blockers)
    result = await project_read_tools.get_blockers(
        Pool(),
        claims=object(),
        project_reference="Payments",
        project_id=None,
        blocker_query="credentials",
        statuses=None,
        severities=["HIGH"],
        limit=10,
    )
    assert result.total_returned == 0
    assert captured["statuses"] == ["OPEN"]
    assert captured["severities"] == ["HIGH"]


@pytest.mark.asyncio
async def test_activity_returns_updates_and_history(monkeypatch):
    stamped = datetime(2026, 9, 13, tzinfo=UTC)

    async def resolve(*args, **kwargs):
        return _resolution()

    async def updates(*args, **kwargs):
        return []

    async def history(*args, **kwargs):
        return []

    monkeypatch.setattr(project_read_tools, "resolve_project_for_actor", resolve)
    monkeypatch.setattr(project_read_tools.project_state, "list_project_updates_async", updates)
    monkeypatch.setattr(project_read_tools.project_queries, "list_history_async", history)
    result = await project_read_tools.get_activity(
        Pool(),
        claims=object(),
        project_reference="Payments",
        project_id=None,
        since=stamped,
        limit=20,
    )
    assert result.updates == []
    assert result.history == []
