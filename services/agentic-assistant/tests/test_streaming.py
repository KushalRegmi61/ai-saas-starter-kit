"""Async graph streaming tests with retrieval and LLM boundaries mocked."""

import pytest
from rag.types import AccessFilter, SearchResult, Source

import agent.graph.streaming as streaming
from agent.config import get_agent_settings


def _result():
    return SearchResult(text="policy text", source=Source(source="policy.pdf", score=0.9))


@pytest.mark.asyncio
async def test_streaming_workflow_emits_tokens_and_grounding(monkeypatch):
    monkeypatch.setattr(get_agent_settings(), "openai_api_key", "test-key")

    def retrieve(state):
        return {
            **state,
            "results": [_result()],
            "workflow_steps": [*state["workflow_steps"], "retrieved one"],
        }

    class FakeChunk:
        def __init__(self, content):
            self.content = content

    class FakeModel:
        async def astream(self, messages, config=None):
            yield FakeChunk("See ")
            yield FakeChunk("policy.pdf")

    monkeypatch.setattr(streaming, "retrieve_context", retrieve)
    monkeypatch.setattr(streaming.common, "_chat_model", lambda: FakeModel())

    events = [
        event
        async for event in streaming.stream_answer(
            "What is the policy?",
            access_filter=AccessFilter(departments=["all"], max_access_level=3),
        )
    ]

    assert [event["type"] for event in events] == ["step", "step", "step", "token", "token", "done"]
    assert events[-1]["answer"] == "See policy.pdf"
    assert events[-1]["grounded"] is True
