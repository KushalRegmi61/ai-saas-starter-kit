"""Project-state service used by the project-scoped MCP tools."""

from __future__ import annotations

from typing import Any

from auth.store import record_audit_event_async
from auth.types import AssistantClaims

from models import project_audit, project_state, projects
from models.project_tokens import ProjectMcpContext


class ProjectStateError(RuntimeError):
    """Base error for validated project-state operations."""


class ProjectStateNotFound(ProjectStateError):
    """Raised when a feature or blocker is outside the bound project."""


class ProjectStateValidationError(ProjectStateError):
    """Raised when a project-state mutation is invalid."""


async def _authorized_project(pool: Any, *, claims: AssistantClaims, project_id: str):
    # Import lazily because service.projects depends on agent.authz, whose
    # package initializer registers graph tools that depend on this service.
    from service import projects as project_access

    project = await project_access.get_project_for_actor(
        pool, claims=claims, project_id=project_id
    )
    return project


async def get_project_context_for_actor(pool: Any, *, claims: AssistantClaims, project_id: str):
    project = await _authorized_project(pool, claims=claims, project_id=project_id)
    async with pool.connection() as connection:
        features = await project_state.list_project_features_async(
            connection, project_id=project_id
        )
        blockers = await project_state.list_open_project_blockers_async(
            connection, project_id=project_id
        )
        latest_update = await project_state.get_latest_project_update_async(
            connection, project_id=project_id
        )
    counts = {status.value: 0 for status in project_state.FeatureStatus}
    grouped = {status.value: [] for status in project_state.FeatureStatus}
    for feature in features:
        counts[feature.status.value] += 1
        grouped[feature.status.value].append(feature.name)
    return project_state.ProjectContext(
        project=project,
        feature_counts=counts,
        features_by_status=grouped,
        open_blockers=blockers,
        latest_update=latest_update,
        scope={"project_id": project_id},
    )


async def list_features_for_actor(pool: Any, *, claims: AssistantClaims, project_id: str):
    await _authorized_project(pool, claims=claims, project_id=project_id)
    async with pool.connection() as connection:
        return await project_state.list_project_features_async(connection, project_id=project_id)


async def list_updates_for_actor(
    pool: Any, *, claims: AssistantClaims, project_id: str, limit: int = 50
):
    await _authorized_project(pool, claims=claims, project_id=project_id)
    async with pool.connection() as connection:
        return await project_state.list_project_updates_async(
            connection, project_id=project_id, limit=limit
        )


async def list_history_for_actor(
    pool: Any, *, claims: AssistantClaims, project_id: str, limit: int = 100
):
    await _authorized_project(pool, claims=claims, project_id=project_id)
    async with pool.connection() as connection:
        return await project_state.list_project_feature_history_async(
            connection, project_id=project_id, limit=limit
        )


async def list_audit_for_actor(
    pool: Any, *, claims: AssistantClaims, project_id: str, limit: int = 100
):
    await _authorized_project(pool, claims=claims, project_id=project_id)
    async with pool.connection() as connection:
        return await project_audit.list_project_audit_events_async(
            connection, project_id=project_id, limit=limit
        )


async def get_project_context(connection: Any, *, context: ProjectMcpContext):
    project = await projects.get_project_async(connection, context.project_id)
    if project is None or project.lead_id != context.lead_id:
        raise ProjectStateNotFound("project is no longer available")
    features = await project_state.list_project_features_async(
        connection, project_id=context.project_id
    )
    blockers = await project_state.list_open_project_blockers_async(
        connection, project_id=context.project_id
    )
    latest_update = await project_state.get_latest_project_update_async(
        connection, project_id=context.project_id
    )
    counts = {status.value: 0 for status in project_state.FeatureStatus}
    grouped = {status.value: [] for status in project_state.FeatureStatus}
    for feature in features:
        counts[feature.status.value] += 1
        grouped[feature.status.value].append(feature.name)
    return project_state.ProjectContext(
        project=project,
        feature_counts=counts,
        features_by_status=grouped,
        open_blockers=blockers,
        latest_update=latest_update,
        scope={"project_id": context.project_id},
    )


async def get_project_features(connection: Any, *, context: ProjectMcpContext):
    return await project_state.list_project_features_async(
        connection, project_id=context.project_id
    )


async def get_previous_update(connection: Any, *, context: ProjectMcpContext):
    return await project_state.get_latest_project_update_async(
        connection, project_id=context.project_id
    )


async def update_feature_status(
    pool: Any, *, context: ProjectMcpContext, feature_id: str, new_status: str
):
    try:
        status = project_state.FeatureStatus(new_status)
    except ValueError as exc:
        raise ProjectStateValidationError("unsupported feature status") from exc
    async with pool.connection() as connection, connection.transaction():
        try:
            feature, old_status = await project_state.update_feature_status_async(
                connection,
                project_id=context.project_id,
                feature_id=feature_id,
                new_status=status,
                changed_by=context.lead_id,
            )
        except KeyError as exc:
            raise ProjectStateNotFound("feature is not in the authenticated project") from exc
        await record_audit_event_async(
            connection,
            actor_id=context.lead_id,
            actor_email=None,
            action="project.feature_status_updated",
            resource="assistant_project_feature",
            target_id=feature.id,
            detail={
                "project_id": context.project_id,
                "token_id": context.token_id,
                "old_status": old_status.value,
                "new_status": feature.status.value,
            },
        )
        return feature


async def submit_daily_update(
    pool: Any,
    *,
    context: ProjectMcpContext,
    summary: str,
    completion_percentage: int,
    blocker_ids: list[str],
):
    normalized_summary = summary.strip()
    if not normalized_summary or len(normalized_summary) > 5_000:
        raise ProjectStateValidationError("summary must contain 1 to 5000 characters")
    if not 0 <= completion_percentage <= 100:
        raise ProjectStateValidationError("completion percentage must be between 0 and 100")
    if len(blocker_ids) > 100 or len(set(blocker_ids)) != len(blocker_ids):
        raise ProjectStateValidationError("blocker IDs must be unique and bounded")

    async with pool.connection() as connection, connection.transaction():
        blockers = await project_state.get_project_blockers_by_ids_async(
            connection, project_id=context.project_id, blocker_ids=blocker_ids
        )
        if len(blockers) != len(blocker_ids):
            raise ProjectStateNotFound("one or more blockers are not in the project")
        update = await project_state.create_daily_project_update_async(
            connection,
            project_id=context.project_id,
            submitted_by=context.lead_id,
            summary=normalized_summary,
            completion_percentage=completion_percentage,
            blocker_ids=blocker_ids,
        )
        await connection.execute(
            "UPDATE assistant_projects SET completion_percentage = %s, updated_at = now() "
            "WHERE id = %s AND lead_id = %s",
            (completion_percentage, context.project_id, context.lead_id),
        )
        await record_audit_event_async(
            connection,
            actor_id=context.lead_id,
            actor_email=None,
            action="project.daily_update_submitted",
            resource="assistant_daily_project_update",
            target_id=update.id,
            detail={
                "project_id": context.project_id,
                "token_id": context.token_id,
                "completion_percentage": completion_percentage,
                "blocker_count": len(blocker_ids),
            },
        )
        return update
