"""Tests for the ReAct agent graph: routing, grounding, graph structure."""

import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from rag.types import AccessFilter, SearchResult, Source

from agent.graph.nodes import check_grounding, route_after_agent, route_after_classify
from agent.graph.nodes.classify import _enforce_project_selection, _parse_response
from agent.graph.nodes.generate_final import _assemble_context
from agent.graph.nodes.out_of_scope import OUT_OF_SCOPE_RESPONSE
from agent.graph.nodes.routing import _needs_project_search_fallback
from agent.graph.state import make_initial_state, merge_project_evidence
from agent.graph.tool_runner import (
    _build_project_evidence,
    force_project_search,
    make_tool_runner,
)
from agent.graph.workflow import get_agent_graph


def _state(**kw):
    base = make_initial_state(
        "q?",
        access_filter=AccessFilter(departments=["all"], max_access_level=3),
    )
    base["workflow_steps"] = []
    base.update(kw)
    return base


def _result(text="t", source="s.pdf", score=0.9):
    return SearchResult(text=text, source=Source(source=source, score=score))


# --------------------------------------------------------------------------- #
# Routing tests                                                                #
# --------------------------------------------------------------------------- #


def test_route_after_classify_chitchat():
    assert route_after_classify(_state(intent="chitchat")) == "chitchat"


def test_route_after_classify_needs_tools():
    assert route_after_classify(_state(intent="needs_tools")) == "needs_tools"


def test_route_after_classify_out_of_scope_skips_tools():
    assert route_after_classify(_state(intent="out_of_scope")) == "out_of_scope"


def test_route_after_classify_unknown_fails_closed():
    assert route_after_classify(_state(intent="unknown_xyz")) == "out_of_scope"


def test_invalid_classifier_output_fails_closed():
    assert _parse_response("not json") == {"intent": "out_of_scope", "tools": []}
    assert _parse_response("[]") == {"intent": "out_of_scope", "tools": []}
    assert _parse_response('{"intent":"unknown","tools":[]}') == {
        "intent": "out_of_scope",
        "tools": [],
    }


def test_out_of_scope_classifier_result_keeps_tools_empty():
    assert _parse_response('{"intent":"out_of_scope","tools":["search_knowledge_base"]}') == {
        "intent": "out_of_scope",
        "tools": [],
    }


def test_route_after_agent_routes_to_tools_when_under_budget():
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"question": "q"},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )
    state = _state(messages=[ai_msg], tool_call_count=1, loop_tokens_used=100)
    assert route_after_agent(state) == "tools"


def test_route_after_agent_ends_when_no_tool_calls():
    ai_msg = AIMessage(content="Here is the answer.")
    state = _state(messages=[ai_msg], tool_call_count=1, loop_tokens_used=100)
    assert route_after_agent(state) == "generate"


def test_route_after_agent_forces_selected_project_rag_before_final_answer():
    state = _state(
        selected_tools=["get_project_overview", "search_project_knowledge"],
        messages=[AIMessage(content="The project is on track.")],
        project_tool_outcomes=[
            {"tool": "get_project_overview", "status": "resolved", "result_count": 1}
        ],
    )
    assert route_after_agent(state) == "force_project_search"


def test_route_after_agent_forces_project_rag_when_model_skips_all_tools():
    state = _state(
        selected_tools=["get_project_overview", "search_project_knowledge"],
        messages=[AIMessage(content="The project is on track.")],
    )
    assert route_after_agent(state) == "force_project_search"


def test_route_after_agent_ends_at_iteration_cap():
    from agent.graph.nodes.agent import MAX_ITERATIONS

    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"question": "q"},
                "id": "call_2",
                "type": "tool_call",
            }
        ],
    )
    state = _state(messages=[ai_msg], tool_call_count=MAX_ITERATIONS, loop_tokens_used=100)
    assert route_after_agent(state) == "generate"


