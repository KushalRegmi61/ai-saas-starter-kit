"""Tools bind the host filter; the tool boundary carries tenant + access policy."""

from rag.types import AccessFilter, SearchResponse

import agent.tools.search as search_mod
from agent.tools import make_rag_tools


def _filter(**kw):
    base = {"departments": ["hr", "all", "general"], "max_access_level": 1}
    base.update(kw)
    return AccessFilter(**base)


def test_tool_registered_with_name_and_description():
    (tool,) = make_rag_tools(_filter())
    assert tool.name == "search_knowledge_base"
    assert "knowledge base" in tool.description.lower()


def test_tool_forwards_filter_and_tenant(monkeypatch):

    seen = {}

    def fake_search_rag(question, top_k=4, search_mode="auto", access_filter=None):
        seen["question"] = question
        seen["top_k"] = top_k
        seen["search_mode"] = search_mode
        seen["filter"] = access_filter
        return SearchResponse(question=question, results=[], search_mode="hybrid")

    monkeypatch.setattr(search_mod, "search_rag", fake_search_rag)
    (tool,) = make_rag_tools(_filter(tenant="acme"))
    out = tool.invoke({"question": "pto policy?", "top_k": 2, "search_mode": "hybrid"})
    assert seen["question"] == "pto policy?"
    assert seen["top_k"] == 2
    assert seen["search_mode"] == "hybrid"
    assert seen["filter"].tenant == "acme"
    assert seen["filter"].departments == ["hr", "all", "general"]
    assert out["search_mode"] == "hybrid"
    assert tool.metadata == {"tenant": "acme"}


def test_tool_accepts_none_filter(monkeypatch):

    def fake_search_none(**kw):
        return SearchResponse(question=kw["question"], results=[])

    monkeypatch.setattr(search_mod, "search_rag", fake_search_none)
    (tool,) = make_rag_tools(None)
    out = tool.invoke({"question": "hi"})
    assert out["results"] == []
    assert tool.metadata == {"tenant": None}
