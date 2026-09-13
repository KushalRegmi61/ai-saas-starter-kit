"""Tests for the tool registry and search_knowledge_base tool."""


from rag.types import AccessFilter, SearchResponse, SearchResult, Source

import agent.tools.search as search_mod
from agent.tools.registry import (
    get_all_tools,
    get_entries,
    get_tool_names,
    get_tool_schemas_for_classifier,
    get_tools_by_name,
)


def _filter(**kw):
    base = {"departments": ["hr", "all", "general"], "max_access_level": 1}
    base.update(kw)
    return AccessFilter(**base)


def _result(text="policy text", source="policy.pdf", score=0.9):
    return SearchResult(text=text, source=Source(source=source, score=score))


# --------------------------------------------------------------------------- #
# Registry tests                                                               #
# --------------------------------------------------------------------------- #

def test_registry_contains_search_tool():
    names = get_tool_names()
    assert "search_knowledge_base" in names


def test_registry_tool_has_required_metadata():
    entries = get_entries()
    entry = next(e for e in entries if e.name == "search_knowledge_base")
    assert entry.category == "knowledge"
    assert entry.requires_access_filter is True
    assert "knowledge base" in entry.description.lower()
    assert entry.when_to_use  # non-empty


def test_get_all_tools_returns_callables():
    tools = get_all_tools()
    assert len(tools) >= 1
    assert all(hasattr(t, "invoke") for t in tools)


def test_get_tools_by_name_filters_correctly():
    tools = get_tools_by_name(["search_knowledge_base"])
    assert len(tools) == 1
    assert tools[0].name == "search_knowledge_base"


def test_get_tools_by_name_skips_unknown():
    tools = get_tools_by_name(["search_knowledge_base", "nonexistent_tool"])
    assert len(tools) == 1  # nonexistent silently skipped


def test_classifier_schema_contains_tool_info():
    schema = get_tool_schemas_for_classifier()
    assert "search_knowledge_base" in schema
    assert "knowledge" in schema
    assert "Use when:" in schema


# --------------------------------------------------------------------------- #
# search_knowledge_base tool tests                                             #
# --------------------------------------------------------------------------- #

def test_tool_name_and_description():
    tool = search_mod.search_knowledge_base
    assert tool.name == "search_knowledge_base"
    assert "knowledge base" in tool.description.lower()


def test_tool_schema_hides_access_filter():
    """access_filter must NOT appear in the LLM-visible tool schema.

    LangChain exposes two schemas:
      - args_schema: full internal schema including injected args (used by ToolNode)
      - tool_call_schema: the schema sent to the LLM — injected args are stripped here
    We assert against tool_call_schema because that is what the model sees.
    """
    tool = search_mod.search_knowledge_base
    # tool_call_schema is what gets serialised into the OpenAI function definition
    llm_schema = tool.tool_call_schema.model_json_schema()
    props = llm_schema.get("properties", {})
    assert "access_filter" not in props, "access_filter must be invisible to the LLM"
    assert "tool_call_id" not in props, "tool_call_id must be invisible to the LLM"
    assert "question" in props
    assert "top_k" in props
    assert "search_mode" in props


def test_tool_forwards_access_filter_to_search_rag(monkeypatch):
    """Verify access_filter reaches search_rag unchanged."""
    seen = {}

    def fake_search_rag(question, top_k=4, search_mode="auto", access_filter=None):
        seen["question"] = question
        seen["filter"] = access_filter
        return SearchResponse(question=question, results=[], search_mode="semantic")

    monkeypatch.setattr(search_mod, "search_rag", fake_search_rag)

    filt = _filter(tenant="acme")
    # Invoke directly bypassing ToolNode injection by passing args explicitly
    search_mod.search_knowledge_base.func(
        question="pto policy?",
        tool_call_id="call_123",
        access_filter=filt,
        top_k=2,
        search_mode="hybrid",
    )

    assert seen["question"] == "pto policy?"
    assert seen["filter"].tenant == "acme"
    assert seen["filter"].departments == ["hr", "all", "general"]


def test_tool_returns_no_context_message_when_empty(monkeypatch):
    def fake_empty(question, **kw):
        return SearchResponse(question=question, results=[], search_mode="semantic")

    monkeypatch.setattr(search_mod, "search_rag", fake_empty)

    cmd = search_mod.search_knowledge_base.func(
        question="unknown topic",
        tool_call_id="call_456",
        access_filter=None,
    )
    # Command.update should contain a ToolMessage with no-context message
    messages = cmd.update.get("messages", [])
    assert len(messages) == 1
    assert "No relevant" in messages[0].content


def test_tool_returns_formatted_chunks(monkeypatch):
    def fake_results(question, **kw):
        return SearchResponse(
            question=question,
            results=[_result("chunk text", "doc.pdf", 0.85)],
            search_mode="hybrid",
        )

    monkeypatch.setattr(search_mod, "search_rag", fake_results)

    cmd = search_mod.search_knowledge_base.func(
        question="policy?",
        tool_call_id="call_789",
        access_filter=None,
    )
    messages = cmd.update.get("messages", [])
    assert "chunk text" in messages[0].content
    assert "doc.pdf" in messages[0].content
    assert cmd.update["sources"][0]["source"] == "doc.pdf"


def test_tool_sources_carry_truncated_snippet(monkeypatch):
    long_text = "x" * 500

    def fake_results(question, **kw):
        return SearchResponse(
            question=question,
            results=[_result(long_text, "doc.pdf", 0.85)],
            search_mode="hybrid",
        )

    monkeypatch.setattr(search_mod, "search_rag", fake_results)

    cmd = search_mod.search_knowledge_base.func(
        question="policy?",
        tool_call_id="call_snip",
        access_filter=None,
    )
    source = cmd.update["sources"][0]
    assert source["source"] == "doc.pdf"
    assert source["snippet"] == "x" * search_mod.SNIPPET_CHARS
    assert len(source["snippet"]) == search_mod.SNIPPET_CHARS


def test_tool_snippet_does_not_break_grounding_shape(monkeypatch):
    """Grounding reads only Source keys; the extra snippet key must be inert."""

    def fake_results(question, **kw):
        return SearchResponse(
            question=question,
            results=[_result("pto policy allows carryover", "policy.pdf", 0.9)],
            search_mode="hybrid",
        )

    monkeypatch.setattr(search_mod, "search_rag", fake_results)

    cmd = search_mod.search_knowledge_base.func(
        question="pto?",
        tool_call_id="call_ground",
        access_filter=None,
    )
    source = cmd.update["sources"][0]
    assert set(source) >= {"source", "page", "chunk_index", "score", "snippet"}
    assert Source(**{k: v for k, v in source.items() if k != "snippet"})