def test_route_after_agent_ends_at_token_cap():
    from agent.graph.nodes.agent import MAX_LOOP_TOKENS

    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_knowledge_base",
                "args": {"question": "q"},
                "id": "call_3",
                "type": "tool_call",
            }
        ],
    )
    state = _state(messages=[ai_msg], tool_call_count=1, loop_tokens_used=MAX_LOOP_TOKENS)
    assert route_after_agent(state) == "generate"


def test_route_after_agent_ends_on_empty_messages():
    assert route_after_agent(_state(messages=[])) == "generate"


# --------------------------------------------------------------------------- #
# Grounding tests                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_check_grounding_true_when_source_cited():
    state = _state(
        answer="Per s.pdf, pto accrues monthly.",
        results=[_result()],
        sources=[{"source": "s.pdf"}],
    )
    out = await check_grounding(state)
    assert out["grounded"] is True


@pytest.mark.asyncio
async def test_check_grounding_true_for_abstain():
    state = _state(
        answer="I do not know.",
        results=[_result()],
        sources=[],
    )
    assert (await check_grounding(state))["grounded"] is True


@pytest.mark.asyncio
async def test_check_grounding_false_when_no_results(monkeypatch):
    monkeypatch.setattr(
        "agent.graph.nodes.grounding.invoke_recovery_response",
        AsyncMock(return_value="I couldn't find enough accessible information to answer that."),
    )
    assert (await check_grounding(_state(answer="hello", results=[], sources=[])))["grounded"] is False


@pytest.mark.asyncio
async def test_needs_tools_without_evidence_gets_warm_rejection(monkeypatch):
    state = _state(
        intent="needs_tools", answer="The answer is definitely X", results=[], sources=[]
    )
    monkeypatch.setattr(
        "agent.graph.nodes.grounding.invoke_recovery_response",
        AsyncMock(return_value="I couldn't find enough accessible information to answer that."),
    )
    output = await check_grounding(state)
    assert output["answer"] != OUT_OF_SCOPE_RESPONSE
    assert output["grounded"] is False


@pytest.mark.asyncio
async def test_valid_rag_answer_requires_and_accepts_source_citation():
    result = _result(text="The handbook says X.", source="handbook.pdf")
    state = _state(
        intent="needs_tools",
        answer="According to handbook.pdf, the handbook says X.",
        results=[result],
        sources=[{"source": "handbook.pdf"}],
    )
    output = await check_grounding(state)
    assert output["answer"] == state["answer"]
    assert output["grounded"] is True


@pytest.mark.asyncio
async def test_valid_project_answer_requires_resolved_project_name():
    from agent.types import ProjectToolEvidence

    state = _state(
        intent="needs_tools",
        selected_tools=["get_project_overview"],
        answer="Workalaya is 50 percent complete.",
        project_evidence=[
            ProjectToolEvidence(
                tool="get_project_overview",
                status="resolved",
                project_name="Workalaya",
                result_count=1,
            )
        ],
    )
    output = await check_grounding(state)
    assert output["answer"] == state["answer"]
    assert output["grounded"] is True


@pytest.mark.asyncio
async def test_answer_with_internal_data_is_replaced(monkeypatch):
    result = _result(text="The handbook says X.", source="handbook.pdf")
    state = _state(
        intent="needs_tools",
        answer="handbook.pdf says project_id p-1 is active.",
        results=[result],
        sources=[{"source": "handbook.pdf"}],
    )
    monkeypatch.setattr(
        "agent.graph.nodes.grounding.invoke_recovery_response",
        AsyncMock(return_value="I couldn't find enough accessible information to answer that."),
    )
    output = await check_grounding(state)
    assert output["answer"] != OUT_OF_SCOPE_RESPONSE
    assert "project_id" not in output["answer"]


# --------------------------------------------------------------------------- #
# Graph structure test                                                         #
# --------------------------------------------------------------------------- #


