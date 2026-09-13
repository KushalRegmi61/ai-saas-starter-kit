"""Project credential API response and authorization contract tests."""

from datetime import UTC, datetime, timedelta

import pytest
from auth.types import AssistantClaims

import api.project_tokens as token_api
import service.project_tokens as token_service
from models.project_tokens import ProjectToken
from models.projects import ProjectNotFound


def _claims(role: str) -> AssistantClaims:
    return AssistantClaims(subject=f"{role}-1", role=role, issued_at=1, expires_at=2)


def _token() -> ProjectToken:
    now = datetime.now(UTC)
    return ProjectToken(
        id="token-1",
        project_id="project-1",
        created_by="lead-1",
        label="Claude laptop",
        expires_at=now + timedelta(days=30),
        created_at=now,
    )


@pytest.mark.asyncio
async def test_create_response_contains_raw_token_only_once(monkeypatch):
    async def create(*args, **kwargs):
        return _token(), "prj_secret"

    monkeypatch.setattr(token_api.project_tokens, "create_project_token", create)
    response = await token_api.create_token(
        "project-1",
        token_api.ProjectTokenCreateRequest(label="Claude laptop"),
        None,
        _claims("lead"),
    )
    assert response.token == "prj_secret"
    assert response.id == "token-1"


@pytest.mark.asyncio
async def test_list_response_excludes_secret_and_creator(monkeypatch):
    async def list_tokens(*args, **kwargs):
        return [_token()]

    monkeypatch.setattr(token_api.project_tokens, "list_project_tokens", list_tokens)
    response = await token_api.list_tokens("project-1", None, _claims("admin"))
    payload = response[0].model_dump()
    assert "token" not in payload
    assert "created_by" not in payload


@pytest.mark.asyncio
async def test_forbidden_service_error_maps_to_403():
    error = token_api._error(token_service.ProjectTokenForbidden("denied"))
    assert error.status_code == 403


@pytest.mark.asyncio
async def test_missing_project_maps_to_404(monkeypatch):
    async def missing(*args, **kwargs):
        raise ProjectNotFound("missing")

    monkeypatch.setattr(token_api.project_tokens, "list_project_tokens", missing)
    with pytest.raises(Exception) as raised:
        await token_api.list_tokens("missing", None, _claims("admin"))
    assert raised.value.status_code == 404
