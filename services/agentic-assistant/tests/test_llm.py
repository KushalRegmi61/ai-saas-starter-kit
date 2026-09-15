"""LLM adapter tests for native async streaming configuration."""

from types import SimpleNamespace

import pytest

import agent.llm as llm
from agent.config import AgentSettings


@pytest.mark.asyncio
async def test_stream_response_preserves_inherited_graph_callbacks(monkeypatch):
    seen = {}

    class FakeModel:
        async def astream(self, messages, config=None):
            seen["config"] = config
            yield SimpleNamespace(content="first")
            yield SimpleNamespace(content="second")

    monkeypatch.setattr(llm, "_chat_model", lambda **kwargs: FakeModel())

    tokens = [
        token
        async for token in llm.stream_response(
            llm.LLMContext(question="hello"),
            config={"callbacks": ["langgraph-event-stream"]},
        )
    ]

    assert tokens == ["first", "second"]
    assert seen["config"]["callbacks"] == ["langgraph-event-stream"]


def test_chat_model_factory_resolves_fast_route(monkeypatch):
    from agent import llm as llm_mod

    monkeypatch.setenv("AGENTIC_ASSISTANT_FAST_MODEL", "fast-model-x")
    monkeypatch.delenv("AGENTIC_ASSISTANT_REASONING_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_CHAT_MODEL", raising=False)
    settings = AgentSettings(_env_file=None)
    assert settings.resolve_fast_model() == "fast-model-x"

    seen = {}
    monkeypatch.setattr(
        llm_mod, "ChatOpenAI", lambda **kwargs: seen.update(kwargs) or object()
    )
    monkeypatch.setattr(llm_mod, "get_agent_settings", lambda: settings)
    llm_mod._chat_model(route="fast")
    assert seen["model"] == "fast-model-x"


def test_chat_model_factory_resolves_reasoning_route(monkeypatch):
    from agent import llm as llm_mod

    monkeypatch.delenv("AGENTIC_ASSISTANT_FAST_MODEL", raising=False)
    monkeypatch.setenv("AGENTIC_ASSISTANT_REASONING_MODEL", "reasoning-model-y")
    monkeypatch.delenv("OPENAI_CHAT_MODEL", raising=False)
    settings = AgentSettings(_env_file=None)
    assert settings.resolve_reasoning_model() == "reasoning-model-y"

    seen = {}
    monkeypatch.setattr(
        llm_mod, "ChatOpenAI", lambda **kwargs: seen.update(kwargs) or object()
    )
    monkeypatch.setattr(llm_mod, "get_agent_settings", lambda: settings)
    llm_mod._chat_model(route="reasoning")
    assert seen["model"] == "reasoning-model-y"


def test_chat_model_factory_defaults_to_documented_models(monkeypatch):
    from agent import llm as llm_mod

    monkeypatch.delenv("AGENTIC_ASSISTANT_FAST_MODEL", raising=False)
    monkeypatch.delenv("AGENTIC_ASSISTANT_REASONING_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_CHAT_MODEL", raising=False)
    settings = AgentSettings(_env_file=None)

    seen = {}
    monkeypatch.setattr(
        llm_mod, "ChatOpenAI", lambda **kwargs: seen.update(kwargs) or object()
    )
    monkeypatch.setattr(llm_mod, "get_agent_settings", lambda: settings)

    llm_mod._chat_model(route="fast")
    assert seen["model"] == "gpt-4o-mini"
    llm_mod._chat_model(route="reasoning")
    assert seen["model"] == "gpt-5-nano"