def test_graph_compiles_with_expected_nodes():
    graph = get_agent_graph()
    node_keys = set(graph.nodes.keys())
    assert "classify_intent" in node_keys
    assert "chitchat_respond" in node_keys
    assert "out_of_scope" in node_keys
    assert "agent" in node_keys
    assert "tools" in node_keys


def test_project_questions_force_knowledge_search_with_structured_reads():
    selected = _enforce_project_selection(
        "Tell me about the Workalay internal agentic assistant project",
        {"intent": "needs_tools", "tools": ["search_knowledge_base"]},
    )["tools"]
    assert "get_project_overview" in selected
    assert "search_project_knowledge" in selected

    daily = _enforce_project_selection(
        "What was the daily update for Workalay?",
        {"intent": "needs_tools", "tools": []},
    )["tools"]
    assert "get_project_activity" in daily
    assert "search_project_knowledge" in daily

    context = _enforce_project_selection(
        "What is the current progress and context?",
        {"intent": "chitchat", "tools": []},
    )["tools"]
    assert context == ["get_project_overview", "search_project_knowledge"]


def test_explicit_status_question_also_requires_project_knowledge_search():
    selected = _enforce_project_selection(
        "What is the project completion percentage?",
        {"intent": "needs_tools", "tools": []},
    )["tools"]
    assert selected == ["get_project_overview", "search_project_knowledge"]


def test_empty_structured_project_result_forces_knowledge_search():
    state = _state(
        selected_tools=["get_project_activity", "search_project_knowledge"],
        project_tool_outcomes=[
            {"tool": "get_project_activity", "status": "resolved", "result_count": 0}
        ],
    )
    assert _needs_project_search_fallback(state)


def test_project_rag_is_forced_even_when_structured_result_is_non_empty():
    state = _state(
        selected_tools=["get_project_overview", "search_project_knowledge"],
        project_tool_outcomes=[
            {"tool": "get_project_overview", "status": "resolved", "result_count": 1}
        ],
    )
    assert _needs_project_search_fallback(state)


def test_project_context_guidance_is_present_for_empty_results():
    state = _state(
        selected_tools=["get_project_activity", "search_project_knowledge"],
        project_tool_outcomes=[
            {"tool": "get_project_activity", "status": "resolved", "result_count": 0}
        ],
    )
    context = _assemble_context(state)
    assert "no records were found" in context
    assert "Project tool outcome summary" in context


def test_project_context_requires_resolved_project_name_in_answer():
    context = _assemble_context(
        _state(
            resolved_project={"project_id": "p-1", "name": "Workalaya"},
            selected_tools=["get_project_blockers"],
        )
    )
    assert "Resolved project identity: Workalaya" in context
    assert "mention that project in the opening sentence" in context


def test_project_context_requires_human_friendly_summarization():
    context = _assemble_context(
        _state(
            resolved_project={"project_id": "p-1", "name": "Workalaya"},
            selected_tools=["get_project_blockers"],
        )
    )
    assert "plain, human-friendly language" in context
    assert "do not copy raw tool JSON" in context


@pytest.mark.asyncio
async def test_tool_runner_promotes_project_knowledge_to_grounding_state():
    result = _result(text="The assistant ships weekly.", source="workalay.md")

    class FakeToolNode:
        async def ainvoke(self, _state, config=None):
            return {
                "messages": [
                    ToolMessage(
                        name="search_project_knowledge",
                        tool_call_id="call-1",
                        content=json.dumps(
                            {
                                "resolution": {
                                    "status": "resolved",
                                    "project": {
                                        "project_id": "p-1",
                                        "name": "Workalay",
                                        "description": "Internal assistant",
                                    },
                                    "candidates": [],
                                    "message": "resolved",
                                },
                                "results": [result.model_dump(mode="json")],
                                "query": "about Workalay",
                            }
                        ),
                    )
                ]
            }

    state = _state()
    output = await make_tool_runner(FakeToolNode())(state)
    assert output["project_tool_outcomes"][0]["knowledge_result_count"] == 1
    assert output["project_evidence"][0].project_name == "Workalay"
    assert output["project_evidence"][0].records[0]["source"] == "workalay.md"
    assert output["results"][0].text == result.text
    assert output["sources"][0]["source"] == "workalay.md"
    assert output["resolved_project"].name == "Workalay"


