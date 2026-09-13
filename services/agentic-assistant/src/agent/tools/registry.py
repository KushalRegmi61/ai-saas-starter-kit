"""Professional tool registry for the agentic assistant.

Single source of truth for all tools available to the agent. Every tool
self-registers at import time via register(). The registry exposes typed
methods consumed by:
  - classify_intent node  → get_tool_schemas_for_classifier()
  - agent_node            → get_tools_by_name(), get_all_tools()
  - workflow.py ToolNode  → get_all_tools()

Adding a new tool (3 steps only):
  1. Create tools/<name>.py, decorate with @tool, call register(ToolEntry(...))
  2. Import the module in tools/__init__.py to trigger registration
  3. Nothing else changes — classifier, agent, ToolNode all pick it up automatically

Thread safety: registry is populated at import time (module-level), read-only
at request time. No locks needed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# ToolEntry — one entry per registered tool                                   #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ToolEntry:
    """Declarative metadata for one agent tool.

    Fields:
        name:                   Must match the @tool("name") decorator exactly.
        description:            What the tool does — shown to the LLM as the
                                tool's docstring / schema description.
        when_to_use:            Richer classifier hint — shown only in the
                                intent-classifier system prompt, not to the LLM
                                during tool calling.
        category:               Logical grouping for future filtering/routing.
                                Convention: "knowledge" | "web" | "compute" |
                                "data" | "communication" | "utility"
        tool_fn:                The @tool-decorated BaseTool instance.
        requires_access_filter: True if the tool reads ABAC-gated data.
                                Informational — enforcement is via InjectedState.
        always_include:         If True, ToolNode always receives this tool
                                regardless of classifier selection (e.g. a
                                future `discover` escape-hatch tool).
        tags:                   Optional free-form labels for future routing,
                                audit, or cost attribution.
    """

    name: str
    description: str
    when_to_use: str
    category: str
    tool_fn: BaseTool
    requires_access_filter: bool = True
    always_include: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# Internal registry store                                                      #
# --------------------------------------------------------------------------- #

_REGISTRY: list[ToolEntry] = []
_REGISTRY_INDEX: dict[str, ToolEntry] = {}


# --------------------------------------------------------------------------- #
# Registration                                                                 #
# --------------------------------------------------------------------------- #

def register(entry: ToolEntry) -> ToolEntry:
    """Register a tool. Called at module import time inside each tool file.

    Raises ValueError on duplicate name — fail loud so mis-wired tools are
    caught at startup, not silently overwritten.
    """
    if entry.name in _REGISTRY_INDEX:
        raise ValueError(
            f"Tool '{entry.name}' is already registered. "
            "Each tool name must be unique across the registry."
        )
    _REGISTRY.append(entry)
    _REGISTRY_INDEX[entry.name] = entry
    logger.debug("tool registered: name=%s category=%s", entry.name, entry.category)
    return entry


# --------------------------------------------------------------------------- #
# Query API                                                                    #
# --------------------------------------------------------------------------- #

def get_all_tools() -> list[BaseTool]:
    """All registered tool functions — passed to ToolNode."""
    logger.debug("registry: get_all_tools count=%d", len(_REGISTRY))
    return [e.tool_fn for e in _REGISTRY]


def get_tools_by_name(names: list[str]) -> list[BaseTool]:
    """Return tool functions for the given names. Unknown names are skipped
    with a warning rather than raising — classifier output may lag a registry
    change during a rolling deploy."""
    logger.info("registry: get_tools_by_name requested=%s", names)
    result = []
    for name in names:
        entry = _REGISTRY_INDEX.get(name)
        if entry is None:
            logger.warning("classifier selected unknown tool: %s — skipped", name)
        else:
            result.append(entry.tool_fn)
    # Always append always_include tools even if not in names
    for entry in _REGISTRY:
        if entry.always_include and entry.tool_fn not in result:
            result.append(entry.tool_fn)
    return result


def get_tool_names() -> list[str]:
    """All registered tool names."""
    return [e.name for e in _REGISTRY]


def get_tool_schemas_for_classifier() -> str:
    """Formatted tool catalogue for the intent-classifier system prompt.

    Format per tool:
        - <name> [<category>]: <description>
          Use when: <when_to_use>

    The classifier uses this to decide both the intent and which specific
    tools are relevant for the user's question.
    """
    if not _REGISTRY:
        return "(no tools registered)"
    lines: list[str] = []
    for entry in _REGISTRY:
        lines.append(
            f"- {entry.name} [{entry.category}]: {entry.description}\n"
            f"  Use when: {entry.when_to_use}"
        )
    return "\n".join(lines)


def get_entries() -> list[ToolEntry]:
    """Full ToolEntry list — for introspection, tests, and admin tooling."""
    return list(_REGISTRY)
