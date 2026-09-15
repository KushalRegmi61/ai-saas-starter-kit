"""Model-route contract: fast vs reasoning tiers per node."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from rag.types import AccessFilter

from agent.graph.state import make_initial_state


def _state(**kw):
    base = make_initial_state(
        "q?",
        access_filter=AccessFilter(departments=["all"], max_access_level=3),
    )
    base["workflow_steps"] = []
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_classification_uses_fast_route(monkeypatch):
    import agent.graph.nodes.classify as classify_mod

    seen = {}

    async def fake_invoke(ctx, config=None, route=None, callbacks=None):
        seen["route"] = route
        return '{"intent": "chitchat", "tools": []}'

    monkeypatch.setattr(classify_mod, "invoke_response", fake_invoke)
    await classify_mod.classify_intent(_state(question="hello"))
    assert seen["route"] == "fast"


@pytest.mark.asyncio
async def test_chitchat_uses_fast_route(monkeypatch):
    import agent.graph.nodes.chitchat as chitchat_mod

    seen = {}

    async def fake_stream(ctx, config=None, route=None):
        seen["route"] = route
        yield "hi"

    monkeypatch.setattr(chitchat_mod, "stream_response", fake_stream)
    monkeypatch.setattr(
        "agent.graph.nodes.chitchat.check_grounding",
        AsyncMock(side_effect=lambda state, config=None: state),
    )
    await chitchat_mod.chitchat_respond(_state(question="hello"))
    assert seen["route"] == "fast"


@pytest.mark.asyncio
async def test_react_tool_calls_use_reasoning_route(monkeypatch):
    import agent.graph.nodes.agent as agent_mod

    seen = {}

    async def fake_invoke(messages, tools, config=None, callbacks=None, route=None):
        seen["route"] = route
        return AIMessage(content="done")

    monkeypatch.setattr(agent_mod, "invoke_with_tools", fake_invoke)
    await agent_mod.agent_node(_state(question="q?", messages=[]))
    assert seen["route"] == "reasoning"


@pytest.mark.asyncio
async def test_final_grounded_generation_uses_reasoning_route(monkeypatch):
    import importlib

    final_mod = importlib.import_module("agent.graph.nodes.generate_final")

    seen = {}

    async def fake_stream(ctx, config=None, route=None):
        seen["route"] = route
        yield "answer"

    monkeypatch.setattr(final_mod, "stream_response", fake_stream)
    monkeypatch.setattr(
        final_mod,
        "check_grounding",
        AsyncMock(side_effect=lambda state, config=None: state),
    )
    await final_mod.generate_final(_state(question="q?"))
    assert seen["route"] == "reasoning"


@pytest.mark.asyncio
async def test_recovery_responses_use_fast_route(monkeypatch):
    import agent.llm as llm_mod

    seen = {}

    class FakeModel:
        async def ainvoke(self, messages, config=None):
            return SimpleNamespace(content="recovery answer")

    def fake_chat_model(*, model_name=None, route=None, streaming=True):
        seen["route"] = route
        seen["streaming"] = streaming
        return FakeModel()

    monkeypatch.setattr(llm_mod, "_chat_model", fake_chat_model)
    text = await llm_mod.invoke_recovery_response(question="q?", context="outcome")
    assert text == "recovery answer"
    assert seen["route"] == "fast"
    assert seen["streaming"] is False
