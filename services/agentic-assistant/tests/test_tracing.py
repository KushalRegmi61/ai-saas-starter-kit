"""Tracing is a no-op without keys; callbacks empty; client lazy."""

import agent.tracing as tracing_mod
from agent.tracing import get_langchain_callbacks, is_tracing_enabled, trace_span


def test_disabled_by_default():
    assert is_tracing_enabled() is False
    assert get_langchain_callbacks() == []
    with trace_span("ask", {"question": "hi"}) as span:
        span["output"] = {"ok": True}
        assert span["output"] == {"ok": True}


def test_span_closed_on_error_without_keys():
    # Disabled path must not raise or mask the original error.
    try:
        with trace_span("boom"):
            raise RuntimeError("inner")
    except RuntimeError as e:
        assert str(e) == "inner"
    else:
        raise AssertionError("expected RuntimeError")


def test_client_initializes_when_keyed(monkeypatch):
    class FakeSettings:
        langfuse_public_key = "pk"
        langfuse_secret_key = "sk"
        langfuse_base_url = ""

    class FakeClient:
        def __init__(self, **kw):
            self.kw = kw

    monkeypatch.setattr(tracing_mod, "get_agent_settings", lambda: FakeSettings())
    monkeypatch.setattr(tracing_mod, "_langfuse_client", None)
    try:
        import langfuse

        monkeypatch.setattr(langfuse, "Langfuse", FakeClient, raising=False)
        client = tracing_mod.get_langfuse_client()
        assert client.kw == {"public_key": "pk", "secret_key": "sk"}
        assert tracing_mod.get_langfuse_client() is client
    finally:
        tracing_mod.reset_langfuse_client()


def test_reset_langfuse_client():
    tracing_mod._langfuse_client = object()
    tracing_mod.reset_langfuse_client()
    assert tracing_mod._langfuse_client is None
