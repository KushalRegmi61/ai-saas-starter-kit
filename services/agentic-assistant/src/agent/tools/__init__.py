"""Tool registry: one file per tool, aggregated here.

Adding a tool:
  1. Create `tools/<name>.py` with `def make_<name>_tool(access_filter)`.
  2. Append it to `make_rag_tools` below (keeps tool ordering explicit).
Tool functions take only LLM-facing args (question, top_k, ...); the host
`AccessFilter` is bound at build time, never supplied by the model.
"""

from langchain_core.tools import BaseTool
from rag.types import AccessFilter

from agent.tools.search import make_search_tool


def make_rag_tools(access_filter: AccessFilter | None) -> list[BaseTool]:
    """Bind the host-resolved filter (+ its tenant) into callable tools."""
    return [make_search_tool(access_filter)]


__all__ = ["make_rag_tools"]
