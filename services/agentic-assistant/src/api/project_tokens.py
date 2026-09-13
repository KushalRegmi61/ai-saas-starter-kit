"""JWT-protected project credential management API."""

from __future__ import annotations

from datetime import datetime

from auth.types import AssistantClaims
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from agent.authz import require_jwt_user
from api.auth import get_user_pool
from models.project_tokens import ProjectToken, ProjectTokenError, ProjectTokenNotFound
from models.projects import ProjectError, ProjectNotFound
from service import project_tokens

router = APIRouter(prefix="/projects/{project_id}/tokens")


class ProjectTokenCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=100)


class ProjectTokenResponse(BaseModel):
    id: str
    project_id: str
    label: str
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime | None

    @classmethod
    def from_token(cls, token: ProjectToken) -> ProjectTokenResponse:
        return cls.model_validate(token.model_dump(exclude={"created_by"}))


class ProjectTokenCreatedResponse(ProjectTokenResponse):
    token: str


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ProjectNotFound, ProjectTokenNotFound)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    if isinstance(exc, project_tokens.ProjectTokenForbidden):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Project credential access denied"
        )
    if isinstance(exc, (ProjectError, ProjectTokenError, ValueError)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid project credential request",
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project credential request"
    )


@router.post("", response_model=ProjectTokenCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_token(
    project_id: str,
    payload: ProjectTokenCreateRequest,
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> ProjectTokenCreatedResponse:
    try:
        token, raw_token = await project_tokens.create_project_token(
            pool, claims=claims, project_id=project_id, label=payload.label
        )
    except (
        ProjectError,
        ProjectTokenError,
        project_tokens.ProjectTokenForbidden,
        ValueError,
    ) as exc:
        raise _error(exc) from None
    metadata = ProjectTokenResponse.from_token(token)
    return ProjectTokenCreatedResponse(**metadata.model_dump(), token=raw_token)


@router.get("", response_model=list[ProjectTokenResponse])
async def list_tokens(
    project_id: str,
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> list[ProjectTokenResponse]:
    try:
        tokens = await project_tokens.list_project_tokens(
            pool, claims=claims, project_id=project_id
        )
    except (
        ProjectError,
        ProjectTokenError,
        project_tokens.ProjectTokenForbidden,
        ValueError,
    ) as exc:
        raise _error(exc) from None
    return [ProjectTokenResponse.from_token(token) for token in tokens]


@router.post("/{token_id}/revoke", response_model=ProjectTokenResponse)
async def revoke_token(
    project_id: str,
    token_id: str,
    pool: AsyncConnectionPool = Depends(get_user_pool),
    claims: AssistantClaims = Depends(require_jwt_user),
) -> ProjectTokenResponse:
    try:
        token = await project_tokens.revoke_project_token(
            pool, claims=claims, project_id=project_id, token_id=token_id
        )
    except (
        ProjectError,
        ProjectTokenError,
        project_tokens.ProjectTokenForbidden,
        ValueError,
    ) as exc:
        raise _error(exc) from None
    return ProjectTokenResponse.from_token(token)
