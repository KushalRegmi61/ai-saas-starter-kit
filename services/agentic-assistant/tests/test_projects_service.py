"""Role-scoped project service tests."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from auth.types import AssistantClaims

import service.projects as project_service
from models.projects import Project, ProjectStatus


def _claims(role: str, subject: str = "u-1") -> AssistantClaims:
    return AssistantClaims(subject=subject, role=role, issued_at=1, expires_at=2)


def _project(project_id="p-1", lead_id=None) -> Project:
    stamped = datetime(2026, 9, 13, tzinfo=UTC)
    return Project(
        id=project_id,
        name="Payments",
        description="Payment project",
        lead_id=lead_id,
        status=ProjectStatus.ON_TRACK,
        created_at=stamped,
        updated_at=stamped,
    )


class FakeConnection:
    def __init__(self):
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self):
        self.transactions += 1
        yield


class FakePool:
    def __init__(self):
        self.connection_instance = FakeConnection()

    @asynccontextmanager
    async def connection(self):
        yield self.connection_instance


@pytest.mark.asyncio
async def test_manager_sees_all_projects_and_lead_is_scoped(monkeypatch):
    all_projects = [_project("p-1", "lead-1"), _project("p-2", "lead-2")]

    async def list_all(connection):
        return all_projects

    async def list_for_lead(connection, lead_id):
        return [all_projects[0]]

    monkeypatch.setattr(project_service.projects, "list_projects_async", list_all)
    monkeypatch.setattr(project_service.projects, "list_projects_for_lead_async", list_for_lead)

    assert (
        await project_service.list_projects_for_actor(FakePool(), claims=_claims("manager"))
        == all_projects
    )
    assert await project_service.list_projects_for_actor(
        FakePool(), claims=_claims("lead", "lead-1")
    ) == [all_projects[0]]


@pytest.mark.asyncio
async def test_employee_cannot_access_projects():
    with pytest.raises(project_service.ProjectForbidden):
        await project_service.list_projects_for_actor(FakePool(), claims=_claims("employee"))


@pytest.mark.asyncio
async def test_lead_cannot_get_another_leads_project(monkeypatch):
    async def get_other_project(connection, project_id):
        return _project(project_id, "other-lead")

    monkeypatch.setattr(project_service.projects, "get_project_async", get_other_project)
    with pytest.raises(project_service.ProjectForbidden):
        await project_service.get_project_for_actor(
            FakePool(), claims=_claims("lead", "lead-1"), project_id="p-1"
        )


@pytest.mark.asyncio
async def test_admin_create_is_transactional_and_audited(monkeypatch):
    created = _project()
    events = []

    async def create(*args, **kwargs):
        return created

    async def record(connection, **kwargs):
        events.append(kwargs)

    monkeypatch.setattr(project_service.projects, "create_project_async", create)
    monkeypatch.setattr(project_service, "record_audit_event_async", record)

    pool = FakePool()
    result = await project_service.create_project(
        pool, claims=_claims("admin"), name="Payments", description=None
    )

    assert result == created
    assert pool.connection_instance.transactions == 1
    assert events[0]["action"] == "project.created"


@pytest.mark.asyncio
async def test_non_admin_cannot_mutate_project(monkeypatch):
    async def fail_create(*args, **kwargs):
        pytest.fail("non-admin must be blocked before persistence")

    monkeypatch.setattr(project_service.projects, "create_project_async", fail_create)
    with pytest.raises(project_service.ProjectForbidden):
        await project_service.create_project(
            FakePool(), claims=_claims("manager"), name="Payments", description=None
        )
