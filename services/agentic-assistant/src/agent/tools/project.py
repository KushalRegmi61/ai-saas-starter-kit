"""Minimal read-only project tools for the authenticated assistant workflow."""

from datetime import datetime
from typing import Annotated, Any

from auth.types import AssistantClaims
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from rag.types import AccessFilter

from agent.tools.registry import ToolEntry, register
from agent.types import (
    ProjectActivityResult,
    ProjectBlockersResult,
    ProjectFeaturesResult,
    ProjectKnowledgeResult,
    ProjectOverviewResult,
    ProjectResolution,
)
from models.project_state import BlockerSeverity, BlockerStatus, FeatureStatus
from service.project_read_tools import (
    get_activity,
    get_blockers,
    get_features,
    get_overview,
)
from service.project_tools import (
    ProjectToolValidationError,
    search_project_knowledge_for_actor,
    validate_top_k,
)


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


@tool("get_project_overview")
async def get_project_overview(
    project_reference: str,
    project_id: str | None = None,
    claims: Annotated[AssistantClaims | None, InjectedState("claims")] = None,
    pool: Annotated[Any, InjectedState("pool")] = None,
) -> ProjectOverviewResult:
    """Read a project's summary, grouped feature state, metrics, and blocker count."""
    context = _context(claims, pool)
    if isinstance(context, ProjectResolution):
        return ProjectOverviewResult(resolution=context)
    try:
        return await get_overview(
            context[1],
            claims=context[0],
            project_reference=project_reference,
            project_id=project_id,
        )
    except ProjectToolValidationError as exc:
        return ProjectOverviewResult(resolution=_validation(str(exc)))


@tool("get_project_features")
async def get_project_features(
    project_reference: str,
    project_id: str | None = None,
    feature_query: str | None = None,
    statuses: list[FeatureStatus] | None = None,
    limit: int = 100,
    claims: Annotated[AssistantClaims | None, InjectedState("claims")] = None,
    pool: Annotated[Any, InjectedState("pool")] = None,
) -> ProjectFeaturesResult:
    """Query authorized project features by natural-language text and status."""
    context = _context(claims, pool)
    if isinstance(context, ProjectResolution):
        return ProjectFeaturesResult(resolution=context)
    try:
        return await get_features(
            context[1],
            claims=context[0],
            project_reference=project_reference,
            project_id=project_id,
            feature_query=feature_query,
            statuses=[status.value for status in statuses] if statuses else None,
            limit=limit,
        )
    except ProjectToolValidationError as exc:
        return ProjectFeaturesResult(resolution=_validation(str(exc)))


@tool("get_project_blockers")
async def get_project_blockers(
    project_reference: str,
    project_id: str | None = None,
    blocker_query: str | None = None,
    statuses: list[BlockerStatus] | None = None,
    severities: list[BlockerSeverity] | None = None,
    limit: int = 50,
    claims: Annotated[AssistantClaims | None, InjectedState("claims")] = None,
    pool: Annotated[Any, InjectedState("pool")] = None,
) -> ProjectBlockersResult:
    """Query authorized project blockers by text, state, and severity."""
    context = _context(claims, pool)
    if isinstance(context, ProjectResolution):
        return ProjectBlockersResult(resolution=context)
    try:
        return await get_blockers(
            context[1],
            claims=context[0],
            project_reference=project_reference,
            project_id=project_id,
            blocker_query=blocker_query,
            statuses=[status.value for status in statuses] if statuses else None,
            severities=[severity.value for severity in severities] if severities else None,
            limit=limit,
        )
    except ProjectToolValidationError as exc:
        return ProjectBlockersResult(resolution=_validation(str(exc)))


@tool("get_project_activity")
async def get_project_activity(
    project_reference: str,
    project_id: str | None = None,
    since: datetime | None = None,
    limit: int = 50,
    claims: Annotated[AssistantClaims | None, InjectedState("claims")] = None,
    pool: Annotated[Any, InjectedState("pool")] = None,
) -> ProjectActivityResult:
    """Read bounded daily updates and feature-status history for a project."""
    context = _context(claims, pool)
    if isinstance(context, ProjectResolution):
        return ProjectActivityResult(resolution=context)
    try:
        return await get_activity(
            context[1],
            claims=context[0],
            project_reference=project_reference,
            project_id=project_id,
            since=since,
            limit=limit,
        )
    except ProjectToolValidationError as exc:
        return ProjectActivityResult(resolution=_validation(str(exc)))


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
    name="get_project_overview",
    description="Read a project's summary, grouped feature state, metrics, and blocker count.",
    when_to_use="Use for a project's overall current state.",
    category="project", tool_fn=get_project_overview, requires_access_filter=True,
    tags=(*_PROJECT_TAGS, "overview"),
))
register(ToolEntry(
    name="get_project_features",
    description="Query a project's features by natural-language text and status.",
    when_to_use="Use for feature-specific status or filtered feature-list questions.",
    category="project", tool_fn=get_project_features, requires_access_filter=True,
    tags=(*_PROJECT_TAGS, "features"),
))
register(ToolEntry(
    name="get_project_blockers",
    description="Query a project's blockers by text, status, and severity.",
    when_to_use="Use when the user asks about project issues, blockers, or risks.",
    category="project", tool_fn=get_project_blockers, requires_access_filter=True,
    tags=(*_PROJECT_TAGS, "blockers"),
))
register(ToolEntry(
    name="get_project_activity",
    description="Read bounded project updates and feature-status history.",
    when_to_use="Use for recent changes, daily updates, or feature transition history.",
    category="project", tool_fn=get_project_activity, requires_access_filter=True,
    tags=(*_PROJECT_TAGS, "activity"),
))
register(ToolEntry(
    name="search_project_knowledge",
    description="Search access-filtered knowledge about one resolved project.",
    when_to_use="Use for project documentation, decisions, reports, or contextual knowledge.",
    category="project", tool_fn=search_project_knowledge, requires_access_filter=True,
    tags=(*_PROJECT_TAGS, "rag"),
))
