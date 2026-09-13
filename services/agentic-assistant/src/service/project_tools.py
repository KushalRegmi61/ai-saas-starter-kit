"""Authenticated service boundary for project discovery and retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from auth.types import AssistantClaims

from agent.types import (
    ProjectCandidate,
    ProjectHistoryItem,
    ProjectHistoryResult,
    ProjectKnowledgeResult,
    ProjectMetricsResult,
    ProjectResolution,
    ProjectStatusResult,
)
from models import projects
from service import projects as project_access
from service.projects import ProjectForbidden

MAX_HISTORY_LIMIT = 100
MAX_TOP_K = 10
MAX_PROJECT_CANDIDATES = 10


class ProjectToolValidationError(ValueError):
    """Raised when a project-agent tool request is malformed."""


def validate_project_reference(project_reference: str) -> str:
    reference = project_reference.strip()
    if not reference:
        raise ProjectToolValidationError("project_reference must not be empty")
    if len(reference) > 500:
        raise ProjectToolValidationError("project_reference must be at most 500 characters")
    return reference


def validate_project_id(project_id: str | None) -> str | None:
    if project_id is None:
        return None
    value = project_id.strip()
    if not value:
        raise ProjectToolValidationError("project_id must not be empty when provided")
    if len(value) > 200:
        raise ProjectToolValidationError("project_id must be at most 200 characters")
    return value


def validate_history_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_HISTORY_LIMIT:
        raise ProjectToolValidationError(f"limit must be between 1 and {MAX_HISTORY_LIMIT}")
    return limit


def validate_top_k(top_k: int) -> int:
    if not 1 <= top_k <= MAX_TOP_K:
        raise ProjectToolValidationError(f"top_k must be between 1 and {MAX_TOP_K}")
    return top_k


def _candidate(project: projects.Project) -> ProjectCandidate:
    return ProjectCandidate(
        project_id=project.id,
        name=project.name,
        description=project.description,
    )


def _reference_matches(reference: str, project: projects.Project) -> bool:
    normalized = " ".join(reference.casefold().split())
    name = " ".join(project.name.casefold().split())
    description = (project.description or "").casefold()
    return normalized == name or normalized in description or normalized in name


async def resolve_project_for_actor(
    pool: Any,
    *,
    claims: AssistantClaims,
    project_reference: str,
    project_id: str | None = None,
) -> ProjectResolution:
    """Resolve an optional ID only after normal actor authorization.

    Natural-language lookup searches only the caller's authorized projects.
    """

    reference = validate_project_reference(project_reference)
    checked_id = validate_project_id(project_id)
    if checked_id is not None:
        try:
            project = await project_access.get_project_for_actor(
                pool, claims=claims, project_id=checked_id
            )
        except ProjectForbidden:
            return ProjectResolution(status="forbidden", message="Project access denied")
        except projects.ProjectNotFound:
            return ProjectResolution(status="not_found", message="Project not found")
        if not _reference_matches(reference, project):
            return ProjectResolution(
                status="validation_error",
                message="project_reference does not match project_id",
            )
        return ProjectResolution(
            status="resolved",
            project=_candidate(project),
            message="Project resolved from the authorized project ID.",
        )

    try:
        candidates = await project_access.search_projects_for_actor(
            pool, claims=claims, reference=reference, limit=MAX_PROJECT_CANDIDATES
        )
    except ProjectForbidden:
        return ProjectResolution(status="forbidden", message="Project access denied")
    safe_candidates = [_candidate(project) for project in candidates]
    normalized_reference = " ".join(reference.casefold().split())
    exact = [
        project
        for project in candidates
        if " ".join(project.name.casefold().split()) == normalized_reference
    ]
    if len(exact) == 1:
        return ProjectResolution(
            status="resolved",
            project=_candidate(exact[0]),
            message="Project resolved by exact name match.",
        )
    if len(safe_candidates) == 1:
        return ProjectResolution(
            status="resolved",
            project=safe_candidates[0],
            message="Project resolved from the authorized project portfolio.",
        )
    if not safe_candidates:
        return ProjectResolution(status="not_found", message="No matching project found")
    return ProjectResolution(
        status="ambiguous",
        candidates=safe_candidates,
        message="Multiple authorized projects match this reference; please clarify.",
    )


async def get_project_status_for_actor(
    pool: Any, *, claims: AssistantClaims, project_reference: str, project_id: str | None = None
) -> ProjectStatusResult:
    resolution = await resolve_project_for_actor(
        pool, claims=claims, project_reference=project_reference, project_id=project_id
    )
    if resolution.project is None:
        return ProjectStatusResult(resolution=resolution)
    context = await _context_for_resolution(pool, claims, resolution)
    return ProjectStatusResult(
        resolution=resolution,
        status=context.project.status.value,
        completion_percentage=context.project.completion_percentage,
        feature_counts=context.feature_counts,
        open_blocker_count=len(context.open_blockers),
    )


async def get_project_history_for_actor(
    pool: Any,
    *,
    claims: AssistantClaims,
    project_reference: str,
    project_id: str | None = None,
    since: datetime | None = None,
    limit: int = 50,
) -> ProjectHistoryResult:
    validate_history_limit(limit)
    resolution = await resolve_project_for_actor(
        pool, claims=claims, project_reference=project_reference, project_id=project_id
    )
    if resolution.project is None:
        return ProjectHistoryResult(resolution=resolution)
    rows = await project_state_service_history(
        pool, claims=claims, project_id=resolution.project.project_id, limit=limit
    )
    items = [
        ProjectHistoryItem(
            feature_id=row.feature_id,
            feature_name=row.feature_name,
            old_status=row.old_status,
            new_status=row.new_status,
            changed_by=row.changed_by,
            changed_at=row.changed_at,
        )
        for row in rows
        if since is None or row.changed_at >= since
    ]
    return ProjectHistoryResult(resolution=resolution, items=items[:limit])


async def get_project_metrics_for_actor(
    pool: Any, *, claims: AssistantClaims, project_reference: str, project_id: str | None = None
) -> ProjectMetricsResult:
    status = await get_project_status_for_actor(
        pool, claims=claims, project_reference=project_reference, project_id=project_id
    )
    return ProjectMetricsResult(
        resolution=status.resolution,
        completion_percentage=status.completion_percentage,
        feature_counts=status.feature_counts,
        open_blocker_count=status.open_blocker_count,
    )


async def search_project_knowledge_for_actor(
    pool: Any,
    *,
    claims: AssistantClaims,
    access_filter: Any,
    project_reference: str,
    query: str,
    project_id: str | None = None,
    top_k: int = 4,
) -> ProjectKnowledgeResult:
    from rag.retrieval.search import search_rag_async

    if not query.strip():
        raise ProjectToolValidationError("query must not be empty")
    validate_top_k(top_k)
    resolution = await resolve_project_for_actor(
        pool, claims=claims, project_reference=project_reference, project_id=project_id
    )
    if resolution.project is None:
        return ProjectKnowledgeResult(resolution=resolution, query=query)
    response = await search_rag_async(
        question=f"{resolution.project.name}: {query.strip()}",
        top_k=top_k,
        access_filter=access_filter,
    )
    return ProjectKnowledgeResult(
        resolution=resolution, results=response.results, query=response.question
    )


async def _context_for_resolution(pool: Any, claims: AssistantClaims, resolution: ProjectResolution):
    assert resolution.project is not None
    from service.project_state import get_project_context_for_actor

    return await get_project_context_for_actor(
        pool, claims=claims, project_id=resolution.project.project_id
    )


async def project_state_service_history(
    pool: Any, *, claims: AssistantClaims, project_id: str, limit: int
):
    from service.project_state import list_history_for_actor

    return await list_history_for_actor(pool, claims=claims, project_id=project_id, limit=limit)
