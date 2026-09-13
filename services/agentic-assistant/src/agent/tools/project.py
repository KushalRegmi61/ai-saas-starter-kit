"""Read-only project tools for the authenticated assistant workflow.

Claims and the database pool are injected from request state and remain hidden
from the model. Resolution and authorization stay in the service layer.

This module intentionally has no future annotations: LangGraph inspects live
``Annotated[..., InjectedState(...)]`` annotations when injecting tool args.
"""

from datetime import datetime
from typing import Annotated, Any

from auth.types import AssistantClaims
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from rag.types import AccessFilter

from agent.tools.registry import ToolEntry, register
from agent.types import (
    ProjectHistoryResult,
    ProjectKnowledgeResult,
    ProjectMetricsResult,
    ProjectResolution,
    ProjectStatusResult,
)
from service.project_tools import (
    ProjectToolValidationError,
    get_project_history_for_actor,
    get_project_metrics_for_actor,
    get_project_status_for_actor,
    resolve_project_for_actor,
    search_project_knowledge_for_actor,
    validate_history_limit,
    validate_top_k,
)
from service.projects import ProjectForbidden


def _validation(message: str) -> ProjectResolution:
    return ProjectResolution(status="validation_error", message=message)


def _context(
    claims: AssistantClaims | None, pool: Any
) -> tuple[AssistantClaims, Any] | ProjectResolution:
    if claims is None or pool is None:
        return ProjectResolution(
            status="forbidden", message="Authenticated project context is unavailable"
        )
    return claims, pool


@tool("resolve_project")
async def resolve_project(
    project_reference: str,
    project_id: str | None = None,
    claims: Annotated[AssistantClaims | None, InjectedState("claims")] = None,
    pool: Annotated[Any, InjectedState("pool")] = None,
) -> ProjectResolution:
    """Resolve a natural-language reference to one authorized project."""
    context = _context(claims, pool)
    if isinstance(context, ProjectResolution):
        return context
    try:
        return await resolve_project_for_actor(
            context[1], claims=context[0], project_reference=project_reference, project_id=project_id
        )
    except (ProjectToolValidationError, ProjectForbidden) as exc:
        if isinstance(exc, ProjectForbidden):
            return ProjectResolution(status="forbidden", message="Project access denied")
        return _validation(str(exc))


@tool("get_project_status")
async def get_project_status(
    project_reference: str,
    project_id: str | None = None,
    claims: Annotated[AssistantClaims | None, InjectedState("claims")] = None,
    pool: Annotated[Any, InjectedState("pool")] = None,
) -> ProjectStatusResult:
    """Read current status, completion, feature counts, and blockers."""
    context = _context(claims, pool)
    if isinstance(context, ProjectResolution):
        return ProjectStatusResult(resolution=context)
    try:
        return await get_project_status_for_actor(
            context[1], claims=context[0], project_reference=project_reference, project_id=project_id
        )
    except ProjectToolValidationError as exc:
        return ProjectStatusResult(resolution=_validation(str(exc)))


@tool("get_project_history")
async def get_project_history(
    project_reference: str,
    project_id: str | None = None,
    since: datetime | None = None,
    limit: int = 50,
    claims: Annotated[AssistantClaims | None, InjectedState("claims")] = None,
    pool: Annotated[Any, InjectedState("pool")] = None,
) -> ProjectHistoryResult:
    """Read bounded feature-status history for one authorized project."""
    try:
        validate_history_limit(limit)
    except ProjectToolValidationError as exc:
        return ProjectHistoryResult(resolution=_validation(str(exc)))
    context = _context(claims, pool)
    if isinstance(context, ProjectResolution):
        return ProjectHistoryResult(resolution=context)
    try:
        return await get_project_history_for_actor(
            context[1],
            claims=context[0],
            project_reference=project_reference,
            project_id=project_id,
            since=since,
            limit=limit,
        )
    except ProjectToolValidationError as exc:
        return ProjectHistoryResult(resolution=_validation(str(exc)))


