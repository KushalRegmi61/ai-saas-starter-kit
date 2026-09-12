"""LangFuse tracing: span context manager + LangChain callbacks.

Ported from enterprise-rag-assistant app/tracing.py, adapted to the v4 SDK
(`langfuse.langchain.CallbackHandler`, old `integrations.langchain` path is
gone). Tracing is a no-op unless both keys are configured.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from agent.config import get_agent_settings

logger = logging.getLogger(__name__)

_langfuse_client = None


def get_langfuse_client():
    """Get or initialize the LangFuse client (lazy: import only when keyed)."""
    global _langfuse_client
    if _langfuse_client is None:
        try:
            from langfuse import Langfuse
        except ImportError as exc:
            raise ImportError("langfuse package is required. Run: pip install langfuse") from exc
        settings = get_agent_settings()
        kwargs: dict[str, Any] = {
            "public_key": settings.langfuse_public_key,
            "secret_key": settings.langfuse_secret_key,
        }
        if settings.langfuse_base_url:
            kwargs["base_url"] = settings.langfuse_base_url
        _langfuse_client = Langfuse(**kwargs)
    return _langfuse_client


def reset_langfuse_client() -> None:
    """Drop the cached client (tests + settings rotation)."""
    global _langfuse_client
    _langfuse_client = None


def is_tracing_enabled() -> bool:
    """True only when both LangFuse keys are configured."""
    settings = get_agent_settings()
    return bool(settings.langfuse_public_key and settings.langfuse_secret_key)


@contextmanager
def trace_span(
    name: str,
    input_data: dict | None = None,
    metadata: dict | None = None,
) -> Generator[dict, None, None]:
    """Trace one operation; yields {} and does nothing when disabled.

    Usage:
        with trace_span("ask", {"question": q}) as span:
            result = run()
            span["output"] = {"answer_length": len(result)}
    """
    if not is_tracing_enabled():
        yield {}
        return
    client = get_langfuse_client()
    observation = client.start_observation(name=name, input=input_data, metadata=metadata)
    observation_id = getattr(observation, "observation_id", None) or getattr(
        observation, "id", None
    )
    try:
        span_dict: dict = {"observation_id": observation_id, "output": None}
        yield span_dict
        if span_dict.get("output") is not None:
            observation.update(output=span_dict["output"])
        observation.end()
    except Exception:
        observation.update(level="ERROR")
        observation.end()
        logger.exception("LangFuse observation failed: name=%s", name)
        raise
    finally:
        client.flush()


def get_langchain_callbacks() -> list:
    """LangChain callbacks for auto-traced LLM calls; [] when disabled."""
    if not is_tracing_enabled():
        return []
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        return []
    settings = get_agent_settings()
    kwargs: dict[str, Any] = {
        "public_key": settings.langfuse_public_key,
        "secret_key": settings.langfuse_secret_key,
    }
    if settings.langfuse_base_url:
        kwargs["base_url"] = settings.langfuse_base_url
    return [CallbackHandler(**kwargs)]
