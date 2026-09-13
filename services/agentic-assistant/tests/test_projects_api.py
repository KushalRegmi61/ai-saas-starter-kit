"""HTTP authorization and response contracts for the project API."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import pytest
from auth.tokens import mint_assistant_token

import api.projects as projects_api
from agent.config import get_agent_settings
from main import app
from models.project_state import (
    DailyProjectUpdate,
    FeatureStatusHistory,
    ProjectContext,
    ProjectFeature,
)
from models.projects import Project, ProjectStatus
from service.projects import ProjectForbidden

SECRET = "project-api-test-secret"


class FakePool:
    @asynccontextmanager
    async def connection(self):
        yield None


def _project() -> Project:
    stamped = datetime(2026, 9, 13, tzinfo=UTC)
    return Project(
        id="p-1",
        name="Payments",
        description=None,
        lead_id=None,
        status=ProjectStatus.ON_TRACK,
        created_at=stamped,
        updated_at=stamped,
    )


def _headers(role: str):
    return {
        "Authorization": "Bearer "
        + mint_assistant_token(user_id=f"{role}-1", role=role, secret=SECRET, ttl_seconds=600)
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "assistant_jwt_secret", SECRET)
    app.state.assistant_user_pool = FakePool()
    yield
    app.state.assistant_user_pool = None


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_admin_can_create_project(client, monkeypatch):
    async def create(*args, **kwargs):
        return _project()

    monkeypatch.setattr(projects_api.projects, "create_project", create)
    async with _client() as http_client:
        response = await http_client.post(
            "/projects", json={"name": "Payments"}, headers=_headers("admin")
        )
    assert response.status_code == 201
    assert response.json()["id"] == "p-1"


@pytest.mark.parametrize("role", ["manager", "lead", "employee"])
@pytest.mark.asyncio
async def test_non_admin_cannot_create_project(client, monkeypatch, role):
    async def create(*args, **kwargs):
        raise ProjectForbidden("Admin role required")

    monkeypatch.setattr(projects_api.projects, "create_project", create)
    async with _client() as http_client:
        response = await http_client.post(
            "/projects", json={"name": "Payments"}, headers=_headers(role)
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_manager_and_lead_can_list_but_employee_is_forbidden(client, monkeypatch):
    async def list_for_actor(pool, *, claims):
        if claims.role == "employee":
            raise ProjectForbidden("Project access denied")
        return [_project()]

    monkeypatch.setattr(projects_api.projects, "list_projects_for_actor", list_for_actor)
    async with _client() as http_client:
        for role in ("admin", "manager", "lead"):
            response = await http_client.get("/projects", headers=_headers(role))
            assert response.status_code == 200
        response = await http_client.get("/projects", headers=_headers("employee"))
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_service_token_and_invalid_jwt_are_rejected(client, monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "agent_service_token", "service-token")
    async with _client() as http_client:
        service_response = await http_client.get(
            "/projects", headers={"Authorization": "Bearer service-token"}
        )
        invalid_response = await http_client.get(
            "/projects", headers={"Authorization": "Bearer invalid"}
        )
    assert service_response.status_code == 401
    assert invalid_response.status_code == 401


@pytest.mark.asyncio
async def test_project_state_reads_are_typed_and_project_scoped(client, monkeypatch):
    project = _project().model_copy(update={"lead_id": "lead-1", "completion_percentage": 72})
    context = ProjectContext(
        project=project,
        feature_counts={status: 0 for status in ("DEV", "QA", "UAT", "PROD", "BUG", "BLOCKED")},
        open_blockers=[],
        latest_update=None,
        scope={"project_id": "p-1"},
    )
    feature = ProjectFeature(id="f-1", project_id="p-1", name="Checkout", status="QA")
    update = DailyProjectUpdate(
        id="u-1", project_id="p-1", submitted_by="lead-1", summary="QA started", completion_percentage=72
    )
    history = FeatureStatusHistory(
        id=1, feature_id="f-1", feature_name="Checkout", old_status="DEV", new_status="QA", changed_by="lead-1"
    )

    async def context_for_actor(*args, **kwargs):
        return context

    async def features_for_actor(*args, **kwargs):
        return [feature]

    async def updates_for_actor(*args, **kwargs):
        assert kwargs["limit"] == 50
        return [update]

    async def history_for_actor(*args, **kwargs):
        assert kwargs["limit"] == 100
        return [history]

    async def audit_for_actor(*args, **kwargs):
        return []

    monkeypatch.setattr(projects_api.project_state, "get_project_context_for_actor", context_for_actor)
    monkeypatch.setattr(projects_api.project_state, "list_features_for_actor", features_for_actor)
    monkeypatch.setattr(projects_api.project_state, "list_updates_for_actor", updates_for_actor)
    monkeypatch.setattr(projects_api.project_state, "list_history_for_actor", history_for_actor)
    monkeypatch.setattr(projects_api.project_state, "list_audit_for_actor", audit_for_actor)

    async with _client() as http_client:
        for suffix in ("context", "features", "updates", "history", "audit"):
            response = await http_client.get(f"/projects/p-1/{suffix}", headers=_headers("manager"))
            assert response.status_code == 200
        response = await http_client.get("/projects/p-1/updates?limit=101", headers=_headers("manager"))
    assert response.status_code == 422
