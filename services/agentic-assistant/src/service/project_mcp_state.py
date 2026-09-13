"""Natural-language, project-bound MCP state operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from auth.store import record_audit_event_async

from models import project_state, project_state_ops
from models.project_state_contracts import (
    ProjectToolResult,
    ProjectUpdatesResult,
    ReferenceCandidate,
)
from models.project_tokens import ProjectMcpContext


class McpStateValidationError(ValueError):
    """Raised for invalid MCP state arguments."""


def _candidate(item: Any, *, feature: bool) -> ReferenceCandidate:
    return ReferenceCandidate(
        id=item.id,
        label=item.name if feature else item.title,
        description=item.description,
        status=item.status.value,
    )


def _resolved_or_candidates(items: list[Any], *, feature: bool) -> ProjectToolResult | Any:
    if not items:
        return ProjectToolResult(status="unresolved", message="No matching project item found")
    if len(items) > 1:
        return ProjectToolResult(
            status="ambiguous",
            message="Multiple project items match the reference",
            candidates=[_candidate(item, feature=feature) for item in items],
        )
    return items[0]


def _bounded_text(value: str | None, *, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise McpStateValidationError(f"{field} must contain 1 to {maximum} characters")
    return normalized


async def get_updates(
    pool: Any, *, context: ProjectMcpContext, since: datetime | None, limit: int
) -> ProjectUpdatesResult:
    if not 1 <= limit <= 100:
        raise McpStateValidationError("limit must be between 1 and 100")
    async with pool.connection() as connection:
        updates = await project_state.list_project_updates_async(
            connection, project_id=context.project_id, since=since, limit=limit
        )
    return ProjectUpdatesResult(
        updates=updates, since=since.isoformat() if since is not None else None, limit=limit
    )


async def manage_feature(
    pool: Any,
    *,
    context: ProjectMcpContext,
    action: str,
    feature_reference: str | None,
    name: str | None,
    description: str | None,
    new_status: str | None,
) -> ProjectToolResult:
    if action not in {"create", "update_status"}:
        raise McpStateValidationError("action must be create or update_status")
    async with pool.connection() as connection, connection.transaction():
        if action == "create":
            feature_name = _bounded_text(name, field="name", maximum=200)
            if feature_name is None:
                raise McpStateValidationError("name is required when creating a feature")
            feature_description = _bounded_text(description, field="description", maximum=2_000)
            status = project_state.FeatureStatus(new_status or "DEV")
            feature = await project_state_ops.create_feature_async(
                connection,
                project_id=context.project_id,
                name=feature_name,
                description=feature_description,
                status=status.value,
            )
            await _audit(connection, context, "project.feature_created", feature.id)
            return ProjectToolResult(status="created", feature=feature)

        reference = _bounded_text(feature_reference, field="feature_reference", maximum=500)
        if reference is None or new_status is None:
            raise McpStateValidationError("feature_reference and new_status are required")
        status = project_state.FeatureStatus(new_status)
        resolved = _resolved_or_candidates(
            await project_state_ops.find_features_async(
                connection, project_id=context.project_id, reference=reference
            ),
            feature=True,
        )
        if isinstance(resolved, ProjectToolResult):
            return resolved
        feature, old_status = await project_state.update_feature_status_async(
            connection,
            project_id=context.project_id,
            feature_id=resolved.id,
            new_status=status,
            changed_by=context.lead_id,
        )
        await _audit(
            connection,
            context,
            "project.feature_status_updated",
            feature.id,
            {"old_status": old_status.value, "new_status": feature.status.value},
        )
        return ProjectToolResult(status="updated", feature=feature)


async def manage_blocker(
    pool: Any,
    *,
    context: ProjectMcpContext,
    action: str,
    blocker_reference: str | None,
    title: str | None,
    description: str | None,
    severity: str,
) -> ProjectToolResult:
    if action not in {"create", "resolve"}:
        raise McpStateValidationError("action must be create or resolve")
    async with pool.connection() as connection, connection.transaction():
        if action == "create":
            blocker_title = _bounded_text(title, field="title", maximum=200)
            if blocker_title is None:
                raise McpStateValidationError("title is required when creating a blocker")
            blocker_description = _bounded_text(description, field="description", maximum=5_000)
            blocker = await project_state_ops.create_blocker_async(
                connection,
                project_id=context.project_id,
                title=blocker_title,
                description=blocker_description,
                severity=project_state.BlockerSeverity(severity).value,
            )
            await _audit(connection, context, "project.blocker_created", blocker.id)
            return ProjectToolResult(status="created", blocker=blocker)

        reference = _bounded_text(blocker_reference, field="blocker_reference", maximum=500)
        if reference is None:
            raise McpStateValidationError("blocker_reference is required")
        resolved = _resolved_or_candidates(
            await project_state_ops.find_blockers_async(
                connection, project_id=context.project_id, reference=reference
            ),
            feature=False,
        )
        if isinstance(resolved, ProjectToolResult):
            return resolved
        blocker = await project_state_ops.resolve_blocker_async(
            connection, project_id=context.project_id, blocker_id=resolved.id
        )
        await _audit(connection, context, "project.blocker_resolved", blocker.id)
        return ProjectToolResult(status="updated", blocker=blocker)


async def submit_update(
    pool: Any,
    *,
    context: ProjectMcpContext,
    summary: str,
    completion_percentage: int,
    blocker_references: list[str],
) -> ProjectToolResult:
    normalized_summary = _bounded_text(summary, field="summary", maximum=5_000)
    if normalized_summary is None:
        raise McpStateValidationError("summary is required")
    if not 0 <= completion_percentage <= 100:
        raise McpStateValidationError("completion percentage must be between 0 and 100")
    if len(blocker_references) > 20 or len(set(blocker_references)) != len(blocker_references):
        raise McpStateValidationError("blocker references must be unique and bounded")
    async with pool.connection() as connection, connection.transaction():
        blocker_ids: list[str] = []
        for reference in blocker_references:
            resolved = _resolved_or_candidates(
                await project_state_ops.find_blockers_async(
                    connection, project_id=context.project_id, reference=reference
                ),
                feature=False,
            )
            if isinstance(resolved, ProjectToolResult):
                return resolved
            blocker_ids.append(resolved.id)
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
        await _audit(connection, context, "project.daily_update_submitted", update.id)
        return ProjectToolResult(status="created", message="Daily update submitted", update=update)


async def _audit(
    connection: Any,
    context: ProjectMcpContext,
    action: str,
    target_id: str,
    extra: dict[str, Any] | None = None,
) -> None:
    detail = {"project_id": context.project_id, "token_id": context.token_id}
    if extra:
        detail.update(extra)
    await record_audit_event_async(
        connection,
        actor_id=context.lead_id,
        actor_email=None,
        action=action,
        resource="assistant_project_state",
        target_id=target_id,
        detail=detail,
    )
