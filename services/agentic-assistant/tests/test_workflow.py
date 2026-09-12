"""Workflow routing + grounding are pure logic; LLM/search are mocked."""

from rag.types import AccessFilter, SearchResult, Source

import agent.graph.nodes as nodes_mod
import agent.graph.nodes.common as common_mod
import agent.tools as tools_mod
from agent.graph.nodes import (
    check_grounding,
    generate_answer,
    grade_context,
    route_after_grade,
    sources_from_state,
)
from agent.graph.workflow import get_agent_graph


def _state(**kw):
    base = {
        "question": "q?",
        "active_question": "q?",
        "top_k": 4,
        "search_mode": "auto",
        "access_filter": AccessFilter(departments=["all"], max_access_level=3),
        "conversation_history": [],
        "attempts": 0,
        "results": [],
        "answer": "",
        "sources": [],
        "needs_rewrite": False,
        "grounded": False,
        "workflow_steps": [],
    }
    base.update(kw)
    return base


def _result(text="t", source="s.pdf", score=0.9):
    return SearchResult(text=text, source=Source(source=source, score=score))


def test_route_after_grade():
    assert route_after_grade(_state(needs_rewrite=True)) == "rewrite"
    assert route_after_grade(_state(needs_rewrite=False)) == "generate"


def test_grade_triggers_rewrite_on_low_score_first_attempt():
    out = grade_context(_state(results=[_result(score=0.1)], attempts=0))
    assert out["needs_rewrite"] is True
    out = grade_context(_state(results=[_result(score=0.9)], attempts=0))
    assert out["needs_rewrite"] is False
    out = grade_context(_state(results=[_result(score=0.1)], attempts=1))
    assert out["needs_rewrite"] is False


def test_generate_answers_unknown_without_results():
    out = generate_answer(_state())
    assert "do not know" in out["answer"].lower()
    assert out["sources"] == []


def test_generate_uses_llm_with_context(monkeypatch):
    class FakeResp:
        content = "See s.pdf for the pto policy."

    monkeypatch.setattr(common_mod, "_chat_model", lambda: FakeLLM())
    out = generate_answer(_state(results=[_result()]))
    assert "s.pdf" in out["answer"]
    assert out["sources"] == [{"source": "s.pdf", "page": None, "chunk_index": None, "score": 0.9}]


class FakeLLM:
    def invoke(self, messages, config=None):
        return FakeLLMResp()


class FakeLLMResp:
    content = "See s.pdf for the pto policy."


def test_check_grounding():
    grounded = check_grounding(
        _state(
            answer="Per s.pdf, pto accrues monthly.",
            results=[_result()],
            sources=[{"source": "s.pdf"}],
        )
    )
    assert grounded["grounded"] is True
    assert check_grounding(_state(answer="hello", results=[], sources=[]))["grounded"] is False
    assert (
        check_grounding(_state(answer="I do not know.", results=[_result()], sources=[]))[
            "grounded"
        ]
        is True
    )


def test_sources_from_state():
    out = sources_from_state(_state(sources=[{"source": "a.pdf"}]))
    assert out[0].source == "a.pdf"


def test_graph_compiles_with_expected_nodes():
    graph = get_agent_graph()
    assert set(graph.nodes.keys()) >= {
        "retrieve",
        "grade",
        "rewrite",
        "generate",
        "grounding_check",
    }


def test_retrieve_uses_tool_boundary(monkeypatch):
    seen = {}

    class FakeTool:
        def invoke(self, payload):
            seen.update(payload)
            return {"results": [], "question": payload["question"], "search_mode": "hybrid"}

    monkeypatch.setattr(tools_mod, "make_rag_tools", lambda filt: [FakeTool()])
    out = nodes_mod.retrieve_context(_state(active_question="pto?", top_k=3))
    assert seen == {"question": "pto?", "top_k": 3, "search_mode": "auto"}
    assert out["results"] == []
