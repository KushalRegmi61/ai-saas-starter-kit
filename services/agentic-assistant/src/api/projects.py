"""Authenticated project management API."""

from __future__ import annotations

from datetime import datetime

from auth.types import AssistantClaims
from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from agent.authz import require_jwt_user
from api.auth import get_user_pool
from models.project_audit import ProjectAuditEvent
from models.project_state import (
    DailyProjectUpdate,
    FeatureStatusHistory,
    ProjectContext,
    ProjectFeature,
)
from models.projects import (
    InvalidLeadAssignment,
    LeadNotFound,
    Project,
    ProjectError,
    ProjectNotFound,
    ProjectStatus,
)
from service import project_state, projects

router = APIRouter(prefix="/projects")


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None
    lead_id: str | None
    status: ProjectStatus
    completion_percentage: int
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_project(cls, project: Project) -> ProjectResponse:
        return cls.model_validate(project.model_dump())


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    status: ProjectStatus | None = None


class ProjectLeadRequest(BaseModel):
    lead_id: str | None = None


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProjectNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if isinstance(exc, LeadNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    if isinstance(exc, InvalidLeadAssignment):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="User is not a lead"
        )
    if isinstance(exc, projects.ProjectForbidden):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project access denied")
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project request")


def _state_error(exc: Exception) -> HTTPException:
    return _error(exc)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> ProjectResponse:
    try:
        project = await projects.create_project(
            pool, claims=claims, name=payload.name, description=payload.description
        )
    except (ProjectError, projects.ProjectForbidden, ValueError) as exc:
        raise _error(exc) from None
    return ProjectResponse.from_project(project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> list[ProjectResponse]:
    try:
        result = await projects.list_projects_for_actor(pool, claims=claims)
    except (ProjectError, projects.ProjectForbidden, ValueError) as exc:
        raise _error(exc) from None
    return [ProjectResponse.from_project(project) for project in result]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> ProjectResponse:
    try:
        project = await projects.get_project_for_actor(pool, claims=claims, project_id=project_id)
    except (ProjectError, projects.ProjectForbidden, ValueError) as exc:
        raise _error(exc) from None
    return ProjectResponse.from_project(project)


@router.get("/{project_id}/context", response_model=ProjectContext)
async def get_project_context(
    project_id: str,
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> ProjectContext:
    try:
        return await project_state.get_project_context_for_actor(
            pool, claims=claims, project_id=project_id
        )
    except (ProjectError, projects.ProjectForbidden, ValueError) as exc:
        raise _state_error(exc) from None


@router.get("/{project_id}/features", response_model=list[ProjectFeature])
async def get_project_features(
    project_id: str,
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> list[ProjectFeature]:
    try:
        return await project_state.list_features_for_actor(
            pool, claims=claims, project_id=project_id
        )
    except (ProjectError, projects.ProjectForbidden, ValueError) as exc:
        raise _state_error(exc) from None


@router.get("/{project_id}/updates", response_model=list[DailyProjectUpdate])
async def get_project_updates(
    project_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> list[DailyProjectUpdate]:
    try:
        return await project_state.list_updates_for_actor(
            pool, claims=claims, project_id=project_id, limit=limit
        )
    except (ProjectError, projects.ProjectForbidden, ValueError) as exc:
        raise _state_error(exc) from None


@router.get("/{project_id}/history", response_model=list[FeatureStatusHistory])
async def get_project_history(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=200),
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> list[FeatureStatusHistory]:
    try:
        return await project_state.list_history_for_actor(
            pool, claims=claims, project_id=project_id, limit=limit
        )
    except (ProjectError, projects.ProjectForbidden, ValueError) as exc:
        raise _state_error(exc) from None


@router.get("/{project_id}/audit", response_model=list[ProjectAuditEvent])
async def get_project_audit(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=200),
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> list[ProjectAuditEvent]:
    try:
        return await project_state.list_audit_for_actor(
            pool, claims=claims, project_id=project_id, limit=limit
        )
    except (ProjectError, projects.ProjectForbidden, ValueError) as exc:
        raise _state_error(exc) from None


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> ProjectResponse:
    try:
        project = await projects.update_project_as_admin(
            pool,
            claims=claims,
            project_id=project_id,
            fields=payload.model_fields_set,
            name=payload.name,
            description=payload.description,
            status=payload.status,
        )
    except (ProjectError, projects.ProjectForbidden, ValueError) as exc:
        raise _error(exc) from None
    return ProjectResponse.from_project(project)


@router.patch("/{project_id}/lead", response_model=ProjectResponse)
async def replace_project_lead(
    project_id: str,
    payload: ProjectLeadRequest,
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> ProjectResponse:
    try:
        project = await projects.replace_project_lead(
            pool, claims=claims, project_id=project_id, lead_id=payload.lead_id
        )
    except (ProjectError, projects.ProjectForbidden, ValueError) as exc:
        raise _error(exc) from None
    return ProjectResponse.from_project(project)