def test_force_project_search_uses_resolved_project_name():
    state = _state(resolved_project={"project_id": "p-1", "name": "Workalay", "description": None})
    output = force_project_search(state)
    assert output["messages"][0].tool_calls[0]["name"] == "search_project_knowledge"
    assert output["messages"][0].tool_calls[0]["args"]["project_reference"] == "Workalay"


def test_force_project_search_uses_question_when_project_is_not_resolved():
    state = _state(question="Tell me about the Agent Knowledge Graph project.")
    output = force_project_search(state)
    assert output["messages"][0].tool_calls[0]["args"]["project_reference"] == state["question"]


def test_project_empty_evidence_uses_explicit_current_record_semantics():
    from agent.graph.nodes.generate_final import _format_project_evidence

    text = _format_project_evidence(
        [
            {
                "tool": "get_project_blockers",
                "status": "resolved",
                "project_name": "Workalay",
                "result_count": 0,
                "summary": {},
                "records": [],
            }
        ]
    )
    assert "No blockers are currently reported for Workalay" in text


def test_project_evidence_reducer_keeps_one_latest_card_per_tool():
    first = _build_project_evidence(
        "get_project_blockers",
        {"resolution": {"status": "resolved", "project": {"name": "P"}}, "blockers": []},
    )
    latest = _build_project_evidence(
        "get_project_blockers",
        {
            "resolution": {"status": "resolved", "project": {"name": "P"}},
            "blockers": [{"title": "Billing", "status": "open", "severity": "critical"}],
        },
    )
    assert first is not None and latest is not None
    merged = merge_project_evidence([first], [latest])
    assert len(merged) == 1
    assert merged[0].records[0]["title"] == "Billing"


@pytest.mark.parametrize(
    ("tool", "payload", "count"),
    [
        (
            "get_project_overview",
            {
                "resolution": {"status": "resolved", "project": {"name": "P"}},
                "feature_counts": {},
                "open_blocker_count": 0,
            },
            1,
        ),
        (
            "get_project_features",
            {
                "resolution": {"status": "resolved", "project": {"name": "P"}},
                "features": [],
                "feature_counts": {},
            },
            0,
        ),
        (
            "get_project_blockers",
            {"resolution": {"status": "resolved", "project": {"name": "P"}}, "blockers": []},
            0,
        ),
        (
            "get_project_activity",
            {
                "resolution": {"status": "resolved", "project": {"name": "P"}},
                "updates": [],
                "history": [],
            },
            0,
        ),
        (
            "search_project_knowledge",
            {
                "resolution": {"status": "resolved", "project": {"name": "P"}},
                "query": "q",
                "results": [],
            },
            0,
        ),
    ],
)
def test_project_tool_evidence_covers_empty_result_contract(tool, payload, count):
    evidence = _build_project_evidence(tool, payload)
    assert evidence is not None
    assert evidence.project_name == "P"
    assert evidence.result_count == count
    assert evidence.records == []


@pytest.mark.parametrize("status", ["ambiguous", "not_found", "forbidden"])
def test_project_tool_evidence_preserves_resolution_outcomes(status):
    evidence = _build_project_evidence(
        "get_project_blockers",
        {"resolution": {"status": status, "message": "safe message"}, "blockers": []},
    )
    assert evidence is not None
    assert evidence.status == status
    assert evidence.project_name is None


# --------------------------------------------------------------------------- #
# Global RAG fallback after denied project access                              #
# --------------------------------------------------------------------------- #


