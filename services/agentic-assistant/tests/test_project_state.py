"""Project-state persistence and service tests."""

import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import ModuleType

import pytest

from models import project_state
from models.project_tokens import ProjectMcpContext
from models.projects import Project, ProjectStatus
from service import project_state as state_service


class Result:
    def __init__(self, rows):
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return self.rows


class SchemaConnection:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return Result([])


def _context() -> ProjectMcpContext:
    return ProjectMcpContext(
        token_id="token-1",
        project_id="project-1",
        project_name="Payments",
        lead_id="lead-1",
        token_label="laptop",
    )


@pytest.mark.asyncio
async def test_project_state_schema_is_idempotent():
    connection = SchemaConnection()
    await project_state.ensure_project_state_tables_async(connection)
    await project_state.ensure_project_state_tables_async(connection)
    assert len(connection.calls) == 16
    assert "assistant_project_features" in connection.calls[0][0]
    assert "assistant_feature_status_history" in connection.calls[3][0]


@pytest.mark.asyncio
async def test_context_aggregates_project_features_and_open_blockers(monkeypatch):
    stamped = datetime(2026, 9, 13, tzinfo=UTC)
    project = Project(
        id="project-1",
        name="Payments",
        lead_id="lead-1",
        status=ProjectStatus.AT_RISK,
        completion_percentage=72,
        created_at=stamped,
        updated_at=stamped,
    )
    features = [
        project_state.ProjectFeature(
            id="feature-1", project_id="project-1", name="Auth", status="QA"
        ),
        project_state.ProjectFeature(
            id="feature-2", project_id="project-1", name="Billing", status="DEV"
        ),
    ]
    blocker = project_state.ProjectBlocker(
        id="blocker-1",
        project_id="project-1",
        title="Credentials",
        severity="HIGH",
        status="OPEN",
    )

    async def get_project(connection, project_id):
        return project if project_id == "project-1" else None

    async def list_features(connection, project_id):
        return features

    async def list_blockers(connection, project_id):
        return [blocker]

    async def latest_update(connection, project_id):
        return None

    monkeypatch.setattr(state_service.projects, "get_project_async", get_project)
    monkeypatch.setattr(project_state, "list_project_features_async", list_features)
    monkeypatch.setattr(project_state, "list_open_project_blockers_async", list_blockers)
    monkeypatch.setattr(project_state, "get_latest_project_update_async", latest_update)

    result = await state_service.get_project_context(object(), context=_context())
    assert result.project.completion_percentage == 72
    assert result.feature_counts["QA"] == 1
    assert result.feature_counts["DEV"] == 1
    assert result.open_blockers[0].id == "blocker-1"
    assert result.scope == {"project_id": "project-1"}


class FakeConnection:
    @asynccontextmanager
    async def transaction(self):
        yield


class FakePool:
    @asynccontextmanager
    async def connection(self):
        yield FakeConnection()


@pytest.mark.asyncio
async def test_daily_update_rejects_cross_project_blockers(monkeypatch):
    async def no_matching_blockers(connection, project_id, blocker_ids):
        return []

    monkeypatch.setattr(project_state, "get_project_blockers_by_ids_async", no_matching_blockers)
    with pytest.raises(state_service.ProjectStateNotFound):
        await state_service.submit_daily_update(
            FakePool(),
            context=_context(),
            summary="Blocked by credentials",
            completion_percentage=72,
            blocker_ids=["other-project-blocker"],
        )


@pytest.mark.asyncio
async def test_daily_update_validates_completion_before_database(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("invalid completion must be rejected before persistence")

    monkeypatch.setattr(project_state, "get_project_blockers_by_ids_async", fail)
    with pytest.raises(state_service.ProjectStateValidationError):
        await state_service.submit_daily_update(
            FakePool(),
            context=_context(),
            summary="Update",
            completion_percentage=101,
            blocker_ids=[],
        )


@pytest.mark.asyncio
async def test_actor_scoped_reads_use_project_access_service(monkeypatch):
    calls = []

    async def authorize(pool, *, claims, project_id):
        calls.append((pool, claims, project_id))
        return Project(id=project_id, name="Payments")

    access_module = ModuleType("service.projects")
    access_module.get_project_for_actor = authorize
    import service

    monkeypatch.setitem(sys.modules, "service.projects", access_module)
    monkeypatch.setattr(service, "projects", access_module, raising=False)
    async def list_features(*args, **kwargs):
        return []

    monkeypatch.setattr(state_service.project_state, "list_project_features_async", list_features)

    claims = object()
    pool = FakePool()
    result = await state_service.list_features_for_actor(
        pool, claims=claims, project_id="project-1"
    )

    assert result == []
    assert calls == [(pool, claims, "project-1")]


def test_context_is_bound_to_the_token_project():
    assert _context().project_id == "project-1"