@tool("get_project_metrics")
async def get_project_metrics(
    project_reference: str,
    project_id: str | None = None,
    claims: Annotated[AssistantClaims | None, InjectedState("claims")] = None,
    pool: Annotated[Any, InjectedState("pool")] = None,
) -> ProjectMetricsResult:
    """Read completion and feature metrics for one authorized project."""
    context = _context(claims, pool)
    if isinstance(context, ProjectResolution):
        return ProjectMetricsResult(resolution=context)
    try:
        return await get_project_metrics_for_actor(
            context[1], claims=context[0], project_reference=project_reference, project_id=project_id
        )
    except ProjectToolValidationError as exc:
        return ProjectMetricsResult(resolution=_validation(str(exc)))


@tool("search_project_knowledge")
async def search_project_knowledge(
    project_reference: str,
    query: str,
    project_id: str | None = None,
    top_k: int = 4,
    access_filter: Annotated[AccessFilter | None, InjectedState("access_filter")] = None,
    claims: Annotated[AssistantClaims | None, InjectedState("claims")] = None,
    pool: Annotated[Any, InjectedState("pool")] = None,
) -> ProjectKnowledgeResult:
    """Search access-filtered knowledge after resolving the project."""
    if not query.strip():
        return ProjectKnowledgeResult(
            resolution=_validation("query must not be empty"), query=query
        )
    if access_filter is None:
        return ProjectKnowledgeResult(
            resolution=ProjectResolution(
                status="forbidden", message="Authenticated access filter is unavailable"
            ),
            query=query,
        )
    try:
        validate_top_k(top_k)
    except ProjectToolValidationError as exc:
        return ProjectKnowledgeResult(resolution=_validation(str(exc)), query=query)
    context = _context(claims, pool)
    if isinstance(context, ProjectResolution):
        return ProjectKnowledgeResult(resolution=context, query=query)
    try:
        return await search_project_knowledge_for_actor(
            context[1],
            claims=context[0],
            access_filter=access_filter,
            project_reference=project_reference,
            query=query,
            project_id=project_id,
            top_k=top_k,
        )
    except ProjectToolValidationError as exc:
        return ProjectKnowledgeResult(resolution=_validation(str(exc)), query=query)


_PROJECT_TAGS = ("project", "read-only")

register(ToolEntry(
    name="resolve_project", description="Resolve a natural-language project reference against authorized projects.",
    when_to_use="Use first when a project name or description fragment is not already resolved.",
    category="project", tool_fn=resolve_project, requires_access_filter=True,
    tags=(*_PROJECT_TAGS, "discovery"),
))
register(ToolEntry(
    name="get_project_status", description="Read an authorized project's current status, completion, blockers, and feature counts.",
    when_to_use="Use for current project state after the project reference is known.",
    category="project", tool_fn=get_project_status, requires_access_filter=True,
    tags=(*_PROJECT_TAGS, "structured-state"),
))
register(ToolEntry(
    name="get_project_history", description="Read bounded feature-status history for an authorized project.",
    when_to_use="Use for project progress changes or history since a supplied date.",
    category="project", tool_fn=get_project_history, requires_access_filter=True,
    tags=(*_PROJECT_TAGS, "history"),
))
register(ToolEntry(
    name="get_project_metrics", description="Read completion and feature metrics for an authorized project.",
    when_to_use="Use for project measurements, counts, and completion questions.",
    category="project", tool_fn=get_project_metrics, requires_access_filter=True,
    tags=(*_PROJECT_TAGS, "metrics"),
))
register(ToolEntry(
    name="search_project_knowledge", description="Search access-filtered knowledge about one resolved project.",
    when_to_use="Use for project documentation, decisions, reports, or contextual knowledge.",
    category="project", tool_fn=search_project_knowledge, requires_access_filter=True,
    tags=(*_PROJECT_TAGS, "rag"),
))