def _denied_outcomes():
    return [
        {"tool": "get_project_overview", "status": "forbidden", "result_count": 0},
        {"tool": "search_project_knowledge", "status": "forbidden", "result_count": 0},
    ]


def test_route_after_agent_falls_back_to_global_search_when_project_access_denied():
    from agent.graph.nodes.routing import _needs_global_search_fallback

    state = _state(
        selected_tools=["get_project_overview", "search_project_knowledge"],
        messages=[AIMessage(content="I cannot access this project.")],
        project_tool_outcomes=_denied_outcomes(),
    )
    assert _needs_global_search_fallback(state) is True
    assert route_after_agent(state) == "force_global_search"


def test_route_after_agent_prefers_project_search_before_global_fallback():
    state = _state(
        selected_tools=["get_project_overview", "search_project_knowledge"],
        messages=[AIMessage(content="The project is on track.")],
    )
    assert route_after_agent(state) == "force_project_search"


def test_route_after_agent_skips_global_fallback_once_search_has_run():
    state = _state(
        selected_tools=["get_project_overview", "search_project_knowledge"],
        messages=[
            AIMessage(content="I cannot access this project."),
            ToolMessage(
                name="search_knowledge_base",
                tool_call_id="call-global-1",
                content="No relevant information found in the knowledge base for this query.",
            ),
        ],
        project_tool_outcomes=_denied_outcomes(),
    )
    assert route_after_agent(state) == "generate"


def test_route_after_agent_skips_global_fallback_for_non_project_questions():
    state = _state(
        selected_tools=["search_knowledge_base"],
        messages=[AIMessage(content="Here is the answer.")],
    )
    assert route_after_agent(state) == "generate"


def test_force_global_search_calls_knowledge_base_with_question():
    from agent.graph.tool_runner import force_global_search

    state = _state(question="Tell me about the internal agentic assistant project")
    output = force_global_search(state)
    call = output["messages"][0].tool_calls[0]
    assert call["name"] == "search_knowledge_base"
    assert call["args"]["question"] == state["question"]
    assert "global_search_fallback_called" in output["workflow_steps"][-1]


def test_denied_project_access_adds_knowledge_fallback_guidance():
    state = _state(
        selected_tools=["get_project_overview", "search_project_knowledge"],
        messages=[
            ToolMessage(
                name="search_knowledge_base",
                tool_call_id="call-global-1",
                content="The assistant answers questions.",
            )
        ],
        project_tool_outcomes=_denied_outcomes(),
    )
    context = _assemble_context(state)
    assert "search_knowledge_base" in context
    assert "forbidden" in context


@pytest.mark.asyncio
async def test_cited_fallback_answer_passes_grounding_despite_denied_access():
    result = _result(text="The assistant answers questions.", source="handbook.pdf")
    state = _state(
        intent="needs_tools",
        selected_tools=["get_project_overview", "search_project_knowledge"],
        answer="According to handbook.pdf, the assistant answers questions.",
        results=[result],
        sources=[{"source": "handbook.pdf"}],
        messages=[
            ToolMessage(
                name="search_knowledge_base",
                tool_call_id="call-global-1",
                content="The assistant answers questions.",
            )
        ],
        project_tool_outcomes=_denied_outcomes(),
    )
    output = await check_grounding(state)
    assert output["grounded"] is True
    assert output["answer"] == state["answer"]


def test_recovery_context_stays_honest_when_fallback_finds_nothing():
    from agent.graph.nodes.grounding import _recovery_context

    state = _state(
        messages=[
            ToolMessage(
                name="search_knowledge_base",
                tool_call_id="call-global-1",
                content="No relevant information found in the knowledge base for this query.",
            )
        ],
        project_tool_outcomes=_denied_outcomes(),
    )
    assert "not accessible" in _recovery_context(state, "missing_evidence")


def test_graph_includes_global_search_fallback_node():
    graph = get_agent_graph()
    assert "force_global_search" in set(graph.nodes.keys())
