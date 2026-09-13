"""Agent tool package.

Tool registration happens at import time — each tool file calls register()
at module level. Importing the module here is the only wiring step needed.

Adding a new tool:
  1. Create tools/<name>.py with @tool + register(ToolEntry(...)) at bottom
  2. Add `from agent.tools import <name>` below (one line)
  3. Done — classifier, agent node, and ToolNode all pick it up automatically
"""

from __future__ import annotations

import logging

# ── Tool registrations (import triggers self-registration) ────────────────── #
from agent.tools import search as _search_tool  # noqa: F401  registers search_knowledge_base

# Re-export registry API so callers import from one place
from agent.tools.registry import (
    ToolEntry,
    get_all_tools,
    get_entries,
    get_tool_names,
    get_tool_schemas_for_classifier,
    get_tools_by_name,
    register,
)

logger = logging.getLogger(__name__)

logger.info("tools: package loaded")

# Future tools — add imports here:
# from agent.tools import web_search as _web_search_tool
# from agent.tools import calculator as _calculator_tool
# from agent.tools import sql_query as _sql_tool

__all__ = [
    "ToolEntry",
    "get_all_tools",
    "get_entries",
    "get_tool_names",
    "get_tool_schemas_for_classifier",
    "get_tools_by_name",
    "register",
]
