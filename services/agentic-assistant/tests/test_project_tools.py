"""Registration, authorization, and retrieval tests for project tools."""

import json

import pytest
from rag.types import AccessFilter, SearchResponse

import agent.tools.project as project_tools
import service.project_tools as project_service
from agent.tools.registry import get_entries, get_tool_names
from service.project_tools import (
    ProjectToolValidationError,
    resolve_project_for_actor,
    validate_project_reference,
    validate_top_k,
)

PROJECT_TOOL_NAMES = {
    "get_project_overview",
    "get_project_features",
    "get_project_blockers",
    "get_project_activity",
    "search_project_knowledge",
}


def test_all_project_tools_are_registered_once():
    names = get_tool_names()
    assert set(names) >= PROJECT_TOOL_NAMES
    assert len(names) == len(set(names))
    assert sum(name in PROJECT_TOOL_NAMES for name in names) == len(PROJECT_TOOL_NAMES)


def test_project_registry_metadata_is_read_only_and_access_scoped():
    entries = {entry.name: entry for entry in get_entries()}
    for name in PROJECT_TOOL_NAMES:
        entry = entries[name]
        assert entry.category == "project"
        assert entry.requires_access_filter is True
        assert entry.enabled is True
        assert "read-only" in entry.tags
        assert entry.when_to_use


def test_project_tool_schemas_accept_optional_id():
    for name in PROJECT_TOOL_NAMES:
        tool = getattr(project_tools, name)
        schema = tool.tool_call_schema.model_json_schema()
        assert "project_reference" in schema["properties"]
        assert "project_id" in schema["properties"]
    knowledge_schema = project_tools.search_project_knowledge.tool_call_schema.model_json_schema()
    assert "access_filter" not in knowledge_schema["properties"]


def test_validation_bounds():
    assert validate_project_reference(" Payments ") == "Payments"
    assert validate_top_k(10) == 10

    with pytest.raises(ProjectToolValidationError):
        validate_project_reference(" ")
    with pytest.raises(ProjectToolValidationError):
        validate_top_k(0)


@pytest.mark.asyncio
async def test_reference_without_id_is_typed_unresolved_result():
    class Claims:
        role = "manager"
        subject = "manager-1"

    async def search(*args, **kwargs):
        return []

    import service.projects as access

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(access, "search_projects_for_actor", search)
    result = await resolve_project_for_actor(
        object(), claims=Claims(), project_reference="Payments"
    )
    assert result.status == "not_found"
    assert result.project is None
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_id_requires_authorized_matching_reference(monkeypatch):
    class Project:
        id = "project-1"
        name = "Payments"
        description = "Payment platform"

    async def authorized(pool, *, claims, project_id):
        assert project_id == "project-1"
        return Project()

    monkeypatch.setattr(project_service.project_access, "get_project_for_actor", authorized)
    result = await resolve_project_for_actor(
        object(), claims=object(), project_reference="Payments", project_id="project-1"
    )
    assert result.status == "resolved"
    assert result.project.project_id == "project-1"

    mismatch = await resolve_project_for_actor(
        object(), claims=object(), project_reference="Other", project_id="project-1"
    )
    assert mismatch.status == "validation_error"


@pytest.mark.asyncio
async def test_reference_resolution_returns_bounded_ambiguous_candidates(monkeypatch):
    class Claims:
        role = "manager"
        subject = "manager-1"

    class Project:
        def __init__(self, project_id, name):
            self.id = project_id
            self.name = name
            self.description = "Payments platform"

    async def candidates(*args, **kwargs):
        assert kwargs["limit"] == 10
        return [Project("a", "Payments API"), Project("b", "Payments Web")]

    monkeypatch.setattr(project_service.project_access, "search_projects_for_actor", candidates)
    result = await resolve_project_for_actor(
        object(), claims=Claims(), project_reference="payments"
    )
    assert result.status == "ambiguous"
    assert [candidate.project_id for candidate in result.candidates] == ["a", "b"]


@pytest.mark.asyncio
async def test_project_knowledge_adds_project_context_and_preserves_filter(monkeypatch):
    class Project:
        id = "project-1"
        name = "Payments"
        description = "Payment platform"

    async def authorized(pool, *, claims, project_id):
        return Project()

    seen = {}

    async def fake_search(**kwargs):
        seen.update(kwargs)
        return SearchResponse(question=kwargs["question"], results=[], search_mode="semantic")

    monkeypatch.setattr(project_service.project_access, "get_project_for_actor", authorized)
    monkeypatch.setattr("rag.retrieval.search.search_rag_async", fake_search)
    result = await project_service.search_project_knowledge_for_actor(
        object(),
        claims=object(),
        access_filter=AccessFilter(departments=["all"], max_access_level=1, tenant="acme"),
        project_reference="Payments",
        project_id="project-1",
        query="latest decision",
        top_k=3,
    )
    assert result.resolution.status == "resolved"
    assert seen["question"] == "Payments: latest decision"
    assert seen["access_filter"].tenant == "acme"


@pytest.mark.asyncio
async def test_registered_tools_return_typed_context_error_without_request_context():
    for name in (
        "get_project_overview",
        "get_project_features",
        "get_project_blockers",
        "get_project_activity",
    ):
        result = await getattr(project_tools, name).ainvoke({"project_reference": "Payments"})
        payload = json.loads(result)
        assert payload["resolution"]["status"] == "forbidden"


def test_project_tools_are_active_in_registry():
    from agent.tools.registry import get_tool_schemas_for_classifier, get_tools_by_name

    assert [tool.name for tool in get_tools_by_name(["get_project_overview"])] == [
        "get_project_overview"
    ]
    schemas = get_tool_schemas_for_classifier()
    assert all(name in schemas for name in PROJECT_TOOL_NAMES)
    assert "resolve_project" not in schemas
