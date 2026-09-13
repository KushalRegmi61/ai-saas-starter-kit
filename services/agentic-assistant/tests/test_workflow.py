"""Tests for the ReAct agent graph: routing, grounding, graph structure."""


from langchain_core.messages import AIMessage
from rag.types import AccessFilter, SearchResult, Source

from agent.graph.nodes import check_grounding, route_after_agent, route_after_classify
from agent.graph.state import make_initial_state
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


def test_route_after_classify_unknown_defaults_to_needs_tools():
    assert route_after_classify(_state(intent="unknown_xyz")) == "needs_tools"


def test_route_after_agent_routes_to_tools_when_under_budget():
    ai_msg = AIMessage(content="", tool_calls=[{"name": "search_knowledge_base",
                                                  "args": {"question": "q"},
                                                  "id": "call_1", "type": "tool_call"}])
    state = _state(messages=[ai_msg], tool_call_count=1, loop_tokens_used=100)
    assert route_after_agent(state) == "tools"


def test_route_after_agent_ends_when_no_tool_calls():
    ai_msg = AIMessage(content="Here is the answer.")
    state = _state(messages=[ai_msg], tool_call_count=1, loop_tokens_used=100)
    assert route_after_agent(state) == "generate"


def test_route_after_agent_ends_at_iteration_cap():
    from agent.graph.nodes.agent import MAX_ITERATIONS
    ai_msg = AIMessage(content="", tool_calls=[{"name": "search_knowledge_base",
                                                  "args": {"question": "q"},
                                                  "id": "call_2", "type": "tool_call"}])
    state = _state(messages=[ai_msg], tool_call_count=MAX_ITERATIONS, loop_tokens_used=100)
    assert route_after_agent(state) == "generate"


def test_route_after_agent_ends_at_token_cap():
    from agent.graph.nodes.agent import MAX_LOOP_TOKENS
    ai_msg = AIMessage(content="", tool_calls=[{"name": "search_knowledge_base",
                                                  "args": {"question": "q"},
                                                  "id": "call_3", "type": "tool_call"}])
    state = _state(messages=[ai_msg], tool_call_count=1, loop_tokens_used=MAX_LOOP_TOKENS)
    assert route_after_agent(state) == "generate"


def test_route_after_agent_ends_on_empty_messages():
    assert route_after_agent(_state(messages=[])) == "generate"


# --------------------------------------------------------------------------- #
# Grounding tests                                                              #
# --------------------------------------------------------------------------- #

def test_check_grounding_true_when_source_cited():
    state = _state(
        answer="Per s.pdf, pto accrues monthly.",
        results=[_result()],
        sources=[{"source": "s.pdf"}],
    )
    out = check_grounding(state)
    assert out["grounded"] is True


def test_check_grounding_true_for_abstain():
    state = _state(
        answer="I do not know.",
        results=[_result()],
        sources=[],
    )
    assert check_grounding(state)["grounded"] is True


def test_check_grounding_false_when_no_results():
    assert check_grounding(_state(answer="hello", results=[], sources=[]))["grounded"] is False


# --------------------------------------------------------------------------- #
# Graph structure test                                                         #
# --------------------------------------------------------------------------- #

def test_graph_compiles_with_expected_nodes():
    graph = get_agent_graph()
    node_keys = set(graph.nodes.keys())
    assert "classify_intent" in node_keys
    assert "chitchat_respond" in node_keys
    assert "agent" in node_keys
    assert "tools" in node_keys
