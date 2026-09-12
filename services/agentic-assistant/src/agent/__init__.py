"""Agentic knowledge assistant: LangGraph workflow over the shared RAG library.

Auth-agnostic like the library it embeds — the host resolves caller identity
to an `AccessFilter` (another session owns auth) and passes it in. Tracing
is a no-op unless LangFuse keys are configured.
"""

from agent.graph.workflow import ask
from agent.tools import make_rag_tools

__all__ = ["ask", "make_rag_tools"]
