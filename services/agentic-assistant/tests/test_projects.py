"""Project persistence contracts and Phase 0 authorization policy tests."""

from datetime import UTC, datetime

import pytest

from agent.authz import (
    PROJECT_ACCESS_ROLES,
    can_assign_project,
    can_view_all_projects,
    can_view_assigned_projects,
)
from models.projects import (
    AssignmentConflict,
    InvalidLeadAssignment,
    LeadNotFound,
    Project,
    ProjectNotFound,
    ProjectStatus,
    assign_project_lead_async,
    create_project_async,
    ensure_project_tables_async,
    list_projects_for_lead_async,
    replace_project_lead_async,
    update_project_async,
)


class Result:
    def __init__(self, rows):
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return self.rows


def _row(*, project_id="p-1", lead_id=None, status="ON_TRACK"):
    stamped = datetime(2026, 9, 13, tzinfo=UTC)
    return (project_id, "Payments", "Payment project", lead_id, status, stamped, stamped)


class FakeConnection:
    def __init__(self, *, project=None, lead=None, projects=None):
        self.calls = []
        self.project = project
        self.lead = lead
        self.projects = projects or []

    async def execute(self, sql, params=()):
        self.calls.append((sql, params))
        lowered = " ".join(sql.lower().split())
        if lowered.startswith("insert into assistant_projects"):
            project_id, name, description, status = params
            self.project = _row(project_id=project_id, status=status)
            self.project = (self.project[0], name, description, *self.project[3:])
            return Result([self.project])
        if "select id, name, description, lead_id, status" in lowered:
            if "where id = %s" in lowered:
                return Result([self.project] if self.project else [])
            if "where lead_id = %s" in lowered:
                return Result(self.projects)
            return Result(self.projects)
        if "select id, role from assistant_users" in lowered:
            return Result([self.lead] if self.lead else [])
        if lowered.startswith("update assistant_projects"):
            lead_id, _project_id = params
            self.project = (*self.project[:3], lead_id, *self.project[4:])
            return Result([self.project])
        return Result([])


@pytest.mark.asyncio
async def test_project_status_values_are_explicit():
    assert [item.value for item in ProjectStatus] == [
        "ON_TRACK",
        "AT_RISK",
        "BLOCKED",
        "COMPLETED",
    ]


@pytest.mark.asyncio
async def test_schema_initialization_is_idempotent_shape():
    connection = FakeConnection()
    await ensure_project_tables_async(connection)
    await ensure_project_tables_async(connection)
    assert len(connection.calls) == 8
    assert "assistant_projects" in connection.calls[0][0]
    assert "ON_TRACK" in connection.calls[0][0]
    assert "ON DELETE RESTRICT" in connection.calls[0][0]


@pytest.mark.asyncio
async def test_create_project_returns_public_shape_without_credentials():
    project = await create_project_async(
        FakeConnection(), name="  Payments ", description="  Payment project  "
    )
    assert isinstance(project, Project)
    assert project.name == "Payments"
    assert project.description == "Payment project"
    assert project.lead_id is None
    assert "password_hash" not in project.model_dump()
    assert "token_hash" not in project.model_dump()


@pytest.mark.asyncio
async def test_create_project_rejects_blank_name():
    with pytest.raises(ValueError, match="project name"):
        await create_project_async(FakeConnection(), name="   ")


@pytest.mark.asyncio
async def test_assign_lead_updates_unassigned_project():
    connection = FakeConnection(project=_row(), lead=("lead-1", "lead"))
    project = await assign_project_lead_async(connection, project_id="p-1", lead_id="lead-1")
    assert project.lead_id == "lead-1"
    assert any("updated_at = now()" in sql for sql, _ in connection.calls)


@pytest.mark.asyncio
async def test_assign_lead_is_idempotent():
    connection = FakeConnection(project=_row(lead_id="lead-1"), lead=("lead-1", "lead"))
    project = await assign_project_lead_async(connection, project_id="p-1", lead_id="lead-1")
    assert project.lead_id == "lead-1"
    assert not any("UPDATE assistant_projects" in sql for sql, _ in connection.calls)


@pytest.mark.asyncio
async def test_assign_lead_rejects_missing_or_non_lead_user():
    with pytest.raises(LeadNotFound):
        await assign_project_lead_async(
            FakeConnection(project=_row()), project_id="p-1", lead_id="missing"
        )
    with pytest.raises(InvalidLeadAssignment):
        await assign_project_lead_async(
            FakeConnection(project=_row(), lead=("manager-1", "manager")),
            project_id="p-1",
            lead_id="manager-1",
        )


@pytest.mark.asyncio
async def test_assign_lead_rejects_silent_replacement_and_missing_project():
    with pytest.raises(AssignmentConflict):
        await assign_project_lead_async(
            FakeConnection(project=_row(lead_id="lead-1"), lead=("lead-2", "lead")),
            project_id="p-1",
            lead_id="lead-2",
        )
    with pytest.raises(ProjectNotFound):
        await assign_project_lead_async(
            FakeConnection(lead=("lead-1", "lead")), project_id="missing", lead_id="lead-1"
        )


@pytest.mark.asyncio
async def test_replace_lead_supports_reassignment_and_unassignment():
    connection = FakeConnection(project=_row(), lead=("lead-2", "lead"))
    replaced = await replace_project_lead_async(connection, project_id="p-1", lead_id="lead-2")
    assert replaced.lead_id == "lead-2"

    connection = FakeConnection(project=_row(lead_id="lead-2"))
    unassigned = await replace_project_lead_async(connection, project_id="p-1", lead_id=None)
    assert unassigned.lead_id is None


@pytest.mark.asyncio
async def test_update_project_can_clear_description():
    class UpdateConnection(FakeConnection):
        async def execute(self, sql, params=()):
            self.calls.append((sql, params))
            if "UPDATE assistant_projects" in sql:
                return Result([(*_row()[:2], None, *_row()[3:])])
            return await super().execute(sql, params)

    project = await update_project_async(
        UpdateConnection(), "p-1", description=None, status=ProjectStatus.BLOCKED
    )
    assert project is not None
    assert project.description is None


@pytest.mark.asyncio
async def test_list_projects_for_lead_uses_lead_scope():
    connection = FakeConnection(projects=[_row(lead_id="lead-1")])
    projects = await list_projects_for_lead_async(connection, "lead-1")
    assert [project.lead_id for project in projects] == ["lead-1"]
    assert connection.calls[-1][1] == ("lead-1",)


def test_project_authorization_policy_is_separate_from_service_token_auth():
    assert can_assign_project("admin")
    assert not can_assign_project("manager")
    assert can_view_all_projects("manager")
    assert can_view_all_projects("admin")
    assert can_view_assigned_projects("lead")
    assert not can_view_assigned_projects("employee")
    assert frozenset({"admin", "manager", "lead"}) == PROJECT_ACCESS_ROLES
