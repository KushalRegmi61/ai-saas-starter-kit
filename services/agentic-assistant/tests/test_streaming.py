"""Tests for stream_graph() in workflow.py — pure event translation."""

import asyncio

import pytest
from rag.types import AccessFilter

from agent.config import get_agent_settings
from agent.graph.workflow import stream_graph


@pytest.mark.asyncio
async def test_stream_graph_raises_without_api_key(monkeypatch):
    settings = get_agent_settings()
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        async for _ in stream_graph("hi"):
            pass


@pytest.mark.asyncio
async def test_stream_graph_emits_done_event(monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "openai_api_key", "test-key")

    final_state = {
        "answer": "Here is the answer.",
        "sources": [],
        "grounded": False,
        "results": [],
        "workflow_steps": ["classify: intent=needs_tools", "generate_final"],
        "messages": [],
    }

    async def fake_astream_events(state, version="v2"):
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": final_state},
            "metadata": {},
        }

    class FakeGraph:
        def astream_events(self, state, version="v2", config=None):
            return fake_astream_events(state, version)

    from agent.graph import workflow as wf
    monkeypatch.setattr(wf, "get_agent_graph", lambda: FakeGraph())

    events = [e async for e in stream_graph(
        "What is the policy?",
        access_filter=AccessFilter(departments=["all"], max_access_level=3),
    )]

    assert events[-1]["type"] == "done"
    assert events[-1]["answer"] == "Here is the answer."


@pytest.mark.asyncio
async def test_stream_graph_survives_non_dict_agent_end_output(monkeypatch):
    """Live graphs report inner-runnable string outputs on agent chain-end.

    The budget step must skip rendering instead of raising AttributeError,
    which previously turned every ReAct ask into a socket server_error.
    """
    monkeypatch.setattr(get_agent_settings(), "openai_api_key", "test-key")

    final_state = {
        "answer": "done", "sources": [], "grounded": False,
        "results": [], "workflow_steps": [], "messages": [],
    }

    async def fake_astream_events(state, version="v2"):
        yield {"event": "on_chain_end", "name": "agent",
               "data": {"output": "inner runnable text output"}, "metadata": {}}
        yield {"event": "on_chain_end", "name": "LangGraph",
               "data": {"output": final_state}, "metadata": {}}

    class FakeGraph:
        def astream_events(self, state, version="v2", config=None):
            return fake_astream_events(state, version)

    from agent.graph import workflow as wf
    monkeypatch.setattr(wf, "get_agent_graph", lambda: FakeGraph())

    events = [e async for e in stream_graph("What is the policy?")]
    assert events[-1]["type"] == "done"
    assert events[-1]["answer"] == "done"
    assert not [e for e in events if e.get("name") == "agent_budget"]


def test_parallel_tool_writes_merge_without_invalid_update():
    """Two searches finishing in one step must not raise InvalidUpdateError.

    Regression: a follow-up whose agent issued two parallel searches crashed
    the live socket (server_error, then a hung connection) because `sources`
    was a LastValue channel. Sources/results accumulate; steps last-win.
    """
    from langgraph.graph import END, START, StateGraph

    from agent.graph.state import AgentState, make_initial_state

    def writer_a(_state):
        return {
            "sources": [{"source": "a.pdf"}],
            "results": [],
            "workflow_steps": ["writer_a"],
        }

    def writer_b(_state):
        return {
            "sources": [{"source": "b.pdf"}],
            "results": [],
            "workflow_steps": ["writer_b"],
        }

    graph = StateGraph(AgentState)
    graph.add_node("writer_a", writer_a)
    graph.add_node("writer_b", writer_b)
    graph.add_edge(START, "writer_a")
    graph.add_edge(START, "writer_b")
    graph.add_edge("writer_a", END)
    graph.add_edge("writer_b", END)

    out = graph.compile().invoke(make_initial_state("policy?", access_filter=None))
    assert sorted(s["source"] for s in out["sources"]) == ["a.pdf", "b.pdf"]
    assert out["workflow_steps"][-1] in ("writer_a", "writer_b")
    assert len(out["workflow_steps"]) == 1


