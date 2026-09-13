"""Grounding node: verify the answer cites retrieved sources (or abstains)."""

from __future__ import annotations

import logging

from agent.graph.state import AgentState

logger = logging.getLogger(__name__)


def check_grounding(state: AgentState) -> AgentState:
    logger.debug("node grounding: start answer_len=%d", len(state.get("answer", "")))
    answer = state["answer"].lower()
    source_names = {
        str(source.get("source", "")).lower() for source in state["sources"] if source.get("source")
    }
    cites_source = any(source_name in answer for source_name in source_names)
    says_unknown = "do not know" in answer or "don't know" in answer
    grounded = bool(state["results"]) and (cites_source or says_unknown)
    logger.info(
        "node grounding: done grounded=%s cites=%s abstains=%s results=%d",
        grounded,
        cites_source,
        says_unknown,
        len(state.get("results", [])),
    )
    return {
        **state,
        "grounded": grounded,
        "workflow_steps": [
            *state["workflow_steps"],
            f"grounding_check grounded={grounded}",
        ],
    }
