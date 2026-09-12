"""Conversation memory windowing, summary rollover, and token fallback tests."""

import pytest

import service.memory as memory
from agent.config import get_agent_settings
from models.conversations import ConversationSnapshot


def _snapshot(turn_count=8, summary=""):
    return ConversationSnapshot(
        conversation_id="c-1",
        owner_subject="u-1",
        rolling_summary=summary,
        summary_through_turn=-1,
        turns=[
            {
                "index": index,
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"turn {index}",
            }
            for index in range(turn_count)
        ],
    )


@pytest.mark.asyncio
async def test_memory_keeps_latest_six_and_summarizes_evicted_turns(monkeypatch):
    settings = get_agent_settings()
    monkeypatch.setattr(settings, "max_history_turns", 6)
    monkeypatch.setattr(settings, "memory_max_tokens", 2048)
    monkeypatch.setattr(settings, "memory_summary_max_tokens", 768)

    async def summarize(existing, turns):
        assert [turn["index"] for turn in turns] == [0, 1]
        return "user needs the earlier context"

    monkeypatch.setattr(memory, "_try_summarize", summarize)
    prepared = await memory.prepare_memory(_snapshot())

    assert prepared.changed is True
    assert prepared.summary == "user needs the earlier context"
    assert prepared.summary_through_turn == 1
    assert prepared.last_turn_index == 7
    assert [turn["index"] for turn in prepared.turns] == [2, 3, 4, 5, 6, 7]


@pytest.mark.asyncio
async def test_memory_fits_newest_turns_to_token_budget(monkeypatch):
    settings = get_agent_settings()
    monkeypatch.setattr(settings, "max_history_turns", 6)
    monkeypatch.setattr(settings, "memory_max_tokens", 12)
    monkeypatch.setattr(settings, "memory_summary_max_tokens", 4)

    async def summarize(existing, turns):
        return "compact"

    monkeypatch.setattr(memory, "_try_summarize", summarize)
    prepared = await memory.prepare_memory(_snapshot(turn_count=6, summary="prior"))

    assert memory._memory_tokens(prepared.summary, prepared.turns) <= 12
    assert prepared.turns[-1]["index"] == 5


@pytest.mark.asyncio
async def test_memory_falls_back_without_advancing_summary(monkeypatch):
    settings = get_agent_settings()
    monkeypatch.setattr(settings, "max_history_turns", 2)
    monkeypatch.setattr(settings, "memory_max_tokens", 100)

    async def summarize(existing, turns):
        return None

    monkeypatch.setattr(memory, "_try_summarize", summarize)
    prepared = await memory.prepare_memory(_snapshot(turn_count=4, summary="existing"))

    assert prepared.changed is False
    assert prepared.summary == "existing"
    assert prepared.summary_through_turn == -1
    assert prepared.last_turn_index == 3
    assert [turn["index"] for turn in prepared.turns] == [2, 3]
