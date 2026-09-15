"""Deterministic answer audit for grounded agent responses."""

from __future__ import annotations

import logging

from agent.graph.nodes.out_of_scope import OUT_OF_SCOPE_RESPONSE
from agent.graph.state import AgentState

logger = logging.getLogger(__name__)


def check_grounding(state: AgentState) -> AgentState:
    logger.debug("node grounding: start answer_len=%d", len(state.get("answer", "")))
    answer_text = state["answer"]
    answer = answer_text.lower()
    source_names = {
        str(source.get("source", "")).lower() for source in state["sources"] if source.get("source")
    }
    cites_source = any(source_name in answer for source_name in source_names)
    says_unknown = "do not know" in answer or "don't know" in answer
    if state.get("intent") == "needs_tools":
        grounded, audit_reason = _audit_grounded_answer(state, answer, cites_source, says_unknown)
        if not grounded:
            logger.warning("node grounding: replacing answer audit_reason=%s", audit_reason)
            answer = OUT_OF_SCOPE_RESPONSE
        else:
            answer = answer_text
    else:
        grounded = bool(state["results"]) and (cites_source or says_unknown)
        audit_reason = "not_applicable"
    logger.info(
        "node grounding: done grounded=%s cites=%s abstains=%s results=%d reason=%s",
        grounded,
        cites_source,
        says_unknown,
        len(state.get("results", [])),
        audit_reason,
    )
    return {
        **state,
        "answer": answer,
        "grounded": grounded,
        "workflow_steps": [
            *state["workflow_steps"],
            f"grounding_check grounded={grounded} reason={audit_reason}",
        ],
    }


_INTERNAL_DATA_PATTERNS = (
    "project_id",
    "tool_call_id",
    "access_filter",
    "authorization",
    "bearer token",
    "assistantclaims",
    "claims.subject",
    "database pool",
    '"resolution"',
    '"tool"',
)


def _audit_grounded_answer(
    state: AgentState,
    answer: str,
    cites_source: bool,
    says_unknown: bool,
) -> tuple[bool, str]:
    """Check evidence, citations, project scope, and internal-data leakage."""
    if any(pattern in answer for pattern in _INTERNAL_DATA_PATTERNS):
        return False, "internal_data"

    results = state.get("results", [])
    evidence = state.get("project_evidence", [])
    resolved_evidence = [
        item
        for item in evidence
        if getattr(item, "status", None) == "resolved"
        or (isinstance(item, dict) and item.get("status") == "resolved")
    ]
    if not results and not resolved_evidence:
        return False, "missing_evidence"

    project_tools = {
        "get_project_overview",
        "get_project_features",
        "get_project_blockers",
        "get_project_activity",
        "search_project_knowledge",
    }
    is_project_answer = bool(project_tools.intersection(state.get("selected_tools", [])))
    if is_project_answer:
        project_names = [
            getattr(item, "project_name", None)
            or (item.get("project_name") if isinstance(item, dict) else None)
            for item in resolved_evidence
        ]
        project_names = [name.casefold() for name in project_names if name]
        if not project_names or not any(name in answer for name in project_names):
            return False, "project_scope"

    if results and not (cites_source or says_unknown):
        return False, "missing_source_citation"

    return True, "passed"
