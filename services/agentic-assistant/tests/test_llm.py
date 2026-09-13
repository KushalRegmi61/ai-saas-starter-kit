"""LLM adapter tests for native async streaming configuration."""

from types import SimpleNamespace

import pytest

import agent.llm as llm


@pytest.mark.asyncio
async def test_stream_response_preserves_inherited_graph_callbacks(monkeypatch):
    seen = {}

    class FakeModel:
        async def astream(self, messages, config=None):
            seen["config"] = config
            yield SimpleNamespace(content="first")
            yield SimpleNamespace(content="second")

    monkeypatch.setattr(llm, "_chat_model", lambda: FakeModel())

    tokens = [
        token
        async for token in llm.stream_response(
            llm.LLMContext(question="hello"),
            config={"callbacks": ["langgraph-event-stream"]},
        )
    ]

    assert tokens == ["first", "second"]
    assert seen["config"]["callbacks"] == ["langgraph-event-stream"]
