"""Deterministic answer audit for grounded agent responses."""

from __future__ import annotations

import logging
import re

from agent.graph.nodes.routing import global_search_completed, project_access_denied
from agent.graph.state import AgentState
from agent.llm import invoke_recovery_response

logger = logging.getLogger(__name__)


async def check_grounding(state: AgentState, config=None) -> AgentState:
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
            answer = await invoke_recovery_response(
                question=state["question"],
                context=_recovery_context(state, audit_reason),
                config=config,
            )
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


def _recovery_context(state: AgentState, reason: str) -> str:
    """Expose only safe, user-facing outcome details to the recovery model."""
    outcomes = state.get("project_tool_outcomes", [])
    statuses = [str(item.get("status")) for item in outcomes if item.get("status")]
    if "forbidden" in statuses and not global_search_completed(state):
        return "The requested project information is not accessible to the current user."
    if "ambiguous" in statuses:
        return "More than one authorized project matched the reference, so the user should clarify which project they mean."
    if "not_found" in statuses:
        return "No authorized project matched the reference."
    if "forbidden" in statuses:
        return (
            "The requested project information is not accessible to the current user, "
            "and no supporting knowledge was found."
        )
    if reason == "missing_source_citation":
        return "Retrieved knowledge was available, but the draft answer did not cite it safely."
    return "The available project and knowledge results did not support a reliable answer."


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

# High-confidence secret/identifier shapes. Unlike the keyword list above,
# these match actual runtime values (UUIDs, call IDs, tokens) and are always
# violations — even if the same shape somehow appears in retrieved docs.
_SENSITIVE_VALUE_PATTERNS = (
    r"call_[A-Za-z0-9_-]{3,}",
    r"eyJ[A-Za-z0-9_\-]{10,}",
    r"sk-[A-Za-z0-9]{10,}",
    r"bearer\s+[A-Za-z0-9_\-\.]{10,}",
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
)


def _retrieved_corpus(state: AgentState) -> str:
    """Lowercased RAG chunk texts the answer may legitimately summarize."""
    parts: list[str] = []
    for item in state.get("results", []) or []:
        text = getattr(item, "text", None)
        if text is None and isinstance(item, dict):
            text = item.get("text")
        if text:
            parts.append(str(text).lower())
    return "\n".join(parts)


def _sensitive_values_from_state(state: AgentState) -> list[str]:
    """Runtime identifiers that must never appear in an answer."""
    values: list[str] = []
    claims = state.get("claims")
    if claims is not None:
        subject = getattr(claims, "subject", None)
        if subject is None and isinstance(claims, dict):
            subject = claims.get("subject")
        if subject:
            values.append(str(subject).lower())
    for msg in state.get("messages", []) or []:
        call_id = getattr(msg, "tool_call_id", None)
        if call_id:
            values.append(str(call_id).lower())
        for call in getattr(msg, "tool_calls", None) or []:
            call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
            if call_id:
                values.append(str(call_id).lower())
    resolved = state.get("resolved_project")
    if resolved is not None:
        pid = getattr(resolved, "project_id", None)
        if pid is None and isinstance(resolved, dict):
            pid = resolved.get("project_id")
        if pid:
            values.append(str(pid).lower())
    return [value for value in values if value]


def _audit_grounded_answer(
    state: AgentState,
    answer: str,
    cites_source: bool,
    says_unknown: bool,
) -> tuple[bool, str]:
    """Check evidence, citations, project scope, and internal-data leakage.

    Keyword hits (``project_id``, ``access_filter``, ...) are only leakage
    when the model introduced them: terms already present in the retrieved
    RAG chunks are legitimate documentation discussion, not echoed runtime
    internals. Actual runtime values (claim subjects, tool call IDs,
    project IDs, token shapes) are always violations.
    """
    for value in _sensitive_values_from_state(state):
        if value in answer:
            return False, f"internal_data:{value[:32]}"

    for value_pattern in _SENSITIVE_VALUE_PATTERNS:
        if re.search(value_pattern, answer, re.IGNORECASE):
            return False, f"internal_data:{value_pattern[:24]}"

    corpus = _retrieved_corpus(state)
    for pattern in _INTERNAL_DATA_PATTERNS:
        if pattern in answer and pattern not in corpus:
            return False, f"internal_data:{pattern}"

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
        missing_project_name = not project_names or not any(
            _project_name_mentioned(name, answer) for name in project_names
        )
        # Denied project access with global knowledge results is the
        # access-fallback path: the RAG chunks are the evidence, so the
        # resolved-project-name requirement does not apply. Citation is
        # still enforced below.
        fallback_evidence = (
            project_access_denied(state) and global_search_completed(state) and bool(results)
        )
        if missing_project_name and not fallback_evidence:
            return False, "project_scope"

    if results and not (cites_source or says_unknown):
        return False, "missing_source_citation"

    return True, "passed"


def _significant_tokens(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, dropping stubs of 1-2 characters."""
    return [
        part for part in re.sub(r"[^a-z0-9]+", " ", text.casefold()).split() if len(part) > 2
    ]


def _project_name_mentioned(project_name: str, answer: str) -> bool:
    """Check the answer names the resolved project, tolerating paraphrase.

    Resolved DB names ("workalaya internal knowledge assistant") rarely match
    draft wording ("Workalaya Agentic Assistant") exactly. Accept the full
    normalized name or a quorum of its significant tokens: all of them for
    short names, at least half for longer ones. An answer about an unrelated
    project shares no significant tokens and still fails.
    """
    name = project_name.casefold()
    if name and name in answer:
        return True
    name_tokens = _significant_tokens(name)
    if not name_tokens:
        return False
    answer_tokens = set(_significant_tokens(answer))
    matched = sum(1 for token in name_tokens if token in answer_tokens)
    if len(name_tokens) <= 2:
        return matched == len(name_tokens)
    return matched >= (len(name_tokens) + 1) // 2
