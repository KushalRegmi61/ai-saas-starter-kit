"""Universal LLM invocation helper.

Single source of truth for all LLM calls in the agent. Three patterns:

  stream_response(ctx)               — async token streaming (chitchat, generate_final)
  invoke_response(ctx)               — single async call, no streaming (classify)
  invoke_with_tools(messages, tools) — async tool-calling (agent ReAct node)

All calls are async so nodes never block the event loop. When nodes use
these helpers, LangGraph's astream_events() picks up on_chat_model_stream
events automatically — stream_graph() in workflow.py translates them to
WebSocket token events without any extra wiring.

Context is decoupled from source:
  LLMContext(question, context=None)       → chitchat (no retrieval)
  LLMContext(question, context=rag_chunks) → grounded RAG answer
  LLMContext(question, context=web_text)   → grounded web answer (future)
  LLMContext(question, context=tool_out)   → grounded tool answer (future)

NOTE: from __future__ import annotations intentionally absent.
Postponed annotations break InjectedState detection in ToolNode.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from agent.config import get_agent_settings

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# System prompts                                                               #
# --------------------------------------------------------------------------- #

_CHITCHAT_SYSTEM = (
    "You are a helpful enterprise knowledge assistant. "
    "The user has sent a conversational message. "
    "Respond naturally, briefly, and professionally. "
    "If they seem to be moving toward a knowledge question, let them know you are ready."
)

_GROUNDED_SYSTEM = (
    "You are an enterprise knowledge assistant.\n"
    "Answer the user's question using ONLY the provided context. "
    "If the context does not contain the answer, say you do not know.\n"
    "Include concise source citations using the source names from the context.\n"
    "When conversation memory is provided, maintain continuity with prior answers "
    "but never invent facts not present in the context."
)


# --------------------------------------------------------------------------- #
# LLMContext — context-agnostic input shape                                   #
# --------------------------------------------------------------------------- #

@dataclass
class LLMContext:
    """Input shape for LLM generation. Decoupled from the source of context.

    Fields:
        question:      The user's current question.
        context:       Retrieved context string — RAG chunks, web results,
                       tool output, etc. None = chitchat (no retrieval).
        system_prompt: Explicit system prompt override. None = auto-select
                       based on whether context is present.
        history:       Conversation turns: [{"role": "user"|"assistant",
                       "content": "..."}].
        summary:       Rolling memory summary from prior compacted turns.
    """

    question: str
    context: str | None = None
    system_prompt: str | None = None
    history: list[dict] = field(default_factory=list)
    summary: str = ""


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

async def stream_response(
    ctx: LLMContext,
    *,
    config: RunnableConfig | None = None,
    callbacks: list | None = None,
) -> AsyncIterator[str]:
    """Stream tokens for any generation scenario.

    Yields individual token strings. Callers accumulate into a full answer:

        full = ""
        async for token in stream_response(ctx, callbacks=get_langchain_callbacks()):
            full += token

    LangGraph astream_events picks up on_chat_model_stream from the
    underlying llm.astream() — stream_graph() in workflow.py translates
    them to WebSocket token events without extra wiring.

    Context determines the system prompt automatically:
      ctx.context is None → _CHITCHAT_SYSTEM  (conversational)
      ctx.context is str  → _GROUNDED_SYSTEM  (answer from retrieved context)
      ctx.system_prompt   → explicit override  (future custom agents)
    """
    messages = _build_messages(ctx)
    llm = _chat_model()
    logger.info(
        "llm stream start: question_len=%d context_len=%d history_turns=%d",
        len(ctx.question),
        len(ctx.context) if ctx.context else 0,
        len(ctx.history),
    )
    try:
        token_count = 0
        async for chunk in llm.astream(
            messages,
            config=_llm_config(config, callbacks),
        ):
            token = _content_text(chunk.content)
            if token:
                token_count += 1
                yield token
        logger.info("llm stream end: chunks=%d", token_count)
    except Exception:
        logger.exception("llm stream failed")
        raise


async def invoke_response(
    ctx: LLMContext,
    *,
    config: RunnableConfig | None = None,
    callbacks: list | None = None,
) -> str:
    """Single async LLM call, no streaming. Returns the full response string.

    Use for intent classification and other single-shot decisions where
    streaming the output to the client is wrong.
    """
    messages = _build_messages(ctx)
    llm = _chat_model()
    logger.info(
        "llm invoke start: question_len=%d has_system_override=%s",
        len(ctx.question),
        bool(ctx.system_prompt),
    )
    try:
        response = await llm.ainvoke(
            messages,
            config=_llm_config(config, callbacks),
        )
        text = _content_text(response.content)
        logger.info("llm invoke end: response_len=%d", len(text))
        return text
    except Exception:
        logger.exception("llm invoke failed")
        raise


async def invoke_with_tools(
    messages: list[BaseMessage],
    tools: list,
    *,
    config: RunnableConfig | None = None,
    callbacks: list | None = None,
) -> AIMessage:
    """Async LLM call with tools bound. Returns the full AIMessage.

    Used by the agent ReAct node. The returned AIMessage may contain
    tool_calls (→ Action) or a direct content string (→ Final Answer).
    """
    logger.info("llm tool call start: messages=%d tools=%d", len(messages), len(tools))
    llm = _chat_model().bind_tools(tools)
    try:
        response = await llm.ainvoke(
            messages,
            config=_llm_config(config, callbacks),
        )
        logger.info(
            "llm tool call end: has_tool_calls=%s",
            bool(getattr(response, "tool_calls", [])),
        )
        return response  # type: ignore[return-value]
    except Exception:
        logger.exception("llm tool call failed")
        raise


# --------------------------------------------------------------------------- #
# Internal helpers (also exported for use in common.py formatters)            #
# --------------------------------------------------------------------------- #

def _chat_model() -> ChatOpenAI:
    """LLM factory — single construction point. Tests patch this."""
    settings = get_agent_settings()
    logger.debug(
        "chat model build: model=%s base_url_configured=%s",
        settings.openai_chat_model,
        bool(settings.openai_base_url),
    )
    kwargs: dict = {
        "model": settings.openai_chat_model,
        "temperature": 0,
        "streaming": True,
        "api_key": settings.openai_api_key,
        "request_timeout": settings.openai_request_timeout_seconds,
        "max_retries": settings.openai_retry_attempts,
    }
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return ChatOpenAI(**kwargs)


def _llm_config(
    config: RunnableConfig | None,
    callbacks: list | None,
) -> RunnableConfig:
    """Preserve inherited LangGraph callbacks while supporting direct callers."""
    if config is None:
        return {"callbacks": callbacks or []}
    if not callbacks:
        return config

    merged = dict(config)
    inherited = merged.get("callbacks")
    if inherited is None:
        merged["callbacks"] = callbacks
    elif isinstance(inherited, list):
        merged["callbacks"] = [*inherited, *callbacks]
    return merged


def _build_messages(ctx: LLMContext) -> list[BaseMessage]:
    """Assemble the message list from an LLMContext."""
    if ctx.system_prompt:
        system_content = ctx.system_prompt
    elif ctx.context is None:
        system_content = _CHITCHAT_SYSTEM
    else:
        system_content = _GROUNDED_SYSTEM

    # Append memory blocks to system prompt
    memory_parts: list[str] = []
    if ctx.summary:
        memory_parts.append(f"Conversation summary:\n{ctx.summary}")
    if ctx.history:
        lines = [
            f"{'User' if t.get('role') == 'user' else 'Assistant'}: {t.get('content', '')}"
            for t in ctx.history[-6:]
        ]
        memory_parts.append("Recent conversation:\n" + "\n".join(lines))
    if memory_parts:
        system_content += "\n\n" + "\n\n".join(memory_parts)

    messages: list[BaseMessage] = [SystemMessage(content=system_content)]
    if ctx.context:
        messages.append(
            HumanMessage(content=f"Question: {ctx.question}\n\nContext:\n{ctx.context}")
        )
    else:
        messages.append(HumanMessage(content=ctx.question))
    return messages


def _content_text(content: object) -> str:
    """Extract plain text from any LangChain message content shape."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content)
