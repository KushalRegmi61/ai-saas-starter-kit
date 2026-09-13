"""Project service orchestration and role-scoped access rules."""

from __future__ import annotations

from typing import Any

from auth.store import record_audit_event_async
from auth.types import AssistantClaims

from agent.authz import can_assign_project, can_view_all_projects, can_view_assigned_projects
from models import projects
from models.project_tokens import revoke_project_tokens_for_project_async


class ProjectForbidden(PermissionError):
    """Raised when a caller cannot access a project or project operation."""


def _require_admin(claims: AssistantClaims) -> None:
    if not can_assign_project(claims.role):
        raise ProjectForbidden("Admin role required")


def _require_project_viewer(claims: AssistantClaims) -> None:
    if not (can_view_all_projects(claims.role) or can_view_assigned_projects(claims.role)):
        raise ProjectForbidden("Project access denied")


async def _audit(
    connection: Any, *, claims: AssistantClaims, action: str, project_id: str, detail: dict
):
    await record_audit_event_async(
        connection,
        actor_id=claims.subject,
        actor_email=None,
        action=action,
        resource="assistant_project",
        target_id=project_id,
        detail=detail,
    )


async def create_project(pool: Any, *, claims: AssistantClaims, name: str, description: str | None):
    _require_admin(claims)
    async with pool.connection() as connection, connection.transaction():
        project = await projects.create_project_async(
            connection, name=name, description=description
        )
        await _audit(
            connection,
            claims=claims,
            action="project.created",
            project_id=project.id,
            detail={"name": project.name},
        )
        return project


async def list_projects_for_actor(pool: Any, *, claims: AssistantClaims):
    _require_project_viewer(claims)
    async with pool.connection() as connection:
        if can_view_all_projects(claims.role):
            return await projects.list_projects_async(connection)
        return await projects.list_projects_for_lead_async(connection, claims.subject)


async def get_project_for_actor(pool: Any, *, claims: AssistantClaims, project_id: str):
    _require_project_viewer(claims)
    async with pool.connection() as connection:
        project = await projects.get_project_async(connection, project_id)
    if project is None:
        raise projects.ProjectNotFound(project_id)
    if can_view_assigned_projects(claims.role) and project.lead_id != claims.subject:
        raise ProjectForbidden("Project access denied")
    return project


async def update_project_as_admin(
    pool: Any,
    *,
    claims: AssistantClaims,
    project_id: str,
    fields: set[str],
    name: str | None,
    description: str | None,
    status: projects.ProjectStatus | None,
):
    _require_admin(claims)
    async with pool.connection() as connection, connection.transaction():
        project = await projects.update_project_async(
            connection,
            project_id,
            name=name if "name" in fields else projects._UNSET,
            description=description if "description" in fields else projects._UNSET,
            status=status if "status" in fields else projects._UNSET,
        )
        if project is None:
            raise projects.ProjectNotFound(project_id)
        await _audit(
            connection,
            claims=claims,
            action="project.updated",
            project_id=project_id,
            detail={"fields": sorted(fields)},
        )
        return project


async def replace_project_lead(
    pool: Any, *, claims: AssistantClaims, project_id: str, lead_id: str | None
):
    _require_admin(claims)
    async with pool.connection() as connection, connection.transaction():
        before = await projects.get_project_async(connection, project_id)
        if before is None:
            raise projects.ProjectNotFound(project_id)
        project = await projects.replace_project_lead_async(
            connection, project_id=project_id, lead_id=lead_id
        )
        if before.lead_id != lead_id:
            invalidated = await revoke_project_tokens_for_project_async(
                connection, project_id=project_id
            )
            action = (
                "project.lead_unassigned"
                if lead_id is None
                else "project.lead_assigned"
                if before.lead_id is None
                else "project.lead_replaced"
            )
            await _audit(
                connection,
                claims=claims,
                action=action,
                project_id=project_id,
                detail={"previous_lead_id": before.lead_id, "new_lead_id": lead_id},
            )
            if invalidated:
                await _audit(
                    connection,
                    claims=claims,
                    action="project.mcp_tokens_invalidated",
                    project_id=project_id,
                    detail={
                        "token_ids": [token.id for token in invalidated],
                        "reason": "lead_changed",
                    },
                )
        return project
