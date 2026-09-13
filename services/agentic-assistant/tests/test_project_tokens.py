"""Project credential persistence and service security tests."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from auth.types import AssistantClaims
from pydantic import ValidationError

import service.project_tokens as token_service
from models.project_tokens import (
    ProjectMcpContext,
    ensure_project_token_tables_async,
    revoke_project_tokens_for_project_async,
)
from models.projects import Project, ProjectStatus


class Result:
    def __init__(self, rows):
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return self.rows


def _token_row(token_id="t-1", project_id="p-1", revoked_at=None):
    stamped = datetime(2026, 9, 13, tzinfo=UTC)
    return (
        token_id,
        project_id,
        "lead-1",
        "Claude laptop",
        stamped + timedelta(days=30),
        None,
        revoked_at,
        stamped,
    )


class SchemaConnection:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return Result([])


@pytest.mark.asyncio
async def test_token_schema_is_idempotent_and_indexed():
    connection = SchemaConnection()
    await ensure_project_token_tables_async(connection)
    await ensure_project_token_tables_async(connection)
    assert len(connection.calls) == 8
    assert "assistant_project_mcp_tokens" in connection.calls[0][0]
    assert "ON DELETE CASCADE" in connection.calls[0][0]
    assert "token_hash" in connection.calls[0][0]


@pytest.mark.asyncio
async def test_revoke_tokens_is_project_scoped():
    class Connection(SchemaConnection):
        async def execute(self, sql, params=()):
            self.calls.append((sql, params))
            if "RETURNING" in sql:
                return Result([_token_row()])
            return Result([])

    connection = Connection()
    revoked = await revoke_project_tokens_for_project_async(connection, project_id="p-1")
    assert revoked[0].project_id == "p-1"
    assert connection.calls[-1][1] == ("p-1",)


def test_context_is_immutable_and_contains_project_scope():
    context = ProjectMcpContext(
        token_id="t-1",
        project_id="p-1",
        project_name="Payments",
        lead_id="lead-1",
        token_label="Claude laptop",
    )
    assert context.project_id == "p-1"
    with pytest.raises(ValidationError):
        context.project_id = "p-2"


def _claims(role: str, subject: str = "lead-1") -> AssistantClaims:
    return AssistantClaims(subject=subject, role=role, issued_at=1, expires_at=2)


def _project(lead_id="lead-1") -> Project:
    return Project(
        id="p-1",
        name="Payments",
        lead_id=lead_id,
        status=ProjectStatus.ON_TRACK,
    )


class FakeConnection:
    @asynccontextmanager
    async def transaction(self):
        yield


class FakePool:
    @asynccontextmanager
    async def connection(self):
        yield FakeConnection()


@pytest.mark.asyncio
async def test_manager_cannot_create_project_token(monkeypatch):
    async def fail_project(*args, **kwargs):
        pytest.fail("manager must be rejected before project lookup")

    monkeypatch.setattr(token_service, "_get_project", fail_project)
    with pytest.raises(token_service.ProjectTokenForbidden):
        await token_service.create_project_token(
            FakePool(), claims=_claims("manager"), project_id="p-1", label="laptop"
        )


@pytest.mark.asyncio
async def test_lead_must_be_current_project_owner(monkeypatch):
    async def get_project(connection, project_id):
        return _project("other-lead")

    monkeypatch.setattr(token_service, "_get_project", get_project)
    with pytest.raises(token_service.ProjectTokenForbidden):
        await token_service.create_project_token(
            FakePool(), claims=_claims("lead"), project_id="p-1", label="laptop"
        )


def test_token_generation_is_hashed_and_expiring(monkeypatch):
    raw = token_service._new_raw_token()
    hashed = token_service._hash_token(raw)
    assert raw.startswith("prj_")
    assert len(hashed) == 64
    assert hashed != raw
    assert timedelta(days=30) == token_service.TOKEN_LIFETIME


@pytest.mark.asyncio
async def test_authenticate_retries_stale_connection_then_succeeds(monkeypatch):
    from types import SimpleNamespace

    from psycopg import OperationalError

    token = SimpleNamespace(id="t-1", project_id="p-1", created_by="lead-1", label="laptop")

    async def find_active(connection, token_hash):
        return (token, "Payments", "lead-1")

    async def touch(connection, token_id):
        return None

    monkeypatch.setattr("models.project_tokens.find_active_project_token_async", find_active)
    monkeypatch.setattr("models.project_tokens.touch_project_token_last_used_async", touch)

    attempts = {"count": 0}

    class FlakyPool:
        @asynccontextmanager
        async def connection(self):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise OperationalError("SSL connection has been closed unexpectedly")
            yield FakeConnection()

    context = await token_service.authenticate_project_token(FlakyPool(), raw_token="prj_test")
    assert context.project_id == "p-1"
    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_authenticate_reraises_persistent_db_outage(monkeypatch):
    from psycopg import OperationalError

    class DeadPool:
        @asynccontextmanager
        async def connection(self):
            raise OperationalError("SSL connection has been closed unexpectedly")
            yield  # pragma: no cover

    with pytest.raises(OperationalError):
        await token_service.authenticate_project_token(DeadPool(), raw_token="prj_test")
