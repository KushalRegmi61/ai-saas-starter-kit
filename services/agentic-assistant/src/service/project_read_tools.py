"""Read-only manager project overview, feature, blocker, and activity tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.types import (
    ProjectActivityResult,
    ProjectBlockersResult,
    ProjectBlockerSummary,
    ProjectFeaturesResult,
    ProjectFeatureSummary,
    ProjectHistoryItem,
    ProjectOverviewResult,
    ProjectResolution,
    ProjectUpdateSummary,
)
from models import project_queries, project_state
from service import projects as project_access
from service.project_tools import (
    ProjectToolValidationError,
    resolve_project_for_actor,
    validate_project_reference,
)

MAX_FEATURE_LIMIT = 100
MAX_BLOCKER_LIMIT = 50
MAX_ACTIVITY_LIMIT = 50


def _validation(message: str) -> ProjectResolution:
    return ProjectResolution(status="validation_error", message=message)


def validate_feature_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_FEATURE_LIMIT:
        raise ProjectToolValidationError(f"limit must be between 1 and {MAX_FEATURE_LIMIT}")
    return limit


def validate_blocker_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_BLOCKER_LIMIT:
        raise ProjectToolValidationError(f"limit must be between 1 and {MAX_BLOCKER_LIMIT}")
    return limit


def validate_activity_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_ACTIVITY_LIMIT:
        raise ProjectToolValidationError(f"limit must be between 1 and {MAX_ACTIVITY_LIMIT}")
    return limit


def _validate_filters(values: list[str] | None, allowed: type[Any], field: str) -> list[str] | None:
    if values is None:
        return None
    if len(values) > len(allowed) or len(set(values)) != len(values):
        raise ProjectToolValidationError(f"{field} contains too many or duplicate values")
    try:
        return [allowed(value).value for value in values]
    except ValueError as exc:
        raise ProjectToolValidationError(f"invalid {field} value") from exc


def _feature_summary(feature: project_state.ProjectFeature) -> ProjectFeatureSummary:
    return ProjectFeatureSummary(
        name=feature.name,
        description=feature.description,
        status=feature.status.value,
        updated_at=feature.updated_at,
    )


def _blocker_summary(blocker: project_state.ProjectBlocker) -> ProjectBlockerSummary:
    return ProjectBlockerSummary(
        title=blocker.title,
        description=blocker.description,
        severity=blocker.severity.value,
        status=blocker.status.value,
        created_at=blocker.created_at,
        resolved_at=blocker.resolved_at,
    )


async def _resolve(
    pool: Any, *, claims: Any, project_reference: str, project_id: str | None
):
    return await resolve_project_for_actor(
        pool, claims=claims, project_reference=project_reference, project_id=project_id
    )


async def get_overview(
    pool: Any, *, claims: Any, project_reference: str, project_id: str | None
) -> ProjectOverviewResult:
    resolution = await _resolve(
        pool, claims=claims, project_reference=project_reference, project_id=project_id
    )
    if resolution.project is None:
        return ProjectOverviewResult(resolution=resolution)
    project = await project_access.get_project_for_actor(
        pool, claims=claims, project_id=resolution.project.project_id
    )
    async with pool.connection() as connection:
        features = await project_queries.list_features_async(
            connection,
            project_id=resolution.project.project_id,
            query=None,
            statuses=None,
            limit=MAX_FEATURE_LIMIT,
        )
        feature_counts = await project_queries.feature_counts_async(
            connection, project_id=resolution.project.project_id
        )
        open_blocker_count = await project_queries.open_blocker_count_async(
            connection, project_id=resolution.project.project_id
        )
        latest = await project_state.get_latest_project_update_async(
            connection, project_id=resolution.project.project_id
        )
    grouped = {status.value: [] for status in project_state.FeatureStatus}
    for feature in features:
        grouped[feature.status.value].append(feature.name)
    complete_counts = {status.value: feature_counts.get(status.value, 0) for status in project_state.FeatureStatus}
    return ProjectOverviewResult(
        resolution=resolution,
        project=resolution.project,
        status=project.status.value,
        completion_percentage=project.completion_percentage,
        features_by_status=grouped,
        feature_counts=complete_counts,
        open_blocker_count=open_blocker_count,
        latest_update=(
            ProjectUpdateSummary(
                summary=latest.summary,
                completion_percentage=latest.completion_percentage,
                created_at=latest.created_at,
            )
            if latest is not None
            else None
        ),
    )


async def get_features(
    pool: Any,
    *,
    claims: Any,
    project_reference: str,
    project_id: str | None,
    feature_query: str | None,
    statuses: list[str] | None,
    limit: int,
) -> ProjectFeaturesResult:
    validate_feature_limit(limit)
    reference = validate_project_reference(project_reference)
    normalized_query = feature_query.strip() if feature_query is not None else None
    if normalized_query == "":
        raise ProjectToolValidationError("feature_query must not be empty")
    status_values = _validate_filters(statuses, project_state.FeatureStatus, "statuses")
    resolution = await _resolve(
        pool, claims=claims, project_reference=reference, project_id=project_id
    )
    if resolution.project is None:
        return ProjectFeaturesResult(resolution=resolution)
    async with pool.connection() as connection:
        features = await project_queries.list_features_async(
            connection,
            project_id=resolution.project.project_id,
            query=normalized_query,
            statuses=status_values,
            limit=limit,
        )
    counts: dict[str, int] = {}
    for feature in features:
        counts[feature.status.value] = counts.get(feature.status.value, 0) + 1
    return ProjectFeaturesResult(
        resolution=resolution,
        features=[_feature_summary(feature) for feature in features],
        feature_counts=counts,
        total_returned=len(features),
    )


async def get_blockers(
    pool: Any,
    *,
    claims: Any,
    project_reference: str,
    project_id: str | None,
    blocker_query: str | None,
    statuses: list[str] | None,
    severities: list[str] | None,
    limit: int,
) -> ProjectBlockersResult:
    validate_blocker_limit(limit)
    normalized_query = blocker_query.strip() if blocker_query is not None else None
    if normalized_query == "":
        raise ProjectToolValidationError("blocker_query must not be empty")
    status_values = _validate_filters(
        statuses or [project_state.BlockerStatus.OPEN.value],
        project_state.BlockerStatus,
        "statuses",
    ) or []
    severity_values = _validate_filters(severities, project_state.BlockerSeverity, "severities")
    resolution = await _resolve(
        pool, claims=claims, project_reference=project_reference, project_id=project_id
    )
    if resolution.project is None:
        return ProjectBlockersResult(resolution=resolution)
    async with pool.connection() as connection:
        blockers = await project_queries.list_blockers_async(
            connection,
            project_id=resolution.project.project_id,
            query=normalized_query,
            statuses=status_values,
            severities=severity_values,
            limit=limit,
        )
    return ProjectBlockersResult(
        resolution=resolution,
        blockers=[_blocker_summary(blocker) for blocker in blockers],
        total_returned=len(blockers),
    )


async def get_activity(
    pool: Any,
    *,
    claims: Any,
    project_reference: str,
    project_id: str | None,
    since: datetime | None,
    limit: int,
) -> ProjectActivityResult:
    validate_activity_limit(limit)
    resolution = await _resolve(
        pool, claims=claims, project_reference=project_reference, project_id=project_id
    )
    if resolution.project is None:
        return ProjectActivityResult(resolution=resolution)
    async with pool.connection() as connection:
        updates = await project_state.list_project_updates_async(
            connection, project_id=resolution.project.project_id, since=since, limit=limit
        )
        history = await project_queries.list_history_async(
            connection, project_id=resolution.project.project_id, since=since, limit=limit
        )
    return ProjectActivityResult(
        resolution=resolution,
        updates=[
            ProjectUpdateSummary(
                summary=update.summary,
                completion_percentage=update.completion_percentage,
                created_at=update.created_at,
            )
            for update in updates
        ],
        history=[
            ProjectHistoryItem(
                feature_id=item.feature_id,
                feature_name=item.feature_name,
                old_status=item.old_status.value,
                new_status=item.new_status.value,
                changed_by=item.changed_by,
                changed_at=item.changed_at,
            )
            for item in history
        ],
    )
