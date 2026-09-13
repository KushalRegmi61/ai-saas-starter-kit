"""Authenticated service boundary for project discovery and retrieval."""

from __future__ import annotations

from typing import Any

from auth.types import AssistantClaims

from agent.types import (
    ProjectCandidate,
    ProjectKnowledgeResult,
    ProjectResolution,
)
from models import projects
from service import projects as project_access
from service.projects import ProjectForbidden

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