@pytest.mark.asyncio
async def test_stream_graph_emits_token_events(monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "openai_api_key", "test-key")

    class FakeChunk:
        def __init__(self, content):
            self.content = content

    final_state = {
        "answer": "Hello world", "sources": [], "grounded": False,
        "results": [], "workflow_steps": [], "messages": [],
    }

    async def fake_astream_events(state, version="v2"):
        yield {"event": "on_chat_model_start", "name": "ChatOpenAI",
               "data": {}, "metadata": {"langgraph_node": "generate_final"}}
        yield {"event": "on_chat_model_stream", "name": "ChatOpenAI",
               "data": {"chunk": FakeChunk("Hello ")},
               "metadata": {"langgraph_node": "generate_final"}}
        yield {"event": "on_chat_model_stream", "name": "ChatOpenAI",
               "data": {"chunk": FakeChunk("world")},
               "metadata": {"langgraph_node": "generate_final"}}
        yield {"event": "on_chain_end", "name": "LangGraph",
               "data": {"output": final_state}, "metadata": {}}

    class FakeGraph:
        def astream_events(self, state, version="v2", config=None):
            return fake_astream_events(state, version)

    from agent.graph import workflow as wf
    monkeypatch.setattr(wf, "get_agent_graph", lambda: FakeGraph())

    events = [e async for e in stream_graph("What is the policy?")]
    token_events = [e for e in events if e["type"] == "token"]
    assert len(token_events) == 2
    assert token_events[0]["content"] == "Hello "
    assert token_events[1]["content"] == "world"


@pytest.mark.asyncio
async def test_stream_graph_suppresses_classifier_tokens(monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "openai_api_key", "test-key")

    class FakeChunk:
        content = "needs_tools"

    final_state = {
        "answer": "", "sources": [], "grounded": False,
        "results": [], "workflow_steps": [], "messages": [],
    }

    async def fake_astream_events(state, version="v2"):
        yield {"event": "on_chat_model_start", "name": "ChatOpenAI",
               "data": {}, "metadata": {"langgraph_node": "classify_intent"}}
        yield {"event": "on_chat_model_stream", "name": "ChatOpenAI",
               "data": {"chunk": FakeChunk()},
               "metadata": {"langgraph_node": "classify_intent"}}
        yield {"event": "on_chain_end", "name": "LangGraph",
               "data": {"output": final_state}, "metadata": {}}

    class FakeGraph:
        def astream_events(self, state, version="v2", config=None):
            return fake_astream_events(state, version)

    from agent.graph import workflow as wf
    monkeypatch.setattr(wf, "get_agent_graph", lambda: FakeGraph())

    events = [e async for e in stream_graph("hi")]
    token_events = [e for e in events if e["type"] == "token"]
    assert token_events == [], "classifier tokens must be suppressed"


@pytest.mark.asyncio
async def test_stream_graph_forwards_generation_chunks_before_graph_completion(monkeypatch):
    """A provider chunk must be observable without waiting for graph completion."""
    monkeypatch.setattr(get_agent_settings(), "openai_api_key", "test-key")
    graph_release = asyncio.Event()
    final_state = {
        "answer": "Hello world", "sources": [], "grounded": False,
        "results": [], "workflow_steps": [], "messages": [],
    }

    async def fake_astream_events(state, version="v2"):
        yield {
            "event": "on_chain_start",
            "name": "generate_final",
            "data": {},
            "metadata": {"langgraph_node": "generate_final"},
        }
        yield {
            "event": "on_chat_model_stream",
            "name": "ChatOpenAI",
            "data": {"chunk": type("Chunk", (), {"content": "Hello "})()},
            "metadata": {"langgraph_node": "generate_final"},
        }
        await graph_release.wait()
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": final_state},
            "metadata": {},
        }

    class FakeGraph:
        def astream_events(self, state, version="v2", config=None):
            return fake_astream_events(state, version)

    from agent.graph import workflow as wf
    monkeypatch.setattr(wf, "get_agent_graph", lambda: FakeGraph())

    events = stream_graph("hi")
    assert (await events.__anext__())["type"] == "step"
    token_event = await events.__anext__()
    assert token_event == {"type": "token", "content": "Hello "}

    graph_release.set()
    remaining = [event async for event in events]
    assert remaining[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_stream_graph_only_forwards_generation_node_tokens(monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "openai_api_key", "test-key")
    final_state = {
        "answer": "final", "sources": [], "grounded": False,
        "results": [], "workflow_steps": [], "messages": [],
    }

    async def fake_astream_events(state, version="v2"):
        for node, content in (("agent", "hidden reasoning"), ("generate_final", "visible")):
            yield {
                "event": "on_chat_model_stream",
                "name": "ChatOpenAI",
                "data": {"chunk": type("Chunk", (), {"content": content})()},
                "metadata": {"langgraph_node": node},
            }
        yield {
            "event": "on_chat_model_stream",
            "name": "ChatOpenAI",
            "data": {"chunk": type("Chunk", (), {"content": "unknown"})()},
            "metadata": {},
        }
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": final_state},
            "metadata": {},
        }

    class FakeGraph:
        def astream_events(self, state, version="v2", config=None):
            return fake_astream_events(state, version)

    from agent.graph import workflow as wf
    monkeypatch.setattr(wf, "get_agent_graph", lambda: FakeGraph())

    events = [event async for event in stream_graph("hi")]
    assert [event["content"] for event in events if event["type"] == "token"] == ["visible"]
